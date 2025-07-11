import json
import os
import re
from copy import deepcopy
from quiz_generator import create_穴埋め # quiz_generator.py から関数をインポート

def generate_quiz_notebooks(original_notebook_path="2_control_flow.ipynb"):
    """
    元のJupyter Notebookを読み込み、3つの難易度の穴埋め問題バージョンを生成する。
    """
    try:
        with open(original_notebook_path, 'r', encoding='utf-8') as f:
            notebook_content_str = f.read()
            notebook_json = json.loads(notebook_content_str)
    except FileNotFoundError:
        print(f"エラー: 元のNotebookファイルが見つかりません: {original_notebook_path}")
        return
    except json.JSONDecodeError:
        print(f"エラー: NotebookファイルのJSONパースに失敗しました: {original_notebook_path}")
        return

    difficulties = {
        "easy": {"path": "1_easy/2_control_flow.ipynb", "blanks": 5},
        "normal": {"path": "2_normal/2_control_flow.ipynb", "blanks": 10},
        "hard": {"path": "3_hard/2_control_flow.ipynb", "blanks": 20}
    }

    # 対象となるセルのヘッダーパターン
    # 「# 解答欄001 - グラフ構築」のような形式
    target_cell_header_pattern = r"# 解答欄\d{3} - グラフ構築"

    for level, details in difficulties.items():
        print(f"\n--- {level.upper()} バージョンを生成中 ({details['path']}) ---")
        new_notebook = deepcopy(notebook_json) # 元のNotebookをディープコピー

        for cell in new_notebook.get("cells", []):
            if cell.get("cell_type") == "code":
                source_lines = cell.get("source", [])
                if source_lines:
                    # セルの最初の行が対象パターンのコメントか確認
                    if re.match(target_cell_header_pattern, source_lines[0].strip()):
                        print(f"  対象セル発見: {source_lines[0].strip()}")
                        original_code = "".join(source_lines)
                        modified_code = create_穴埋め(original_code, details["blanks"])

                        # 元の行ごとのリスト形式に戻す
                        modified_source_lines = [line + '\n' for line in modified_code.splitlines(False)]
                        # 最後の行の末尾の改行を調整 (元のソースと同じように)
                        if modified_source_lines and modified_code.endswith('\n'):
                             # create_穴埋め が末尾に改行をつけない場合、元の最終行が改行で終わっていれば合わせる
                            pass # splitlines(False) と line + '\n' で対応できているはず
                        elif modified_source_lines and not modified_code.endswith('\n') and original_code.endswith('\n'):
                            # まれなケース：modified_codeが改行なしで終わり、original_codeが改行ありの場合
                            # 通常create_穴埋めは改行を保持するので、ここに来ることは少ない
                            modified_source_lines[-1] = modified_source_lines[-1].rstrip('\n')

                        # もし元の最終行が改行なしで、splitlines で余計な改行がついていたら削除
                        if not original_code.endswith('\n') and modified_source_lines:
                            modified_source_lines[-1] = modified_source_lines[-1].rstrip('\n')
                        elif original_code.endswith('\n') and modified_source_lines and not modified_source_lines[-1].endswith('\n'):
                             modified_source_lines[-1] += '\n'


                        cell["source"] = modified_source_lines
                        print(f"    -> {details['blanks']} 個の穴埋め処理を実行。")

        # ファイルに保存
        output_path = details["path"]
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(new_notebook, f, indent=1, ensure_ascii=False) # indent=1 はJupyterの標準的なフォーマット
            print(f"  {level.upper()} バージョンのNotebookを保存しました: {output_path}")
        except IOError:
            print(f"エラー: ファイルへの書き込みに失敗しました: {output_path}")

if __name__ == "__main__":
    # `2_control_flow.ipynb` がこのスクリプトと同じディレクトリにあると仮定
    # quiz_generator.py も同じディレクトリにある必要がある
    generate_quiz_notebooks()
