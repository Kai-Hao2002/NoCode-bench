import os
import sys
import shutil
import subprocess
import time
import re
import stat
import platform
import json
from google import generativeai as genai
from google.generativeai.types import GenerationConfig, RequestOptions
from django.conf import settings
from unidiff import PatchSet
from io import StringIO

# --- 核心設定 (Core Configuration) ---
ROOT_WORKSPACE = os.path.join(settings.BASE_DIR, 'nocode_workspaces')
os.makedirs(ROOT_WORKSPACE, exist_ok=True)
ORIGINAL_DATASET_ROOT = os.path.join(settings.BASE_DIR, 'NoCode-bench_Verified', 'data')


# --- 權限錯誤處理 (Permission Error Handler) ---
def onerror(func, path, exc_info):
    if not os.access(path, os.W_OK):
        os.chmod(path, stat.S_IWUSR | stat.S_IWRITE)
        func(path)
    else:
        raise


# --- 測試名稱格式轉換 (Test Name Format Conversion) ---
def _convert_test_name_to_pytest_format(test_name: str) -> str:
    """
    Convert test name from unittest/Django format to pytest format.
    
    Unittest/Django format: "test_name (module.path.ClassName)"
    Pytest format: "module/path.py::ClassName::test_name"
    
    If the test_name is already in pytest format (contains "::"), return it unchanged.
    """
    # Check if already in pytest format
    if '::' in test_name:
        return test_name
    
    # Try to match unittest format: "test_name (module.path.ClassName)"
    match = re.match(r'^(\w+)\s+\(([^)]+)\)$', test_name.strip())
    
    if match:
        test_method = match.group(1)
        full_class_path = match.group(2)
        
        # Split the full class path into module path and class name
        # e.g., "pagination.tests.PaginationTests" -> module: "pagination.tests", class: "PaginationTests"
        parts = full_class_path.rsplit('.', 1)
        
        if len(parts) == 2:
            module_path, class_name = parts
            # Convert module path to file path
            # e.g., "pagination.tests" -> "tests/pagination/tests.py"
            file_path = module_path.replace('.', '/') + '.py'
            
            # Return in pytest format: file_path::ClassName::test_method
            return f"{file_path}::{class_name}::{test_method}"
    
    # If conversion failed, return original
    return test_name

        
# 🚀 新增 (NEW): 用於應用補丁的輔助函數
# (Helper function for applying patches)
def _apply_patch(workspace_path: str, patch_str: str) -> tuple[bool, str | None]:
    """
    將一個補丁字符串應用到 Git 倉庫。
    (Applies a patch string to a git repo.)
    """
    if not patch_str:
        msg = "Warning: Empty patch string provided to _apply_patch."
        print(msg)
        return False, msg # 🚀 更改 (CHANGE)
    try:
        result = subprocess.run(
            ['git', 'apply', '--ignore-whitespace'],
            input=patch_str,
            cwd=workspace_path,
            text=True,
            check=False,
            capture_output=True,
            encoding='utf-8'
        )
        if result.returncode == 0:
            return True, None # 🚀 更改 (CHANGE)
        
        # 🚀 更改 (CHANGE): 捕獲錯誤並返回
        error_msg = f"git apply failed: {result.stderr}"
        print(f"ERROR: {error_msg}")
        return False, error_msg
        
    except Exception as e:
        # 🚀 更改 (CHANGE): 捕獲錯誤並返回
        error_msg = f"ERROR: Exception during _apply_patch: {e}"
        print(error_msg)
        return False, error_msg


# --- 輔助函數 (Helper Functions) ---

def setup_workspace(nocode_bench_id: str) -> str:
    """
    (此函數保持不變)
    (This function is unchanged)
    """
    parts = nocode_bench_id.split('__')
    repo_owner = parts[0]
    repo_name_base = parts[1].split('-')[0]
    repo_path_segment = os.path.join(repo_owner, repo_name_base)
    original_repo_path = os.path.join(ORIGINAL_DATASET_ROOT, repo_path_segment)
    run_id = str(time.time()).replace('.', '')
    temp_dir = os.path.join(ROOT_WORKSPACE, f'run_{nocode_bench_id.replace("__", "_")}_{run_id}')
    
    if not os.path.exists(original_repo_path):
        raise FileNotFoundError(f"Original codebase not found! Check path: {original_repo_path}")
    
    try:
        shutil.copytree(original_repo_path, temp_dir)
        subprocess.run(['git', 'init'], cwd=temp_dir, check=True, capture_output=True, text=True, encoding='utf-8')
        subprocess.run(['git', 'add', '.'], cwd=temp_dir, check=True, capture_output=True, text=True, encoding='utf-8')
        subprocess.run(['git', 'commit', '-m', 'Initial snapshot', '--allow-empty'], cwd=temp_dir, check=True, capture_output=True, text=True, encoding='utf-8')
        return temp_dir
    except subprocess.CalledProcessError as e:
        raise IOError(f"Failed to initialize Git: {e.stderr}")
    except Exception as e:
        raise IOError(f"File operation failed: {e}")


