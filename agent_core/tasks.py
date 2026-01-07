# agent_core/tasks.py
import logging
import shutil
import os
import subprocess
from celery import shared_task
from django.utils import timezone
from django.db import connection
from django.conf import settings
from google import generativeai as genai

from .models import EvaluationTask, EvaluationResult, EvaluationAttempt

# Import new utilities
from .utils.workspace import setup_workspace, setup_custom_workspace, get_file_contexts, onerror
from .utils.llm_client import get_relevant_files, build_prompt_for_attempt, parse_llm_response,generate_with_retry
from .utils.docker_runner import run_tests_in_docker
from .utils.metrics import calculate_all_metrics

logger = logging.getLogger(__name__)

@shared_task(bind=True)
def process_evaluation_task(self, task_id):
    MAX_ATTEMPTS = 1
    task = None
    workspace_path = None
    final_status = 'FAILED'
    final_patch = ""
    applied_successfully = False
    
    try:
        task = EvaluationTask.objects.get(pk=task_id)
        workspace_id_to_use = task.base_task_id if task.base_task_id else task.nocode_bench_id

        # Setup
        EvaluationResult.objects.filter(task=task).delete()
        EvaluationAttempt.objects.filter(task=task).delete()
        task.status = 'RUNNING'
        task.start_time = timezone.now()
        task.celery_task_id = self.request.id
        task.error_details = None
        task.save()
        
        logger.info(f"Starting task {task.id} for '{workspace_id_to_use}'")

        if not settings.GEMINI_API_KEY: raise Exception("Gemini client not configured.")
        genai.configure(api_key=settings.GEMINI_API_KEY)
        

        # 1. file retrieval setup
        search_model = genai.GenerativeModel('gemini-2.5-flash')
        # 2. use coder model for generation
        coder_model = genai.GenerativeModel('gemini-2.5-pro') 
        
        workspace_path = setup_workspace(workspace_id_to_use)
        
        # use Flash to find relevant files
        logger.info(f"[Task {task.id}] Finding files using Flash model...")
        relevant_files = get_relevant_files(search_model, task.doc_change_input, workspace_path)
        
        if not relevant_files: raise Exception("AI failed to identify relevant files.")
        
        # fetch file contents
        # limit to 200,000 chars
        context_content_str = get_file_contexts(workspace_path, relevant_files, max_chars=200000)
        
        if not context_content_str: raise Exception("Relevant files could not be read.")

        history = []
        f2p_passed_count = f2p_total_count = p2p_passed_count = p2p_total_count = 0
        regression_tests_passed = False

        # 2. Attempt Loop
        for i in range(MAX_ATTEMPTS):
            attempt_num = i + 1
            prompt_text = build_prompt_for_attempt(task.doc_change_input, context_content_str, history)
            
            # --- Logic formerly in services.run_agent_attempt ---
            try:
                response = generate_with_retry(coder_model, prompt_text)
                raw_response = response.text
            except Exception as e:
                # if all retries fail
                logger.error(f"LLM Generation failed after retries: {e}")
                final_status = 'FAILED'
                break

            modified_files = parse_llm_response(raw_response)
            
            # Apply Changes
            if modified_files:
                subprocess.run(['git', 'reset', '--hard', 'HEAD'], cwd=workspace_path, capture_output=True)
                for file_path, new_content in modified_files.items():
                    if '..' in file_path: continue
                    full_path = os.path.join(workspace_path, file_path)
                    os.makedirs(os.path.dirname(full_path), exist_ok=True)
                    
                    # added newline='\n' to prevent CRLF on Windows
                    # new line to ensure content itself does not contain CRLF (double safety)
                    with open(full_path, 'w', encoding='utf-8', newline='\n') as f: 
                        # write content with LF 
                        f.write(new_content.replace('\r\n', '\n'))
                
                # Get Git Diff
                diff_res = subprocess.run(
                    ['git', 'diff'], 
                    cwd=workspace_path, 
                    capture_output=True, 
                    text=True, 
                    encoding='utf-8'
                )
                
                # final_patch with LF endings
                final_patch = diff_res.stdout.replace('\r\n', '\n')
                
                status_code = 'PASSED'
            else:
                status_code = 'APPLY_FAILED'
                final_patch = ""

            test_output = ""
            if status_code != 'APPLY_FAILED' and final_patch.strip():
                
                safe_p2p_names = list(set([t.split('[')[0] for t in task.p2p_test_names]))
                
                # Run Docker Tests
                f2p_p, f2p_t, p2p_p, p2p_t, test_output = run_tests_in_docker(
                    str(task.id), task.repo, task.version, task.base_commit,
                    final_patch, task.feature_test_patch, 
                    task.f2p_test_names, 
                    safe_p2p_names
                )

                f2p_passed_count, f2p_total_count = f2p_p, f2p_t
                p2p_passed_count, p2p_total_count = p2p_p, p2p_t
                
                ft_pass = (f2p_p == f2p_t) if f2p_t > 0 else False
                rt_pass = (p2p_p == p2p_t) if p2p_t > 0 else True
                regression_tests_passed = rt_pass
                
                if ft_pass and rt_pass: 
                    status_code = 'PASSED'
                else: 
                    status_code = 'TEST_FAILED'
            # ----------------------------------------------------

            EvaluationAttempt.objects.create(
                task=task, attempt_number=attempt_num, status=status_code,
                prompt_text=prompt_text, raw_response=raw_response,
                generated_patch=final_patch, test_output=test_output
            )
            
            applied_successfully = (status_code != 'APPLY_FAILED')
            if status_code == 'PASSED':
                final_status = 'COMPLETED'
                break
            elif status_code == 'APPLY_FAILED':
                final_status = 'FAILED_APPLY'
                break
            else:
                final_status = 'FAILED_TEST'
                history.append(f"ATTEMPT {attempt_num} FAILED.\nPATCH:\n{final_patch}\nERRORS:\n{test_output}")

        # 3. Metrics & Save
        run_time = (timezone.now() - task.start_time).total_seconds()
        metrics = calculate_all_metrics(
            f2p_passed_count, f2p_total_count, p2p_passed_count, p2p_total_count,
            regression_tests_passed, applied_successfully,
            final_patch, task.ground_truth_patch or "", run_time
        )
        
        EvaluationResult.objects.create(task=task, generated_patch=final_patch, **metrics)
        task.status = final_status
        task.end_time = timezone.now()
        task.save()
            
    except Exception as e:
        logger.error(f"Task {task_id} error: {e}", exc_info=True)
        if task:
            task.status = 'FAILED'
            task.error_details = str(e)
            task.end_time = timezone.now()
            task.save()
    finally:
        connection.close()
        if workspace_path and os.path.exists(workspace_path):
            shutil.rmtree(workspace_path, onerror=onerror)

