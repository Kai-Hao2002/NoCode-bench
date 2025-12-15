# agent_core/utils/metrics.py
from unidiff import PatchSet
from io import StringIO

def parse_patch(patch_str: str) -> dict[str, set[int]]:
    if not patch_str: return {}
    try:
        patch = PatchSet(StringIO(patch_str))
        changed_files = {}
        for patched_file in patch:
            if patched_file.is_binary_file: continue
            file_path = patched_file.target_file[2:] if patched_file.target_file.startswith('b/') else patched_file.target_file
            changed_lines = set()
            for hunk in patched_file:
                for line in hunk:
                    if line.is_added:
                        changed_lines.add(line.target_line_no)
                    elif line.is_removed:
                        changed_lines.add(line.source_line_no)
            if changed_lines:
                changed_files[file_path] = changed_lines
        return changed_files
    except Exception as e:
        print(f"Error parsing patch: {e}")
        return {}

def calculate_all_metrics(
    f2p_passed_count: int,
    f2p_total_count: int,
    p2p_passed_count: int,
    p2p_total_count: int,
    regression_tests_passed: bool,
    applied_successfully: bool, 
    generated_patch: str, 
    ground_truth_patch: str, 
    run_time_seconds: float
) -> dict:
# --- 1. Success%  ---
    # F2P (Feature Tests):
    f2p_all_passed = (f2p_passed_count == f2p_total_count) if f2p_total_count > 0 else False
    
    # P2P (Regression Tests):
    # [CHANGE] If total is 0 (meaning no regression tests for this task, or none selected), treat as True (Pass/Ignore)
    if p2p_total_count > 0:
        p2p_all_passed = (p2p_passed_count == p2p_total_count)
    else:
        # No regression tests means no regressions, so consider as passed
        p2p_all_passed = True 
    
    if f2p_all_passed and p2p_all_passed:
        success_percent = 100.0
    else:
        success_percent = 0.0

    # --- 2. RT%  ---
    if p2p_total_count > 0:
        if p2p_passed_count == p2p_total_count:
            rt_percent = 100.0
        else:
            rt_percent = 0.0
    else:
        # No regression tests means no regressions, so consider as fully passing
        rt_percent = 100.0

    # --- 3. FV-Macro ---
    if f2p_total_count > 0:
        fv_macro = (f2p_passed_count / f2p_total_count) * 100.0
    else:
        fv_macro = 0.0

    # Applied%
    applied_percent = 100.0 if applied_successfully else 0.0
    
    # File%
    pred_files_lines = parse_patch(generated_patch)
    gold_files_lines = parse_patch(ground_truth_patch)
    pred_file_set = set(pred_files_lines.keys())
    gold_file_set = set(gold_files_lines.keys())
    
    file_intersection = len(pred_file_set.intersection(gold_file_set))
    
    if len(gold_file_set) > 0:
        file_percent = (file_intersection / len(gold_file_set)) * 100.0
    else:
        file_percent = 100.0 if len(pred_file_set) == 0 else 0.0

    return {
        'success_percent': success_percent,
        'applied_percent': applied_percent,
        'rt_percent': round(rt_percent, 2),
        'fv_macro': round(fv_macro, 2),
        'file_percent': round(file_percent, 2),
        'num_token': len(generated_patch.split()),
        'run_time_seconds': run_time_seconds,
        'f2p_passed_count': f2p_passed_count,
        'f2p_total_count': f2p_total_count,
        'p2p_passed_count': p2p_passed_count,
        'p2p_total_count': p2p_total_count,
    }