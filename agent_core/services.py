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
# 🚀 新增 (NEW): 測試文件的來源
# (Source for test files)
TEST_DATASET_ROOT = os.path.join(settings.BASE_DIR, 'NoCode-bench_Verified', 'test')


# --- 權限錯誤處理 (Permission Error Handler) ---
def onerror(func, path, exc_info):
    if not os.access(path, os.W_OK):
        os.chmod(path, stat.S_IWUSR | stat.S_IWRITE)
        func(path)
    else:
        raise

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


def _run_tests_in_workspace(workspace_path: str, nocode_bench_id: str) -> tuple[int, int, bool, str]:
    """
    🚀 更改 (CHANGE): 
    運行兩種測試：新功能測試 (test.py) 和迴歸測試 (pytest)。
    返回 (f2p_passed_count, f2p_total_count, regression_tests_passed, full_log)
    
    (Run both tests: the new feature test (test.py) and regression tests (pytest).)
    (Returns (f2p_passed_count, f2p_total_count, regression_tests_passed, full_log))
    """
    venv_path = os.path.join(workspace_path, 'venv')
    
    if platform.system() == "Windows":
        python_executable = os.path.join(venv_path, 'Scripts', 'python.exe')
        pip_executable = os.path.join(venv_path, 'Scripts', 'pip.exe')
    else:
        python_executable = os.path.join(venv_path, 'bin', 'python')
        pip_executable = os.path.join(venv_path, 'bin', 'pip')

    full_log = []
    
    # 最終結果 (Final results)
    f2p_passed_count = 0
    f2p_total_count = 0
    regression_tests_passed = False
    
    try:
        # 1. 創建 Venv (Create Venv)
        print(f"Creating venv at {venv_path}...")
        result = subprocess.run([sys.executable, '-m', 'venv', venv_path], cwd=workspace_path, capture_output=True, check=False)
        log_stdout = result.stdout.decode('utf-8', errors='replace')
        log_stderr = result.stderr.decode('utf-8', errors='replace')
        full_log.append(f"--- Venv Creation ---\n{log_stdout}\n{log_stderr}")
        if result.returncode != 0:
            return 0, 0, False, f"Failed to create venv.\n{log_stderr}"

        # 2a. 🚀 更改 (CHANGE): 安裝現代測試套件 + json-report
        # (Install modern test suite + json-report)
        print("Installing modern test dependencies (pytest, trustme, pytest-json-report)...")
        deps_to_install = ['pytest', 'trustme', 'pytest-json-report']
        install_cmd = [pip_executable, 'install'] + deps_to_install
        result = subprocess.run(install_cmd, cwd=workspace_path, capture_output=True, check=False)
        log_stdout = result.stdout.decode('utf-8', errors='replace')
        log_stderr = result.stderr.decode('utf-8', errors='replace')
        full_log.append(f"--- Dependency Installation (Step 1/2) ---\n{log_stdout}\n{log_stderr}")
        if result.returncode != 0:
            full_log.append("FATAL: Step 1/2 failed, aborting test run.")
            return 0, 0, False, "\n".join(full_log)

        # 2b. 安裝專案本身 (Install project itself)
        if os.path.exists(os.path.join(workspace_path, 'setup.py')):
            print("Found setup.py. Installing package in editable mode...")
            install_cmd_no_test = [pip_executable, 'install', '-e .']
            result_no_test = subprocess.run(install_cmd_no_test, cwd=workspace_path, capture_output=True, check=False)
            log_stdout = result_no_test.stdout.decode('utf-8', errors='replace')
            log_stderr = result_no_test.stderr.decode('utf-8', errors='replace')
            full_log.append(f"--- Dependency Installation (Step 2/2) ---\n{log_stdout}\n{log_stderr}")
            if result_no_test.returncode != 0:
                 print(f"WARNING: Fallback 'pip install -e .' failed. {result_no_test.stderr}")

        # 3. 複製新功能測試文件 (Copy the new feature test file)
        feature_test_src_path = os.path.join(TEST_DATASET_ROOT, nocode_bench_id, 'test.py')
        feature_test_dest_path = os.path.join(workspace_path, 'test_new_feature.py')
        if not os.path.exists(feature_test_src_path):
            full_log.append(f"FATAL: Feature test file not found at {feature_test_src_path}")
            return 0, 0, False, "\n".join(full_log)
        shutil.copy(feature_test_src_path, feature_test_dest_path)
        print(f"Copied feature test file to {feature_test_dest_path}")

        # 4. 🚀 運行測試 1：新功能測試 (帶 JSON 報告)
        # (Run Test 1: The Feature Test (with JSON report))
        print("Running pytest (Test 1: Feature Test)...")
        f2p_report_file = os.path.join(workspace_path, 'f2p_report.json')
        pytest_cmd_feature = [python_executable, '-m', 'pytest', 'test_new_feature.py', '--json-report', f'--json-report-file={f2p_report_file}']
        result_feature = subprocess.run(pytest_cmd_feature, cwd=workspace_path, capture_output=True, check=False, timeout=300)
        log_stdout = result_feature.stdout.decode('utf-8', errors='replace')
        log_stderr = result_feature.stderr.decode('utf-8', errors='replace')
        full_log.append(f"--- Pytest Execution (Feature Test) ---\n{log_stdout}\n{log_stderr}")
        
        # 🚀 新增 (NEW): 解析 F2P 測試計數
        # (Parse F2P test counts)
        try:
            with open(f2p_report_file, 'r') as f:
                report = json.load(f)
                f2p_total_count = report.get('summary', {}).get('total', 0)
                f2p_passed_count = report.get('summary', {}).get('passed', 0)
            print(f"Feature test results: {f2p_passed_count} / {f2p_total_count} passed.")
        except Exception as e:
            print(f"ERROR: Could not parse f2p_report.json: {e}")
            full_log.append(f"ERROR: Could not parse f2p_report.json: {e}")

        # 5. 運行測試 2：迴歸測試 (Run Test 2: The Regression Tests)
        print("Running pytest (Test 2: Regression Tests)...")
        pytest_cmd_regression = [python_executable, '-m', 'pytest', '--ignore=test_new_feature.py'] 
        result_regression = subprocess.run(pytest_cmd_regression, cwd=workspace_path, capture_output=True, check=False, timeout=300)
        log_stdout = result_regression.stdout.decode('utf-8', errors='replace')
        log_stderr = result_regression.stderr.decode('utf-8', errors='replace')
        full_log.append(f"--- Pytest Execution (Regression Tests) ---\n{log_stdout}\n{log_stderr}")
        regression_tests_passed = (result_regression.returncode == 0)
        print(f"Regression tests passed: {regression_tests_passed}")

        # 6. 返回兩個結果 (Return both results)
        return f2p_passed_count, f2p_total_count, regression_tests_passed, "\n".join(full_log)

    except subprocess.TimeoutExpired:
        full_log.append("--- Pytest Execution ---\nERROR: Pytest timed out after 300 seconds.")
        return f2p_passed_count, f2p_total_count, regression_tests_passed, "\n".join(full_log)
    except Exception as e:
        full_log.append(f"--- Testing Framework Error ---\nAn unexpected error occurred: {e}")
        return f2p_passed_count, f2p_total_count, regression_tests_passed, "\n".join(full_log)


