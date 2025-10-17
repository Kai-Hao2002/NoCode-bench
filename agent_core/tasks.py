# agent_core/tasks.py
from celery import shared_task
from django.utils import timezone
from .models import EvaluationTask, EvaluationResult
from .services import run_gemini_agent
import logging
import sys

logger = logging.getLogger(__name__)

@shared_task(bind=True)
def process_evaluation_task(self, task_id):
    
    task = None
    try:
        # 1. 取得任務並更新狀態 (簡略)
        task = EvaluationTask.objects.get(pk=task_id)
        # ... (更新狀態、儲存) ...
        
        # 2. 執行 Agent 核心邏輯
        results = run_gemini_agent(
            task_id, 
            task.nocode_bench_id, 
            task.doc_change_input
        )
        
        # 3. 檢查是否有錯誤 (來自 services.py)
        if 'error' in results and results['error']:
            raise Exception(results['error'])
        
        # 4. 儲存 EvaluationResult (問題發生點！)
        EvaluationResult.objects.create(
            task=task,
            success_percent=results['Success%'],
            applied_percent=results['Applied%'],
            rt_percent=results['RT%'],
            fv_micro=results['FV-Micro'],
            fv_macro=results['FV-Macro'],
            file_percent=results['File%'],
            num_token=results['num_token'],
            generated_patch=results['generated_patch']
        )
        
        # 5. 任務成功完成
        task.status = 'COMPLETED'
        task.end_time = timezone.now()
        task.save()
        
        logger.info(f"Task {task.id} completed successfully and result saved to DB.")
        
    except Exception as e:
        # 🎯 這裡會捕獲並日誌記錄所有寫入資料庫的錯誤
        
        # 必須將錯誤訊息寫入 Celery 日誌和資料庫
        error_message = f"Task Failed. Trace: {e}. Full Exception: {sys.exc_info()}"
        logger.error(error_message) # 打印到 Celery 終端機
        
        if task:
            task.status = 'FAILED'
            task.error_details = error_message
            task.end_time = timezone.now()
            task.save()
        
        # 保持 raise，但我們已經有了詳細的日誌
        raise