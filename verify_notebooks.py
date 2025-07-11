import json
import re
import copy # Not strictly needed for this verification script but good practice if modifying dicts

def find_problem_cells(cells):
    problem_cell_indices = []
    for i, cell in enumerate(cells):
        if cell["cell_type"] == "markdown":
            source = "".join(cell["source"])
            if source.startswith("### ■ 問題"):
                problem_cell_indices.append(i)
    return problem_cell_indices

def find_corresponding_answer_cell_indices(cells, problem_cell_index, problem_num_str):
    answer_cell_indices = []
    # Corrected logic to find all relevant answer cells for a given problem number
    # This was a bug in the previous thought process where only the first was considered by mistake.
    # The generation script correctly handles multiple cells per problem.
    for i in range(problem_cell_index + 1, len(cells)):
        cell = cells[i]
        if cell["cell_type"] == "code":
            source_lines = cell["source"]
            if source_lines and isinstance(source_lines, list) and source_lines[0].startswith(f"# 解答欄{problem_num_str}"):
                answer_cell_indices.append(i)
        # Stop searching for answer cells for this problem if we encounter the next problem's markdown
        elif cell["cell_type"] == "markdown" and "".join(cell["source"]).startswith("### ■ 問題"):
            # Check if it's a *different* problem
            next_match = re.search(r"### ■ 問題(\d+)", "".join(cell["source"]))
            if next_match and next_match.group(1).zfill(3) != problem_num_str:
                break
    return answer_cell_indices


def count_blanks_in_cell(cell_source):
    if isinstance(cell_source, list):
        cell_source = "".join(cell_source)
    return cell_source.count("____")

def compare_notebooks(original_nb_path, generated_nb_path, expected_blanks_min, expected_blanks_max):
    print(f"\n--- Verifying: {generated_nb_path} ---")
    try:
        with open(original_nb_path, 'r', encoding='utf-8') as f:
            original_nb = json.load(f)
        with open(generated_nb_path, 'r', encoding='utf-8') as f:
            generated_nb = json.load(f)
    except Exception as e:
        print(f"  Error reading notebook files: {e}")
        return False

    original_cells = original_nb["cells"]
    generated_cells = generated_nb["cells"]

    if len(original_cells) != len(generated_cells):
        print(f"  Cell count mismatch: Original {len(original_cells)}, Generated {len(generated_cells)}")
        # This is a significant issue, but we can try to proceed with other checks.

    problem_cell_indices_orig = find_problem_cells(original_cells)

    all_checks_passed_for_this_file = True

    problem_to_answer_indices_orig = {}
    for p_idx in problem_cell_indices_orig:
        problem_cell_source = "".join(original_cells[p_idx]["source"])
        match = re.search(r"### ■ 問題(\d+)", problem_cell_source)
        if match:
            problem_num_str = match.group(1).zfill(3)
            answer_indices = find_corresponding_answer_cell_indices(original_cells, p_idx, problem_num_str)
            if answer_indices:
                 problem_to_answer_indices_orig[problem_num_str] = (p_idx, answer_indices)

    # Check blank counts in answer cells
    for problem_num_str, (p_idx_orig, answer_indices_list_orig) in problem_to_answer_indices_orig.items():
        # Find corresponding problem markdown cell in generated to get the starting point for answer cell search
        p_idx_gen = -1
        for i, cell_gen in enumerate(generated_cells):
            if cell_gen["cell_type"] == "markdown":
                # Ensure problem_num_str (e.g., "001") correctly matches "### ■ 問題001"
                problem_title_prefix = f"### ■ 問題{problem_num_str}"
                if "".join(cell_gen["source"]).startswith(problem_title_prefix):
                    p_idx_gen = i
                    break

        if p_idx_gen == -1:
            problem_title_for_message = "### ■ 問題" + problem_num_str
            print(f"  Problem {problem_num_str}: Markdown cell for problem title '{problem_title_for_message}' not found in generated notebook.")
            all_checks_passed_for_this_file = False
            continue

        answer_indices_list_gen = find_corresponding_answer_cell_indices(generated_cells, p_idx_gen, problem_num_str)

        if not answer_indices_list_gen:
            print(f"  Problem {problem_num_str}: Answer cells not found in generated notebook after identified problem markdown at index {p_idx_gen}.")
            all_checks_passed_for_this_file = False
            continue

        # Compare each answer cell part
        for k, ans_idx_orig in enumerate(answer_indices_list_orig):
            if k >= len(answer_indices_list_gen):
                print(f"  Problem {problem_num_str}, Answer Cell Part {k+1}: Missing in generated notebook.")
                all_checks_passed_for_this_file = False
                continue

            ans_idx_gen = answer_indices_list_gen[k]
            if ans_idx_gen < len(generated_cells) and generated_cells[ans_idx_gen]["cell_type"] == "code":
                num_blanks_found = count_blanks_in_cell(generated_cells[ans_idx_gen]["source"])
                # The blank generation logic might not always hit the exact number,
                # so we check if it's at least 1 and not excessively more than expected.
                # For this check, let's be a bit more lenient on the upper bound if min is met.
                current_min_expected = expected_blanks_min
                current_max_expected = expected_blanks_max

                # If the original cell was very short, fewer blanks might be generated.
                # A more sophisticated check might be needed if num_blanks is large.
                # For now, we assume if blanks are present, it's a good sign.
                # The generation script aims for `num_blanks`.

                if not (current_min_expected <= num_blanks_found <= current_max_expected if current_min_expected > 0 else num_blanks_found >=0) :
                     # If 0 blanks are expected (e.g. a problem with no answer code), then 0 should be found.
                    if expected_blanks_min == 0 and num_blanks_found == 0:
                         print(f"  Problem {problem_num_str}, Answer Cell Part {k+1}: Correctly 0 blanks. Found: {num_blanks_found}")
                    elif num_blanks_found < 1 and expected_blanks_min > 0: # Expecting blanks but found none
                        print(f"  Problem {problem_num_str}, Answer Cell Part {k+1}: No blanks found. Expected: {current_min_expected}-{current_max_expected}")
                        all_checks_passed_for_this_file = False
                    elif num_blanks_found > current_max_expected : # Too many blanks
                        print(f"  Problem {problem_num_str}, Answer Cell Part {k+1}: Too many blanks. Found: {num_blanks_found}, Expected max: {current_max_expected}")
                        all_checks_passed_for_this_file = False
                    else: # Reasonable number of blanks
                         print(f"  Problem {problem_num_str}, Answer Cell Part {k+1}: Blanks found: {num_blanks_found} (Expected range: {current_min_expected}-{current_max_expected})")

                else:
                    print(f"  Problem {problem_num_str}, Answer Cell Part {k+1}: Correct number of blanks. Found: {num_blanks_found}")
            else:
                print(f"  Problem {problem_num_str}, Answer Cell Part {k+1}: Corresponding cell in generated notebook is not a code cell or index out of bounds.")
                all_checks_passed_for_this_file = False

    # Compare non-answer cells
    answer_cell_indices_all_problems_gen = set()
    problem_cell_indices_gen = find_problem_cells(generated_cells)
    for p_idx_g in problem_cell_indices_gen:
        problem_cell_source_g = "".join(generated_cells[p_idx_g]["source"])
        match_g = re.search(r"### ■ 問題(\d+)", problem_cell_source_g)
        if match_g:
            problem_num_str_g = match_g.group(1).zfill(3)
            ans_indices_g = find_corresponding_answer_cell_indices(generated_cells, p_idx_g, problem_num_str_g)
            answer_cell_indices_all_problems_gen.update(ans_indices_g)

    for i in range(min(len(original_cells), len(generated_cells))):
        is_original_answer_cell = False
        for _, ans_indices_list in problem_to_answer_indices_orig.values():
            if i in ans_indices_list:
                is_original_answer_cell = True
                break
        if is_original_answer_cell:
            continue

        # Also check if it's an identified answer cell in the generated notebook, just in case of index shifts.
        # However, the primary check is against original non-answer cells.
        # If cell counts differ, this comparison becomes less reliable for trailing cells.

        if original_cells[i]["cell_type"] != generated_cells[i]["cell_type"]:
            print(f"  Cell {i}: Type mismatch. Original: {original_cells[i]['cell_type']}, Generated: {generated_cells[i]['cell_type']}")
            all_checks_passed_for_this_file = False
            continue

        original_source = original_cells[i].get("source", [])
        generated_source = generated_cells[i].get("source", [])
        if not isinstance(original_source, list): original_source = [str(original_source)] # Ensure list for comparison
        if not isinstance(generated_source, list): generated_source = [str(generated_source)]

        if original_source != generated_source:
            # Allow for minor whitespace changes in markdown that might occur during JSON dump/load
            if original_cells[i]["cell_type"] == "markdown" and "".join(original_source).strip() == "".join(generated_source).strip():
                pass # Likely just EOL or trailing space differences, accept
            else:
                print(f"  Cell {i} (type: {original_cells[i]['cell_type']}): Content mismatch (non-answer cell).")
                # For brevity, don't print full content diff here.
                all_checks_passed_for_this_file = False

    if all_checks_passed_for_this_file:
        print(f"  Verification successful for {generated_nb_path}")
    else:
        print(f"  Verification FAILED for {generated_nb_path}")
    return all_checks_passed_for_this_file

