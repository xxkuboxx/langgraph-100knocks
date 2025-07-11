import json
import re
import random
from copy import deepcopy

# 優先的に穴埋めするキーワードリスト
# (出現頻度、重要度などを考慮して調整)
LANGGRAPH_KEYWORDS = [
    "StateGraph", "END", "Interrupt", "MemorySaver",
    "add_node", "add_edge", "add_conditional_edges",
    "set_entry_point", "compile", "invoke", "get_state",
    "TypedDict", "Annotated",
    # LangChain Core (よく使われるもの)
    "HumanMessage", "AIMessage", "SystemMessage",
    # Python basic keywords (if relevant in context)
    "def", "class", "return", "if", "else", "elif", "for", "while", "try", "except", "import", "from"
]

# その他の一般的なキーワード (優先度低め)
GENERAL_KEYWORDS = [
    "state", "graph", "workflow", "config", "checkpointer",
    "payload", "response", "client", "prompt", "tool", "agent",
    "message", "data", "input", "output", "result", "log", "context"
]

ALL_KEYWORDS = LANGGRAPH_KEYWORDS + GENERAL_KEYWORDS

def get_potential_blanks(code_content):
    """
    コード文字列から穴埋め候補となるキーワードと、その出現箇所を抽出する。
    重複を許容し、出現順にリストで返す。
    """
    potential_blanks = []
    # 正規表現でキーワード、変数名、関数名などを抽出
    # より洗練されたASTパースも考えられるが、ここでは正規表現ベースで進める
    for word in re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', code_content):
        if word in ALL_KEYWORDS:
            potential_blanks.append(word)
        # 単純な変数名なども候補に入れる (優先度は低い)
        elif len(word) > 2 and not word.startswith('_') and word not in ['os', 'sys', 'self', 'cls', 'print', 'str', 'int', 'list', 'dict', 'True', 'False', 'None']: # 除外リスト
             potential_blanks.append(word)

    # LangGraphのキーワードを優先的に前に持ってくる
    langgraph_found = [b for b in potential_blanks if b in LANGGRAPH_KEYWORDS]
    general_found = [b for b in potential_blanks if b in GENERAL_KEYWORDS and b not in langgraph_found]
    other_found = [b for b in potential_blanks if b not in LANGGRAPH_KEYWORDS and b not in general_found]

    # 優先順位に従って結合。LangGraphキーワード内では出現頻度が高いものを優先することも考えられるが、一旦出現順で。
    # 同じキーワードが複数回出てくる場合、それぞれが独立した穴埋め候補となるようにする。
    sorted_blanks = langgraph_found + general_found + other_found
    return sorted_blanks

