# agent_core/urls.py
from rest_framework.routers import DefaultRouter
from django.urls import path, include
from .views import EvaluationTaskViewSet 

router = DefaultRouter()
# Register a ViewSet; DRF will automatically generate paths such as /tasks/ and /tasks/pk/.
router.register(r'tasks', EvaluationTaskViewSet, basename='task') 

urlpatterns = router.urls