@shared_task(bind=True)
def process_custom_demo_task(self, task_id):
    task = None
    workspace_path = None
    try:
        task = EvaluationTask.objects.get(pk=task_id)
        task.status = 'RUNNING'
        task.start_time = timezone.now()
        task.save()

        if not settings.GEMINI_API_KEY: raise Exception("No Gemini Key")
        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-2.5-pro')

        # Parse custom ID
        github_url = task.nocode_bench_id.replace("custom_", "", 1).split('#')[0]
        
        workspace_path = setup_custom_workspace(github_url)
        relevant_files = get_relevant_files(model, task.doc_change_input, workspace_path)
        context_content_str = get_file_contexts(workspace_path, relevant_files)
        
        prompt = build_prompt_for_attempt(task.doc_change_input, context_content_str, [])
        
        # Simple Agent Run (No Docker)
        response = model.generate_content(prompt)
        
        # 1. Apply Changes
        token_count = 0
        if response.usage_metadata:
            token_count = response.usage_metadata.total_token_count
            
        modified_files = parse_llm_response(response.text)
        
        final_patch = ""
        if modified_files:
            for file_path, new_content in modified_files.items():
                if '..' in file_path: continue
                full_path = os.path.join(workspace_path, file_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, 'w', encoding='utf-8') as f: f.write(new_content)
            
            res = subprocess.run(['git', 'diff', '--no-prefix'], cwd=workspace_path, capture_output=True, text=True, encoding='utf-8')
            final_patch = res.stdout
            task.status = 'COMPLETED'
        else:
            task.status = 'FAILED_APPLY'

        # 2. Calculate run time
        end_time = timezone.now()
        run_time = (end_time - task.start_time).total_seconds()

        # 3. Save Result
        EvaluationResult.objects.create(
            task=task, 
            generated_patch=final_patch, 
            applied_percent=100.0 if task.status=='COMPLETED' else 0.0,
            p2p_passed_count=-1, 
            p2p_total_count=-1,
            num_token=token_count,        
            run_time_seconds=run_time     
        )
        
        task.end_time = end_time
        task.save()
        
    except Exception as e:
        logger.error(f"Demo Task {task_id} error: {e}", exc_info=True)
        if task:
            task.status = 'FAILED'
            task.error_details = str(e)
            task.save()
    finally:
        connection.close()
        if workspace_path: shutil.rmtree(workspace_path, onerror=onerror)