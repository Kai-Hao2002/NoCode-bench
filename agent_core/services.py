import os
import sys
import shutil
import subprocess
import time
import re
import stat
from google import generativeai as genai
from django.conf import settings
from django.db import connection

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

# --- 輔助函數 (Helper Functions) ---
def extract_code_from_response(response_text: str) -> str:
    """從 AI 回應中穩定地提取第一個 markdown 程式碼區塊內的完整程式碼。"""
    match = re.search(r"```(python|py)?\n(.*?)```", response_text, re.DOTALL)
    if match:
        return match.group(2).strip()
    return response_text.strip()

def setup_workspace(nocode_bench_id: str) -> str:
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
        subprocess.run(['git', 'init'], cwd=temp_dir, check=True, capture_output=True, text=True)
        subprocess.run(['git', 'add', '.'], cwd=temp_dir, check=True, capture_output=True, text=True)
        subprocess.run(['git', 'commit', '-m', 'Initial snapshot', '--allow-empty'], cwd=temp_dir, check=True, capture_output=True, text=True)
        initial_commit_hash = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=temp_dir, check=True, capture_output=True, text=True).stdout.strip()
        with open(os.path.join(temp_dir, '.initial_commit'), 'w') as f:
            f.write(initial_commit_hash)
        return temp_dir
    except subprocess.CalledProcessError as e:
        raise IOError(f"Failed to initialize Git: {e.stderr}")
    except Exception as e:
        raise IOError(f"File operation failed: {e}")

def apply_patch_to_repo(temp_dir: str, patch_code: str) -> tuple[bool, str]:
    if not patch_code.strip():
        return False, "Patch content was empty."
    try:
        result = subprocess.run(
            ['git', 'apply', '--ignore-whitespace'],
            input=patch_code, cwd=temp_dir, text=True, check=False, capture_output=True
        )
        if result.returncode == 0:
            return True, None
        return False, f"Git apply failed. Stderr: {result.stderr.strip()}"
    except Exception as e:
        return False, f"An unexpected error occurred during git apply: {e}"

def calculate_metrics(tests_passed, applied_successfully, patch_code, run_time_seconds):
    if tests_passed:
        success_percent, applied_percent = 100.0, 100.0
    elif applied_successfully:
        success_percent, applied_percent = 0.0, 100.0
    else:
        success_percent, applied_percent = 0.0, 0.0
    return {
        'success_percent': success_percent, 'applied_percent': applied_percent,
        'rt_percent': run_time_seconds, 'fv_micro': 0.0, 'fv_macro': 0.0,
        'file_percent': 0.0, 'num_token': len(patch_code.split()),
    }

def _get_relevant_files_from_llm(model, doc_change: str, workspace_path: str) -> list[str]:
    all_files = []
    for root, _, files in os.walk(workspace_path):
        if '.git' in root or 'docs' in root: continue
        for file in files:
            if file.endswith(('.py', '.html', '.css', '.js', 'setup.py', 'requirements.txt')):
                all_files.append(os.path.relpath(os.path.join(root, file), workspace_path))
    prompt = (
        f"You are a file locator agent. Based on the documentation change below, identify the most relevant CODE files to modify from the provided file list.\n\n"
        f"**DOCUMENTATION CHANGE:**\n{doc_change}\n\n"
        f"**CODE FILE LIST:**\n{', '.join(all_files)}\n\n"
        "**INSTRUCTIONS:** Your output MUST ONLY be a comma-separated list of file paths."
    )
    response = model.generate_content(prompt)
    return [f.strip().replace('\\', '/') for f in response.text.split(',') if f.strip()]

