# agent_core/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import EvaluationTask, EvaluationResult 
from django.db.models import Avg, Count, Sum 
from .serializers import TaskStartSerializer, EvaluationTaskSerializer,DemoTaskSerializer,CustomDemoSerializer
from .tasks import process_evaluation_task, process_custom_demo_task
import time

class EvaluationTaskViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = EvaluationTask.objects.all().order_by('-start_time')
    serializer_class = EvaluationTaskSerializer

    @action(detail=False, methods=['post'], serializer_class=TaskStartSerializer, url_path='start-task')
    def start_task(self, request):
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
             task.result.delete() # Clear old result
        task.save()
        return Response(
            EvaluationTaskSerializer(task).data, 
            status=status.HTTP_202_ACCEPTED
        )

    @action(detail=False, methods=['post'], url_path='start-all')
    def start_all_tasks(self, request):
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


    # This function will now correctly average all 7 metrics
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

        # 3. Calculate aggregations
        
        # Paper: FV-Micro = SUM(f2p_passed) / SUM(f2p_total) 
        total_counts = results_queryset.aggregate(
            total_f2p_passed=Sum('f2p_passed_count'),
            total_f2p_total=Sum('f2p_total_count')
        )
        fv_micro = 0.0
        if total_counts['total_f2p_total'] and total_counts['total_f2p_total'] > 0:
            fv_micro = (total_counts['total_f2p_passed'] / total_counts['total_f2p_total']) * 100.0

        # (Calculate averages for all other metrics)
        averages = results_queryset.aggregate(
            Success_Percent=Avg('success_percent'),
            Applied_Percent=Avg('applied_percent'),
            RT_Percent=Avg('rt_percent'),           
            FV_Macro=Avg('fv_macro'),            
            File_Percent=Avg('file_percent'),      
            Avg_Runtime_Seconds=Avg('run_time_seconds'),
            Avg_Tokens=Avg('num_token')         
        )
        
        # Insert our manually calculated FV-Micro
        averages['FV_Micro'] = fv_micro 

        progress_percent = (finished_tasks_count / total_tasks) * 100

        return Response({
            "total_tasks": total_tasks,
            "finished_tasks": finished_tasks_count,
            "progress_percent": round(progress_percent, 2),
            "average_metrics": averages
        })
    @action(detail=False, methods=['post'], serializer_class=DemoTaskSerializer, url_path='run-demo')
    def run_demo(self, request):
        """
        Using a user-defined doc change, the new evaluation 
        is run based on an existing benchmark instance.
        """
        serializer = DemoTaskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        base_id = serializer.validated_data['base_nocode_bench_id']
        custom_doc = serializer.validated_data['custom_doc_change']

        try:
            # 1. Find the basic task to copy its settings.
            base_task = EvaluationTask.objects.get(nocode_bench_id=base_id)
        except EvaluationTask.DoesNotExist:
            return Response(
                {"error": f"base task '{base_id}' not found。"},
                status=status.HTTP_404_NOT_FOUND
            )

        # 2. Create a new task (or find a task specific to the demo)
        # We add a suffix to make it unique.
        demo_nocode_id = f"demo_{base_id}_{time.time()}"
        
        new_task = EvaluationTask.objects.create(
            nocode_bench_id=demo_nocode_id,
            doc_change_input=custom_doc, # <-- Use user-defined prompts

            base_task_id=base_id,
            
            # Copy all other data from the basic task.
            ground_truth_patch=base_task.ground_truth_patch,
            feature_test_patch=base_task.feature_test_patch,
            f2p_test_names=base_task.f2p_test_names,
            p2p_test_names=base_task.p2p_test_names,
            
            status='PENDING'
        )

        # 3. Start Celery task
        celery_result = process_evaluation_task.delay(new_task.id) 
        new_task.celery_task_id = celery_result.id
        new_task.save()
        
        # 4. Return data for the new task
        return Response(
            EvaluationTaskSerializer(new_task).data, 
            status=status.HTTP_202_ACCEPTED
        )
    
    @action(detail=False, methods=['post'], serializer_class=CustomDemoSerializer, url_path='run-custom-repo')
    def run_custom_repo(self, request):
        """
        在一個自定義的 GitHub 倉庫上運行 Agent。
        """
        serializer = CustomDemoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        github_url = serializer.validated_data['github_url']
        custom_doc = serializer.validated_data['doc_change']

        # We "abuse" the nocode_bench_id field to store the Git URL
        # and use 'base_task_id' to mark this as a custom task
        demo_nocode_id = f"custom_{github_url}#{time.time()}"
        
        new_task = EvaluationTask.objects.create(
            nocode_bench_id=demo_nocode_id,
            doc_change_input=custom_doc,
            base_task_id="CUSTOM_REPO_DEMO", # <-- tag as custom demo
            
            # (All NoCode-bench related fields are empty)
            ground_truth_patch="",
            feature_test_patch="",
            f2p_test_names=[],
            p2p_test_names=[],
            
            status='PENDING'
        )

        # 3. Start a *new* Celery quest
        celery_result = process_custom_demo_task.delay(new_task.id) 
        new_task.celery_task_id = celery_result.id
        new_task.save()
        
        # 4. Return data for the new task
        return Response(
            EvaluationTaskSerializer(new_task).data, 
            status=status.HTTP_202_ACCEPTED
        )