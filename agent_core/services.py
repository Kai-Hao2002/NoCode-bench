import os
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
def extract_patch_from_response(response_text: str) -> str:
    match = re.search(r"```(diff|python|py)?\n(.*?)```", response_text, re.DOTALL)
    if match:
        return match.group(2).strip()
    if response_text.strip().startswith(('---', 'diff --git')):
        return response_text.strip()
    return ""

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
        return temp_dir
    except subprocess.CalledProcessError as e:
        raise IOError(f"Failed to initialize Git: {e.stderr}")
    except Exception as e:
        raise IOError(f"File operation failed: {e}")

def apply_patch_to_repo(temp_dir: str, patch_code: str) -> tuple[bool, str]:
    if not patch_code.strip():
        return False, "Patch content was empty or invalid."
    try:
        result = subprocess.run(
            ['git', 'apply', '--verbose', '-p1', '--3way', '--recount', '--ignore-whitespace', '--whitespace=fix'],
            input=patch_code, cwd=temp_dir, text=True, check=False, capture_output=True
        )
        if result.returncode == 0:
            return True, None
        else:
            status_result = subprocess.run(['git', 'status', '--porcelain'], cwd=temp_dir, text=True, capture_output=True)
            if status_result.stdout.strip():
                return True, f"Patch applied with conflicts. Stderr: {result.stderr.strip()}"
            return False, f"Git apply failed. Stderr: {result.stderr.strip()} | Stdout: {result.stdout.strip()}"
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

# --- 🚀 兩階段 AI 策略函數 (Two-Pass AI Strategy Functions) ---
def _get_relevant_files_from_llm(model, doc_change: str, workspace_path: str) -> list[str]:
    all_files = []
    for root, _, files in os.walk(workspace_path):
        if '.git' in root: continue
        for file in files:
            all_files.append(os.path.relpath(os.path.join(root, file), workspace_path))
    prompt = (
        f"You are a file locator agent. Based on the documentation change below, identify the most relevant files to modify from the provided file list.\n\n"
        f"**DOCUMENTATION CHANGE:**\n{doc_change}\n\n"
        f"**FILE LIST:**\n{', '.join(all_files)}\n\n"
        "**INSTRUCTIONS:**\n"
        "1. List the full paths of the files that most likely need to be changed.\n"
        "2. Your output MUST ONLY be a comma-separated list of file paths. Do not include any other text."
    )
    response = model.generate_content(prompt)
    return [f.strip().replace('\\', '/') for f in response.text.split(',') if f.strip() and not f.strip().endswith(('.rst', '.md'))]

def _get_full_context_from_files(workspace_path: str, file_list: list[str]) -> str:
    context = []
    for file_path in file_list:
        full_path = os.path.join(workspace_path, file_path)
        if os.path.exists(full_path):
            try:
                with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    context.append(f"--- Full content of file: {file_path} ---\n{content}\n")
            except Exception:
                continue
    return "\n".join(context)

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

        # --- 🚀 執行兩階段策略 (Execute Two-Pass Strategy) ---
        relevant_files = _get_relevant_files_from_llm(model, doc_change, workspace_path)
        if not relevant_files:
            return {'error': "AI failed to identify any relevant CODE files to modify.", 'status': 'FAILED'}

        full_context = _get_full_context_from_files(workspace_path, relevant_files)
        
        # 🚀 終極提示詞：加入嚴格的負面指令 (Ultimate Prompt: Add strict negative constraints)
        prompt = (
            f"You are an expert AI software engineer. Generate a unified diff CODE patch to implement a feature.\n\n"
            f"**DOCUMENTATION CHANGE TO IMPLEMENT:**\n{doc_change}\n\n"
            f"**FULL CONTENT OF RELEVANT CODE FILES:**\n{full_context}\n\n"
            "**CRITICAL INSTRUCTIONS:**\n"
            "1. Your entire response MUST ONLY be the required CODE patch in the unified diff format.\n"
            "2. Each file's changes MUST be preceded by its own `diff --git` header.\n"
            "3. **DO NOT** generate patches for documentation files (`.rst`, `.md`). Your output must only contain changes for CODE files (`.py`, etc.).\n"
            "4. **DO NOT** include any explanatory text, greetings, or apologies. Only the diff."
        )

        response = model.generate_content(prompt)
        patch_code = extract_patch_from_response(response.text)

        print("\n" + "="*20 + " DEBUG: AI GENERATED PATCH " + "="*20)
        print(patch_code)
        print("="*24 + " END OF PATCH " + "="*24 + "\n")

        applied_successfully, git_error = apply_patch_to_repo(workspace_path, patch_code)
        tests_passed = False
        test_stderr = None
        if applied_successfully:
            # Install dependencies before running tests
            if os.path.exists(os.path.join(workspace_path, 'requirements.txt')):
                subprocess.run(['pip', 'install', '-r', 'requirements.txt'], cwd=workspace_path, check=True, capture_output=True, text=True)
            elif os.path.exists(os.path.join(workspace_path, 'setup.py')):
                 subprocess.run(['pip', 'install', '.'], cwd=workspace_path, check=True, capture_output=True, text=True)
            
            test_result = subprocess.run(['pytest'], cwd=workspace_path, text=True, check=False, capture_output=True)
            tests_passed = (test_result.returncode == 0)
            test_stderr = test_result.stderr
            
        run_time = time.time() - start_time
        final_results = calculate_metrics(tests_passed, applied_successfully, patch_code, run_time)
        final_results['generated_patch'] = patch_code
        if tests_passed:
            final_results['status'] = 'COMPLETED'
        elif applied_successfully:
            final_results['status'] = 'FAILED_TEST'
            final_results['error'] = f"Pytest failed. Stderr: {test_stderr[:1000]}"
        else:
            final_results['status'] = 'FAILED_APPLY'
            final_results['error'] = f"Git Apply failed. {git_error}"
        return final_results
        
    except Exception as e:
        return {'error': f"An unexpected error occurred in the agent: {e}", 'status': 'FAILED'}
    finally:
        connection.close()
        if workspace_path and os.path.exists(workspace_path):
            shutil.rmtree(workspace_path, onerror=onerror)

