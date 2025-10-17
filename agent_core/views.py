from django.shortcuts import render

# agent_core/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import EvaluationTask
from .serializers import TaskStartSerializer, EvaluationTaskSerializer
from .tasks import process_evaluation_task

class EvaluationTaskViewSet(viewsets.ReadOnlyModelViewSet):
    """提供任務的讀取和狀態查詢。"""
    queryset = EvaluationTask.objects.all().order_by('-start_time')
    serializer_class = EvaluationTaskSerializer

    @action(detail=False, methods=['post'], serializer_class=TaskStartSerializer, url_path='start')
    def start_task(self, request):
        """接收請求並啟動 Celery 異步任務。"""
        serializer = TaskStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        nocode_id = serializer.validated_data['nocode_bench_id']
        doc_change = serializer.validated_data['doc_change_input']

        # 1. 建立任務記錄
        task = EvaluationTask.objects.create(
            nocode_bench_id=nocode_id,
            doc_change_input=doc_change,
            status='PENDING'
        )

        # 2. 啟動 Celery 任務
        # process_evaluation_task 會接收 task.id (primary key)
        celery_result = process_evaluation_task.delay(task.id) 

        # 3. 更新 task 中的 Celery ID (雖然在 task 中也會更新，但這裡提前記錄)
        task.celery_task_id = celery_result.id
        task.save()

        # 4. 返回 202 Accepted
        return Response(
            EvaluationTaskSerializer(task).data, 
            status=status.HTTP_202_ACCEPTED
        )
