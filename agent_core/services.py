# agent_core/services.py
import os
import shutil
import subprocess
import time
import re
from google import genai
from google.genai import types
from google.genai.errors import APIError
from django.conf import settings # 用於安全地存取 settings.GEMINI_API_KEY

# --- 核心配置 ---
# 隔離工作區的根目錄 (確保此目錄在系統中存在，例如 /tmp/nocode_bench_runs/)
ROOT_WORKSPACE = os.path.join(settings.BASE_DIR, 'nocode_workspaces') 
os.makedirs(ROOT_WORKSPACE, exist_ok=True)


# --- 輔助函數 (Utility Functions) ---

def setup_workspace(nocode_bench_id):
    """
    根據任務 ID 複製原始程式碼庫到一個隔離的工作目錄。
    注意：您需要將 '/path/to/your/nocode_data/' 替換為您資料集的實際路徑。
    """
    # 假設 NoCode-bench 資料集的所有 Codebase 儲存在此路徑
    ORIGINAL_REPOS_ROOT = '/path/to/your/nocode_data/' 
    
    original_repo_path = os.path.join(ORIGINAL_REPOS_ROOT, nocode_bench_id)
    
    # 建立一個獨特且隔離的暫存目錄
    run_id = str(time.time()).replace('.', '')
    temp_dir = os.path.join(ROOT_WORKSPACE, f'run_{nocode_bench_id}_{run_id}')
    
    if not os.path.exists(original_repo_path):
        # ⚠️ 這是為了防止找不到資料集，實務上應該是存在的
        os.makedirs(original_repo_path, exist_ok=True) 
        # ⚠️ 模擬一個空的程式碼庫以供測試，您應該替換為複製真實 Codebase
        # raise ValueError(f"原始程式碼庫未找到: {original_repo_path}")
    
    # 複製原始程式碼庫到工作目錄 (假設使用 shutil.copytree 複製整個目錄)
    shutil.copytree(original_repo_path, temp_dir)
    return temp_dir

def read_codebase_context(workspace_path):
    """
    模擬 Agent 讀取 codebase，作為給 LLM 的上下文。
    實務上，您需要設計複雜邏輯來判斷哪些檔案與任務相關。
    這裡僅為簡單示例。
    """
    context = []
    # 簡單地讀取幾個關鍵檔案的結構
    for root, _, files in os.walk(workspace_path):
        for file in files:
            # 排除大型檔案、虛擬環境和隱藏檔案
            if file.endswith(('.py', '.txt', '.json', 'setup.cfg')) and not file.startswith('.') and not 'venv' in root:
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read(1000) # 只讀取前 1000 字元作為預覽
                        context.append(f"--- File: {os.path.relpath(file_path, workspace_path)} ---\n{content}\n...\n")
                except Exception:
                    continue
    return "\n".join(context)

def apply_patch_to_repo(temp_dir, patch_code):
    """
    實作邏輯來應用 LLM 生成的補丁程式碼。
    實務上，通常使用 Git 或 'patch' 工具。這裡使用一個簡單的檔案寫入/刪除模擬。
    """
    # 由於補丁應用邏輯非常複雜且容易出錯，我們在這裡簡化為一個成功的模擬。
    # ⚠️ 建議使用專門處理 diff/patch 格式的函式庫來確保可靠性。
    # 如果您的 patch_code 是標準的 `git diff` 或 `unified diff` 格式，
    # 可以使用 Python 的 `subprocess` 執行 `patch` 或 `git apply`。
    
    # 模擬應用成功
    if patch_code.strip():
        # 這裡應該檢查補丁是否會修改文件
        # 如果是 git patch 格式，則應用
        # subprocess.run(['git', 'apply', '--ignore-whitespace', '-'], input=patch_code, cwd=temp_dir, text=True, check=True)
        return True # 假設補丁應用成功
    return False

