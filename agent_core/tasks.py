import logging
from celery import shared_task
from django.utils import timezone
from django.db import connection
import shutil
import os

from .models import EvaluationTask, EvaluationResult, EvaluationAttempt
from .services import (
    setup_workspace, 
    run_agent_attempt,
    run_agent_attempt_with_reflexion,  # 方案二：导入新的 Reflexion 函数
    _get_relevant_files_from_llm, 
    _get_file_contexts,
    calculate_all_metrics,
    onerror,
    parse_patch,
    setup_custom_workspace,
    run_agent_demo_attempt
)
from google import generativeai as genai
from django.conf import settings


logger = logging.getLogger(__name__)

def _build_prompt_for_attempt(doc_change: str, context_content_str: str, history: list[str]) -> str:
    """
    (此函數保持不變)
    """
    
    # 階段一：第一次嘗試
    if not history:
        return (
            f"You are an expert AI software engineer. Your task is to implement a feature based on a documentation change.\n\n"
            f"**DOCUMENTATION CHANGE TO IMPLEMENT:**\n{doc_change}\n\n"
            f"**ORIGINAL FILE CONTENTS (ALL RELEVANT FILES):**\n"
            f"{context_content_str}\n\n"
            f"**CRITICAL INSTRUCTIONS:**\n"
            "1.  **Analyze Dependencies:** Carefully read all provided files. Pay close attention to how they import from each other, especially `compat.py` and `__init__.py`.\n"
            "2.  **Implement Correctly:** Your task is to rewrite the files to implement the change. Ensure any new symbols (like `JSONDecodeError`) are correctly defined, imported, and exported in *all* necessary files (like `compat.py` and `__init__.py`) according to the existing project structure.\n"
            "3.  **Full Files Only:** Your response MUST ONLY contain the new, full file contents, separated by special delimiters.\n"
            "4.  **No Unchanged Files:** Do NOT include files that do not need to be changed.\n"
            "5.  **No Tests:** **DO NOT** modify any files in `test/` or `tests/` directories.\n"
            "6.  **No Explanation:** Do NOT include any other text, explanations, or markdown ` ``` `.\n\n"
            "**REQUIRED RESPONSE FORMAT:**\n"
            "--- START OF FILE: path/to/file1.py ---\n"
            "(Full new content of file1.py)\n"
            "--- END OF FILE: path/to/file1.py ---\n"
        )
    
    # 階段二：調試嘗試
    history_str = "\n\n".join(history)
    return (
        f"You are an expert AI software engineer. Your previous attempt to fix the code failed the test suite.\n\n"
        f"**ORIGINAL DOCUMENTATION CHANGE:**\n{doc_change}\n\n"
        f"**ORIGINAL FILE CONTENTS (ALL RELEVANT FILES):**\n"
        f"{context_content_str}\n\n"
        f"**PREVIOUS FAILED ATTEMPTS (Prompts, Code, and Errors):**\n"
        f"{history_str}\n\n"
        f"**YOUR TASK:**\n"
        "1.  Analyze the test failures from your last attempt. If you see errors about `f2p_report.json` or `ImportError`, it means your generated code had a fatal bug (probably in `compat.py` or `__init__.py`).\n"
        "2.  **Review your previous patch:** Look for logic errors, especially in `compat.py` or `__init__.py`.\n"
        "3.  Generate a NEW, CORRECTED version of the code to fix the errors.\n"
        "4.  Provide the full file contents for ALL files you need to modify.\n"
        "5.  **DO NOT** modify any files in `test/` or `tests/` directories. The error is in your application code.\n\n"
        "**REQUIRED RESPONSE FORMAT (SAME AS BEFORE):**\n"
        "--- START OF FILE: path/to/file1.py ---\n"
        "(Full new content of file1.py)\n"
        "--- END OF FILE: path/to/file1.py ---\n"
    )


