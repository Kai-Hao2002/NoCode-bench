# agent_core/services.py
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
from google.generativeai.types import GenerationConfig
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
        
# 🚀 新增 (NEW): 用於應用補丁的輔助函數
# (Helper function for applying patches)
def _apply_patch(workspace_path: str, patch_str: str) -> tuple[bool, str | None]:
    """
    將一個補丁字符串應用到 Git 倉庫。
    """
    if not patch_str:
        return False, "Warning: Empty patch string provided."
    
    # 嘗試 1: 標準應用 (Standard apply)
    # 嘗試 2: 忽略空白與換行符 (Ignore whitespace and newlines - CRITICAL FOR WINDOWS)
    # 嘗試 3: 忽略上下文不匹配 (Recalculate context - use with caution)
    
    commands_to_try = [
        ['git', 'apply', '--ignore-whitespace', '--verbose'],
        ['git', 'apply', '--ignore-space-change', '--ignore-whitespace', '--verbose'],
        ['git', 'apply', '--recount', '--unidiff-zero', '--ignore-whitespace', '--verbose'] # 強力模式
    ]

    last_error = ""

    for cmd in commands_to_try:
        try:
            result = subprocess.run(
                cmd,
                input=patch_str,
                cwd=workspace_path,
                text=True,
                check=False,
                capture_output=True,
                encoding='utf-8' # 確保編碼正確
            )
            if result.returncode == 0:
                return True, None
            
            last_error = result.stderr
        except Exception as e:
            last_error = str(e)

    # 如果所有嘗試都失敗
    error_msg = f"git apply failed after multiple attempts. Last error: {last_error}"
    print(f"ERROR: {error_msg}")
    return False, error_msg


# --- 輔助函數 (Helper Functions) ---

