# nocode_project/celery.py
import os
from celery import Celery

# 為 'django' 專案設定預設的 Django 設置模組
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nocode_project.settings')

app = Celery('nocode_project')

# 使用 Django 設置來配置 Celery
app.config_from_object('django.conf:settings', namespace='CELERY')

# 從所有已註冊的 Django app 配置中自動載入任務
app.autodiscover_tasks()