def _run_tests_in_workspace(
    workspace_path: str, 
    feature_test_patch: str, 
    f2p_test_names: list[str], 
    p2p_test_names: list[str]
) -> tuple[int, int, bool, str]:
    """
    🚀 更改 (CHANGE): 
    此函數現在會自動查找並安裝 test-requirements.txt
    (This function will now automatically find and install test-requirements.txt)
    """
    venv_path = os.path.join(workspace_path, 'venv')
    
    if platform.system() == "Windows":
        python_executable = os.path.join(venv_path, 'Scripts', 'python.exe')
        pip_executable = os.path.join(venv_path, 'Scripts', 'pip.exe')
    else:
        python_executable = os.path.join(venv_path, 'bin', 'python')
        pip_executable = os.path.join(venv_path, 'bin', 'pip')

    full_log = []
    
    f2p_passed_count = 0
    f2p_total_count = len(f2p_test_names) # 總數是 F2P 列表的長度
    regression_tests_passed = False
    
    try:
        # 1. 創建 Venv (Create Venv)
        print(f"Creating venv at {venv_path}...")
        result = subprocess.run([sys.executable, '-m', 'venv', venv_path], cwd=workspace_path, capture_output=True, check=False)
        log_stdout = result.stdout.decode('utf-8', errors='replace')
        log_stderr = result.stderr.decode('utf-8', errors='replace')
        full_log.append(f"--- Venv Creation ---\n{log_stdout}\n{log_stderr}")
        if result.returncode != 0:
            # 方案三：Venv 创建失败视为环境错误
            return 0, f2p_total_count, False, f"ENV_ERROR: Failed to create venv.\n{log_stderr}"

        # 2a. 安裝核心測試套件
        print("Installing modern test dependencies (pytest, trustme, pytest-json-report, setuptools)...")
        deps_to_install = ['pytest', 'trustme', 'pytest-json-report', 'setuptools']
        install_cmd = [pip_executable, 'install'] + deps_to_install
        result = subprocess.run(install_cmd, cwd=workspace_path, capture_output=True, check=False)
        log_stdout = result.stdout.decode('utf-8', errors='replace')
        log_stderr = result.stderr.decode('utf-8', errors='replace')
        full_log.append(f"--- Dependency Installation (Step 1/3) ---\n{log_stdout}\n{log_stderr}")
        if result.returncode != 0:
            full_log.append("FATAL: Step 1/3 (pytest installation) failed, aborting test run.")
            # 方案三：标记为环境错误
            return 0, f2p_total_count, False, "ENV_ERROR: " + "\n".join(full_log)
            
        # 🚀 更改 (CHANGE): 步驟 2b - 使用 os.walk 遞歸查找依賴檔案
        print("Searching for project-specific test requirements...")
        # (將列表轉換為集合 (Set) 以加快查找速度)
        dev_req_files_set = set(['requirements-dev.txt','requirements.txt','rtd_requirements.txt','requirements_test_min.txt','requirements_test_pre_commit.txt','requirements_test.txt', 'test-requirements.txt', 'requirements-tests.txt', 'dev-requirements.txt'])
        found_dev_req = False
        for root, dirs, files in os.walk(workspace_path):
            # 避免搜索 .git 和 venv 目錄
            if '.git' in dirs: dirs.remove('.git')
            if 'venv' in dirs: dirs.remove('venv')
            
            if found_dev_req: break # 找到一個就立即停止搜索

            for file_name in files:
                if file_name in dev_req_files_set:
                    req_path = os.path.join(root, file_name)
                    found_dev_req = True
                    
                    # (使用相對路徑進行日誌記錄，更清晰)
                    rel_req_path = os.path.relpath(req_path, workspace_path)
                    print(f"Found {rel_req_path}. Installing test dependencies...")
                    
                    install_cmd_dev = [pip_executable, 'install', '-r', req_path]
                    result_dev = subprocess.run(install_cmd_dev, cwd=workspace_path, capture_output=True, check=False)
                    log_stdout_dev = result_dev.stdout.decode('utf-8', errors='replace')
                    log_stderr_dev = result_dev.stderr.decode('utf-8', errors='replace')
                    
                    full_log.append(f"--- Dependency Installation (Step 2/3: {rel_req_path}) ---\n{log_stdout_dev}\n{log_stderr_dev}")
                    
                    if result_dev.returncode != 0:
                        print(f"WARNING: Failed to install some dependencies from {rel_req_path}. {log_stderr_dev}")
                        full_log.append(f"WARNING: Installation of {rel_req_path} failed. This may or may not be critical.")
                        # 方案三：检查是否是严重错误
                        if "error" in log_stderr_dev.lower() and "could not find" in log_stderr_dev.lower():
                            print(f"CRITICAL: Dependency installation failed critically.")
                            return 0, f2p_total_count, False, "ENV_ERROR: " + "\n".join(full_log)
                    
                    break # 找到一個就跳出內部循環 (files loop)
        
        if not found_dev_req:
            print("No project-specific test requirement files found. Proceeding.")
            full_log.append("--- Dependency Installation (Step 2/3) ---\nNo project-specific test requirements file found.")
            
        # 2c. 安裝專案本身 (原來的 2b)
        if os.path.exists(os.path.join(workspace_path, 'setup.py')):
            print("Found setup.py. Installing package in editable mode...")
            install_cmd_no_test = [pip_executable, 'install', '-e .']
            result_no_test = subprocess.run(install_cmd_no_test, cwd=workspace_path, capture_output=True, check=False)
            log_stdout = result_no_test.stdout.decode('utf-8', errors='replace')
            log_stderr = result_no_test.stderr.decode('utf-8', errors='replace')
            full_log.append(f"--- Dependency Installation (Step 3/3) ---\n{log_stdout}\n{log_stderr}")
            if result_no_test.returncode != 0:
                 print(f"WARNING: Fallback 'pip install -e .' failed. {result_no_test.stderr}")

        # 3. 應用 'test_patch'
        print(f"Applying ground-truth test patch...")
        # 🚀 更改 (CHANGE): 捕獲元組 (tuple)
        success, error_msg = _apply_patch(workspace_path, feature_test_patch)
        
        if not success:
             # 🚀 更改 (CHANGE): 將詳細錯誤添加到日誌中
             log_message = f"FATAL: Failed to apply ground-truth test patch (test_patch).\nDetails: {error_msg}"
             full_log.append(log_message)
             return 0, f2p_total_count, False, "\n".join(full_log)

        # 4. 運行測試 1：F2P 測試 (帶 JSON 報告)
        print(f"Running pytest (Test 1: {f2p_total_count} Feature Tests)...")
        f2p_report_file = os.path.join(workspace_path, 'f2p_report.json')
        # Convert test names to pytest format
        f2p_test_names_converted = [_convert_test_name_to_pytest_format(name) for name in f2p_test_names]
        pytest_cmd_feature = [python_executable, '-m', 'pytest', '--json-report', f'--json-report-file={f2p_report_file}'] + f2p_test_names_converted
        
        result_feature = subprocess.run(pytest_cmd_feature, cwd=workspace_path, capture_output=True, check=False, timeout=300)
        log_stdout = result_feature.stdout.decode('utf-8', errors='replace')
        log_stderr = result_feature.stderr.decode('utf-8', errors='replace')
        full_log.append(f"--- Pytest Execution (Feature Test) ---\n{log_stdout}\n{log_stderr}")
        
        try:
            with open(f2p_report_file, 'r') as f:
                report = json.load(f)
                f2p_passed_count = report.get('summary', {}).get('passed', 0)
            print(f"Feature test results: {f2p_passed_count} / {f2p_total_count} passed.")
        except Exception as e:
            print(f"ERROR: Could not parse f2p_report.json: {e}")
            full_log.append(f"ERROR: Could not parse f2p_report.json: {e}")

        # 5. 運行測試 2：P2P 迴歸測試
        p2p_total_count = len(p2p_test_names)
        if p2p_total_count > 0:
            print(f"Running pytest (Test 2: {p2p_total_count} Regression Tests)...")
            # Convert test names to pytest format
            p2p_test_names_converted = [_convert_test_name_to_pytest_format(name) for name in p2p_test_names]
            pytest_cmd_regression = [python_executable, '-m', 'pytest'] + p2p_test_names_converted
            result_regression = subprocess.run(pytest_cmd_regression, cwd=workspace_path, capture_output=True, check=False, timeout=300)
            log_stdout = result_regression.stdout.decode('utf-8', errors='replace')
            log_stderr = result_regression.stderr.decode('utf-8', errors='replace')
            full_log.append(f"--- Pytest Execution (Regression Tests) ---\n{log_stdout}\n{log_stderr}")
            regression_tests_passed = (result_regression.returncode == 0)
            print(f"Regression tests passed: {regression_tests_passed}")
        else:
            print("No regression tests (P2P tests) found for this instance. Setting RT% to 100%.")
            regression_tests_passed = True # 如果沒有 P2P 測試，則視為 100% 通過

        # 6. 返回兩個結果
        return f2p_passed_count, f2p_total_count, regression_tests_passed, "\n".join(full_log)

    except subprocess.TimeoutExpired:
        full_log.append("--- Pytest Execution ---\nERROR: Pytest timed out after 300 seconds.")
        return f2p_passed_count, f2p_total_count, regression_tests_passed, "\n".join(full_log)
    except Exception as e:
        full_log.append(f"--- Testing Framework Error ---\nAn unexpected error occurred: {e}")
        return f2p_passed_count, f2p_total_count, regression_tests_passed, "\n".join(full_log)


