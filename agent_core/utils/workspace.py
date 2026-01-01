# agent_core/utils/workspace.py
import os
import shutil
import subprocess
import time
import stat
from django.conf import settings

# root workspace directory
ROOT_WORKSPACE = os.path.join(settings.BASE_DIR, 'nocode_workspaces')
ORIGINAL_DATASET_ROOT = os.path.join(settings.BASE_DIR, 'NoCode-bench_Verified', 'data')

def onerror(func, path, exc_info):
    if not os.access(path, os.W_OK):
        os.chmod(path, stat.S_IWUSR | stat.S_IWRITE)
        func(path)
    else:
        raise

def setup_workspace(nocode_bench_id: str) -> str:
    os.makedirs(ROOT_WORKSPACE, exist_ok=True)
    
    # repository slug extraction
    if '__' in nocode_bench_id:
        owner = nocode_bench_id.split('__')[0]
        rest = nocode_bench_id.split('__')[1]
        
        # scikit-learn-18280 -> ['scikit-learn', '18280']
        repo_name = rest.rsplit('-', 1)[0]
        
        repo_slug = f"{owner}/{repo_name}"
    else:

        if '/' in nocode_bench_id:
             repo_slug = nocode_bench_id.rsplit('-', 1)[0]
        else:
            parts = nocode_bench_id.split('-')
            repo_slug = "-".join(parts[:-1])

    original_repo_path = os.path.join(ORIGINAL_DATASET_ROOT, repo_slug.replace('/', os.sep))
    run_id = str(time.time()).replace('.', '')
    temp_dir = os.path.join(ROOT_WORKSPACE, f'run_{nocode_bench_id.replace("/", "_")}_{run_id}')
    
    if not os.path.exists(original_repo_path):
        print(f"CRITICAL: Codebase for {repo_slug} not found. Creating empty workspace.")
        os.makedirs(temp_dir, exist_ok=True)
    else:
        print(f"Copying codebase from {original_repo_path} to {temp_dir}...")
        shutil.copytree(original_repo_path, temp_dir)

    # Git Init
    subprocess.run(['git', 'init'], cwd=temp_dir, capture_output=True, check=False)
    subprocess.run(['git', 'config', 'user.email', 'agent@test.com'], cwd=temp_dir)
    subprocess.run(['git', 'config', 'user.name', 'Agent'], cwd=temp_dir)
    subprocess.run(['git', 'add', '.'], cwd=temp_dir, capture_output=True, check=False)
    subprocess.run(['git', 'commit', '-m', 'Initial'], cwd=temp_dir, capture_output=True, check=False)
    
    return temp_dir

def setup_custom_workspace(github_url: str) -> str:
    os.makedirs(ROOT_WORKSPACE, exist_ok=True)
    run_id = str(time.time()).replace('.', '')
    repo_name = github_url.split('/')[-1].replace('.git', '')
    temp_dir = os.path.join(ROOT_WORKSPACE, f'demo_{repo_name}_{run_id}')
    
    try:
        print(f"Cloning repo from {github_url} into {temp_dir}...")
        subprocess.run(
            ['git', 'clone', '--depth', '1', github_url, temp_dir],
            check=True, capture_output=True, text=True, encoding='utf-8'
        )
        subprocess.run(['git', 'init'], cwd=temp_dir, check=False, capture_output=True)
        return temp_dir
    except Exception as e:
        raise IOError(f"Failed to clone Git repo: {e}")

def get_file_contexts(workspace_path: str, relevant_files: list[str], max_chars: int = 200000) -> str:
    """
    read relevant files from the workspace and return their contents concatenated.
    do not exceed max_chars in total.
    """
    parts = []
    total_chars = 0
    
    for file_path in relevant_files:
        full_path = os.path.join(workspace_path, file_path)
        if os.path.exists(full_path):
            try:
                with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                    
                content = content.replace('\r\n', '\n')
                
                # check if adding this file exceeds max_chars
                if total_chars + len(content) > max_chars:
                    remaining = max_chars - total_chars
                    if remaining > 500: # if at least 500 chars can be added
                        content = content[:remaining] + "\n...[TRUNCATED DUE TO SIZE LIMIT]..."
                        parts.append(f"--- START OF FILE: {file_path} ---\n{content}\n--- END OF FILE: {file_path} ---\n")
                    else:
                        print(f"Skipping {file_path} due to context limit.")
                    
                    # reached max_chars, stop processing further files
                    break
                
                parts.append(f"--- START OF FILE: {file_path} ---\n{content}\n--- END OF FILE: {file_path} ---\n")
                total_chars += len(content)
                
            except Exception as e:
                print(f"Error reading {file_path}: {e}")
                
    return "\n".join(parts)