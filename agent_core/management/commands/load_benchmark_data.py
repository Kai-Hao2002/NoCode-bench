# agent_core/management/commands/load_benchmark_data.py
import os
import json
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from agent_core.models import EvaluationTask

class Command(BaseCommand):
    help = 'Loads the 114 instances from NoCode-bench_Verified/test/data.jsonl into the database.'

    def handle(self, *args, **options):
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
                        
                        # 🚀 更改 (CHANGE): 這些是來自 data.jsonl 的 *真實* 鍵名
                        # (These are the *real* key names from data.jsonl)
                        nocode_bench_id = data.get('instance_id')
                        doc_change = data.get('problem_statement')
                        ground_truth_patch = data.get('feature_patch')
                        feature_test_patch = data.get('test_patch')
                        f2p_test_names = data.get('FAIL2PASS', [])
                        p2p_test_names = data.get('PASS2PASS', [])


                        if not all([nocode_bench_id, doc_change, ground_truth_patch, feature_test_patch]):
                            self.stdout.write(self.style.WARNING(f"Skipping {nocode_bench_id or 'instance'}: missing required fields (id, problem_statement, feature_patch, or test_patch)."))
                            continue
                        
                        EvaluationTask.objects.create(
                            nocode_bench_id=nocode_bench_id,
                            doc_change_input=doc_change,
                            ground_truth_patch=ground_truth_patch,
                            feature_test_patch=feature_test_patch, # 🚀 儲存
                                                                  # (Save)
                            f2p_test_names=f2p_test_names,       # 🚀 儲存
                                                                  # (Save)
                            p2p_test_names=p2p_test_names,       # 🚀 儲存
                                                                  # (Save)
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