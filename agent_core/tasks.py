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
    _get_relevant_files_from_llm, 
    _get_file_contexts,
    calculate_all_metrics,
    onerror
)
from google import generativeai as genai
from django.conf import settings


logger = logging.getLogger(__name__)

def _build_prompt_for_attempt(doc_change: str, context_content_str: str, history: list[str]) -> str:
    """
    (此函數保持不變)
    (This function is unchanged)
    """
    
    # 這是第一次嘗試
    if not history:
        return (
            f"You are an expert AI software engineer. Your task is to implement a feature based on a documentation change.\n\n"
            f"**DOCUMENTATION CHANGE TO IMPLEMENT:**\n{doc_change}\n\n"
            f"**ORIGINAL FILE CONTENTS:**\n"
            f"{context_content_str}\n\n"
            f"**CRITICAL INSTRUCTIONS:**\n"
            "1. Your task is to rewrite the files to implement the change.\n"
            "2. Your response MUST ONLY contain the new, full file contents, separated by special delimiters.\n"
            "3. Do NOT include files that do not need to be changed.\n"
            "4. Do NOT include any other text, explanations, or markdown ` ``` `.\n\n"
            "**REQUIRED RESPONSE FORMAT:**\n"
            "--- START OF FILE: path/to/file1.py ---\n"
            "(Full new content of file1.py)\n"
            "--- END OF FILE: path/to/file1.py ---\n"
            "--- START OF FILE: path/to/file2.py ---\n"
            "(Full new content of file2.py)\n"
            "--- END OF FILE: path/to/file2.py ---\n"
        )
    
    # 這是調試嘗試
    history_str = "\n\n".join(history)
    return (
        f"You are an expert AI software engineer. Your previous attempt to fix the code failed the test suite.\n\n"
        f"**ORIGINAL DOCUMENTATION CHANGE:**\n{doc_change}\n\n"
        f"**ORIGINAL FILE CONTENTS:**\n"
        f"{context_content_str}\n\n"
        f"**PREVIOUS FAILED ATTEMPTS (Prompts, Code, and Errors):**\n"
        f"{history_str}\n\n"
        f"**YOUR TASK:**\n"
        "1. Analyze the test failures from your last attempt.\n"
        "2. Generate a NEW, CORRECTED version of the code to fix the errors.\n"
        "3. Provide the full file contents for ALL files you need to modify, even if you only change one line.\n\n"
        "**REQUIRED RESPONSE FORMAT (SAME AS BEFORE):**\n"
        "--- START OF FILE: path/to/file1.py ---\n"
        "(Full new content of file1.py)\n"
        "--- END OF FILE: path/to/file1.py ---\n"
    )