# --- 核心 Agent 函數 (Core Agent Function) ---
def run_gemini_agent(task_id: int, nocode_bench_id: str, doc_change: str):
    if not settings.GEMINI_API_KEY:
        return {'error': "Gemini client not configured. Check GEMINI_API_KEY.", 'status': 'FAILED'}
    genai.configure(api_key=settings.GEMINI_API_KEY)
    start_time = time.time()
    workspace_path = None
    try:
        workspace_path = setup_workspace(nocode_bench_id)
        model = genai.GenerativeModel('gemini-2.5-flash')

        relevant_files = _get_relevant_files_from_llm(model, doc_change, workspace_path)
        if not relevant_files:
            return {'error': "AI failed to identify any relevant CODE files to modify.", 'status': 'FAILED'}
        
        print(f"DEBUG: AI identified files to modify: {relevant_files}")
        
        for file_to_modify in relevant_files:
            full_path = os.path.join(workspace_path, file_to_modify)
            if not os.path.exists(full_path):
                print(f"WARNING: File `{file_to_modify}` identified by AI does not exist. Skipping.")
                continue

            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                original_content = f.read()

            prompt = (
                f"You are an expert AI software engineer. Your task is to rewrite a single file to implement a feature while maintaining backward compatibility.\n\n"
                f"**DOCUMENTATION CHANGE TO IMPLEMENT:**\n{doc_change}\n\n"
                f"**ORIGINAL FULL CONTENT OF THE FILE `{file_to_modify}`:**\n```python\n{original_content}\n```\n\n"
                "**CRITICAL INSTRUCTIONS:**\n"
                "1. Your entire response MUST BE a single markdown code block containing the new, complete, and modified version of the file.\n"
                "2. **IMPORTANT**: Ensure your changes are backward-compatible. Do not remove or rename existing classes or functions if other parts of the code might still be using them. If adding a new exception, consider inheriting from an existing one to maintain compatibility.\n"
                "3. DO NOT output a diff/patch. Output the FULL file content.\n"
                "4. DO NOT include any explanatory text."
            )
            
            response = model.generate_content(prompt)
            modified_content = extract_code_from_response(response.text)
            
            if not modified_content:
                 print(f"WARNING: AI did not generate modified content for {file_to_modify}. Skipping.")
                 continue

            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(modified_content)
            
            subprocess.run(['git', 'add', file_to_modify], cwd=workspace_path, check=True)
            subprocess.run(['git', 'commit', '-m', f'AI modification for {file_to_modify}'], cwd=workspace_path, check=True)
            print(f"--- Successfully overwrote and committed file {file_to_modify}.")

        with open(os.path.join(workspace_path, '.initial_commit'), 'r') as f:
            initial_commit_hash = f.read().strip()
        
        diff_result = subprocess.run(['git', 'diff', initial_commit_hash, 'HEAD'], cwd=workspace_path, text=True, capture_output=True)
        final_patch_str = diff_result.stdout
        
        if not final_patch_str:
            return {'error': "AI modifications resulted in no effective code changes.", 'status': 'FAILED_APPLY', 'generated_patch': ''}

        print("\n" + "="*20 + " DEBUG: FINAL MACHINE-GENERATED PATCH " + "="*20)
        print(final_patch_str)
        print("="*24 + " END OF PATCH " + "="*24 + "\n")

        subprocess.run(['git', 'reset', '--hard', initial_commit_hash], cwd=workspace_path, check=True)
        
        applied_successfully, git_error = apply_patch_to_repo(workspace_path, final_patch_str)
        if not applied_successfully:
            return {'status': 'FAILED_APPLY', 'error': f"FATAL: Failed to apply the self-generated patch. {git_error}", 'generated_patch': final_patch_str}

        # --- 建立並準備隔離的虛擬環境 (Create and Prepare Isolated Virtual Environment) ---
        print("--- Creating isolated virtual environment for testing... ---")
        venv_path = os.path.join(workspace_path, '.venv_test')
        subprocess.run([sys.executable, '-m', 'venv', venv_path], check=True, capture_output=True, text=True)

        python_executable = os.path.join(venv_path, 'Scripts', 'python.exe') if sys.platform == "win32" else os.path.join(venv_path, 'bin', 'python')
        
        def run_command(cmd, cwd):
            try:
                subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError as e:
                raise IOError(
                    f"Command failed: `{' '.join(cmd)}`\n"
                    f"Return Code: {e.returncode}\n"
                    f"Stdout: {e.stdout}\n"
                    f"Stderr: {e.stderr}"
                )

        print("--- Installing dependencies in isolated environment... ---")
        run_command([python_executable, '-m', 'pip', 'install', '--upgrade', 'pip', 'setuptools'], cwd=workspace_path)
        run_command([python_executable, '-m', 'pip', 'install', 'pytest', 'trustme'], cwd=workspace_path)
        
        if os.path.exists(os.path.join(workspace_path, 'setup.py')):
             run_command([python_executable, '-m', 'pip', 'install', '.[test]'], cwd=workspace_path)
        elif os.path.exists(os.path.join(workspace_path, 'requirements.txt')):
            run_command([python_executable, '-m', 'pip', 'install', '-r', 'requirements.txt'], cwd=workspace_path)

        print("--- Running tests in isolated environment... ---")
        pytest_executable = os.path.join(venv_path, 'Scripts', 'pytest.exe') if sys.platform == "win32" else os.path.join(venv_path, 'bin', 'pytest')
        
        # 🚀 修正：捕捉 stdout 和 stderr (FIX: Capture both stdout and stderr)
        test_result = subprocess.run([pytest_executable], cwd=workspace_path, text=True, check=False, capture_output=True)
        tests_passed = (test_result.returncode == 0)
        test_output = f"Stdout: {test_result.stdout}\nStderr: {test_result.stderr}"
            
        run_time = time.time() - start_time
        final_results = calculate_metrics(tests_passed, True, final_patch_str, run_time)
        final_results['generated_patch'] = final_patch_str
        
        if tests_passed:
            final_results['status'] = 'COMPLETED'
        else:
            final_results['status'] = 'FAILED_TEST'
            final_results['error'] = f"Pytest failed. Full output:\n{test_output[:2000]}"

        return final_results
        
    except Exception as e:
        return {'error': f"An unexpected error occurred in the agent: {e}", 'status': 'FAILED'}
    finally:
        connection.close()
        if workspace_path and os.path.exists(workspace_path):
            shutil.rmtree(workspace_path, onerror=onerror)