def create_穴埋め(code_content, num_blanks):
    """
    コード文字列を受け取り、指定された数の穴を '____' で作成する。
    """
    if num_blanks == 0:
        return code_content

    potential_blanks = get_potential_blanks(code_content)
    if not potential_blanks:
        return code_content

    # 実際に穴にするキーワードを決定 (重複を許容しつつ、指定数まで)
    # ランダム性は持たせず、抽出された候補リストの前から順番に選ぶ
    blanks_to_make = potential_blanks[:num_blanks]

    # 選ばれたキーワードをコード中で '____' に置き換える
    # 置き換えは1回のみ (例えば 'StateGraph' が2回出てきても、blanks_to_make に1つだけなら最初の1つだけ置換)
    # これを実現するために、各キーワードの出現回数をカウントし、何番目の出現を置き換えるか管理する

    modified_code = code_content

    # どのキーワードを何回置き換えたかを記録
    replaced_counts = {keyword: 0 for keyword in set(blanks_to_make)}

    # blanks_to_make に含まれるキーワードの総出現回数を事前にカウント
    keyword_total_occurrences_in_code = {kw: 0 for kw in set(blanks_to_make)}
    for word in re.finditer(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', modified_code):
        if word.group(1) in keyword_total_occurrences_in_code:
            keyword_total_occurrences_in_code[word.group(1)] += 1

    # blanks_to_make で指定されたキーワードを、コード中で順番に置き換えていく
    # 例: blanks_to_make = ["StateGraph", "add_node", "StateGraph"]
    # 1. 最初の "StateGraph" を置換
    # 2. 最初の "add_node" を置換
    # 3. 2番目の "StateGraph" を置換

    # 置き換え対象のキーワードとその出現インデックスを事前に特定
    # (keyword, occurrence_index_in_code) のタプルリスト
    # occurrence_index_in_code は0ベース
    targets_for_replacement = []

    # blanks_to_make の各要素について、それがコード中で何番目の出現に対応するかを決定
    # 例: code = "A B A C A", blanks_to_make = ["A", "A", "B"]
    # targets_for_replacement = [("A", 0), ("A", 1), ("B", 0)]

    # blanks_to_make にあるキーワードの、現在の処理対象としての出現回数を追跡
    current_occurrence_in_blanks_to_make = {kw: 0 for kw in set(blanks_to_make)}
    for kw_to_blank in blanks_to_make:
        targets_for_replacement.append((kw_to_blank, current_occurrence_in_blanks_to_make[kw_to_blank]))
        current_occurrence_in_blanks_to_make[kw_to_blank] += 1

    # 実際にコードを走査して置き換え
    # 現在のキーワードが、コード全体で何番目の出現かを追跡
    current_keyword_occurrence_in_code = {kw: 0 for kw in set(blanks_to_make)}

    def replacer(match):
        word = match.group(1)
        if word in replaced_counts: # 置き換え対象のキーワードか
            # この出現が、 targets_for_replacement のいずれかと一致するか確認
            # (word, current_keyword_occurrence_in_code[word]) が targets_for_replacement に含まれるか
            target_tuple = (word, current_keyword_occurrence_in_code[word])

            if target_tuple in targets_for_replacement:
                # この出現は置き換え対象なので、targets_for_replacement から削除 (一度使ったら終わり)
                targets_for_replacement.remove(target_tuple)
                current_keyword_occurrence_in_code[word] += 1 # コード中の出現回数をインクリメント
                return "____" # 置換
            else:
                current_keyword_occurrence_in_code[word] += 1 # コード中の出現回数をインクリメント
                return word # 置換しない
        return word # 関係ない単語

    modified_code = re.sub(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', replacer, modified_code)

    return modified_code

if __name__ == '__main__':
    # テスト用
    sample_code = """
    # グラフ構築
    workflow = StateGraph(ConditionalState)
    workflow.add_node("check", check_number_node)
    workflow.add_node("even", even_node)
    workflow.add_node("odd", odd_node)
    workflow.set_entry_point("check")

    # 条件付きエッジの追加
    workflow.add_conditional_edges(
        "check",
        route_by_parity,
        {
            "to_even": "even",
            "to_odd": "odd"
        }
    )

    workflow.add_edge("even", END)
    workflow.add_edge("odd", END)
    graph = workflow.compile()
    result = graph.invoke({"number": 10})
    """
    print("--- Easy (5 blanks) ---")
    print(create_穴埋め(sample_code, 5))
    print("\n--- Normal (10 blanks) ---")
    print(create_穴埋め(sample_code, 10))
    print("\n--- Hard (15 blanks, or less if not enough candidates) ---")
    print(create_穴埋め(sample_code, 15))

    test_code_2 = "StateGraph StateGraph StateGraph"
    print(create_穴埋め(test_code_2, 2)) # ____ ____ StateGraph

    test_code_3 = "def func1():\n    val = StateGraph()\n    return val\n\ndef func2(graph: StateGraph):\n    graph.add_node('A', lambda x: x)\n    return graph.compile()"
    print("\n--- Complex (7 blanks) ---")
    print(create_穴埋め(test_code_3, 7))

    test_code_4 = "data = {'key': 'value', 'count': 0}\nprint(data['key'])"
    print("\n--- General keywords (2 blanks) ---")
    print(create_穴埋め(test_code_4, 2))

    test_code_5 = "from langgraph.graph import StateGraph, END\nworkflow = StateGraph(ExampleState)\nworkflow.add_node('A', node_a)\nworkflow.add_node('B', node_b)\nworkflow.set_entry_point('A')\nworkflow.add_edge('A', 'B')\nworkflow.add_edge('B', END)\ngraph = workflow.compile()"
    print("\n--- Test Case from Notebook (Easy 5) ---")
    print(create_穴埋め(test_code_5, 5))
    print("\n--- Test Case from Notebook (Normal 10) ---")
    print(create_穴埋め(test_code_5, 10)) # Should pick up StateGraph, END, add_node, set_entry_point, add_edge, compile, workflow, graph etc.
    print("\n--- Test Case from Notebook (Hard 15) ---")
    print(create_穴埋め(test_code_5, 15))


    # 問題001の解答欄コード
    q1_code = """
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, END
from langchain_core.messages import AIMessage # AIMessageは解答例で使うのでここでは不要かも

# 状態定義
class ConditionalState(TypedDict):
    number: int
    message: str

# ノード定義
def check_number_node(state: ConditionalState):
    print(f"入力された数値: {state['number']}")
    return {} # 何も更新しない

def even_node(state: ConditionalState):
    msg = f"{state['number']} は偶数です。"
    print(msg)
    return {"message": msg}

def odd_node(state: ConditionalState):
    msg = f"{state['number']} は奇数です。"
    print(msg)
    return {"message": msg}

# ルーター関数
def route_by_parity(state: ConditionalState):
    if state["number"] % 2 == 0:
        return "to_even" # 偶数ならこの名前を返す (解答例より)
    else:
        return "to_odd" # 奇数ならこの名前を返す (解答例より)

# グラフ構築
workflow = StateGraph(ConditionalState)
workflow.add_node("check", check_number_node)
workflow.add_node("even", even_node)
workflow.add_node("odd", odd_node)
workflow.set_entry_point("check")

# 条件付きエッジの追加
workflow.add_conditional_edges(
    "check",
    route_by_parity,
    {
        "to_even": "even",
        "to_odd": "odd" # 解答例より
    }
)

workflow.add_edge("even", END)
workflow.add_edge("odd", END)
graph = workflow.compile()
"""
    print("\n--- Q1 Easy (5 blanks) ---")
    print(create_穴埋め(q1_code, 5))
    # Expected: StateGraph, END, add_node, set_entry_point, add_conditional_edges
    print("\n--- Q1 Normal (10 blanks) ---")
    print(create_穴埋め(q1_code, 10))
    # Expected: StateGraph, END, add_node, add_node, add_node, set_entry_point, add_conditional_edges, add_edge, add_edge, compile
    print("\n--- Q1 Hard (20 blanks) ---")
    print(create_穴埋め(q1_code, 20))
    # Expected: StateGraph, END, add_node, add_node, add_node, set_entry_point, add_conditional_edges, add_edge, add_edge, compile, TypedDict, Annotated, ConditionalState, workflow, route_by_parity, graph, state, number, message, check_number_node (or similar)
    # The current keyword list might not be exhaustive enough for 20 unique, high-quality blanks in this specific example.
    # The `get_potential_blanks` function will pick from available ones.

"""
出力例:
--- Q1 Easy (5 blanks) ---

from typing import TypedDict, Annotated
from langgraph.graph import ____, ____
from langchain_core.messages import AIMessage # AIMessageは解答例で使うのでここでは不要かも

# 状態定義
class ConditionalState(TypedDict):
    number: int
    message: str

# ノード定義
def check_number_node(state: ConditionalState):
    print(f"入力された数値: {state['number']}")
    return {} # 何も更新しない

def even_node(state: ConditionalState):
    msg = f"{state['number']} は偶数です。"
    print(msg)
    return {"message": msg}

def odd_node(state: ConditionalState):
    msg = f"{state['number']} は奇数です。"
    print(msg)
    return {"message": msg}

# ルーター関数
def route_by_parity(state: ConditionalState):
    if state["number"] % 2 == 0:
        return "to_even" # 偶数ならこの名前を返す (解答例より)
    else:
        return "to_odd" # 奇数ならこの名前を返す (解答例より)

# グラフ構築
workflow = StateGraph(ConditionalState)
workflow.____("check", check_number_node)
workflow.add_node("even", even_node)
workflow.add_node("odd", odd_node)
workflow.____("check")

# 条件付きエッジの追加
workflow.____(
    "check",
    route_by_parity,
    {
        "to_even": "even",
        "to_odd": "odd" # 解答例より
    }
)

workflow.add_edge("even", END)
workflow.add_edge("odd", END)
graph = workflow.compile()

(実際の出力は `get_potential_blanks` と `create_穴埋め` のロジックに依存します)
"""
