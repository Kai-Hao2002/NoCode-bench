# agent_core/utils/llm_client.py
import os
import json
import re
import logging
from google.generativeai.types import GenerationConfig

logger = logging.getLogger(__name__)

def generate_with_retry(model, prompt, generation_config=None):
    """
    直接呼叫 API
    """
    return model.generate_content(prompt, generation_config=generation_config)

def parse_llm_response(raw_response_text: str) -> dict[str, str]:
    modified_files = {}
    file_chunks = re.split(r'--- START OF FILE: (.*?) ---\n', raw_response_text)
    if len(file_chunks) < 2:
        return modified_files
    for i in range(1, len(file_chunks), 2):
        file_path = file_chunks[i].strip()
        content = re.sub(r'--- END OF FILE: .*? ---', '', file_chunks[i+1], flags=re.DOTALL).strip()
        if file_path and content:
            modified_files[file_path] = content
    return modified_files

def get_relevant_files(model, doc_change: str, workspace_path: str) -> list[str]:
    all_files = []
    for root, dirs, files in os.walk(workspace_path):
        if '.git' in dirs: dirs.remove('.git')
        if '.venv' in dirs: dirs.remove('.venv')
        if 'venv' in dirs: dirs.remove('venv')
        for file in files:
            if file.endswith(('.py', '.html', '.css', '.js', '.c', '.cpp', '.h')):
                rel_path = os.path.relpath(os.path.join(root, file), workspace_path)
                all_files.append(rel_path.replace('\\', '/'))
    
    if not all_files: return []

    prompt = (
        f"You are a tech lead. Identify the files needed to implement this documentation change.\n"
        f"**DOC CHANGE:**\n{doc_change}\n\n"
        f"**FILES:**\n{', '.join(all_files[:3000])}\n"
        f"(Total {len(all_files)} files)\n\n"
        f"**INSTRUCTIONS:**\n"
        "1. Identify the CORE files that need modification.\n"
        "2. Return JSON: {{\"files\": [\"path/to/core.py\"]}}\n"
    )

    try:
        # 2. 使用重試函數 (Use the retry function)
        response = generate_with_retry(
            model, 
            prompt,
            generation_config=GenerationConfig(response_mime_type="application/json")
        )
        data = json.loads(response.text)
        llm_files = data.get("files", [])
        valid_files = [f for f in llm_files if f in all_files]
        return valid_files
    except Exception as e:
        print(f"Error in file finding: {e}")
        return []

def build_prompt_for_attempt(doc_change: str, context_content_str: str, history: list[str]) -> str:
    # (此函數保持不變)
    safety_checklist = (
        "**CRITICAL SAFETY CHECKLIST:**\n"
        "1.  **Verify APIs:** Before calling a method, verify it exists in the class definition.\n"
        "2.  **Do NOT Change Signatures:** Keep arguments/return types unless necessary.\n"
        "3.  **Check Imports:** Do not remove necessary imports.\n"
    )

    if not history:
        return (
            f"You are an expert AI software engineer. Implement a feature based on a documentation change.\n\n"
            f"**DOCUMENTATION CHANGE:**\n{doc_change}\n\n"
            f"**ORIGINAL FILE CONTENTS:**\n{context_content_str}\n\n"
            f"{safety_checklist}\n"
            f"**INSTRUCTIONS:**\n"
            "1. Read files and implement the change.\n"
            "2. Response MUST ONLY contain full file contents using the delimiter format.\n"
            "3. DO NOT modify test files.\n\n"
            "**FORMAT:**\n"
            "--- START OF FILE: path/to/file1.py ---\n(content)\n--- END OF FILE: path/to/file1.py ---\n"
        )
    
    history_str = "\n\n".join(history)
    return (
        f"You are an expert AI software engineer. Previous attempt failed.\n\n"
        f"**ORIGINAL DOC CHANGE:**\n{doc_change}\n\n"
        f"**ORIGINAL FILES:**\n{context_content_str}\n\n"
        f"**PREVIOUS FAILED ATTEMPTS:**\n{history_str}\n\n"
        f"{safety_checklist}\n"
        f"**YOUR TASK:**\n"
        "Analyze errors (AttributeError, ImportError, etc.) and Fix the Logic.\n"
        "Provide full file contents.\n"
        "**FORMAT:**\n"
        "--- START OF FILE: path/to/file1.py ---\n(content)\n--- END OF FILE: path/to/file1.py ---\n"
    )