import os
import json
from django.core.management.base import BaseCommand
from django.conf import settings
from agent_core.models import EvaluationTask

# 數據集文件的確切路徑
DATA_FILE_PATH = os.path.join(settings.BASE_DIR, 'NoCode-bench_Verified', 'test', 'data.jsonl') 

class Command(BaseCommand):
    help = 'Loads the NoCode-bench verified (test) dataset from test/data.jsonl'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.SUCCESS(f'Starting data ingestion from {DATA_FILE_PATH}...'))
        
        if not os.path.exists(DATA_FILE_PATH):
            self.stderr.write(self.style.ERROR(f'Data file not found: {DATA_FILE_PATH}'))
            self.stderr.write(self.style.ERROR('Please ensure "NoCode-bench_Verified/test/data.jsonl" exists in the project root.'))
            return

        total_tasks_created = 0
        total_tasks_updated = 0

        # 讀取這一個 .jsonl 檔案
        try:
            with open(DATA_FILE_PATH, 'r', encoding='utf-8') as f:
                for line_number, line in enumerate(f, 1):
                    try:
                        data = json.loads(line)
                        
                        # --- 這是修改過的部分 ---
                        # 從 JSON 中提取數據
                        repo_name = data.get('repo')             # <-- 修改
                        instance_id = data.get('instance_id')    # <-- 修改
                        prompt_input = data.get('problem_statement') # <-- 修改

                        if not (repo_name and instance_id and prompt_input):
                            self.stderr.write(self.style.ERROR(f'Missing "repo", "instance_id", or "problem_statement" in line {line_number}'))
                            continue
                        
                        # 構建唯一的 nocode_bench_id (使用 "instance_id")
                        bench_id = instance_id

                        # 創建或更新任務
                        task, created = EvaluationTask.objects.update_or_create(
                            nocode_bench_id=bench_id,
                            defaults={
                                'doc_change_input': prompt_input, # 儲存 "problem_statement"
                                'status': 'PENDING'
                            }
                        )
                        # --- 修改結束 ---
                        
                        if created:
                            total_tasks_created += 1
                        else:
                            total_tasks_updated += 1

                    except json.JSONDecodeError:
                        self.stderr.write(self.style.ERROR(f'Failed to decode JSON on line {line_number}'))

        except Exception as e:
            self.stderr.write(self.style.ERROR(f'Error reading file {DATA_FILE_PATH}: {e}'))

        self.stdout.write(self.style.SUCCESS('Data ingestion complete.'))
        self.stdout.write(self.style.SUCCESS(f'Total tasks created: {total_tasks_created}'))
        self.stdout.write(self.style.SUCCESS(f'Total tasks updated: {total_tasks_updated}'))