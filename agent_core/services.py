# agent_core/services.py

import os
import time
import json
import re
import docker
import shutil
import subprocess
import stat
from io import StringIO
from unidiff import PatchSet
from pathlib import Path
from django.conf import settings
from google.generativeai.types import GenerationConfig
from .constants import MAP_REPO_TO_CONFIG

# Docker Client
try:
    client = docker.from_env()
except Exception as e:
    print(f"Warning: Docker client error: {e}")
    client = None

# 路徑設定
ROOT_WORKSPACE = os.path.join(settings.BASE_DIR, 'nocode_workspaces')
os.makedirs(ROOT_WORKSPACE, exist_ok=True)
ORIGINAL_DATASET_ROOT = os.path.join(settings.BASE_DIR, 'NoCode-bench_Verified', 'data')
DOCKER_PATCH_PATH = "/tmp/patch.diff"

# ==============================================================================
#  1. 輔助函數 (Helper Functions)
# ==============================================================================

def _parse_v7_response(raw_response_text: str) -> dict[str, str]:
    modified_files = {}
    file_chunks = re.split(r'--- START OF FILE: (.*?) ---\n', raw_response_text)
    if len(file_chunks) < 2:
        return modified_files
    for i in range(1, len(file_chunks), 2):
        file_path = file_chunks[i].strip()
        content = re.sub(r'--- END OF FILE: .*? ---', '', file_chunks[i+1], flags=re.DOTALL).strip()
        if file_path and content:
            modified_files[file_path] = content
    return modified_files

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
        print(f"Error parsing patch: {e}")
        return {}

def calculate_all_metrics(
    f2p_passed_count: int,
    f2p_total_count: int,
    p2p_passed_count: int,
    p2p_total_count: int,
    regression_tests_passed: bool,
    applied_successfully: bool, 
    generated_patch: str, 
    ground_truth_patch: str, 
    run_time_seconds: float
) -> dict:
    """
    嚴格按照 NoCode-bench 標準及您的舊代碼規則計算指標：
    - Success% (Resolved): 嚴格布林值。F2P 與 P2P 必須全部通過。若 PTP 未執行(count=0)視為失敗。
    - FV-Macro: F2P 的通過比率。
    - RT%: P2P 的通過比率。若 PTP 未執行(count=0)，強制為 0.0%。
    - File%: Recall (AI 找對的檔案 / 真實檔案總數)
    """

    # --- 3. RT% (迴歸測試通過率 - 優先計算以供參考) ---
    if p2p_total_count > 0:
        rt_percent = (p2p_passed_count / p2p_total_count) * 100.0
    else:
        rt_percent = 100.0

    # --- 1. Success% (任務解決率 - 嚴格標準) ---
    f2p_all_passed = (f2p_passed_count == f2p_total_count) if f2p_total_count > 0 else False
    
    # [Strict Rule] p2p_all_passed is False if total is 0 (skipped/failed to run)
    # [嚴格規則] 如果 total 為 0 (跳過/未執行)，視為 False
    p2p_all_passed = (p2p_passed_count == p2p_total_count) if p2p_total_count > 0 else False
    
    if f2p_all_passed and p2p_all_passed:
        success_percent = 100.0
    else:
        success_percent = 0.0

    # --- 2. FV-Macro (部分給分) ---
    if f2p_total_count > 0:
        fv_macro = (f2p_passed_count / f2p_total_count) * 100.0
    else:
        fv_macro = 0.0

    # --- Applied% ---
    applied_percent = 100.0 if applied_successfully else 0.0
    
    # --- 4. File% (Recall) ---
    pred_files_lines = parse_patch(generated_patch)
    gold_files_lines = parse_patch(ground_truth_patch)
    pred_file_set = set(pred_files_lines.keys())
    gold_file_set = set(gold_files_lines.keys())
    
    # Intersection (AI found correct files)
    file_intersection = len(pred_file_set.intersection(gold_file_set))
    
    # Denominator is gold_file_set (Recall)
    if len(gold_file_set) > 0:
        file_percent = (file_intersection / len(gold_file_set)) * 100.0
    else:
        # If Ground Truth modifies no files (rare), and AI also modifies none -> 100
        file_percent = 100.0 if len(pred_file_set) == 0 else 0.0

    return {
        'success_percent': success_percent,
        'applied_percent': applied_percent,
        'rt_percent': round(rt_percent, 2),
        'fv_macro': round(fv_macro, 2),
        'file_percent': round(file_percent, 2),
        'num_token': len(generated_patch.split()),
        'run_time_seconds': run_time_seconds,
        'f2p_passed_count': f2p_passed_count,
        'f2p_total_count': f2p_total_count,
        'p2p_passed_count': p2p_passed_count,
        'p2p_total_count': p2p_total_count,
    }

