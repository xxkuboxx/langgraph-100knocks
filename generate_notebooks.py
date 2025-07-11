import json
import re
import copy
import os
import random

# LangGraph特有のキーワードリスト (優先度高)
LANGGRAPH_KEYWORDS = [
    "StateGraph", "END", "ToolNode", "MessageGraph", "StatefulRunnable",
    "add_node", "add_edge", "add_conditional_edges", "set_entry_point", "set_finish_point",
    "compile", "invoke", "stream", "batch", "update_state", "get_state",
    "add_messages", "AIMessage", "HumanMessage", "ToolMessage", "SystemMessage", "ChatMessage",
    "BaseMessage", "ToolCall", "tool_calls",
    "TypedDict", "Annotated",
    "LangGraph", "langgraph",
    "prebuilt", "graph", "checkpoint",
    "bind_tools" # LLMにツールをバインドするメソッド
]
# Pythonの主要キーワード (優先度中)
PYTHON_KEYWORDS = [
    "def", "class", "return", "import", "from", "if", "else", "elif",
    "for", "while", "try", "except", "finally", "with", "yield", "lambda",
    "async", "await", "pass", "break", "continue", "global", "nonlocal",
    "assert", "del", "in", "is", "not", "and", "or",
    "True", "False", "None"
]
# LangChain Coreの主要クラス (参考)
LANGCHAIN_CORE_KEYWORDS = [
    "tool", # @tool decorator
    "ChatPromptTemplate", "MessagesPlaceholder",
    "RunnablePassthrough", "RunnableLambda", "RunnableParallel", "RunnableSequence",
    "StrOutputParser", "JsonOutputParser",
    "ChatOpenAI", "AzureChatOpenAI", "ChatVertexAI", "ChatGoogleGenerativeAI", "ChatAnthropic", "ChatBedrock"
]

# 穴埋め対象とするキーワードセット (優先順位を考慮して結合)
# より具体性の高いもの、LangGraphに特有なものを優先的に選ぶため、出現頻度やパターンマッチングで重み付けも考慮できる
TARGET_KEYWORDS_PRIORITIZED = LANGGRAPH_KEYWORDS + PYTHON_KEYWORDS + LANGCHAIN_CORE_KEYWORDS

def find_problem_cells(cells):
    problem_cell_indices = []
    for i, cell in enumerate(cells):
        if cell["cell_type"] == "markdown":
            source = "".join(cell["source"])
            if source.startswith("### ■ 問題"):
                problem_cell_indices.append(i)
    return problem_cell_indices

def find_corresponding_answer_cell(cells, problem_cell_index, problem_num_str):
    # 解答欄セルの特定ロジック
    # 問題セルの後にある「# 解答欄XXX」で始まるコードセルを探す
    # 複数の解答欄セルがある場合も考慮 (e.g., 解答欄XXX - グラフ構築, 解答欄XXX - グラフ実行)
    # ひとまず、問題番号に紐づく最初の解答欄コードセルを対象とする
    # より洗練させるなら、解答欄の種類（グラフ構築、実行など）も区別できるようにする
    answer_cell_indices = []
    # print(f"Searching for answer cell for problem {problem_num_str} after cell {problem_cell_index}")
    for i in range(problem_cell_index + 1, len(cells)):
        cell = cells[i]
        if cell["cell_type"] == "code":
            source_lines = cell["source"]
            if source_lines and isinstance(source_lines, list) and source_lines[0].startswith(f"# 解答欄{problem_num_str}"):
                # print(f"  Found potential answer cell at index {i}: {source_lines[0].strip()}")
                answer_cell_indices.append(i)
    return answer_cell_indices


