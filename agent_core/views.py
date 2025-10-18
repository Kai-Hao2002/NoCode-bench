# agent_core/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import EvaluationTask
from .serializers import TaskStartSerializer, EvaluationTaskSerializer
from .tasks import process_evaluation_task # 假設您的任務名稱是這個

class EvaluationTaskViewSet(viewsets.ReadOnlyModelViewSet):
    """提供任務的讀取、狀態查詢和觸發。"""
    queryset = EvaluationTask.objects.all().order_by('-start_time')
    serializer_class = EvaluationTaskSerializer

    @action(detail=False, methods=['post'], serializer_class=TaskStartSerializer, url_path='start-task')
    def start_task(self, request):
        """
        接收一個 nocode_bench_id，查找數據庫中對應的任務並啟動它。
        """
        serializer = TaskStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        nocode_id = serializer.validated_data['nocode_bench_id']

        # 1. 查找 (Get) 任務，而不是創建 (Create)
        try:
            task = EvaluationTask.objects.get(nocode_bench_id=nocode_id)
        except EvaluationTask.DoesNotExist:
            return Response(
                {"error": f"Task with nocode_bench_id '{nocode_id}' not found. Please run 'load_benchmark_data' first."},
                status=status.HTTP_404_NOT_FOUND
            )

        # 檢查任務是否已在運行
        if task.status == 'RUNNING':
            return Response(
                {"message": "Task is already running."},
                status=status.HTTP_409_CONFLICT
            )

        # 2. 啟動 Celery 任務 (我們傳遞的是數據庫的主鍵 task.id)
        celery_result = process_evaluation_task.delay(task.id) 

        # 3. 更新 task 狀態和 Celery ID
        task.celery_task_id = celery_result.id
        task.status = 'PENDING' # 設置為 PENDING，Celery worker 會將其切換為 RUNNING
        task.result = None # 如果是重新運行，清除舊結果
        task.save()

        # 4. 返回 202 Accepted
        return Response(
            EvaluationTaskSerializer(task).data, 
            status=status.HTTP_202_ACCEPTED
        )

    @action(detail=False, methods=['post'], url_path='start-all')
    def start_all_tasks(self, request):
        """
        (推薦) 啟動數據庫中所有處於 'PENDING' 狀態的任務。
        """
        # 查找所有 PENDING 或 FAILED 的任務以重新運行
        tasks_to_run = EvaluationTask.objects.filter(
            status__in=['PENDING', 'FAILED', 'FAILED_APPLY', 'FAILED_TEST']
        )
        
        count = 0
        for task in tasks_to_run:
            # 清除舊結果並重置狀態
            if hasattr(task, 'result'):
                task.result.delete()
            
            celery_result = process_evaluation_task.delay(task.id)
            task.celery_task_id = celery_result.id
            task.status = 'PENDING'
            task.save()
            count += 1

        return Response(
            {"message": f"Queued {count} tasks for processing."},
            status=status.HTTP_202_ACCEPTED
        )