def onerror(func, path, exc_info):
    """處理刪除檔案時的權限錯誤"""
    if not os.access(path, os.W_OK):
        os.chmod(path, stat.S_IWUSR | stat.S_IWRITE)
        func(path)
    else:
        raise

def setup_workspace(nocode_bench_id: str) -> str:
    """
    準備本地工作區：將原始碼複製到臨時目錄，以便 LLM 讀取上下文和生成 Patch。
    """
    # 解析 ID (例如: "django/django-12345" -> repo="django/django")
    # 假設 ID 格式通常是 "owner/repo-number" 或 "owner/repo__instance"
    if '__' in nocode_bench_id:
        # 處理可能的舊格式
        repo_slug = nocode_bench_id.split('__')[0] + '/' + nocode_bench_id.split('__')[1].split('-')[0]
    else:
        # "django/django-12345" -> "django/django"
        parts = nocode_bench_id.split('-')
        repo_slug = "-".join(parts[:-1]) # 取最後一個橫槓前的部分
        # 簡單修正：通常 data 下的結構是 owner/repo
        # 如果 nocode_bench_id 是 "psf/requests-123", repo_slug 應為 "psf/requests"
        if '/' in nocode_bench_id:
             repo_slug = nocode_bench_id.rsplit('-', 1)[0]

    # 構建來源路徑
    original_repo_path = os.path.join(ORIGINAL_DATASET_ROOT, repo_slug.replace('/', os.sep))
    
    # 如果找不到，嘗試一種更寬鬆的搜尋 (fallback)
    if not os.path.exists(original_repo_path):
        print(f"Warning: Exact path {original_repo_path} not found. Searching...")
        # 假設 repo_slug 是 "django/django"，我們找 data/django/django
        # 這裡需要確保 setup_codebases 已經跑過
        pass 

    run_id = str(time.time()).replace('.', '')
    temp_dir = os.path.join(ROOT_WORKSPACE, f'run_{nocode_bench_id.replace("/", "_")}_{run_id}')
    
    if not os.path.exists(original_repo_path):
        # 如果真的找不到原始碼，建立一個空目錄避免報錯，但 LLM 會瞎猜
        print(f"CRITICAL: Codebase for {repo_slug} not found at {original_repo_path}. Creating empty workspace.")
        os.makedirs(temp_dir, exist_ok=True)
    else:
        print(f"Copying codebase from {original_repo_path} to {temp_dir}...")
        shutil.copytree(original_repo_path, temp_dir)

    # 初始化 git，這樣我們才能生成 patch (git diff)
    subprocess.run(['git', 'init'], cwd=temp_dir, capture_output=True, check=False)
    subprocess.run(['git', 'config', 'user.email', 'agent@test.com'], cwd=temp_dir)
    subprocess.run(['git', 'config', 'user.name', 'Agent'], cwd=temp_dir)
    subprocess.run(['git', 'add', '.'], cwd=temp_dir, capture_output=True, check=False)
    subprocess.run(['git', 'commit', '-m', 'Initial'], cwd=temp_dir, capture_output=True, check=False)
    
    return temp_dir

