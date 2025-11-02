# agent_core/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import EvaluationTask, EvaluationResult 
from django.db.models import Avg, Count, Sum 
from .serializers import TaskStartSerializer, EvaluationTaskSerializer
from .tasks import process_evaluation_task

class EvaluationTaskViewSet(viewsets.ReadOnlyModelViewSet):
    """提供任務的讀取、狀態查詢和觸發。"""
    queryset = EvaluationTask.objects.all().order_by('-start_time')
    serializer_class = EvaluationTaskSerializer

    @action(detail=False, methods=['post'], serializer_class=TaskStartSerializer, url_path='start-task')
    def start_task(self, request):
        """
        (此函數保持不變)
        (This function is unchanged)
        """
        serializer = TaskStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        nocode_id = serializer.validated_data['nocode_bench_id']
        try:
            task = EvaluationTask.objects.get(nocode_bench_id=nocode_id)
        except EvaluationTask.DoesNotExist:
            return Response(
                {"error": f"Task with nocode_bench_id '{nocode_id}' not found. Please run 'load_benchmark_data' first."},
                status=status.HTTP_404_NOT_FOUND
            )
        if task.status == 'RUNNING':
            return Response(
                {"message": "Task is already running."},
                status=status.HTTP_409_CONFLICT
            )
        celery_result = process_evaluation_task.delay(task.id) 
        task.celery_task_id = celery_result.id
        task.status = 'PENDING'
        if hasattr(task, 'result'):
             task.result.delete() # 清除舊結果 (Clear old result)
        task.save()
        return Response(
            EvaluationTaskSerializer(task).data, 
            status=status.HTTP_202_ACCEPTED
        )

    @action(detail=False, methods=['post'], url_path='start-all')
    def start_all_tasks(self, request):
        """
        (此函數保持不變)
        (This function is unchanged)
        """
        tasks_to_run = EvaluationTask.objects.filter(
            status__in=['PENDING', 'FAILED', 'FAILED_APPLY', 'FAILED_TEST']
        )
        count = 0
        for task in tasks_to_run:
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

    # 🚀 更改 (CHANGE): 
    # 此函數現在將正確計算所有 7 個指標的平均值
    # (This function will now correctly average all 7 metrics)
    @action(detail=False, methods=['get'], url_path='summary')
    def summary(self, request):
        """
        計算並返回所有已完成任務的總體平均指標。
        (Calculates and returns the aggregate average metrics for all completed tasks.)
        """
        
        total_tasks = EvaluationTask.objects.count()
        if total_tasks == 0:
            return Response({"message": "No tasks loaded."}, status=status.HTTP_404_NOT_FOUND)

        results_queryset = EvaluationResult.objects.all()
        finished_tasks_count = results_queryset.count()

        if finished_tasks_count == 0:
            return Response({
                "message": "No tasks have completed yet.",
                "total_tasks": total_tasks,
                "finished_tasks": 0,
                "progress_percent": 0.0,
                "average_metrics": None
            })

        # 3. 🚀 更改 (CHANGE): 計算聚合
        # (Calculate aggregations)
        
        # 論文 (Paper): FV-Micro = SUM(f2p_passed) / SUM(f2p_total) [cite: 459]
        total_counts = results_queryset.aggregate(
            total_f2p_passed=Sum('f2p_passed_count'),
            total_f2p_total=Sum('f2p_total_count')
        )
        fv_micro = 0.0
        if total_counts['total_f2p_total'] and total_counts['total_f2p_total'] > 0:
            fv_micro = (total_counts['total_f2p_passed'] / total_counts['total_f2p_total']) * 100.0

        # 計算所有其他指標的平均值
        # (Calculate averages for all other metrics)
        averages = results_queryset.aggregate(
            Success_Percent=Avg('success_percent'),
            Applied_Percent=Avg('applied_percent'),
            RT_Percent=Avg('rt_percent'),           # 
            FV_Macro=Avg('fv_macro'),             # [cite: 461]
            File_Percent=Avg('file_percent'),       # [cite: 379]
            Avg_Runtime_Seconds=Avg('run_time_seconds'),
            Avg_Tokens=Avg('num_token')           # [cite: 377]
        )
        
        # 🚀 新增 (NEW): 插入我們手動計算的 FV-Micro
        # (Insert our manually calculated FV-Micro)
        averages['FV_Micro'] = fv_micro # [cite: 459]

        progress_percent = (finished_tasks_count / total_tasks) * 100

        return Response({
            "total_tasks": total_tasks,
            "finished_tasks": finished_tasks_count,
            "progress_percent": round(progress_percent, 2),
            "average_metrics": averages
        })