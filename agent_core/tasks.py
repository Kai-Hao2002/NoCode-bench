### 2. `agent_core/tasks.py` (修正版 Corrected)
import logging
from celery import shared_task
from django.utils import timezone
from .models import EvaluationTask, EvaluationResult
from .services import run_gemini_agent

logger = logging.getLogger(__name__)

@shared_task(bind=True)
def process_evaluation_task(self, task_id):
    """
    用於處理單個 NoCode-bench 評估實例的 Celery 任務。
    (Celery task to process a single NoCode-bench evaluation instance.)
    """
    task = None
    try:
        task = EvaluationTask.objects.get(pk=task_id)

        # 🚀 修正：在運行前，先刪除所有與此任務相關的舊結果
        # (FIX: Before running, delete any old results associated with this task)
        EvaluationResult.objects.filter(task=task).delete()

        # 1. 取得任務並更新狀態 (Get task and set status)
        task.status = 'RUNNING'
        task.start_time = timezone.now()
        task.celery_task_id = self.request.id
        task.error_details = None # 清除先前的錯誤 (Clear previous errors)
        task.save()
        
        logger.info(f"Starting task {task.id} for instance '{task.nocode_bench_id}'...")

        # 2. 執行 Agent 核心邏輯 (Execute the core agent logic)
        results = run_gemini_agent(
            task.id,
            task.nocode_bench_id, 
            task.doc_change_input
        )
        
        # 3. 處理 Agent 返回的結果 (Process the results from the agent)
        final_status = results.get('status', 'FAILED')
        error_message = results.get('error', 'No error details provided.')
        
        if final_status != 'COMPLETED':
            logger.error(f"Task {task.id} finished with status: {final_status}. Reason: {error_message}")
            task.error_details = error_message
        
        # 4. 儲存 EvaluationResult (Save the EvaluationResult)
        # 由於舊的已被刪除，我們現在可以安全地使用 .create()
        # (Since old ones were deleted, we can now safely use .create())
        EvaluationResult.objects.create(
            task=task,
            success_percent=results.get('success_percent', 0.0),
            applied_percent=results.get('applied_percent', 0.0),
            rt_percent=results.get('rt_percent', 0.0),
            fv_micro=results.get('fv_micro', 0.0),
            fv_macro=results.get('fv_macro', 0.0),
            file_percent=results.get('file_percent', 0.0),
            num_token=results.get('num_token', 0),
            generated_patch=results.get('generated_patch', '')
        )
        
        # 5. 更新最終狀態 (Update the final status)
        task.status = final_status
        task.end_time = timezone.now()
        task.save()
        
        if final_status == 'COMPLETED':
            logger.info(f"Task {task.id} completed successfully.")
            
    except Exception as e:
        # 捕獲意外的異常 (Catch unexpected exceptions)
        error_trace = f"An unexpected exception occurred in tasks.py for task {task_id}: {e}"
        logger.error(error_trace, exc_info=True)
        
        if task:
            task.status = 'FAILED'
            task.error_details = error_trace
            task.end_time = timezone.now()
            task.save()