def _generate_repo_skeleton(workspace_path: str, max_files: int = 100) -> str:
    """
    方案一：生成项目骨架 (Repo Skeleton)
    包含：文件路径、类名、函数名、docstring，但不包含具体实现
    """
    skeleton_parts = []
    file_count = 0
    
    # 获取所有Python文件
    for root, dirs, files in os.walk(workspace_path):
        # 排除常见的非核心目录
        dirs[:] = [d for d in dirs if d not in ['.git', 'venv', '__pycache__', '.tox', 'node_modules', '.pytest_cache']]
        
        if file_count >= max_files:
            break
            
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, workspace_path)
                
                # 跳过测试文件
                if 'test' in rel_path.lower():
                    continue
                
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    
                    # 提取类和函数定义（简化版骨架）
                    import_lines = [line for line in content.split('\n') if line.startswith('import ') or line.startswith('from ')]
                    class_lines = [line for line in content.split('\n') if line.strip().startswith('class ')]
                    func_lines = [line for line in content.split('\n') if line.strip().startswith('def ') and not line.strip().startswith('def _')]
                    
                    if import_lines or class_lines or func_lines:
                        skeleton_parts.append(f"\n--- FILE: {rel_path} ---")
                        if import_lines:
                            skeleton_parts.append("# Imports:\n" + "\n".join(import_lines[:5]))  # 只取前5个
                        if class_lines:
                            skeleton_parts.append("# Classes:\n" + "\n".join(class_lines[:10]))
                        if func_lines:
                            skeleton_parts.append("# Functions:\n" + "\n".join(func_lines[:10]))
                        
                        file_count += 1
                        
                except Exception as e:
                    continue
    
    return "\n".join(skeleton_parts)