@shared_task(bind=True)
def process_evaluation_task(self, task_id):
    """
    (此函數與 V16 版本幾乎相同)
    """
    # TODO: 调高此处 提升成功率
    MAX_ATTEMPTS = 1 
    task = None
    workspace_path = None
    final_status = 'FAILED'
    final_patch = ""
    applied_successfully = False
    
    try:
        task = EvaluationTask.objects.get(pk=task_id)

        # 🚀 修正：檢查這是否為 demo 任務，以決定使用哪個 ID
        workspace_id_to_use = task.base_task_id if task.base_task_id else task.nocode_bench_id

        # 1. 設置
        EvaluationResult.objects.filter(task=task).delete()
        EvaluationAttempt.objects.filter(task=task).delete()

        task.status = 'RUNNING'
        task.start_time = timezone.now()
        task.celery_task_id = self.request.id
        task.error_details = None
        task.save()
        
        # 🚀 修正：在日誌中使用正確的 ID
        logger.info(f"Starting task {task.id} for instance '{workspace_id_to_use}' with {MAX_ATTEMPTS} attempts...")

        # 設置 Gemini 模型和工作區
        if not settings.GEMINI_API_KEY:
            raise Exception("Gemini client not configured. Check GEMINI_API_KEY.")
        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-2.5-pro')
        
        # 🚀 修正：使用正確的 ID 設置工作區
        workspace_path = setup_workspace(workspace_id_to_use)
        # 🚀 恢復為 LLM 檔案查找
        logger.info(f"[Task {task.id}] Using LLM file finder...")
        relevant_files = _get_relevant_files_from_llm(model, task.doc_change_input, workspace_path)
        if not relevant_files:
            raise Exception("AI (LLM) failed to identify any relevant CODE files to modify.")
        
        logger.info(f"[Task {task.id}] Files to be used for context: {relevant_files}")

        context_content_str = _get_file_contexts(workspace_path, relevant_files)
        if not context_content_str:
            raise Exception("AI identified files, but they could not be read.")

        history = []
        regression_tests_passed = False
        f2p_passed_count = 0
        f2p_total_count = 0
        tests_passed = False

        # 2. 調試循環
        # 方案二：使用 Reflexion Loop 替代手动循环
        # Reflexion 会在内部处理重试逻辑
        prompt_text = _build_prompt_for_attempt(task.doc_change_input, context_content_str, [])
        
        # 🚀 方案二: 使用带 Reflexion 的新函数
        attempt_result = run_agent_attempt_with_reflexion(
            workspace_path=workspace_path,
            model=model,
            initial_prompt=prompt_text,
            feature_test_patch=task.feature_test_patch,
            f2p_test_names=task.f2p_test_names,
            p2p_test_names=task.p2p_test_names,
            max_reflexion_iterations=MAX_ATTEMPTS  # 使用 MAX_ATTEMPTS 作为最大迭代次数
        )
        
        # 记录结果（Reflexion 已经完成了所有尝试）
        reflexion_iters = attempt_result.get('reflexion_iterations', 1)
        logger.info(f"[Task {task.id}] Reflexion completed after {reflexion_iters} iteration(s)")
        
        # 创建一个 EvaluationAttempt 记录（代表整个 Reflexion 过程）
        attempt = EvaluationAttempt.objects.create(
            task=task,
            attempt_number=1,  # 整个 Reflexion 算作一次尝试
            status=attempt_result['status'],
            prompt_text=prompt_text,
            raw_response=attempt_result['raw_response'],
            generated_patch=attempt_result['patch'],
            test_output=attempt_result.get('test_output', f"Reflexion completed in {reflexion_iters} iterations")
        )
        
        final_patch = attempt_result['patch']
        applied_successfully = (attempt_result['status'] not in ['APPLY_FAILED', 'ENV_ERROR'])
        
        tests_passed = (attempt_result['status'] == 'PASSED')
        regression_tests_passed = attempt_result.get('regression_tests_passed', False)
        f2p_passed_count = attempt_result.get('f2p_passed_count', 0)
        f2p_total_count = attempt_result.get('f2p_total_count', 0)

        # 根据结果设置最终状态
        if tests_passed:
            logger.info(f"[Task {task.id}] PASSED tests after {reflexion_iters} Reflexion iteration(s).")
            final_status = 'COMPLETED'
        elif attempt_result['status'] == 'ENV_ERROR':
            logger.error(f"[Task {task.id}] Environment error detected. Cannot continue.")
            final_status = 'FAILED_APPLY'
            task.error_details = attempt_result.get('error', 'Environment setup failed.')
        elif attempt_result['status'] == 'APPLY_FAILED':
            logger.error(f"[Task {task.id}] FAILED TO APPLY after {reflexion_iters} iteration(s).")
            final_status = 'FAILED_APPLY'
            task.error_details = attempt_result.get('error', 'AI response parsing failed.')
        else:  # TEST_FAILED
            logger.warning(f"[Task {task.id}] FAILED tests after {reflexion_iters} Reflexion iteration(s).")
            final_status = 'FAILED_TEST'

        # 3. 循環後處理
        logger.info(f"[Task {task.id}] Loop finished with status: {final_status}")
        
        task.refresh_from_db()
        ground_truth_patch = task.ground_truth_patch or ""
        run_time = (timezone.now() - task.start_time).total_seconds()
        
        metrics = calculate_all_metrics(
            f2p_passed_count=f2p_passed_count,
            f2p_total_count=f2p_total_count,
            regression_tests_passed=regression_tests_passed,
            applied_successfully=applied_successfully,
            generated_patch=final_patch,
            ground_truth_patch=ground_truth_patch,
            run_time_seconds=run_time
        )
        
        # (此 'create' 調用與 V16 相同)
        EvaluationResult.objects.create(
            task=task,
            success_percent=metrics.get('success_percent', 0.0),
            applied_percent=metrics.get('applied_percent', 0.0),
            rt_percent=metrics.get('rt_percent', 0.0),
            fv_macro=metrics.get('fv_macro', 0.0),
            file_percent=metrics.get('file_percent', 0.0),
            num_token=metrics.get('num_token', 0),
            run_time_seconds=metrics.get('run_time_seconds', 0.0),
            f2p_passed_count=metrics.get('f2p_passed_count', 0),
            f2p_total_count=metrics.get('f2p_total_count', 0),
            generated_patch=final_patch
        )
        
        # 5. 更新最終狀態
        task.status = final_status
        task.end_time = timezone.now()
        task.save()
        
        if final_status == 'COMPLETED':
            logger.info(f"Task {task.id} completed successfully.")
            
    except Exception as e:
        error_trace = f"An unexpected exception occurred in tasks.py for task {task_id}: {e}"
        logger.error(error_trace, exc_info=True)
        if task:
            task.status = 'FAILED'
            task.error_details = error_trace
            task.end_time = timezone.now()
            task.save()
            
    finally:
        connection.close()
        if workspace_path and os.path.exists(workspace_path):
            logger.info(f"[Task {task.id}] --- Cleaning up workspace: {workspace_path} ---")
            shutil.rmtree(workspace_path, onerror=onerror)