def setup_workspace(nocode_bench_id: str) -> str:
    """
    (此函數保持不變)
    (This function is unchanged)
    """
    parts = nocode_bench_id.split('__')
    repo_owner = parts[0]
    match = re.match(r'^(.*?)-(\d+)$', parts[1])
    if match:
        repo_name_base = match.group(1) # e.g., 'scikit-learn', 'matplotlib'
    else:
        # 如果 regex 匹配失敗，退回到舊的（可能有缺陷的）邏輯
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
) -> tuple[int, int, int, int, str]: # 🚀 更改 (CHANGE): 返回 4 個計數器
    """
    🚀 更改 (CHANGE): 
    此函數現在運行 *所有* 測試一次，並從一個 JSON 報告中解析 F2P 和 P2P 的計數。
    這解決了 WinError 206（檔名太長）的問題。
    """
    venv_path = os.path.join(workspace_path, 'venv')
    
    if platform.system() == "Windows":
        python_executable = os.path.join(venv_path, 'Scripts', 'python.exe')
        pip_executable = os.path.join(venv_path, 'Scripts', 'pip.exe')
    else:
        python_executable = os.path.join(venv_path, 'bin', 'python')
        pip_executable = os.path.join(venv_path, 'bin', 'pip')

    full_log = []
    
    # 初始化所有 4 個計數器
    f2p_passed_count = 0
    f2p_total_count = len(f2p_test_names)
    p2p_passed_count = 0
    p2p_total_count = len(p2p_test_names)
    
    try:
        # --- 步驟 1-3：安裝 (與之前相同) ---
        
        # 1. 創建 Venv
        # (我們保留 Python 3.9/3.8 的回退邏輯，以解決依賴地獄)
        print("Creating venv...")
        python_exec_to_try = ['python3.9', 'python3.8', sys.executable]
        venv_created = False
        log_stdout = ""
        log_stderr = ""
        
        for py_exec in python_exec_to_try:
            print(f"Attempting to create venv with {py_exec}...")
            full_log.append(f"--- Venv Creation (Attempt: {py_exec}) ---")
            try:
                result = subprocess.run(
                    [py_exec, '-m', 'venv', venv_path], 
                    cwd=workspace_path, capture_output=True, check=True,
                    text=True, encoding='utf-8', errors='replace'
                )
                log_stdout = result.stdout
                log_stderr = result.stderr
                full_log.append(f"{log_stdout}\n{log_stderr}")
                venv_created = True
                print(f"Successfully created venv with {py_exec}.")
                break 
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                log_stderr = str(e)
                full_log.append(f"Failed to create venv with {py_exec}: {log_stderr}")
        
        if not venv_created:
            return 0, f2p_total_count, 0, p2p_total_count, f"Failed to create venv. Last error: {log_stderr}"

        # 1a. 安裝核心測試套件
        print("Installing modern test dependencies (pytest, trustme, pytest-json-report, setuptools)...")
        deps_to_install = ['pytest', 'trustme', 'pytest-json-report', 'setuptools']
        install_cmd = [pip_executable, 'install'] + deps_to_install
        result = subprocess.run(install_cmd, cwd=workspace_path, capture_output=True, check=False)
        log_stdout = result.stdout.decode('utf-8', errors='replace')
        log_stderr = result.stderr.decode('utf-8', errors='replace')
        full_log.append(f"--- Dependency Installation (Step 1/3) ---\n{log_stdout}\n{log_stderr}")
        if result.returncode != 0:
            full_log.append("FATAL: Step 1/3 failed, aborting test run.")
            return 0, f2p_total_count, 0, p2p_total_count, "\n".join(full_log)
            

        # 2. 安裝專案的測試依賴項 (os.walk)
        print("Searching for project-specific test requirements...")
        dev_req_files_set = set(['requirements-dev.txt','requirements.txt','rtd_requirements.txt','requirements_test_min.txt','requirements_test_pre_commit.txt','requirements_test.txt', 'test-requirements.txt', 'requirements-tests.txt', 'dev-requirements.txt'])
        found_dev_req = False
        for root, dirs, files in os.walk(workspace_path):
            if '.git' in dirs: dirs.remove('.git')
            if 'venv' in dirs: dirs.remove('venv')
            if found_dev_req: break
            for file_name in files:
                if file_name in dev_req_files_set:
                    req_path = os.path.join(root, file_name)
                    found_dev_req = True
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
                    break
        
        if not found_dev_req:
            print("No project-specific test requirement files found. Proceeding.")
            full_log.append("--- Dependency Installation (Step 2/3) ---\nNo project-specific test requirements file found.")
            
        # 3. 安裝專案本身
        if os.path.exists(os.path.join(workspace_path, 'setup.py')):
            print("Found setup.py. Installing package in editable mode...")
            install_cmd_no_test = [pip_executable, 'install', '-e .']
            result_no_test = subprocess.run(install_cmd_no_test, cwd=workspace_path, capture_output=True, check=False)
            log_stdout = result_no_test.stdout.decode('utf-8', errors='replace')
            log_stderr = result_no_test.stderr.decode('utf-8', errors='replace')
            full_log.append(f"--- Dependency Installation (Step 3/3) ---\n{log_stdout}\n{log_stderr}")
            if result_no_test.returncode != 0:
                 print(f"WARNING: Fallback 'pip install -e .' failed. {result_no_test.stderr}")

        # 4. 應用 'test_patch'
        print(f"Applying ground-truth test patch...")
        success, error_msg = _apply_patch(workspace_path, feature_test_patch)
        if not success:
             log_message = f"FATAL: Failed to apply ground-truth test patch (test_patch).\nDetails: {error_msg}"
             full_log.append(log_message)
             return 0, f2p_total_count, 0, p2p_total_count, "\n".join(full_log)

        # --- 步驟 5：運行所有測試 (新) ---
        
        print(f"Running pytest (All tests) with JSON report...")
        report_file = os.path.join(workspace_path, 'combined_report.json')
        
        # 🚀 更改 (CHANGE): 我們只運行 'pytest'，不傳遞任何單獨的測試名稱。
        # 這避免了 WinError 206。
        pytest_cmd = [python_executable, '-m', 'pytest', '--json-report', f'--json-report-file={report_file}']
        
        # (我們使用 600 秒 (10 分鐘) 的 timeout)
        result_all = subprocess.run(pytest_cmd, cwd=workspace_path, capture_output=True, check=False, timeout=600)
        log_stdout = result_all.stdout.decode('utf-8', errors='replace')
        log_stderr = result_all.stderr.decode('utf-8', errors='replace')
        full_log.append(f"--- Pytest Execution (Combined) ---\n{log_stdout}\n{log_stderr}")
        
        # --- 步驟 6：解析組合報告 (新) ---
        
        try:
            with open(report_file, 'r') as f:
                report = json.load(f)
            
            # 創建快速查找集合
            f2p_set = set(f2p_test_names)
            p2p_set = set(p2p_test_names)
            
            if 'tests' in report:
                for test in report['tests']:
                    nodeid = test.get('nodeid')
                    outcome = test.get('outcome')
                    
                    if outcome == 'passed':
                        if nodeid in f2p_set:
                            f2p_passed_count += 1
                        elif nodeid in p2p_set:
                            p2p_passed_count += 1
            
            print(f"Feature test results: {f2p_passed_count} / {f2p_total_count} passed.")
            print(f"Regression test results: {p2p_passed_count} / {p2p_total_count} passed.")
            
        except Exception as e:
            print(f"ERROR: Could not parse {report_file}: {e}")
            full_log.append(f"ERROR: Could not parse {report_file}: {e}")

        # 7. 返回所有 4 個計數器
        return f2p_passed_count, f2p_total_count, p2p_passed_count, p2p_total_count, "\n".join(full_log)

    except subprocess.TimeoutExpired:
        full_log.append("--- Pytest Execution ---\nERROR: Pytest timed out after 600 seconds.")
        return f2p_passed_count, f2p_total_count, p2p_passed_count, p2p_total_count, "\n".join(full_log)
    except Exception as e:
        full_log.append(f"--- Testing Framework Error ---\nAn unexpected error occurred: {e}")
        return f2p_passed_count, f2p_total_count, p2p_passed_count, p2p_total_count, "\n".join(full_log)