def _keyword_search(workspace_path: str, doc_change: str) -> list[str]:
    """
    修复版：基于关键词在代码库中搜索相关文件
    """
    import re
    
    # 1. 提取关键词 (保持不变)
    potential_identifiers = re.findall(r'\b[A-Z][a-zA-Z0-9]+\b|\b[a-z_][a-z0-9_]+\b', doc_change)
    common_words = {'the', 'and', 'for', 'with', 'this', 'that', 'from', 'will', 'should', 'must', 'can', 'may', 'example', 'test', 'file', 'code', 'change', 'fix', 'bug', 'issue'}
    keywords = {word for word in potential_identifiers if len(word) > 3 and word.lower() not in common_words}
    keywords = list(keywords)[:10]
    
    if not keywords:
        return []
    
    print(f"[Keyword Search] Searching for: {keywords}")
    
    matched_files = set()
    for keyword in keywords:
        try:
            # 2. 执行搜索 (保持不变)
            if platform.system() == "Windows":
                result = subprocess.run(
                    ['findstr', '/S', '/M', '/I', keyword, '*.py'],
                    cwd=workspace_path,
                    capture_output=True,
                    text=True,
                    timeout=20 # 增加超时时间
                )
            else:
                result = subprocess.run(
                    ['grep', '-r', '-l', '-i', keyword, '--include=*.py', '.'],
                    cwd=workspace_path,
                    capture_output=True,
                    text=True,
                    timeout=20
                )
            
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    raw_line = line.strip()
                    if raw_line and 'test' not in raw_line.lower():
                        # --- 关键修复开始 ---
                        # 1. 确保我们有一个相对于 workspace 的干净路径
                        # findstr/grep 输出通常已经是相对于 cwd 的，但为了保险：
                        
                        # 如果路径已经是绝对路径（极少见但可能），直接使用
                        if os.path.isabs(raw_line):
                            full_path = raw_line
                        else:
                            # 拼接成绝对路径
                            full_path = os.path.join(workspace_path, raw_line)
                        
                        # 2. 规范化路径（处理 .. 和冗余分隔符）
                        full_path = os.path.normpath(full_path)
                        
                        # 3. 再次检查该文件是否真的在 workspace 内部
                        # (防止符号链接跳出，或者之前的路径计算错误)
                        if not full_path.startswith(os.path.abspath(workspace_path)):
                            continue

                        # 4. 安全地计算相对路径
                        rel_path = os.path.relpath(full_path, workspace_path)
                        
                        # 5. 统一分隔符为 '/'
                        clean_path = rel_path.replace('\\', '/')
                        
                        # 6. 再次过滤掉以 .. 开头的路径 (双重保险)
                        if not clean_path.startswith('..'):
                            matched_files.add(clean_path)
                        # --- 关键修复结束 ---

        except Exception as e:
            print(f"[Keyword Search] Error searching for {keyword}: {e}")
            continue
    
    result = list(matched_files)[:5]
    print(f"[Keyword Search] Found {len(result)} files: {result}")
    return result

def _get_relevant_files_from_llm(model, doc_change: str, workspace_path: str) -> list[str]:
    """
    方案一改进：结合骨架搜索和关键词搜索
    """
    # 方案一：先进行关键词搜索
    keyword_files = _keyword_search(workspace_path, doc_change)
    
    all_files = []
    # (os.walk 迴圈保持不變)
    for root, _, files in os.walk(workspace_path):
        if '.git' in root or 'docs' in root or '.venv' in root or 'venv' in root: continue
        for file in files:
            if file.endswith(('.py', '.html', '.css', '.js', 'setup.py', 'requirements.txt')):
                rel_path = os.path.relpath(os.path.join(root, file), workspace_path)
                all_files.append(rel_path.replace('\\', '/'))
    if not all_files:
        print(f"[Task] WARNING: os.walk found NO files in {workspace_path}")
        return keyword_files  # 至少返回关键词搜索的结果
    
    # 方案一：生成骨架
    print("[Task] Generating repository skeleton...")
    skeleton = _generate_repo_skeleton(workspace_path)
    skeleton_size = len(skeleton)
    print(f"[Task] Skeleton size: {skeleton_size} characters")
    
    file_list_str = ', '.join(all_files).replace('\\', '/')
    if not file_list_str:
        print(f"[Task] WARNING: No code files found to analyze.")
        return keyword_files

    # 🚀 這是新的、更智慧的提示詞（包含骨架和关键词搜索结果）
    # 在构建 prompt_text 变量时，确保包含以下说明：
    
    system_instruction = """
    You are an expert software engineer.
    
    IMPORTANT: When you modify files, DO NOT output the entire file. 
    Output ONLY the specific code blocks that need to be changed using a SEARCH/REPLACE format.
    
    FORMAT:
    File: path/to/file.py
    <<<<
    [Original code snippet to be replaced (must match exactly)]
    ====
    [New code snippet]
    >>>>
    
    EXAMPLE:
    File: django/utils/text.py
    <<<<
    def slugify(value, allow_unicode=False):
        value = str(value)
    ====
    def slugify(value, allow_unicode=False):
        value = str(value)
        if allow_unicode:
            value = unicodedata.normalize('NFKC', value)
    >>>>
    
    RULES:
    1. Use multiple <<<< ==== >>>> blocks for multiple changes in one file.
    2. The content inside <<<< must match the original file EXACTLY (byte-for-byte), or the patch will fail.
    3. Include 2-3 lines of context around the change in the <<<< block to ensure uniqueness.
    """
    

    prompt_text = (
        f"You are an expert file locator agent. Your goal is to identify ALL files required for a code change, including dependency files.\n\n"
        f"**DOCUMENTATION CHANGE:**\n{doc_change}\n\n"
        f"**PROJECT STRUCTURE (Skeleton):**\n"
        f"{skeleton[:20000]}\n\n"  # 限制骨架大小
        f"**CODE FILE LIST:**\n{file_list_str}\n\n"
        f"**FILES FOUND BY KEYWORD SEARCH (High Priority):**\n"
        f"{', '.join(keyword_files) if keyword_files else 'None'}\n\n"
        f"**THINKING PROCESS (CRITICAL):**\n"
        "1.  **Core Logic:** Which file contains the primary code to be modified based on the documentation? (e.g., 'requests/models.py')\n"
        "2.  **New Symbols:** Does this change introduce new classes, functions, or exceptions? (e.g., 'JSONDecodeError')\n"
        "3.  **Definition:** Where should this new symbol be *defined*? (e.g., 'requests/exceptions.py')\n"
        "4.  **Dependencies (The most important step):**\n"
        "    - **Compatibility:** Is there a `compat.py` file that needs to be updated to handle this new symbol across different Python versions? (e.g., 'requests/compat.py')\n"
        "    - **Exporting:** Does this new symbol need to be made public? Check the relevant `__init__.py` file. (e.g., 'requests/__init__.py')\n"
        "    - **Imports:** Which other files *use* the code from step 1 and will now need to import the new symbol from step 3? (e.g., 'requests/models.py' imports from 'requests/exceptions.py')\n\n"
        f"**INSTRUCTIONS:**\n"
        "1.  Review your thinking process and list ALL files identified in steps 1-4.\n"
        "2.  Respond ONLY with a JSON object:\n"
        "   {\n"
        "     \"files\": [\"path/to/file1.py\", \"path/to/file2.py\", \"path/to/compat.py\", \"path/to/__init__.py\"]\n"
        "   }\n"
        "3.  **DO NOT** include any files from `test/` or `tests/` directories.\n"
        "   DO NOT include actions or code content in this step."
    )
    prompt = system_instruction + "\n\n" + prompt_text
    response_text = None
    try:
        response = model.generate_content(
            prompt,
            generation_config=GenerationConfig(
                response_mime_type="application/json"
            ),
            request_options=RequestOptions(timeout=300)  # 5 minutes timeout for file finding - FIXED
        )
        # (函數的其餘部分保持不變)
        response_text = response.text
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if not json_match:
            print(f"[Task] ERROR: AI response did not contain a JSON object. Response: {response_text}")
            return []
        json_text = json_match.group(0)
        print(f"[Task] DEBUG: File finder LLM response (extracted):\n{json_text}")
        data = json.loads(json_text)
        if "files" not in data or not isinstance(data["files"], list):
            print(f"[Task] ERROR: AI response JSON was in wrong format: {json_text}")
            return []
        llm_files = data["files"]
        valid_files = [f.strip().replace('\\', '/') for f in llm_files if f.strip() in all_files]
        
        # 方案一：强制包含关键词搜索找到的文件
        # for kw_file in keyword_files:
        #     if kw_file not in valid_files:
        #         valid_files.append(kw_file)
        #         print(f"[Task] Force-including keyword-matched file: {kw_file}")
        for kw_file in keyword_files:
            if kw_file not in valid_files:
                valid_files.append(kw_file)
                print(f"[Task] Force-including keyword-matched file: {kw_file}")
                
        if not valid_files and llm_files:
             print(f"[Task] WARNING: AI found files {llm_files}, but none were in the master 'all_files' list.")
        return valid_files
    except json.JSONDecodeError:
        print(f"[Task] ERROR: AI response was not valid JSON: {response_text}")
        return []
    except Exception as e:
        print(f"[Task] ERROR: Failed to parse AI file list: {e}\nResponse text: {response_text}")
        return []