def _get_relevant_files_from_llm(model, doc_change: str, workspace_path: str) -> list[str]:
    """
    (此函數保持不變)
    (This function is unchanged)
    """
    all_files = []
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

    prompt = (
        f"You are a file locator agent. Based on the documentation change below, identify the most relevant CODE files to modify from the provided file list.\n\n"
        f"**DOCUMENTATION CHANGE:**\n{doc_change}\n\n"
        f"**CODE FILE LIST:**\n{file_list_str}\n\n"
        f"**INSTRUCTIONS:**\n"
        "Respond ONLY with a JSON object in the following format:\n"
        "{\n"
        "  \"files\": [\"path/to/file1.py\", \"path/to/file2.py\"]\n"
        "}\n"
        "Include ONLY files from the list provided. If no files are relevant, return an empty list: {\"files\": []}."
    )
    
    response_text = None
    try:
        response = model.generate_content(
            prompt,
            generation_config=GenerationConfig(
                response_mime_type="application/json"
            )
        )
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
# (parse_patch and calculate_f1_score are unchanged)
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
    f2p_passed_count: int,       # 🚀 更改 (CHANGE)
    f2p_total_count: int,        # 🚀 更改 (CHANGE)
    regression_tests_passed: bool, # 🚀 更改 (CHANGE)
    applied_successfully: bool, 
    generated_patch: str, 
    ground_truth_patch: str, 
    run_time_seconds: float
) -> dict:
    """
    計算 NoCode-bench 所需的全套指標。
    (Calculates the full suite of metrics required by NoCode-bench.)
    """
    
    # 1. 🚀 更改 (CHANGE): 指標計算
    # (Metric Calculations)
    
    # Success% = 新功能測試是否 100% 通過？ 
    # (Are new feature tests 100% passed?)
    success_percent = 100.0 if (f2p_passed_count == f2p_total_count and f2p_total_count > 0) else 0.0
    
    # RT% = 迴歸測試是否 100% 通過？ 
    # (Are regression tests 100% passed?)
    rt_percent = 100.0 if regression_tests_passed else 0.0
    
    applied_percent = 100.0 if applied_successfully else 0.0

    # 2. FV-Macro (每個實例) [cite: 461]
    # (FV-Macro (per-instance))
    fv_macro = 100.0 * (f2p_passed_count / f2p_total_count) if f2p_total_count > 0 else 0.0

    # 3. File% (精確率) [cite: 379]
    # (File% (Precision))
    pred_files_lines = parse_patch(generated_patch)
    gold_files_lines = parse_patch(ground_truth_patch)
    pred_file_set = set(pred_files_lines.keys())
    gold_file_set = set(gold_files_lines.keys())
    
    file_intersection = len(pred_file_set.intersection(gold_file_set))
    if len(pred_file_set) == 0:
        file_percent = 100.0 if len(gold_file_set) == 0 else 0.0
    else:
        # TP / (TP + FP) or TP / len(pred_set)
        file_percent = (file_intersection / len(pred_file_set)) * 100.0

    return {
        'success_percent': success_percent,
        'applied_percent': applied_percent,
        'rt_percent': rt_percent,
        'fv_micro': 0.0, # 將在 summary API 中計算 [cite: 459]
                         # (Will be calculated in summary API)
        'fv_macro': fv_macro, # 每個實例的 FV-Macro [cite: 461]
                              # (Per-instance FV-Macro)
        'file_percent': file_percent,
        'num_token': len(generated_patch.split()),      # [cite: 377]
        'run_time_seconds': run_time_seconds,         # 運行時間
                                                      # (Runtime)
        'f2p_passed_count': f2p_passed_count,         # 🚀 新增 (NEW)
        'f2p_total_count': f2p_total_count,           # 🚀 新增 (NEW)
    }