@shared_task(bind=True)
def process_evaluation_task(self, task_id):
    """
    (此函數的大部分內容保持不變，除了 'EvaluationResult.objects.create' 調用)
    (Most of this function is unchanged, except the 'EvaluationResult.objects.create' call)
    """
    
    MAX_ATTEMPTS = 3
    task = None
    workspace_path = None
    final_status = 'FAILED'
    final_patch = ""
    applied_successfully = False
    
    try:
        task = EvaluationTask.objects.get(pk=task_id)

        # 1. 設置 (Setup)
        EvaluationResult.objects.filter(task=task).delete()
        EvaluationAttempt.objects.filter(task=task).delete()

        task.status = 'RUNNING'
        task.start_time = timezone.now()
        task.celery_task_id = self.request.id
        task.error_details = None
        task.save()
        
        logger.info(f"Starting task {task.id} for instance '{task.nocode_bench_id}' with {MAX_ATTEMPTS} attempts...")

        # 設置 Gemini 模型和工作區
        if not settings.GEMINI_API_KEY:
            raise Exception("Gemini client not configured. Check GEMINI_API_KEY.")
        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-2.5-pro')
        workspace_path = setup_workspace(task.nocode_bench_id)
        
        relevant_files = _get_relevant_files_from_llm(model, task.doc_change_input, workspace_path)
        if not relevant_files:
            raise Exception("AI failed to identify any relevant CODE files to modify.")
        
        context_content_str = _get_file_contexts(workspace_path, relevant_files)
        if not context_content_str:
            raise Exception("AI identified files, but they could not be read.")

        history = []
        regression_tests_passed = False
        f2p_passed_count = 0
        f2p_total_count = 0
        tests_passed = False

        # 2. 調試循環 (The Debug Loop)
        for i in range(MAX_ATTEMPTS):
            attempt_num = i + 1
            logger.info(f"[Task {task.id}] Starting attempt {attempt_num}/{MAX_ATTEMPTS}...")
            
            prompt_text = _build_prompt_for_attempt(task.doc_change_input, context_content_str, history)
            
            attempt_result = run_agent_attempt(
                workspace_path=workspace_path,
                model=model,
                prompt_text=prompt_text,
                nocode_bench_id=task.nocode_bench_id
            )
            
            attempt = EvaluationAttempt.objects.create(
                task=task,
                attempt_number=attempt_num,
                status=attempt_result['status'],
                prompt_text=prompt_text,
                raw_response=attempt_result['raw_response'],
                generated_patch=attempt_result['patch'],
                test_output=attempt_result.get('test_output', '')
            )
            
            final_patch = attempt_result['patch']
            applied_successfully = (attempt_result['status'] != 'APPLY_FAILED')
            
            tests_passed = (attempt_result['status'] == 'PASSED')
            regression_tests_passed = attempt_result.get('regression_tests_passed', False)
            f2p_passed_count = attempt_result.get('f2p_passed_count', 0)
            f2p_total_count = attempt_result.get('f2p_total_count', 0)

            if tests_passed:
                logger.info(f"[Task {task.id}] Attempt {attempt_num} PASSED tests.")
                final_status = 'COMPLETED'
                break 
            
            elif attempt_result['status'] == 'APPLY_FAILED':
                logger.error(f"[Task {task.id}] Attempt {attempt_num} FAILED TO APPLY. Stopping loop.")
                final_status = 'FAILED_APPLY'
                task.error_details = attempt_result.get('error', 'AI response parsing failed.')
                break

            elif attempt_result['status'] == 'TEST_FAILED':
                logger.warning(f"[Task {task.id}] Attempt {attempt_num} FAILED tests. Looping...")
                final_status = 'FAILED_TEST'
                history.append(f"--- ATTEMPT {attempt_num} (FAILED) ---")
                history.append(f"GENERATED PATCH:\n{attempt_result['patch']}")
                history.append(f"PYTEST ERRORS:\n{attempt_result['test_output']}")

        # 3. 循環後處理 (Post-Loop Processing)
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
        
        # 🚀 修正 (THE KEY FIX): 
        # 確保 'EvaluationResult.objects.create' 調用
        # 與 'models.py' 和 'services.py' 中的 V14 更改完全匹配。
        # (Ensure the 'EvaluationResult.objects.create' call
        # perfectly matches the V14 changes in 'models.py' and 'services.py'.)
        EvaluationResult.objects.create(
            task=task,
            success_percent=metrics.get('success_percent', 0.0),
            applied_percent=metrics.get('applied_percent', 0.0),
            rt_percent=metrics.get('rt_percent', 0.0),
            fv_micro=0.0, # 這是故意的！我們在 'views.py' 中全局計算它
                          # (This is intentional! We calculate it globally in 'views.py')
            fv_macro=metrics.get('fv_macro', 0.0),
            file_percent=metrics.get('file_percent', 0.0),
            num_token=metrics.get('num_token', 0),
            run_time_seconds=metrics.get('run_time_seconds', 0.0),
            f2p_passed_count=metrics.get('f2p_passed_count', 0),
            f2p_total_count=metrics.get('f2p_total_count', 0),
            generated_patch=final_patch
        )
        
        # 5. 更新最終狀態 (Update the final status)
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