def get_keywords_from_solution_code(code_source_list):
    """
    解答コードからキーワードや識別子を抽出する（簡易版）。
    より高度な抽出にはAST (Abstract Syntax Tree) の解析が望ましい。
    """
    keywords = set()
    full_code = "".join(code_source_list)

    # Pythonの識別子にマッチする正規表現
    # これには変数名、関数名、クラス名などが含まれる
    identifiers = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', full_code)
    keywords.update(identifiers)

    # 文字列リテラルや数値リテラルは除外（ただし、TARGET_KEYWORDS_PRIORITIZED に含まれるものは残す）
    # ここでは簡易的に、TARGET_KEYWORDS_PRIORITIZED に含まれるもののみを対象とするフィルタリングを行う

    found_keywords = set()
    for token in identifiers: # まず識別子全体をチェック
        if token in TARGET_KEYWORDS_PRIORITIZED:
            found_keywords.add(token)

    # コード行をチェックして、ドット区切りのメソッド呼び出しなどもキーワードとして追加
    for line in code_source_list:
        # 例: workflow.add_node, llm.bind_tools など
        matches = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*)\b', line)
        for match in matches:
            # matchが "messages.AIMessage" のような形ではなく、"workflow.add_node" のような形であることを期待
            # 簡易的なので、"state[\"messages\"]" の "messages" のようなものは拾わない。
            # より正確にはASTを使うべき
            if any(kw in match for kw in LANGGRAPH_KEYWORDS + PYTHON_KEYWORDS): # 関連キーワードを含むか
                 found_keywords.add(match)

    # print(f"  Extracted keywords from code: {found_keywords}")
    return found_keywords