if __name__ == "__main__":
    original_notebook_path = "3_single_agent.ipynb"
    verification_results = {}

    # These are the *target* numbers of blanks for each difficulty.
    # The verification will check if the number of blanks is within a reasonable range (e.g., >=1 and <= target)
    blank_targets = {
        "1_easy/3_single_agent.ipynb": 5,
        "2_normal/3_single_agent.ipynb": 10,
        "3_hard/3_single_agent.ipynb": 20,
    }

    generated_files_to_verify = ["1_easy/3_single_agent.ipynb", "2_normal/3_single_agent.ipynb", "3_hard/3_single_agent.ipynb"]
    overall_success = True

    for gen_file_path in generated_files_to_verify:
        target_blanks = blank_targets.get(gen_file_path)
        if target_blanks is None:
            print(f"Warning: No blank target defined for {gen_file_path}. Skipping blank count check for this file.")
            # Fallback to a generic check if needed, or ensure all files have targets
            min_b, max_b = (0, 0) # Or some other default
        else:
            # Expect at least 1 blank (if target > 0), up to the target number.
            # The generation script tries to make `target_blanks` but might make fewer if not enough candidates.
            min_b = 1 if target_blanks > 0 else 0
            max_b = target_blanks

        result = compare_notebooks(original_notebook_path, gen_file_path, min_b, max_b)
        verification_results[gen_file_path] = result
        if not result:
            overall_success = False

    print("\n--- Overall Verification Summary ---")
    for file_path, status in verification_results.items():
        print(f"{file_path}: {'PASSED' if status else 'FAILED'}")

    if overall_success:
        print("\nAll generated notebooks passed critical verification checks.")
    else:
        print("\nSome generated notebooks FAILED critical verification checks.")