def _get_relevant_files_from_llm(model, doc_change: str, workspace_path: str) -> list[str]:
    """
    (此函數保持不變)
    """
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
        return []
    file_list_str = ', '.join(all_files).replace('\\', '/')
    if not file_list_str:
        print(f"[Task] WARNING: No code files found to analyze.")
        return []

    # 🚀 這是新的、更智慧的提示詞
    # In agent_core/services.py

    prompt = (
        f"You are an expert file locator agent. Your goal is to identify ALL files required for a code change, AND files that might break due to side effects.\n\n"
        f"**DOCUMENTATION CHANGE:**\n{doc_change}\n\n"
        f"**CODE FILE LIST:**\n{file_list_str}\n\n"
        f"**THINKING PROCESS:**\n"
        "1.  **Core Logic:** Where is the primary code change? (e.g., 'utils.py')\n"
        "2.  **Impact Analysis (CRITICAL FOR REGRESSION):** Who IMPORTS or USES the code from step 1? If you modify a shared function, you MUST inspect the files that call it to ensure backward compatibility.\n" # <--- 新增這行 (Added this)
        "3.  **Dependencies:** Check `compat.py` and `__init__.py`.\n"
        "4.  **Selection:** List the files to modify AND the files to read for context.\n\n"
        f"**INSTRUCTIONS:**\n"
        "1.  Respond ONLY with a JSON object: {{\"files\": [\"path/to/mod.py\", \"path/to/caller.py\"]}}\n"
        "2.  It is better to include a few extra 'caller' files to prevent regression bugs than to miss them.\n" # <--- 鼓勵多選 (Encourage slightly lower precision for better context)
    )
    response_text = None
    try:
        response = model.generate_content(
            prompt,
            generation_config=GenerationConfig(
                response_mime_type="application/json"
            )
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
    (此函數保持不變)
    (This function is unchanged)
    """
    context_prompt_parts = []
    # ... (此函數的其餘部分保持不變) ...
    for file_path in relevant_files:
        full_path = os.path.join(workspace_path, file_path)
        if not os.path.exists(full_path):
            print(f"WARNING: File `{file_path}` identified by AI does not exist. Skipping.")
            continue
        try:
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                file_content = f.read()
            context_prompt_parts.append(
                f"--- START OF FILE: {file_path} ---\n"
                f"{file_content}\n"
                f"--- END OF FILE: {file_path} ---\n"
            )
        except Exception as e:
            print(f"Error reading file {file_path}: {e}")
    return "\n".join(context_prompt_parts)

def _parse_v7_response(raw_response_text: str) -> dict[str, str]:
    """
    (此函數保持不變)
    (This function is unchanged)
    """
    modified_files = {}
    # ... (此函數的其餘部分保持不變) ...
    file_chunks = re.split(r'--- START OF FILE: (.*?) ---\n', raw_response_text)
    if len(file_chunks) < 2:
        raise ValueError("AI response did not contain any '--- START OF FILE: ' delimiters.")
    for i in range(1, len(file_chunks), 2):
        file_path = file_chunks[i].strip()
        content_part = file_chunks[i+1]
        content = re.sub(r'--- END OF FILE: .*? ---', '', content_part, flags=re.DOTALL).strip()
        if file_path and content:
            modified_files[file_path] = content
        else:
            print(f"WARNING: Could not parse file chunk: Filepath='{file_path}', Content preview='{content[:50]}...'")
    if not modified_files:
        raise ValueError("AI response was parsed, but no valid file content blocks were found.")
    return modified_files


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
    # 🚀 新增 (NEW): P2P 計數器
    p2p_passed_count: int,
    p2p_total_count: int,
    regression_tests_passed: bool, # (我們仍然接受這個，但會忽略它)
    applied_successfully: bool, 
    generated_patch: str, 
    ground_truth_patch: str, 
    run_time_seconds: float
) -> dict:
    """
    🚀 更改 (CHANGE): 此函數現在接受 P2P 計數器並計算 RT% 百分比。
    """
    
    # 1. Success% 和 RT%
    success_percent = 100.0 if (f2p_passed_count == f2p_total_count and f2p_total_count > 0) else 0.0
    applied_percent = 100.0 if applied_successfully else 0.0
    
    # 🚀 更改 (CHANGE): RT% 現在是 P2P 測試的百分比
    # (如果沒有 P2P 測試，則 RT% 為 100%)
    rt_percent = 100.0 * (p2p_passed_count / p2p_total_count) if p2p_total_count > 0 else 100.0
    
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
        'rt_percent': rt_percent, # 🚀 現在是百分比
        'fv_macro': fv_macro,
        'file_percent': file_percent,
        'num_token': len(generated_patch.split()),
        'run_time_seconds': run_time_seconds,
        'f2p_passed_count': f2p_passed_count,
        'f2p_total_count': f2p_total_count,
        'p2p_passed_count': p2p_passed_count, # 🚀 新增 (NEW)
        'p2p_total_count': p2p_total_count,   # 🚀 新增 (NEW)
    }

# --- 核心 Agent 工作函數 (Core Agent Worker Function) ---

def run_agent_attempt(
    workspace_path: str, 
    model, 
    prompt_text: str, 
    feature_test_patch: str,
    f2p_test_names: list[str],
    p2p_test_names: list[str]
) -> dict:
    """
    執行一次 Agent 嘗試：生成代碼 -> 應用 -> 測試。
    (Executes one Agent attempt: Generate Code -> Apply -> Test.)
    
    🚀 重大修改 (MAJOR CHANGE): 
    現在實施「嚴格通過標準」(Strict Passing Criteria)。
    只有當 F2P (新功能) 和 P2P (舊功能) 全部通過時，才視為成功。
    (Now enforces Strict Passing Criteria. Only considered successful if BOTH F2P and P2P pass.)
    """
    
    raw_response_text = ""
    final_patch_str = ""
    test_output = ""
    
    try:
        # 重置工作區 (Reset workspace)
        subprocess.run(['git', 'reset', '--hard', 'HEAD'], cwd=workspace_path, capture_output=True, text=True, check=True)
        
        # 1. 生成程式碼 (Generate Code)
        response = model.generate_content(prompt_text)
        raw_response_text = response.text
        
        # 2. 解析回應 (Parse Response)
        try:
            modified_files = _parse_v7_response(raw_response_text)
        except Exception as e:
            print(f"ERROR: AI response parsing failed: {e}\nRaw Response: {raw_response_text[:1000]}")
            return {
                'status': 'APPLY_FAILED', 'error': f"AI response parsing failed: {e}",
                'patch': '', 'raw_response': raw_response_text,
                'f2p_passed_count': 0, 'f2p_total_count': 0, 
                'p2p_passed_count': 0, 'p2p_total_count': 0,
                'regression_tests_passed': False
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
                    'f2p_passed_count': 0, 'f2p_total_count': 0, 
                    'p2p_passed_count': 0, 'p2p_total_count': 0,
                    'regression_tests_passed': False
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
                'p2p_passed_count': 0, 'p2p_total_count': 0,
                'regression_tests_passed': False,
            }

        # 5. 運行組合測試並捕獲 4 個計數器 (Run combined tests and capture 4 counters)
        f2p_passed_count, f2p_total_count, p2p_passed_count, p2p_total_count, test_output = _run_tests_in_workspace(
            workspace_path, 
            feature_test_patch,
            f2p_test_names,
            p2p_test_names
        )
        
        # --- 🚀 關鍵修改邏輯 (CRITICAL MODIFIED LOGIC) ---
        
        # 判斷 F2P 是否全過 (Check if all Feature tests passed)
        feature_tests_passed = (f2p_passed_count == f2p_total_count) if f2p_total_count > 0 else False
        
        # 判斷 P2P 是否全過 (Check if all Regression tests passed)
        # 如果沒有 P2P 測試 (count=0)，預設視為通過
        regression_tests_passed = (p2p_passed_count == p2p_total_count) if p2p_total_count > 0 else True
        
        # 只有當 "兩者皆為 True" 時，才算任務成功 (COMPLETED/PASSED)
        # Only consider the task successful if BOTH are True
        if feature_tests_passed and regression_tests_passed:
            status = 'PASSED'
        else:
            status = 'TEST_FAILED' 
            # 注意：即使 F2P 通過了，如果 Regression 失敗，這裡也會變成 TEST_FAILED。
            # 這樣 tasks.py 就會捕捉到並進行重試。
            # Note: Even if F2P passed, if Regression failed, this becomes TEST_FAILED.
            # This ensures tasks.py catches it and triggers a retry.

        return {
            'status': status, 
            'patch': final_patch_str,
            'test_output': test_output, 
            'raw_response': raw_response_text,
            'f2p_passed_count': f2p_passed_count,
            'f2p_total_count': f2p_total_count,
            'p2p_passed_count': p2p_passed_count,
            'p2p_total_count': p2p_total_count,
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
            'f2p_passed_count': 0, 'f2p_total_count': 0, 
            'p2p_passed_count': 0, 'p2p_total_count': 0,
            'regression_tests_passed': False
        }

def setup_custom_workspace(github_url: str) -> str:
    """
    (此函數保持不變)
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
    (此函數保持不變)
    """
    
    raw_response_text = ""
    final_patch_str = ""
    
    try:
        # 重置工作區
        subprocess.run(['git', 'reset', '--hard', 'HEAD'], cwd=workspace_path, capture_output=True, text=True, check=True)
        
        # 1. 生成程式碼
        response = model.generate_content(prompt_text)
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