def generate_blanks_in_code_v2(code_lines, num_blanks, problem_keywords):
    """
    コード行のリストを受け取り、指定された数の穴埋めを行う。
    キーワードベースで、より重要な部分を優先的に穴埋めする。
    """
    modified_lines = [line for line in code_lines]
    blank_placeholder = "____"
    blanked_locations = set() # (line_index, word_index_in_line) をタプルで保存

    potential_blanks = [] # (priority, line_idx, word_idx_in_line, word, original_line)

    # 優先キーワードリスト (高優先度から順に)
    priority_keywords = LANGGRAPH_KEYWORDS + PYTHON_KEYWORDS + list(problem_keywords) # 問題固有のキーワードも追加

    for i, line in enumerate(modified_lines):
        if line.strip().startswith("#"): # コメント行はスキップ
            continue

        # 行を単語（トークン）に分割する。正規表現で単語、数値、演算子、区切り文字を保持。
        # () や [] や {} や . や = や , もトークンとして分割
        words = re.findall(r"(\b\w+\b|[.,()\[\]{}:=+\-*/%\"'`])", line)
        # print(f"Line {i}: {line.strip()} -> Words: {words}")


        for j, word in enumerate(words):
            # 優先度付け
            priority = 0
            if word in LANGGRAPH_KEYWORDS:
                priority = 3
            elif word in PYTHON_KEYWORDS:
                priority = 2
            elif word in problem_keywords: # 解答例から抽出したキーワード
                priority = 1

            # `.` を含むメソッド呼び出しなど (e.g., `workflow.add_node`)
            if '.' in word and any(kw in word for kw in LANGGRAPH_KEYWORDS):
                priority = max(priority, 3)


            if priority > 0:
                # 既に穴埋めされた単語や、文字列リテラルの一部は避ける (簡易チェック)
                is_part_of_string = False
                # 簡単なチェック: 前後のトークンがクォートか
                if (j > 0 and words[j-1] in ['"', "'"]) and \
                   (j < len(words) -1 and words[j+1] in ['"', "'"]):
                    is_part_of_string = True

                # "____" が含まれる行のwordは対象外 (既に穴埋め済みとみなす)
                if blank_placeholder in line: # これは行全体なので、もう少し細かく見るべき
                    pass # 一旦対象外とはしない

                if not is_part_of_string:
                     potential_blanks.append((priority, i, j, word, line))

    # 優先度でソート (高いものが先)、同じ優先度ならランダム性を持たせるためにシャッフルも有効
    potential_blanks.sort(key=lambda x: x[0], reverse=True)
    # random.shuffle(potential_blanks) # 同じ優先度内でのランダム性

    blanks_made = 0
    # print(f"Potential blanks found: {len(potential_blanks)}")

    # 実際に穴埋め処理
    # 行ごとに変更を適用するため、行の内容を保持するリストを操作する
    temp_modified_lines = list(modified_lines)

    for priority, line_idx, word_idx, word_to_blank, original_line_content in potential_blanks:
        if blanks_made >= num_blanks:
            break

        # 行を再分割して、該当単語を置換 (ここでのword_idxは分割後のインデックス)
        current_line_words = re.findall(r"(\b\w+\b|[.,()\[\]{}:=+\-*/%\"'`])", temp_modified_lines[line_idx])

        # word_idxが現在の行の単語リストの範囲内か確認
        if word_idx < len(current_line_words) and current_line_words[word_idx] == word_to_blank:
            # 同じ場所を複数回穴埋めしないようにチェック
            if (line_idx, word_idx) in blanked_locations:
                continue

            # word_to_blank が ____ でないことを確認
            if current_line_words[word_idx] == blank_placeholder:
                continue

            # 該当箇所を置換
            # 前後の空白や区切り文字を維持するために、元の行から再構成するアプローチがより堅牢
            # ここでは、正規表現で単語を直接置換する

            # word_to_blank が部分文字列として他の単語に含まれないようにする (e.g., "state" vs "StateGraph")
            # \b は単語境界を示す
            # 確実に置換するために、置換対象の単語の出現回数を数え、word_idxに相当するn番目の出現を置換する

            # line_content_for_replacement = temp_modified_lines[line_idx]
            # occurrences = [m.start() for m in re.finditer(r'\b' + re.escape(word_to_blank) + r'\b', line_content_for_replacement)]

            # target_occurrence_index = -1
            # current_word_occurrence = 0
            # temp_words_for_index = re.findall(r"(\b\w+\b|[.,()\[\]{}:=+\-*/%\"'`])", temp_modified_lines[line_idx])
            # for k_idx, k_word in enumerate(temp_words_for_index):
            #     if k_word == word_to_blank:
            #         if k_idx == word_idx : # これが置換対象の単語
            #             target_occurrence_index = current_word_occurrence
            #             break
            #         current_word_occurrence +=1

            # if target_occurrence_index != -1:
            #     count = 0
            #     def replace_nth(match):
            #         nonlocal count
            #         if count == target_occurrence_index:
            #             count += 1
            #             return blank_placeholder
            #         count += 1
            #         return match.group(0)

            #     new_line_content = re.sub(r'\b' + re.escape(word_to_blank) + r'\b', replace_nth, line_content_for_replacement, count=target_occurrence_index + 1)

            #     if new_line_content != temp_modified_lines[line_idx]: # 実際に置換が行われたか
            #         temp_modified_lines[line_idx] = new_line_content
            #         blanked_locations.add((line_idx, word_idx))
            #         blanks_made += 1
            #         # print(f"  Blanked: L{line_idx} W{word_idx} '{word_to_blank}' -> {temp_modified_lines[line_idx].strip()}")
            # else:
            #     # print(f"  Skipped (occurrence not found): L{line_idx} W{word_idx} '{word_to_blank}'")
            #     pass

            # よりシンプルな置換: 単語リストを直接操作して再結合
            current_line_words[word_idx] = blank_placeholder

            # 単語リストから行を再構成
            # 元の行の空白や構造をできるだけ維持する
            # この方法は、元の空白が失われる可能性があるため、注意が必要
            # 例えば、`a = b` が `a=b` になるなど。
            # Jupyter Notebookのソースはリストなので、行ごとに保持されている。
            # １行の中の空白は、単語分割の仕方による。
            # 下記は単純な結合なので、元の空白は復元できない。
            # new_line_content = "".join(current_line_words) # これだと空白が消える

            # 元の行の構造を維持するため、置換対象の単語の開始位置と終了位置を特定し、
            # スライスで置換する方が良い

            line_content = temp_modified_lines[line_idx]
            # word_to_blank の n 番目の出現を見つける
            nth_occurrence = 0
            current_find_idx = 0
            # print(f"Attempting to blank '{word_to_blank}' in line (idx {word_idx}): {line_content.rstrip()}")

            temp_split_for_idx = re.findall(r"(\b\w+\b|[.,()\[\]{}:=+\-*/%\"'`])", line_content)

            # word_idx が現在の分割リストのどの実際の出現に対応するかをマッピング
            actual_occurrence_count = 0
            for k_idx, k_word in enumerate(temp_split_for_idx):
                if k_word == word_to_blank:
                    if k_idx == word_idx:
                        nth_occurrence = actual_occurrence_count
                        break
                    actual_occurrence_count += 1

            # print(f"  Targeting {nth_occurrence}-th occurrence of '{word_to_blank}'")

            found_count = 0
            new_line_content = ""
            last_pos = 0
            for match in re.finditer(r'\b' + re.escape(word_to_blank) + r'\b', line_content):
                if found_count == nth_occurrence:
                    new_line_content += line_content[last_pos:match.start()] + blank_placeholder
                    last_pos = match.end()
                    # print(f"    Replaced at [{match.start()}:{match.end()}]")
                    break
                found_count += 1
            if last_pos == 0 and found_count > nth_occurrence : # マッチしたが置換対象ではなかった場合など
                 pass #何もしない、またはエラーケース
            elif last_pos != 0: #置換が行われた
                 new_line_content += line_content[last_pos:]
                 temp_modified_lines[line_idx] = new_line_content
                 blanked_locations.add((line_idx, word_idx)) # (line_idx, word_idx_in_original_split)
                 blanks_made += 1
                 # print(f"  Blanked: L{line_idx} W{word_idx} '{word_to_blank}' -> {temp_modified_lines[line_idx].rstrip()}")
            else:
                # print(f"  Skipped (sub error or no match for occurrence): L{line_idx} W{word_idx} '{word_to_blank}'")
                pass


    # print(f"Blanks made: {blanks_made}")
    return temp_modified_lines