# --- 核心 Agent 工作函數 (Core Agent Worker Function) ---

def run_agent_attempt(workspace_path: str, model, prompt_text: str, nocode_bench_id: str) -> dict: # 🚀 更改 (CHANGE)
    """
    運行一次 Agent 嘗試：重置、編碼、寫入、差異比較、測試。
    (Runs one agent attempt: reset, code, write, diff, test.)
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
                'status': 'APPLY_FAILED',
                'error': f"AI response parsing failed: {e}",
                'patch': '',
                'raw_response': raw_response_text,
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
                    'status': 'APPLY_FAILED',
                    'error': f"Failed to write file {file_path} to disk: {e}",
                    'patch': '',
                    'raw_response': raw_response_text,
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
                'status': 'TEST_FAILED',
                'patch': '',
                'test_output': 'AI agent produced no code changes.',
                'raw_response': raw_response_text,
                'f2p_passed_count': 0,
                'f2p_total_count': 0,
                'regression_tests_passed': False,
            }

        # 5. 🚀 更改 (CHANGE): 運行兩種測試
        # (Run both test types)
        f2p_passed_count, f2p_total_count, regression_tests_passed, test_output = _run_tests_in_workspace(
            workspace_path, 
            nocode_bench_id
        )
        
        # 🚀 更改 (CHANGE): 根據 f2p 計數決定狀態
        # (Determine status based on f2p counts)
        if f2p_total_count > 0 and f2p_passed_count == f2p_total_count:
            # 100% 通過新功能測試 
            # (100% pass on new feature tests)
            return {
                'status': 'PASSED',
                'patch': final_patch_str,
                'test_output': test_output,
                'raw_response': raw_response_text,
                'f2p_passed_count': f2p_passed_count,
                'f2p_total_count': f2p_total_count,
                'regression_tests_passed': regression_tests_passed,
            }
        else:
            # 未能通過所有新功能測試
            # (Failed to pass all new feature tests)
            return {
                'status': 'TEST_FAILED',
                'patch': final_patch_str,
                'test_output': test_output,
                'raw_response': raw_response_text,
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