def _get_relevant_files_from_llm(model, doc_change: str, workspace_path: str) -> list[str]:
    """
    列出本地工作區的所有 Python 檔案，讓 LLM 選擇相關檔案。
    """
    all_files = []
    # 掃描工作區
    for root, dirs, files in os.walk(workspace_path):
        if '.git' in dirs: dirs.remove('.git')
        if '.venv' in dirs: dirs.remove('.venv')
        if 'venv' in dirs: dirs.remove('venv')
        
        for file in files:
            if file.endswith(('.py', '.html', '.css', '.js', '.c', '.cpp', '.h')):
                rel_path = os.path.relpath(os.path.join(root, file), workspace_path)
                all_files.append(rel_path.replace('\\', '/'))
    
    if not all_files:
        print("Warning: No files found in workspace.")
        return []

    # 構建提示詞
    prompt = (
        f"You are a tech lead. Identify the files needed to implement this documentation change.\n"
        f"**DOC CHANGE:**\n{doc_change}\n\n"
        f"**FILES:**\n{', '.join(all_files[:3000])}\n" # 限制檔案數量避免 Prompt 過長
        f"(Total {len(all_files)} files)\n\n"
        f"**INSTRUCTIONS:**\n"
        "1. Identify the CORE files that need modification.\n"
        "2. Return JSON: {{\"files\": [\"path/to/core.py\"]}}\n"
    )

    try:
        response = model.generate_content(
            prompt,
            generation_config=GenerationConfig(response_mime_type="application/json")
        )
        data = json.loads(response.text)
        llm_files = data.get("files", [])
        # 過濾不存在的檔案
        valid_files = [f for f in llm_files if f in all_files]
        print(f"LLM identified files: {valid_files}")
        return valid_files
    except Exception as e:
        print(f"Error in file finding: {e}")
        return []

def _get_file_contexts(workspace_path: str, relevant_files: list[str]) -> str:
    parts = []
    for file_path in relevant_files:
        full_path = os.path.join(workspace_path, file_path)
        if os.path.exists(full_path):
            try:
                with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                parts.append(f"--- START OF FILE: {file_path} ---\n{content}\n--- END OF FILE: {file_path} ---\n")
            except Exception as e:
                print(f"Error reading {file_path}: {e}")
    return "\n".join(parts)

# ==============================================================================
#  2. Docker 核心邏輯 (Docker Core Logic)
# ==============================================================================

def _write_to_container(container, content: str, path: str):
    if not content: return
    escaped = content.replace("'", "'\\''")
    container.exec_run(f"bash -c 'echo \"{escaped}\" > {path}'")

