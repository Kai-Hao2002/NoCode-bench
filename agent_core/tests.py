import pytest
import tempfile
import shutil
import os # 新增 os
from unittest.mock import patch, MagicMock
from rest_framework.test import APIClient
from django.urls import reverse

# Import 專案模組
from agent_core.utils.docker_runner import run_tests_in_docker
from agent_core.models import EvaluationTask, EvaluationResult
from agent_core.tasks import process_evaluation_task
# 新增匯入 parse_llm_response 以便單獨測試它
from agent_core.utils.llm_client import parse_llm_response, get_relevant_files

@pytest.mark.django_db
class TestAgentCore:
    def setup_method(self):
        self.client = APIClient()
        self.task = EvaluationTask.objects.create(
            nocode_bench_id="test_repo/task-001",
            doc_change_input="Fix the bug",
            status="PENDING",
            repo="test/repo",
            version="1.0"
        )

    # --- 1. Model 測試 ---
    def test_evaluation_task_model(self):
        assert EvaluationTask.objects.count() == 1
        assert self.task.status == "PENDING"

    # --- 2. API 測試 (Start Task) ---
    @patch('agent_core.views.process_evaluation_task.delay')
    def test_start_task_api(self, mock_delay):
        mock_result = MagicMock()
        mock_result.id = "fake-celery-id-123"
        mock_delay.return_value = mock_result

        url = reverse('task-start-task')
        data = {'nocode_bench_id': 'test_repo/task-001'}
        response = self.client.post(url, data, format='json')
        
        assert response.status_code == 202
        assert self.task.status == 'PENDING'

    # --- 3. API 測試 (Summary) ---
    def test_summary_api(self):
        EvaluationResult.objects.create(
            task=self.task,
            success_percent=100.0,
            run_time_seconds=60.0,
            generated_patch="diff --git..."
        )
        url = reverse('task-summary')
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.json()['finished_tasks'] == 1

    # --- 4. API 測試 (Start All) ---
    @patch('agent_core.views.process_evaluation_task.delay')
    def test_start_all_tasks_api(self, mock_delay):
        mock_result = MagicMock()
        mock_result.id = "fake-celery-id-batch"
        mock_delay.return_value = mock_result

        url = reverse('task-start-all-tasks')
        response = self.client.post(url)
        assert response.status_code == 202

    # --- 5. 邏輯測試：Tasks (模擬完整流程) ---
    @patch('agent_core.tasks.connection')
    @patch('agent_core.tasks.run_tests_in_docker')
    @patch('agent_core.tasks.subprocess')
    @patch('agent_core.tasks.setup_workspace')
    @patch('agent_core.tasks.get_relevant_files')
    @patch('agent_core.tasks.get_file_contexts')
    @patch('agent_core.tasks.generate_with_retry')
    @patch('agent_core.tasks.settings')
    def test_process_evaluation_task_logic(self, mock_settings, mock_generate, mock_contexts, mock_get_files, mock_setup_ws, mock_subprocess, mock_run_docker, mock_connection):
        """
        測試 process_evaluation_task 函式邏輯，模擬 Git Diff 和 Docker 執行。
        """
        # A. 建立一個臨時目錄作為假的工作區
        test_dir = tempfile.mkdtemp()
        mock_setup_ws.return_value = test_dir

        # B. 設定 Mock 回傳值
        mock_settings.GEMINI_API_KEY = "fake-key"
        mock_get_files.return_value = ["file1.py"]
        mock_contexts.return_value = "context content"
        
        # --- 關鍵修正 (Critical Fix) ---
        # 使用符合 parse_llm_response 要求的格式
        mock_response = MagicMock()
        mock_response.text = (
            "Here is the code:\n"
            "--- START OF FILE: file1.py ---\n"
            "print('fixed')\n"
            "--- END OF FILE: file1.py ---\n"
        )
        mock_generate.return_value = mock_response
        # -----------------------------
        
        # 模擬 subprocess.run (針對 git diff)
        mock_proc = MagicMock()
        mock_proc.stdout = "diff --git a/file1.py b/file1.py\n+print('fixed')"
        mock_proc.returncode = 0
        mock_subprocess.run.return_value = mock_proc

        # 模擬 Docker 回傳測試結果 (Pass)
        mock_run_docker.return_value = (1, 1, 1, 1, "Tests Passed")

        # C. 執行函式
        try:
            process_evaluation_task(self.task.id)
        except Exception as e:
            print(f"Test Error: {e}")
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

        # D. 驗證
        self.task.refresh_from_db()
        # 現在應該成功解析檔案並執行到 Docker 測試，狀態應為 COMPLETED
        assert self.task.status == 'COMPLETED'
        
        mock_run_docker.assert_called()

    # --- 6. 邏輯測試：DockerRunner ---
    @patch('agent_core.utils.docker_runner.client')
    @patch('agent_core.utils.docker_runner.MAP_REPO_TO_CONFIG')
    def test_docker_runner_execution(self, mock_config_map, mock_client):
        mock_config_map.get.return_value = {
            "1.0": {
                "conda_env": "test_env",
                "install": "pip install .",
                "test_cmd": "pytest",
                "pre_install": []
            }
        }
        mock_container = MagicMock()
        mock_client.containers.run.return_value = mock_container
        mock_container.exec_run.return_value = (0, b"Ran 1 tests ... OK")

        f2p, f2p_t, p2p, p2p_t, logs = run_tests_in_docker(
            task_id="123", 
            repo="test/repo", 
            version="1.0", 
            base_commit="HEAD",
            feature_patch="patch...", 
            feature_test_patch="", 
            f2p_test_names=["test_1"], 
            p2p_test_names=[]
        )
        assert mock_client.containers.run.called
        assert f2p_t == 1

    # --- 7. 新增：LLM Utils 測試 (大幅提升 llm_client.py 覆蓋率) ---
    def test_llm_utils_parsing(self):
        """測試回應解析邏輯"""
        raw_text = (
            "Some reasoning...\n"
            "--- START OF FILE: test.py ---\n"
            "print('hello')\n"
            "--- END OF FILE: test.py ---\n"
        )
        result = parse_llm_response(raw_text)
        assert "test.py" in result
        assert result["test.py"] == "print('hello')"

        # 測試格式錯誤的情況
        empty_res = parse_llm_response("No code blocks here")
        assert empty_res == {}
    
    @patch('agent_core.utils.llm_client.generate_with_retry')
    def test_llm_utils_file_finding(self, mock_gen):
        """測試檔案搜尋邏輯"""
        # 模擬 os.walk 環境
        with tempfile.TemporaryDirectory() as tmpdir:
            # 建立假檔案
            with open(os.path.join(tmpdir, "main.py"), "w") as f: f.write("pass")
            os.makedirs(os.path.join(tmpdir, ".git")) # 應該被忽略
            
            # 模擬 LLM 回傳 JSON
            mock_resp = MagicMock()
            mock_resp.text = '{"files": ["main.py"]}'
            mock_gen.return_value = mock_resp
            
            model = MagicMock()
            files = get_relevant_files(model, "change doc", tmpdir)
            
            assert "main.py" in files
            assert len(files) == 1
            
    # --- 8. 新增：Workspace Utils 測試 (提升 workspace.py 覆蓋率) ---
    @patch('agent_core.utils.workspace.subprocess')
    def test_workspace_utils(self, mock_subprocess):
        """測試工作區設定與檔案讀取"""
        from agent_core.utils.workspace import setup_workspace, get_file_contexts
        
        # 1. 測試 setup_workspace
        mock_subprocess.run.return_value.returncode = 0
        ws_path = setup_workspace("test/repo")
        assert "nocode_workspaces" in ws_path
        
        # 2. 測試 get_file_contexts (使用臨時檔案)
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.py")
            with open(file_path, "w") as f:
                f.write("print('hello')")
            
            # 呼叫讀檔函式
            context = get_file_contexts(tmpdir, ["test.py"])
            assert "print('hello')" in context
            assert "--- START OF FILE: test.py ---" in context