@shared_task(bind=True)
def process_custom_demo_task(self, task_id):
    task = None
    workspace_path = None
    
    try:
        task = EvaluationTask.objects.get(pk=task_id)
        task.status = 'RUNNING'
        task.start_time = timezone.now()
        task.celery_task_id = self.request.id
        task.error_details = None
        task.save()

        # 1. 設置模型 (Setup Model)
        if not settings.GEMINI_API_KEY:
            raise Exception("Gemini client not configured. Check GEMINI_API_KEY.")
        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-2.5-pro')

        prefixed_url_with_timestamp = task.nocode_bench_id
        
        if not prefixed_url_with_timestamp.startswith("custom_"):
             raise Exception(f"Task {task_id} is a custom demo but nocode_bench_id is missing 'custom_' prefix.")
        
        # 1. 移除 "custom_" 前綴
        prefixed_url = prefixed_url_with_timestamp.replace("custom_", "", 1)
        # 2. 移除 "#" 和之後的時間戳
        github_url = prefixed_url.split('#')[0]
        
        # 2. 設置工作區 (Setup Workspace) - 使用新的 git clone 函數
        # 我們需要從 nocode_bench_id 欄位獲取 URL (見下一個步驟)
        workspace_path = setup_custom_workspace(github_url)
        
        # 3. 查找檔案 (Find Files)
        relevant_files = _get_relevant_files_from_llm(model, task.doc_change_input, workspace_path)
        if not relevant_files:
            raise Exception("AI failed to identify any relevant CODE files to modify.")
        
        context_content_str = _get_file_contexts(workspace_path, relevant_files)
        if not context_content_str:
            raise Exception("AI identified files, but they could not be read.")

        # 4. 生成提示 (Build Prompt)
        # (我們只使用第 1 次嘗試的提示，因為沒有 "重試" 循環)
        prompt_text = _build_prompt_for_attempt(task.doc_change_input, context_content_str, [])
        
        # 5. 運行 Agent (Run Agent) - 使用新的 "demo" 函數
        attempt_result = run_agent_demo_attempt(
            workspace_path=workspace_path,
            model=model,
            prompt_text=prompt_text
        )
        
        final_patch = attempt_result['patch']
        
        # 6. 儲存結果 (Save Result)
        if attempt_result['status'] == 'COMPLETED':
            EvaluationResult.objects.create(
                task=task,
                generated_patch=final_patch,
                # (所有指標都保持 0.0)
                success_percent=0.0,
                applied_percent=100.0, # 如果到這裡，它就是 100%
                rt_percent=0.0,
                file_percent=0.0,
                # (我們可以將其設為 -1 來表示 "N/A (不適用)")
            )
            task.status = 'COMPLETED'
        else:
            task.status = 'FAILED_APPLY'
            task.error_details = "AI response parsing failed."

        task.end_time = timezone.now()
        task.save()
        
    except Exception as e:
        error_trace = f"An unexpected exception occurred in custom demo task {task_id}: {e}"
        logger.error(error_trace, exc_info=True)
        if task:
            task.status = 'FAILED'
            task.error_details = error_trace
            task.end_time = timezone.now()
            task.save()
            
    finally:
        connection.close()
        if workspace_path and os.path.exists(workspace_path):
            logger.info(f"[Task {task.id}] --- Cleaning up custom workspace: {workspace_path} ---")
            shutil.rmtree(workspace_path, onerror=onerror)