def calculate_metrics(tests_passed, applied_successfully, patch_code, run_time_seconds, **kwargs):
    """
    計算所有必需的 NoCode-bench 指標。
    FV-Micro/Macro 需要複雜的代碼差異分析，這裡僅為佔位符。
    """
    # 計算 Token 數量 (粗略估計)
    num_token = len(patch_code.split())
    
    # 成功率 (Success%)：補丁成功應用 AND 測試通過
    success_percent = 100.0 if tests_passed and applied_successfully else 0.0
    
    metrics = {
        'Success%': success_percent,
        'Applied%': 100.0 if applied_successfully else 0.0,
        'RT%': run_time_seconds, 
        'FV-Micro': 0.5, # 佔位符
        'FV-Macro': 0.5, # 佔位符
        'File%': 0.1,    # 佔位符
        'num_token': num_token,
    }
    return metrics


# --- 核心 Agent 函數 ---

def run_gemini_agent(task_id: int, nocode_bench_id: str, doc_change: str):
    """主要的 LLM 呼叫和 Agent 協調邏輯。"""
    
    # --- 1. 環境設定與計時 ---
    start_time = time.time()
    workspace_path = None
    
    try:
        # 建立工作區
        workspace_path = setup_workspace(nocode_bench_id)
        
        # 提取程式碼上下文
        code_context = read_codebase_context(workspace_path) 
        
        # --- 2. LLM 程式碼生成 (Code Generation) ---
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        
        # 建立詳細的提示 (Prompt Engineering)
        system_prompt = (
            "You are an expert Python software engineer specializing in fixing and adding features "
            "to open-source projects. Your task is to implement a feature based on a documentation change."
            "The project codebase is provided below. You must analyze the code and generate a patch."
            "Your output MUST ONLY be a single markdown code block containing the unified diff or code "
            "changes. Do NOT include any introductory or explanatory text. "
            "Use the unified diff format (starting with ```diff) for complex changes."
        )

        user_prompt = (
            f"**Task ID:** {nocode_bench_id}\n"
            f"**Documentation Change:** {doc_change}\n\n"
            f"**Full Codebase Context:**\n{code_context}\n\n"
            "Generate the necessary code patch ONLY in a single markdown block."
        )

        # 🚀 修正內容結構：將 System Prompt 作為第一個 User 訊息，指導模型行為
        contents = [
            # 第一條訊息：傳遞系統指令，指導模型行為
            {"role": "user", "parts": [
                {"text": "請嚴格遵守以下角色與輸出格式指令：\n" + system_prompt}
            ]},
            # 第二條訊息：傳遞實際的任務輸入
            {"role": "user", "parts": [
                {"text": user_prompt}
            ]},
        ]


        # 修正後的呼叫方式：
        response = client.models.generate_content(
            model='gemini-2.5-pro',
            contents=contents, 
            # ❌ 移除 config=config 參數
        )
        

        # 提取程式碼補丁 (需要穩健的解析邏輯)
        # 尋找 Markdown 程式碼區塊
        match = re.search(r"```(diff|python|py)\n(.*?)\n```", response.text, re.DOTALL)
        patch_code = match.group(2).strip() if match else response.text.strip() # 嘗試提取或使用全文
        
        # --- 3. 運行測試與評估 ---
        applied_successfully = apply_patch_to_repo(workspace_path, patch_code) 
        
        tests_passed = False
        if applied_successfully:
            # ⚠️ 這裡需要實際運行測試的邏輯
            # subprocess.run(['pytest'], cwd=workspace_path, check=False)
            tests_passed = True # 暫時模擬測試通過

        run_time = time.time() - start_time
        
        # 計算最終指標
        results = calculate_metrics(
            tests_passed=tests_passed, 
            applied_successfully=applied_successfully,
            patch_code=patch_code,
            run_time_seconds=run_time
        )
        
        results['generated_patch'] = patch_code
        print(f"DEBUG: Agent Results Calculated: {results}")
        return results

    except APIError as e:
        return {'error': f"Gemini API Error: {e}"}
    except Exception as e:
        return {'error': f"Agent Run Error: {e}"}
    finally:
        # --- 4. 清理 (Cleanup) ---
        if workspace_path and os.path.exists(workspace_path):
            shutil.rmtree(workspace_path)