def process_notebook(notebook_path, output_path_template, num_blanks_map):
    try:
        with open(notebook_path, 'r', encoding='utf-8') as f:
            notebook_content = json.load(f)
    except FileNotFoundError:
        print(f"Error: Notebook file not found at {notebook_path}")
        return
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {notebook_path}")
        return

    cells = notebook_content["cells"]
    problem_cell_indices = find_problem_cells(cells)

    # 問題番号と対応する解答欄セルのインデックスをマッピング
    problem_to_answer_indices = {}
    for p_idx in problem_cell_indices:
        problem_cell_source = "".join(cells[p_idx]["source"])
        match = re.search(r"### ■ 問題(\d+)", problem_cell_source)
        if match:
            problem_num_str = match.group(1).zfill(3) # "001", "002" 形式
            # print(f"Found Problem {problem_num_str} at cell index {p_idx}")
            # この問題に対応する解答欄セル群を探す
            answer_indices = find_corresponding_answer_cell(cells, p_idx, problem_num_str)
            if answer_indices:
                problem_to_answer_indices[problem_num_str] = answer_indices
                # print(f"  Mapped to answer cells: {answer_indices}")
            # else:
                # print(f"  No answer cell found for problem {problem_num_str}")


    for difficulty, num_blanks in num_blanks_map.items():
        new_notebook = copy.deepcopy(notebook_content)
        new_cells = new_notebook["cells"]

        for problem_num_str, answer_cell_idx_list in problem_to_answer_indices.items():
            # print(f"\nProcessing Problem {problem_num_str} for difficulty '{difficulty}' ({num_blanks} blanks)")

            # この問題のコンテキストからキーワードを抽出 (解答例などから)
            # problem_context_keywords = set() # ここでは簡易的に空セット
            # 実際には、対応する解答例セルや解説セルからキーワードを抽出するロジックが必要
            # 例えば、解答例セルは <details><summary>解答XXX</summary> の中の ```python ... ```

            for answer_cell_idx in answer_cell_idx_list: # 各解答欄セルに対して処理
                if new_cells[answer_cell_idx]["cell_type"] == "code":
                    original_code_lines = new_cells[answer_cell_idx]["source"]

                    # 解答例コードからキーワードを抽出 (もしあれば)
                    # ここでは、元の解答欄コード自体からキーワードを抽出する簡易版
                    problem_specific_keywords = get_keywords_from_solution_code(original_code_lines)

                    # print(f"  Answer cell {answer_cell_idx} original code snippet:\n  " + "".join(original_code_lines[:3]).replace("\n", "\n  "))

                    modified_code_lines = generate_blanks_in_code_v2(original_code_lines, num_blanks, problem_specific_keywords)
                    new_cells[answer_cell_idx]["source"] = modified_code_lines
                    # print(f"  Modified code snippet for cell {answer_cell_idx}:\n  " + "".join(modified_code_lines[:3]).replace("\n", "\n  "))

        output_path = output_path_template.format(difficulty=difficulty)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(new_notebook, f, indent=1, ensure_ascii=False)
            print(f"Successfully generated: {output_path}")
        except IOError:
            print(f"Error: Could not write to output file {output_path}")