def _get_file_contexts(workspace_path: str, relevant_files: list[str]) -> str:
    """
    读取相关文件内容并构建上下文字符串
    (Reads relevant file contents and builds context string)
    
    优化：限制单个文件大小，避免prompt过大
    """
    context_prompt_parts = []
    MAX_FILE_SIZE = 50000  # 50KB per file limit to avoid huge prompts
    MAX_TOTAL_SIZE = 200000  # 200KB total context limit
    total_size = 0
    
    for file_path in relevant_files:
        full_path = os.path.join(workspace_path, file_path)
        if not os.path.exists(full_path):
            print(f"WARNING: File `{file_path}` identified by AI does not exist. Skipping.")
            continue
        try:
            # Check file size before reading
            file_size = os.path.getsize(full_path)
            
            if file_size > MAX_FILE_SIZE:
                print(f"WARNING: File `{file_path}` is too large ({file_size} bytes). Truncating to first {MAX_FILE_SIZE} bytes.")
                with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                    file_content = f.read(MAX_FILE_SIZE)
                file_content += "\n\n... [FILE TRUNCATED DUE TO SIZE] ..."
            else:
                with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                    file_content = f.read()
            
            # Check total context size
            content_block = (
                f"--- START OF FILE: {file_path} ---\n"
                f"{file_content}\n"
                f"--- END OF FILE: {file_path} ---\n"
            )
            
            if total_size + len(content_block) > MAX_TOTAL_SIZE:
                print(f"WARNING: Total context size would exceed {MAX_TOTAL_SIZE} bytes. Skipping remaining files.")
                context_prompt_parts.append(
                    f"\n... [REMAINING FILES SKIPPED DUE TO CONTEXT SIZE LIMIT] ...\n"
                )
                break
            
            context_prompt_parts.append(content_block)
            total_size += len(content_block)
            
        except Exception as e:
            print(f"Error reading file {file_path}: {e}")
    
    result = "\n".join(context_prompt_parts)
    print(f"[Context] Total context size: {len(result)} characters ({len(relevant_files)} files)")
    return result

