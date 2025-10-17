# agent_core/urls.py
from rest_framework.routers import DefaultRouter
from django.urls import path, include
from .views import EvaluationTaskViewSet # 確保這裡使用相對匯入

router = DefaultRouter()
# 註冊 ViewSet，DRF 會自動生成 /tasks/ 和 /tasks/pk/ 等路徑
router.register(r'tasks', EvaluationTaskViewSet, basename='task') 

urlpatterns = router.urls