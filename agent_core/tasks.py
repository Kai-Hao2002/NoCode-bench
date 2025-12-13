# agent_core/tasks.py
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
    Constructs the prompt for the LLM.
    Updated to prevent API hallucinations (AttributeError).
    """
    
    # 增強版檢查清單：加入 API 驗證
    # (Enhanced Checklist: Added API Verification)
    safety_checklist = (
        "**CRITICAL SAFETY CHECKLIST:**\n"
        "1.  **Verify APIs (NO HALLUCINATIONS):** Before calling a method on an object (e.g., `linter.add_option(...)`), YOU MUST verify that the method actually exists in the class definition provided in the context. If you don't see `def add_option` in the file, DO NOT CALL IT.\n"
        "2.  **Do NOT Change Signatures:** Do not change the arguments or return type of existing functions unless absolutely necessary.\n"
        "3.  **Use Default Arguments:** If you adding a parameter, provide a default value (e.g., `def func(a, b=None):`).\n"
        "4.  **Check Imports:** Do not remove imports that might be used by other files.\n"
    )

    # 階段一：第一次嘗試 (First Attempt)
    if not history:
        return (
            f"You are an expert AI software engineer. Your task is to implement a feature based on a documentation change.\n"
            f"You must prioritize correctness and strictly follow existing APIs.\n\n"
            f"**DOCUMENTATION CHANGE TO IMPLEMENT:**\n{doc_change}\n\n"
            f"**ORIGINAL FILE CONTENTS (ALL RELEVANT FILES):**\n"
            f"{context_content_str}\n\n"
            f"{safety_checklist}\n"
            f"**INSTRUCTIONS:**\n"
            "1.  **Analyze Dependencies:** Read the provided files to understand the class structures and available methods.\n"
            "2.  **Implement Correctly:** Rewrite the files to implement the change.\n"
            "3.  **Full Files Only:** Your response MUST ONLY contain the new, full file contents, separated by special delimiters.\n"
            "4.  **No Unchanged Files:** Do NOT include files that do not need to be changed.\n"
            "5.  **No Tests:** **DO NOT** modify any files in `test/` or `tests/` directories. Only modify the application code.\n\n"
            "**REQUIRED RESPONSE FORMAT:**\n"
            "--- START OF FILE: path/to/file1.py ---\n"
            "(Full new content of file1.py)\n"
            "--- END OF FILE: path/to/file1.py ---\n"
        )
    
    # 階段二：調試嘗試 (Debug Attempt)
    history_str = "\n\n".join(history)
    return (
        f"You are an expert AI software engineer. Your previous attempt failed the test suite.\n\n"
        f"**WARNING: FATAL ERROR DETECTED**\n"
        "The previous patch caused a crash or regression.\n"
        "**Common Causes for Failures:**\n"
        "- **AttributeError (CRITICAL):** You called a method that does not exist (e.g., `linter.add_option`). Check the `PyLinter` class definition again. Use `register_checker` or `set_option` if applicable, or define the method if it's missing.\n"
        "- **SyntaxError:** You introduced invalid syntax that crashed the test collector.\n"
        "- **ImportError:** You removed a necessary import.\n\n"
        f"**ORIGINAL DOCUMENTATION CHANGE:**\n{doc_change}\n\n"
        f"**ORIGINAL FILE CONTENTS:**\n"
        f"{context_content_str}\n\n"
        f"**PREVIOUS FAILED ATTEMPTS (Prompts, Code, and Errors):**\n"
        f"{history_str}\n\n"
        f"{safety_checklist}\n"
        f"**YOUR TASK:**\n"
        "1.  **Analyze the Errors:** Look at the test output. If you see `AttributeError`, STOP and check the class definition.\n"
        "2.  **Fix the Logic:** Generate a NEW, CORRECTED version of the code.\n"
        "3.  **Provide Full Content:** Provide the full file contents for ALL files you need to modify.\n\n"
        "**REQUIRED RESPONSE FORMAT (SAME AS BEFORE):**\n"
        "--- START OF FILE: path/to/file1.py ---\n"
        "(Full new content of file1.py)\n"
        "--- END OF FILE: path/to/file1.py ---\n"
    )


@shared_task(bind=True)
def process_evaluation_task(self, task_id):
    """
    🚀 更改 (CHANGE): 此任務現在會獲取並儲存 P2P 計數器。
    """
    
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
        # 🚀 新增 (NEW): 初始化 P2P 計數器
        p2p_passed_count = 0
        p2p_total_count = 0
        tests_passed = False

        # 2. 調試循環
        for i in range(MAX_ATTEMPTS):
            attempt_num = i + 1
            logger.info(f"[Task {task.id}] Starting attempt {attempt_num}/{MAX_ATTEMPTS}...")
            
            prompt_text = _build_prompt_for_attempt(task.doc_change_input, context_content_str, history)
            
            # 🚀 更改: 傳入所有測試數據
            attempt_result = run_agent_attempt(
                workspace_path=workspace_path,
                model=model,
                prompt_text=prompt_text,
                feature_test_patch=task.feature_test_patch, # 🚀 新增
                f2p_test_names=task.f2p_test_names,         # 🚀 新增
                p2p_test_names=task.p2p_test_names          # 🚀 新增
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
            # 🚀 新增 (NEW): 獲取 P2P 計數器
            p2p_passed_count = attempt_result.get('p2p_passed_count', 0)
            p2p_total_count = attempt_result.get('p2p_total_count', 0)

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

        # 3. 循環後處理
        logger.info(f"[Task {task.id}] Loop finished with status: {final_status}")
        
        task.refresh_from_db()
        ground_truth_patch = task.ground_truth_patch or ""
        run_time = (timezone.now() - task.start_time).total_seconds()
        
        # 🚀 更改 (CHANGE): 傳入 P2P 計數器
        metrics = calculate_all_metrics(
            f2p_passed_count=f2p_passed_count,
            f2p_total_count=f2p_total_count,
            p2p_passed_count=p2p_passed_count, # 🚀 新增
            p2p_total_count=p2p_total_count,   # 🚀 新增
            regression_tests_passed=regression_tests_passed,
            applied_successfully=applied_successfully,
            generated_patch=final_patch,
            ground_truth_patch=ground_truth_patch,
            run_time_seconds=run_time
        )
        
        # 🚀 更改 (CHANGE): 儲存 P2P 計數器
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
            p2p_passed_count=metrics.get('p2p_passed_count', 0), # 🚀 新增
            p2p_total_count=metrics.get('p2p_total_count', 0),   # 🚀 新增
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
    """
    (此函數保持不變)
    """
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
                # (我們可以在這裡添加 p2p 計數器為 -1，表示 N/A)
                p2p_passed_count=-1,
                p2p_total_count=-1,
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