def _parse_v7_response(raw_response_text: str) -> dict[str, str]:
    """
    (此函數保持不變)
    (This function is unchanged)
    """
    pattern = re.compile(
        r"File:\s*(.*?)\n\s*<<<<\n(.*?)\n====\n(.*?)\n>>>>", 
        re.DOTALL
    )

    matches = pattern.findall(raw_response_text)
    
    if not matches:
        # 如果沒有匹配到块格式，嘗試回退到舊的 "全文件重寫" 格式检查
        if "--- START OF FILE:" in raw_response_text:
            print("WARNING: Falling back to legacy FULL FILE parsing.")
            file_chunks = re.split(r'--- START OF FILE: (.*?) ---\n', raw_response_text)
            for i in range(1, len(file_chunks), 2):
                file_path = file_chunks[i].strip()
                content_part = file_chunks[i+1]
                content = re.sub(r'--- END OF FILE: .*? ---', '', content_part, flags=re.DOTALL).strip()
                modified_files[file_path] = content
            return modified_files
        
        print("WARNING: No valid code blocks found in AI response.")
        return {}
    file_changes = {}
    for file_path, search_block, replace_block in matches:
        file_path = file_path.strip()
        if file_path not in file_changes:
            file_changes[file_path] = []
        file_changes[file_path].append((search_block, replace_block))

    for file_path, changes in file_changes.items():
        pass
    pass
    raise NotImplementedError("由于架构限制，请使用下面的 '方案 B' 修改 run_agent_attempt")


# --- 指標計算 (Metrics Calculation) ---
# (parse_patch 和 calculate_f1_score 保持不變)
def parse_patch(patch_str: str) -> dict[str, set[int]]:
    if not patch_str: return {}
    try:
        patch = PatchSet(StringIO(patch_str))
        changed_files = {}
        for patched_file in patch:
            if patched_file.is_binary_file: continue
            file_path = patched_file.target_file[2:] if patched_file.target_file.startswith('b/') else patched_file.target_file
            changed_lines = set()
            for hunk in patched_file:
                for line in hunk:
                    if line.is_added:
                        changed_lines.add(line.target_line_no)
                    elif line.is_removed:
                        changed_lines.add(line.source_line_no)
            if changed_lines:
                changed_files[file_path] = changed_lines
        return changed_files
    except Exception as e:
        print(f"Error parsing patch: {e}\nPatch content:\n{patch_str[:500]}...")
        return {}

def calculate_f1_score(pred_set: set, gold_set: set) -> float:
    if not gold_set: return 1.0 if not pred_set else 0.0
    if not pred_set: return 0.0
    tp = len(pred_set.intersection(gold_set))
    fp = len(pred_set.difference(gold_set))
    fn = len(gold_set.difference(pred_set))
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
    return f1

def calculate_all_metrics(
    f2p_passed_count: int,
    f2p_total_count: int,
    regression_tests_passed: bool,
    applied_successfully: bool, 
    generated_patch: str, 
    ground_truth_patch: str, 
    run_time_seconds: float
) -> dict:
    """
    (此函數與 V14/V19 版本完全相同)
    (This function is identical to the V14/V19 version)
    """
    
    # 1. Success% 和 RT%
    success_percent = 100.0 if (f2p_passed_count == f2p_total_count and f2p_total_count > 0) else 0.0
    rt_percent = 100.0 if regression_tests_passed else 0.0
    applied_percent = 100.0 if applied_successfully else 0.0

    # 2. FV-Macro (每個實例)
    fv_macro = 100.0 * (f2p_passed_count / f2p_total_count) if f2p_total_count > 0 else 0.0

    # 3. File% (精確率)
    pred_files_lines = parse_patch(generated_patch)
    gold_files_lines = parse_patch(ground_truth_patch)
    pred_file_set = set(pred_files_lines.keys())
    gold_file_set = set(gold_files_lines.keys())
    
    file_intersection = len(pred_file_set.intersection(gold_file_set))
    if len(pred_file_set) == 0:
        file_percent = 100.0 if len(gold_file_set) == 0 else 0.0
    else:
        file_percent = (file_intersection / len(pred_file_set)) * 100.0

    return {
        'success_percent': success_percent,
        'applied_percent': applied_percent,
        'rt_percent': rt_percent,
        'fv_macro': fv_macro,
        'file_percent': file_percent,
        'num_token': len(generated_patch.split()),
        'run_time_seconds': run_time_seconds,
        'f2p_passed_count': f2p_passed_count,
        'f2p_total_count': f2p_total_count,
    }

# --- 核心 Agent 工作函數 (Core Agent Worker Function) ---

def run_agent_attempt_with_reflexion(
    workspace_path: str,
    model,
    initial_prompt: str,
    feature_test_patch: str,
    f2p_test_names: list[str],
    p2p_test_names: list[str],
    max_reflexion_iterations: int = 3  # 方案二：最大自校正次数
) -> dict:
    """
    方案二：实现 Reflexion (Self-Correction Loop)
    运行 Agent 并根据测试失败进行自我调试和重试
    """
    print(f"[Reflexion] Starting with max {max_reflexion_iterations} iterations...")
    
    for iteration in range(max_reflexion_iterations):
        print(f"\n[Reflexion] === Iteration {iteration + 1}/{max_reflexion_iterations} ===")
        
        # 构建当前迭代的 prompt
        if iteration == 0:
            current_prompt = initial_prompt
        else:
            # 在后续迭代中，添加上一次的错误信息
            current_prompt = (
                f"{initial_prompt}\n\n"
                f"**PREVIOUS ATTEMPT FAILED**\n"
                f"Your previous code changes did not pass the tests. Here is the test output:\n\n"
                f"```\n{last_test_output}\n```\n\n"
                f"**INSTRUCTIONS FOR RETRY:**\n"
                f"1. Carefully analyze the test failure messages above\n"
                f"2. Identify what went wrong in your previous implementation\n"
                f"3. Generate corrected code that fixes these specific errors\n"
                f"4. Make sure to address ALL failing tests\n"
                f"5. Do NOT repeat the same mistakes\n"
            )
        
        # 运行一次尝试
        result = run_agent_attempt(
            workspace_path=workspace_path,
            model=model,
            prompt_text=current_prompt,
            feature_test_patch=feature_test_patch,
            f2p_test_names=f2p_test_names,
            p2p_test_names=p2p_test_names
        )
        
        # 检查结果
        status = result.get('status', '')
        
        # 方案三：环境错误不重试
        if status == 'ENV_ERROR':
            print(f"[Reflexion] Environment error detected. Cannot retry.")
            return result
        
        # 如果通过测试，返回成功
        if status == 'PASSED':
            print(f"[Reflexion] SUCCESS after {iteration + 1} iteration(s)!")
            result['reflexion_iterations'] = iteration + 1
            return result
        
        # 如果是最后一次迭代，返回失败
        if iteration == max_reflexion_iterations - 1:
            print(f"[Reflexion] FAILED after {max_reflexion_iterations} iterations.")
            result['reflexion_iterations'] = max_reflexion_iterations
            return result
        
        # 准备下一次迭代
        last_test_output = result.get('test_output', 'No test output available')
        print(f"[Reflexion] Test failed. Preparing retry with error feedback...")
    
    # 不应该到达这里
    return result


