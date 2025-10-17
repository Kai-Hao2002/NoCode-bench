# agent_core/serializers.py
from rest_framework import serializers
from .models import EvaluationTask, EvaluationResult

class TaskStartSerializer(serializers.Serializer):
    # 只需要傳入要執行的實例 ID
    nocode_bench_id = serializers.CharField(max_length=255)
    doc_change_input = serializers.CharField() # 實際的文件變更內容

class EvaluationResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvaluationResult
        exclude = ('id', 'task')

class EvaluationTaskSerializer(serializers.ModelSerializer):
    result = EvaluationResultSerializer(read_only=True) # 巢狀序列化結果

    class Meta:
        model = EvaluationTask
        fields = '__all__'