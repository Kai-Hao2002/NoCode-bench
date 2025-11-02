# nocode_project/celery.py
import os
from celery import Celery

# Set up the default Django settings module for the 'django' project
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nocode_project.settings')

app = Celery('nocode_project')

# Configure Celery using Django settings
app.config_from_object('django.conf:settings', namespace='CELERY')

# Automatically load tasks from all registered Django app configurations
app.autodiscover_tasks()