def run_agent_attempt(
    workspace_path: str, 
    model, 
    prompt_text: str, 
    feature_test_patch: str,  # 🚀 新增 (NEW)
    f2p_test_names: list[str],  # 🚀 新增 (NEW)
    p2p_test_names: list[str]   # 🚀 新增 (NEW)
) -> dict:
    """
    運行一次 Agent 嘗試：重置、編碼、寫入、差異比較、測試。
    (Runs one agent attempt: reset, code, write, diff, test.)
    注意：这个函数现在由 run_agent_attempt_with_reflexion 调用
    """
    
    raw_response_text = ""
    final_patch_str = ""
    test_output = ""
    
    try:
        # 重置工作區 (Reset workspace)
        subprocess.run(['git', 'reset', '--hard', 'HEAD'], cwd=workspace_path, capture_output=True, text=True, check=True)
        
        # 1. 生成程式碼 (Generate Code) with timeout and retry
        max_retries = 1  # Increased from 2 to 3
        retry_count = 0
        response = None
        last_error = None
        
        while retry_count < max_retries:
            try:
                prompt_size = len(prompt_text)
                print(f"[Task] Calling Gemini API (attempt {retry_count + 1}/{max_retries})...")
                print(f"[Task] Prompt size: {prompt_size} characters (~{prompt_size/4:.0f} tokens)")
                response = model.generate_content(
                    prompt_text,
                    request_options=RequestOptions(timeout=300)  # 15 minutes timeout - FIXED: using RequestOptions object
                )
                raw_response_text = response.text
                break  # Success, exit retry loop
            except Exception as api_error:
                last_error = api_error
                retry_count += 1
                error_str = str(api_error)
                
                if "504" in error_str or "Deadline Exceeded" in error_str:
                    if retry_count < max_retries:
                        wait_time = 5 * retry_count  # Reduced wait time (5s instead of 10s)
                        print(f"[Task] API timeout (504). Retrying in {wait_time}s... (attempt {retry_count}/{max_retries})")
                        time.sleep(wait_time)
                    else:
                        print(f"[Task] API timeout after {max_retries} attempts. Giving up.")
                        return {
                            'status': 'APPLY_FAILED', 
                            'error': f"Gemini API timeout after {max_retries} attempts: {error_str}",
                            'patch': '', 'raw_response': '',
                            'f2p_passed_count': 0, 'f2p_total_count': 0, 'regression_tests_passed': False
                        }
                else:
                    # Non-timeout error, don't retry
                    print(f"[Task] API error (non-timeout): {error_str}")
                    return {
                        'status': 'APPLY_FAILED', 
                        'error': f"Gemini API error: {error_str}",
                        'patch': '', 'raw_response': '',
                        'f2p_passed_count': 0, 'f2p_total_count': 0, 'regression_tests_passed': False
                    }
        
        if response is None:
            return {
                'status': 'APPLY_FAILED', 
                'error': f"Failed to get API response after {max_retries} attempts",
                'patch': '', 'raw_response': '',
                'f2p_passed_count': 0, 'f2p_total_count': 0, 'regression_tests_passed': False
            }
        
        # 2. 解析回應 (Parse Response)
        try:
            modified_files = _parse_v7_response(raw_response_text)
        except Exception as e:
            print(f"ERROR: AI response parsing failed: {e}\nRaw Response: {raw_response_text[:1000]}")
            return {
                'status': 'APPLY_FAILED', 'error': f"AI response parsing failed: {e}",
                'patch': '', 'raw_response': raw_response_text,
                'f2p_passed_count': 0, 'f2p_total_count': 0, 'regression_tests_passed': False
            }

        # 3. 將新內容寫入文件 (Write new contents to files)
        for file_path, new_content in modified_files.items():
            try:
                if '..' in file_path: continue
                full_path = os.path.join(workspace_path, file_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
            except Exception as e:
                 return {
                    'status': 'APPLY_FAILED', 'error': f"Failed to write file {file_path} to disk: {e}",
                    'patch': '', 'raw_response': raw_response_text,
                    'f2p_passed_count': 0, 'f2p_total_count': 0, 'regression_tests_passed': False
                }

        # 4. 生成補丁 (Generate Patch)
        diff_result = subprocess.run(
            ['git', 'diff', '--no-prefix'], 
            cwd=workspace_path, capture_output=True, text=True, check=True, encoding='utf-8'
        )
        final_patch_str = diff_result.stdout
        
        if not final_patch_str:
             return {
                'status': 'TEST_FAILED', 'patch': '',
                'test_output': 'AI agent produced no code changes.',
                'raw_response': raw_response_text,
                'f2p_passed_count': 0, 'f2p_total_count': 0,
                'regression_tests_passed': False,
            }

        # 5. 🚀 更改 (CHANGE): 運行兩種測試
        # (Run both test types)
        f2p_passed_count, f2p_total_count, regression_tests_passed, test_output = _run_tests_in_workspace(
            workspace_path, 
            feature_test_patch,
            f2p_test_names,
            p2p_test_names
        )
        
        # 方案三：检查是否是环境错误
        if test_output.startswith("ENV_ERROR:"):
            return {
                'status': 'ENV_ERROR',
                'error': test_output,
                'patch': final_patch_str,
                'test_output': test_output,
                'raw_response': raw_response_text,
                'f2p_passed_count': 0,
                'f2p_total_count': f2p_total_count,
                'regression_tests_passed': False,
            }
        
        if f2p_total_count > 0 and f2p_passed_count == f2p_total_count:
            return {
                'status': 'PASSED', 'patch': final_patch_str,
                'test_output': test_output, 'raw_response': raw_response_text,
                'f2p_passed_count': f2p_passed_count,
                'f2p_total_count': f2p_total_count,
                'regression_tests_passed': regression_tests_passed,
            }
        else:
            return {
                'status': 'TEST_FAILED', 'patch': final_patch_str,
                'test_output': test_output, 'raw_response': raw_response_text,
                'f2p_passed_count': f2p_passed_count,
                'f2p_total_count': f2p_total_count,
                'regression_tests_passed': regression_tests_passed,
            }
        
    except Exception as e:
        print(f"FATAL ERROR in run_agent_attempt: {e}")
        return {
            'status': 'APPLY_FAILED',
            'error': f"An unexpected error occurred in the agent worker: {e}",
            'patch': final_patch_str,
            'test_output': test_output,
            'raw_response': raw_response_text,
            'f2p_passed_count': 0, 'f2p_total_count': 0, 'regression_tests_passed': False
        }

def setup_custom_workspace(github_url: str) -> str:
    """
    從一個 Git URL 複製並初始化一個工作區。
    """
    run_id = str(time.time()).replace('.', '')
    # 產生一個唯一的目錄名稱
    repo_name = github_url.split('/')[-1].replace('.git', '')
    temp_dir = os.path.join(ROOT_WORKSPACE, f'demo_{repo_name}_{run_id}')
    
    try:
        # 複製 Git 倉庫
        print(f"Cloning repo from {github_url} into {temp_dir}...")
        subprocess.run(
            ['git', 'clone', '--depth', '1', github_url, temp_dir],
            check=True, capture_output=True, text=True, encoding='utf-8'
        )
        
        # (可選，但推薦) 初始化 Git，以便我們可以 'git diff'
        subprocess.run(['git', 'init'], cwd=temp_dir, check=True, capture_output=True, text=True, encoding='utf-8')
        subprocess.run(['git', 'add', '.'], cwd=temp_dir, check=True, capture_output=True, text=True, encoding='utf-8')
        subprocess.run(['git', 'commit', '-m', 'Initial snapshot', '--allow-empty'], cwd=temp_dir, check=True, capture_output=True, text=True, encoding='utf-8')
        print(f"Workspace initialized at {temp_dir}")
        return temp_dir
        
    except subprocess.CalledProcessError as e:
        raise IOError(f"Failed to clone Git repo: {e.stderr}")
    except Exception as e:
        raise IOError(f"File operation failed: {e}")

# ... (在 run_agent_attempt 旁邊)

def run_agent_demo_attempt(
    workspace_path: str, 
    model, 
    prompt_text: str
) -> dict:
    """
    運行一次 Agent 嘗試，但 *不執行* 任何測試。
    (Runs one agent attempt, but does *not* run tests.)
    """
    
    raw_response_text = ""
    final_patch_str = ""
    
    try:
        # 重置工作區
        subprocess.run(['git', 'reset', '--hard', 'HEAD'], cwd=workspace_path, capture_output=True, text=True, check=True)
        
        # 1. 生成程式碼 with timeout
        response = model.generate_content(
            prompt_text,
            request_options=RequestOptions(timeout=300)  # 5 minutes timeout - FIXED
        )
        raw_response_text = response.text
        
        # 2. 解析回應
        try:
            modified_files = _parse_v7_response(raw_response_text)
        except Exception as e:
            print(f"ERROR: AI response parsing failed: {e}")
            return {'status': 'APPLY_FAILED', 'patch': '', 'raw_response': raw_response_text}

        # 3. 將新內容寫入文件
        for file_path, new_content in modified_files.items():
            try:
                if '..' in file_path: continue
                full_path = os.path.join(workspace_path, file_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
            except Exception as e:
                 return {'status': 'APPLY_FAILED', 'patch': '', 'raw_response': raw_response_text}

        # 4. 生成補丁
        diff_result = subprocess.run(
            ['git', 'diff', '--no-prefix'], 
            cwd=workspace_path, capture_output=True, text=True, check=True, encoding='utf-8'
        )
        final_patch_str = diff_result.stdout
        
        # 5. 成功返回 (不運行測試)
        return {
            'status': 'COMPLETED', # 狀態總是 COMPLETED，因為沒有測試
            'patch': final_patch_str,
            'raw_response': raw_response_text,
        }
        
    except Exception as e:
        print(f"FATAL ERROR in run_agent_demo_attempt: {e}")
        return {'status': 'APPLY_FAILED', 'patch': '', 'raw_response': raw_response_text}

