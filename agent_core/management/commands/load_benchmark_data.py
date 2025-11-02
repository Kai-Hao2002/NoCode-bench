# agent_core/management/commands/load_benchmark_data.py
import os
import json
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from agent_core.models import EvaluationTask

class Command(BaseCommand):
    help = 'Loads the 114 instances from NoCode-bench_Verified/test/data.jsonl into the database.'

    def handle(self, *args, **options):
        # 🚀 這是 NoCode-bench_Verified/test/data.jsonl 的正確路徑
        # (This is the correct path to NoCode-bench_Verified/test/data.jsonl)
        JSONL_PATH = os.path.join(settings.BASE_DIR, 'NoCode-bench_Verified', 'test', 'data.jsonl')
        
        if not os.path.exists(JSONL_PATH):
            raise CommandError(f"Dataset file not found at: {JSONL_PATH}")

        self.stdout.write("Deleting old tasks...")
        EvaluationTask.objects.all().delete()
        self.stdout.write("Old tasks deleted.")

        count = 0
        self.stdout.write(f"Loading instances from {JSONL_PATH}...")

        try:
            with open(JSONL_PATH, 'r', encoding='utf-8') as f:
                for line in f:
                    if not line.strip():
                        continue
                    
                    try:
                        data = json.loads(line)
                        
                        # 🚀 這是 data.jsonl 中的正確欄位
                        # (These are the correct fields from data.jsonl)
                        nocode_bench_id = data.get('id')
                        doc_change = data.get('doc_change')
                        ground_truth_patch = data.get('solution_patch')
                        feature_test = data.get('test') # 'test' 欄位包含 test.py 程式碼
                                                        # (The 'test' field has the test.py code)

                        if not all([nocode_bench_id, doc_change, ground_truth_patch, feature_test]):
                            self.stdout.write(self.style.WARNING(f"Skipping instance: missing required fields."))
                            continue
                        
                        EvaluationTask.objects.create(
                            nocode_bench_id=nocode_bench_id,
                            doc_change_input=doc_change,
                            ground_truth_patch=ground_truth_patch,
                            feature_test=feature_test, # 🚀 儲存新功能測試
                                                      # (Save the new feature test)
                            status='PENDING'
                        )
                        count += 1
                    except json.JSONDecodeError:
                        self.stdout.write(self.style.WARNING(f"Skipping invalid JSON line: {line[:50]}..."))
                    except Exception as e:
                         self.stdout.write(self.style.ERROR(f"Failed to load instance: {e}"))

        except Exception as e:
            raise CommandError(f"Failed to read data.jsonl file: {e}")

        self.stdout.write(self.style.SUCCESS(f"Successfully loaded {count} tasks."))