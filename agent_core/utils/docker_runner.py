# agent_core/utils/docker_runner.py
import docker
import time
import re
import tarfile
import io
import os
from agent_core.constants import MAP_REPO_TO_CONFIG


DOCKER_PATCH_PATH = "/tmp/patch.diff"

try:
    client = docker.from_env()
except Exception as e:
    print(f"Warning: Docker client error: {e}")
    client = None

def _write_to_container(container, content: str, path: str):
    """
    使用 tar stream 將字串內容以檔案形式寫入容器，避免 shell escaping 和長度限制問題。
    """
    if not content: 
        return

    # 1. 準備 Tar 歸檔 (在記憶體中)
    tar_stream = io.BytesIO()
    with tarfile.open(fileobj=tar_stream, mode='w') as tar:
        encoded_content = content.encode('utf-8')
        
        # 建立 TarInfo (檔案資訊)
        # 注意：put_archive 是解壓到指定目錄，所以這裡只需要檔名
        tar_info = tarfile.TarInfo(name=os.path.basename(path))
        tar_info.size = len(encoded_content)
        tar_info.mtime = time.time()
        
        # 將內容寫入 Tar
        tar.addfile(tar_info, io.BytesIO(encoded_content))
    
    # 指標回到開頭，準備讀取
    tar_stream.seek(0)
    
    # 2. 將 Tar 寫入容器
    # put_archive 會將 tar 解壓到 path 指定的「目錄」下
    dir_path = os.path.dirname(path)
    try:
        container.put_archive(path=dir_path, data=tar_stream)
    except Exception as e:
        print(f"ERROR: Failed to write file to container {path}: {e}")
        raise

def run_tests_in_docker(task_id, repo, version, base_commit, feature_patch, feature_test_patch, f2p_test_names, p2p_test_names):
    if not client: return 0, 0, 0, 0, "Docker client unavailable"
    
    log = []
    container = None
    try:
        cfg_map = MAP_REPO_TO_CONFIG.get(repo)
        if not cfg_map: return 0, 0, 0, 0, f"No config for {repo}"
        
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
            ec, out = container.exec_run(f"git apply {DOCKER_PATCH_PATH}", workdir=wdir)
            
            if ec != 0:
                error_msg = f"ERROR: Apply Test Patch Failed!\nOutput: {out.decode('utf-8', errors='replace')}"
                print(error_msg) 
                log.append(error_msg) 
            else:
                print("Test Patch applied successfully.")

        if feature_patch:
            _write_to_container(container, feature_patch, DOCKER_PATCH_PATH)
            ec, out = container.exec_run(f"git apply -p1 --ignore-whitespace {DOCKER_PATCH_PATH}", workdir=wdir)
            if ec != 0:
                print(f"Warning: Patch failed (code {ec}), trying --reject...")
                ec_rej, out_rej = container.exec_run(f"git apply -p1 --reject {DOCKER_PATCH_PATH}", workdir=wdir)
                if ec_rej != 0:
                     msg = f"ERROR: Apply Feature Patch Failed!\n{out_rej.decode('utf-8', errors='replace')}"
                     print(msg)
                     log.append(msg)
                     
        env = config['conda_env']
        # Pre-install
        cmds = config.get('pre_install', [])
        if not isinstance(cmds, list): cmds = [cmds]
        for cmd in cmds:
            if cmd: container.exec_run(cmd, workdir=wdir)
            
        container.exec_run(f"conda run -n {env} {config['install']}", workdir=wdir)
        
        # Test Execution Helpers
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
            
            if "django" in repo and "--parallel" not in full_cmd:
                try:
                    v_parts = [int(x) for x in version.split('.')[:2]]
                    if v_parts[0] >= 3:
                        full_cmd += " --parallel=1"
                except: pass

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