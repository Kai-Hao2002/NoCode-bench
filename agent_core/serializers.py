# agent_core/serializers.py
from rest_framework import serializers
from .models import EvaluationTask, EvaluationResult

class TaskStartSerializer(serializers.Serializer):
    # Simply pass in the instance ID to be executed
    # We will use this ID to "find" the task in the database
    nocode_bench_id = serializers.CharField(max_length=255) 

class EvaluationResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvaluationResult
        exclude = ('id', 'task')

class EvaluationTaskSerializer(serializers.ModelSerializer):
    result = EvaluationResultSerializer(read_only=True) 

    class Meta:
        model = EvaluationTask
        fields = '__all__'
class DemoTaskSerializer(serializers.Serializer):
    base_nocode_bench_id = serializers.CharField(max_length=255)
    custom_doc_change = serializers.CharField()

class CustomDemoSerializer(serializers.Serializer):
    github_url = serializers.URLField()
    doc_change = serializers.CharField()