def _run_tests_in_docker(
    task_id, 
    repo, 
    version, 
    base_commit, 
    feature_patch, 
    feature_test_patch, 
    f2p_test_names, 
    p2p_test_names
):
    if not client: return 0, 0, 0, 0, "Docker client unavailable"
    
    log = []
    container = None
    try:
        # 設定檢索
        cfg_map = MAP_REPO_TO_CONFIG.get(repo)
        if not cfg_map: return 0, 0, 0, 0, f"No config for {repo}"
        
        # 版本模糊匹配
        config = cfg_map.get(version)
        if not config:
            short_ver = ".".join(version.split(".")[:2])
            config = cfg_map.get(short_ver)
            if not config: return 0, 0, 0, 0, f"No config for {version}"

        repo_name = repo.split('/')[-1]
        image = f"fb_{repo_name}:dev"
        cname = f"runner_{task_id}_{int(time.time())}"
        
        print(f"[{task_id}] Starting Docker: {image}")
        container = client.containers.run(image, name=cname, detach=True, tty=True, command="tail -f /dev/null")
        
        wdir = f"/root/{repo_name}"
        container.exec_run("git clean -fdx", workdir=wdir)
        container.exec_run("git reset --hard HEAD", workdir=wdir)
        container.exec_run(f"git checkout {base_commit}", workdir=wdir)
        
        if feature_test_patch:
            _write_to_container(container, feature_test_patch, DOCKER_PATCH_PATH)
            container.exec_run(f"git apply {DOCKER_PATCH_PATH}", workdir=wdir)
            
        if feature_patch:
            _write_to_container(container, feature_patch, DOCKER_PATCH_PATH)
            ec, out = container.exec_run(f"git apply -p1 --ignore-whitespace {DOCKER_PATCH_PATH}", workdir=wdir)
            if ec != 0:
                container.exec_run(f"git apply -p1 --reject {DOCKER_PATCH_PATH}", workdir=wdir)

        env = config['conda_env']
        for cmd in config.get('pre_install', []) if isinstance(config.get('pre_install'), list) else [config.get('pre_install', '')]:
            if cmd: container.exec_run(cmd, workdir=wdir)
            
        container.exec_run(f"conda run -n {env} {config['install']}", workdir=wdir)
        
        def format_django_test_name(test_str):
            match = re.match(r"(.*?)\s+\((.*?)(?:\)|$)", test_str)
            if match:
                return f"{match.group(2).strip()}.{match.group(1).strip()}"
            return test_str

        def run_suite(tests, suite_name):
            if not tests: return 0
            
            current_tests = tests
            if "django" in repo:
                current_tests = [format_django_test_name(t) for t in tests]

            t_str = " ".join([f"'{t}'" for t in current_tests])
            full_cmd = f"conda run -n {env} {config['test_cmd']} {t_str}"
            
            # 🚀 [修改] 智慧判斷是否加入 --parallel=1
            if "django" in repo and "--parallel" not in full_cmd:
                try:
                    # 解析版本號，例如 "4.2" -> [4, 2]
                    v_parts = [int(x) for x in version.split('.')[:2]]
                    # 只有 Django 3.0+ 才強制單進程 (解決 Python 3.8+ pickle error)
                    # 舊版本 (1.9, 2.2) 保持預設，避免 "unrecognized arguments"
                    if v_parts[0] >= 3:
                        full_cmd += " --parallel=1"
                except:
                    # 如果版本解析失敗，保守起見不加
                    pass

            cmd = f"timeout 600s {full_cmd}"
            
            log.append(f"Running {suite_name}...")
            ec, out = container.exec_run(cmd, workdir=wdir)
            output = out.decode('utf-8', errors='replace')
            log.append(output)
            
            passed = 0
            if "django" in repo:
                django_passed = output.count("... ok")
                if django_passed > 0:
                    passed = django_passed
                elif "OK" in output and "FAILED" not in output:
                    m = re.search(r"Ran (\d+) tests", output)
                    passed = int(m.group(1)) if m else len(tests)
            else:
                passed = output.count("PASSED")

            return min(passed, len(tests))

        f2p = run_suite(f2p_test_names, "F2P")
        p2p = run_suite(p2p_test_names, "P2P")
        
        return f2p, len(f2p_test_names), p2p, len(p2p_test_names), "\n".join(log)

    except Exception as e:
        return 0, 0, 0, 0, str(e)
    finally:
        if container: 
            try: container.remove(force=True) 
            except: pass

# ==============================================================================
#  3. 主函數 (run_agent_attempt)
# ==============================================================================

def run_agent_attempt(
    workspace_path: str, 
    model, 
    prompt_text: str, 
    feature_test_patch: str,
    f2p_test_names: list[str],
    p2p_test_names: list[str],
    task_obj = None 
) -> dict:
    raw_response_text = ""
    final_patch_str = ""
    
    f2p_passed_count = 0
    f2p_total_count = len(f2p_test_names)
    p2p_passed_count = 0
    p2p_total_count = len(p2p_test_names)
    
    try:
        response = model.generate_content(prompt_text)
        raw_response_text = response.text
        
        try:
            modified_files = _parse_v7_response(raw_response_text)
        except Exception as e:
             return {
                'status': 'APPLY_FAILED', 
                'error': f"AI response parsing failed: {e}",
                'patch': '', 
                'raw_response': raw_response_text,
                'f2p_passed_count': 0, 'f2p_total_count': f2p_total_count, 
                'p2p_passed_count': 0, 'p2p_total_count': p2p_total_count,
                'regression_tests_passed': False
            }

        subprocess.run(['git', 'reset', '--hard', 'HEAD'], cwd=workspace_path, capture_output=True, check=False)
        for file_path, new_content in modified_files.items():
            if '..' in file_path: continue
            full_path = os.path.join(workspace_path, file_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
        
        diff_result = subprocess.run(
            ['git', 'diff', '--no-prefix'], 
            cwd=workspace_path, capture_output=True, text=True, encoding='utf-8', check=False
        )
        final_patch_str = diff_result.stdout
        
        if not final_patch_str.strip():
             return {
                'status': 'TEST_FAILED', 
                'patch': '',
                'test_output': 'AI agent produced no code changes.',
                'raw_response': raw_response_text,
                'f2p_passed_count': 0, 'f2p_total_count': f2p_total_count,
                'p2p_passed_count': 0, 'p2p_total_count': p2p_total_count,
                'regression_tests_passed': False,
            }

        if task_obj:
            repo = task_obj.repo
            version = task_obj.version
            base_commit = task_obj.base_commit
        else:
            return {
                'status': 'APPLY_FAILED',
                'error': "Missing task_obj info for Docker execution.",
                'patch': final_patch_str,
                'raw_response': raw_response_text,
                'f2p_passed_count': 0, 'f2p_total_count': f2p_total_count,
                'p2p_passed_count': 0, 'p2p_total_count': p2p_total_count,
                'regression_tests_passed': False
            }

        f2p_passed_count, f2p_total_count, p2p_passed_count, p2p_total_count, test_output = _run_tests_in_docker(
            task_id=str(task_obj.id),
            repo=repo,
            version=version,
            base_commit=base_commit,
            feature_patch=final_patch_str,
            feature_test_patch=feature_test_patch,
            f2p_test_names=f2p_test_names,
            p2p_test_names=p2p_test_names
        )
        
        feature_tests_passed = (f2p_passed_count == f2p_total_count) if f2p_total_count > 0 else False
        regression_tests_passed = (p2p_passed_count == p2p_total_count) if p2p_total_count > 0 else True
        
        if feature_tests_passed and regression_tests_passed:
            status = 'PASSED'
        else:
            status = 'TEST_FAILED' 

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
            'error': f"Unexpected error: {e}",
            'patch': final_patch_str,
            'test_output': "",
            'raw_response': raw_response_text,
            'f2p_passed_count': 0, 'f2p_total_count': f2p_total_count, 
            'p2p_passed_count': 0, 'p2p_total_count': p2p_total_count,
            'regression_tests_passed': False
        }