if __name__ == "__main__":
    base_notebook_path = "3_single_agent.ipynb"

    # num_blanks_map = {
    #     "easy": 5,
    #     "normal": 10,
    #     "hard": 20
    # }
    # 下記はユーザー指示に合わせる
    num_blanks_map_config = {
        "1_easy": 5,
        "2_normal": 10,
        "3_hard": 20
    }

    for difficulty_folder, num_blanks in num_blanks_map_config.items():
        output_template = f"{difficulty_folder}/3_single_agent.ipynb"
        # process_notebookは難易度名(easy, normal, hard)を期待するので調整
        difficulty_name = difficulty_folder.split('_')[1]

        # process_notebookを呼び出す際に、num_blanks_mapを適切に渡す
        # この場合、一度に1つの難易度だけを処理するので、num_blanks_mapは1要素の辞書になる
        single_difficulty_map = {difficulty_name: num_blanks}

        # output_path_template は {difficulty} を含む形式
        # 例: "1_easy/3_single_agent.ipynb" -> これを生成するためのテンプレートは "1_easy/3_single_agent.ipynb" そのものだが、
        # process_notebook内で difficulty_name を使ってパスを生成する形にする
        # process_notebook の output_path_template 引数は、例えば "{difficulty_folder}/3_single_agent.ipynb" のような形ではなく、
        # "tmp_{difficulty}_notebook.ipynb" のように difficulty をプレースホルダとして含むものを想定している。
        # 今回は直接パスを指定する形で process_notebook を修正するか、呼び出し側でパスを組み立てる。

        # process_notebook の呼び出し方を修正
        # 1. 元のnotebookを読み込む
        try:
            with open(base_notebook_path, 'r', encoding='utf-8') as f:
                notebook_content_main = json.load(f)
        except Exception as e:
            print(f"Failed to load base notebook: {e}")
            continue

        cells_main = notebook_content_main["cells"]
        problem_cell_indices_main = find_problem_cells(cells_main)
        problem_to_answer_indices_main = {}
        for p_idx_main in problem_cell_indices_main:
            problem_cell_source_main = "".join(cells_main[p_idx_main]["source"])
            match_main = re.search(r"### ■ 問題(\d+)", problem_cell_source_main)
            if match_main:
                problem_num_str_main = match_main.group(1).zfill(3)
                answer_indices_main = find_corresponding_answer_cell(cells_main, p_idx_main, problem_num_str_main)
                if answer_indices_main:
                    problem_to_answer_indices_main[problem_num_str_main] = answer_indices_main

        # 2. 新しいnotebookオブジェクトを作成
        new_notebook_for_difficulty = copy.deepcopy(notebook_content_main)
        new_cells_for_difficulty = new_notebook_for_difficulty["cells"]

        # 3. 問題ごとに穴埋め処理
        for problem_num_str, answer_cell_idx_list in problem_to_answer_indices_main.items():
            for answer_cell_idx in answer_cell_idx_list:
                if new_cells_for_difficulty[answer_cell_idx]["cell_type"] == "code":
                    original_code_lines = new_cells_for_difficulty[answer_cell_idx]["source"]
                    problem_specific_keywords = get_keywords_from_solution_code(original_code_lines)
                    modified_code_lines = generate_blanks_in_code_v2(original_code_lines, num_blanks, problem_specific_keywords)
                    new_cells_for_difficulty[answer_cell_idx]["source"] = modified_code_lines

        # 4. ファイルに保存
        output_path_final = f"{difficulty_folder}/3_single_agent.ipynb"
        os.makedirs(os.path.dirname(output_path_final), exist_ok=True)
        try:
            with open(output_path_final, 'w', encoding='utf-8') as f:
                json.dump(new_notebook_for_difficulty, f, indent=1, ensure_ascii=False)
            print(f"Successfully generated: {output_path_final}")
        except IOError as e:
            print(f"Error: Could not write to output file {output_path_final}. Error: {e}")
        except Exception as e:
            print(f"An unexpected error occurred while writing {output_path_final}. Error: {e}")

    print("Notebook generation process finished.")