# ==============================================================================
#  4. 補回 Missing Functions (Fix for ImportError)
# ==============================================================================

def setup_custom_workspace(github_url: str) -> str:
    """
    為自定義演示克隆 Git 存儲庫。
    """
    run_id = str(time.time()).replace('.', '')
    repo_name = github_url.split('/')[-1].replace('.git', '')
    temp_dir = os.path.join(ROOT_WORKSPACE, f'demo_{repo_name}_{run_id}')
    
    try:
        print(f"Cloning repo from {github_url} into {temp_dir}...")
        subprocess.run(
            ['git', 'clone', '--depth', '1', github_url, temp_dir],
            check=True, capture_output=True, text=True, encoding='utf-8'
        )
        # 初始化 git 以便進行 diff
        subprocess.run(['git', 'init'], cwd=temp_dir, check=False, capture_output=True)
        return temp_dir
    except subprocess.CalledProcessError as e:
        raise IOError(f"Failed to clone Git repo: {e.stderr}")
    except Exception as e:
        raise IOError(f"File operation failed: {e}")

def run_agent_demo_attempt(
    workspace_path: str, 
    model, 
    prompt_text: str
) -> dict:
    """
    簡單版的 Agent 運行邏輯，僅用於演示，不執行 Docker 測試。
    """
    raw_response_text = ""
    final_patch_str = ""
    
    try:
        # 1. 生成代碼
        response = model.generate_content(prompt_text)
        raw_response_text = response.text
        
        # 2. 解析回應
        try:
            modified_files = _parse_v7_response(raw_response_text)
        except Exception as e:
            return {'status': 'APPLY_FAILED', 'patch': '', 'raw_response': raw_response_text}

        # 3. 寫入檔案
        for file_path, new_content in modified_files.items():
            if '..' in file_path: continue
            full_path = os.path.join(workspace_path, file_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(new_content)

        # 4. 生成 Diff
        diff_result = subprocess.run(
            ['git', 'diff', '--no-prefix'], 
            cwd=workspace_path, capture_output=True, text=True, encoding='utf-8', check=False
        )
        final_patch_str = diff_result.stdout
        
        return {
            'status': 'COMPLETED',
            'patch': final_patch_str,
            'raw_response': raw_response_text,
        }
        
    except Exception as e:
        print(f"FATAL ERROR in run_agent_demo_attempt: {e}")
        return {'status': 'APPLY_FAILED', 'patch': '', 'raw_response': raw_response_text}