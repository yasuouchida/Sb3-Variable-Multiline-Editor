"""
Scratch sb3 変数改行編集ツール Streamlit版

機能:
- ブラウザ上で .sb3 ファイルをアップロード
- ステージ／スプライトをリストから選択
- 「新規作成」または「既存の変数」を選択
- 既存変数の場合、古い内容を複数行テキストエリアに表示して編集
- 編集欄には最初から END 行を用意
- END より前の内容だけを変数値として保存
- 半角スペース・全角スペース・行頭スペース・行末スペースを保持
- 編集済み .sb3 をブラウザからダウンロード

実行方法:
1. このファイルを app.py などの名前で保存
2. 必要ライブラリをインストール
   pip install streamlit
3. 起動
   streamlit run app.py

注意:
- END 行は保存終了位置を示す目印です。
- END より後ろの文字列は保存されません。
- END 行そのものも変数には保存されません。
- END より前のスペースは、行頭・行末を含めてそのまま保存されます。
- Scratch の .sb3 は ZIP 形式です。
- 本ツールは ZIP 内の project.json の variables を編集します。
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from copy import deepcopy
from typing import Any

import streamlit as st


# ============================================================
# 基本設定
# ============================================================

END_MARKER = "<<<END>>>"

st.set_page_config(
    page_title="Scratch sb3 変数改行編集ツール",
    page_icon="🧩",
    layout="wide",
)


# ============================================================
# セッション状態
# ============================================================

def init_session_state() -> None:
    defaults = {
        "project": None,
        "original_sb3_bytes": None,
        "original_filename": None,
        "target_index": 0,
        "mode": "新規作成",
        "selected_var_id": None,
        "var_name": "",
        "var_body": END_MARKER,
        "last_loaded_key": None,
        "message": "",
        "download_bytes": None,
        "download_filename": None,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_session_state()


# ============================================================
# sb3 / project.json の読み書き
# ============================================================

def read_project_json_from_sb3_bytes(sb3_bytes: bytes) -> dict[str, Any]:
    if not zipfile.is_zipfile(io.BytesIO(sb3_bytes)):
        raise ValueError("このファイルは有効な sb3 / ZIP 形式ではありません。")

    with zipfile.ZipFile(io.BytesIO(sb3_bytes), "r") as zf:
        if "project.json" not in zf.namelist():
            raise ValueError("project.json が見つかりません。")

        with zf.open("project.json") as f:
            return json.loads(f.read().decode("utf-8"))


def build_sb3_bytes(original_sb3_bytes: bytes, project: dict[str, Any]) -> bytes:
    output = io.BytesIO()

    with zipfile.ZipFile(io.BytesIO(original_sb3_bytes), "r") as zin:
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == "project.json":
                    data = json.dumps(
                        project,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    zout.writestr(item, data)
                else:
                    zout.writestr(item, zin.read(item.filename))

    return output.getvalue()


# ============================================================
# Scratchデータ操作
# ============================================================

def get_targets(project: dict[str, Any]) -> list[dict[str, Any]]:
    return project.get("targets", [])


def get_current_target() -> dict[str, Any] | None:
    project = st.session_state.project
    if project is None:
        return None

    targets = get_targets(project)
    if not targets:
        return None

    index = st.session_state.target_index
    if index < 0 or index >= len(targets):
        return None

    return targets[index]


def get_variables(target: dict[str, Any]) -> dict[str, Any]:
    return target.setdefault("variables", {})


def make_unique_variable_id(variables: dict[str, Any]) -> str:
    while True:
        candidate = "var_" + uuid.uuid4().hex[:16]
        if candidate not in variables:
            return candidate


def target_display(index: int, target: dict[str, Any]) -> str:
    kind = "ステージ" if target.get("isStage") else "スプライト"
    name = target.get("name", f"target_{index}")
    var_count = len(target.get("variables", {}))
    return f"{kind}: {name} / 変数数: {var_count}"


def variable_display(var_id: str, raw: Any) -> str:
    if isinstance(raw, list) and len(raw) >= 2:
        name = str(raw[0])
        value = raw[1]
    else:
        name = "未対応形式"
        value = raw

    preview = str(value).replace("\n", "↵")
    if len(preview) > 70:
        preview = preview[:70] + "..."

    return f"{name} = {preview}"


def variable_options(target: dict[str, Any]) -> list[tuple[str, str]]:
    variables = get_variables(target)
    options = []

    for var_id, raw in variables.items():
        if isinstance(raw, list) and len(raw) >= 2:
            options.append((variable_display(var_id, raw), var_id))

    return options


def parse_text_before_end(text: str) -> tuple[str, bool]:
    """
    複数行編集欄から END_MARKER より前の内容だけを取り出す。

    重要:
    - strip() や rstrip() は使わない。
    - 半角スペース、全角スペース、行頭スペース、行末スペースを保持する。
    - ただし、END_MARKER を別行に置くための直前の改行だけは除く。
    """
    if END_MARKER not in text:
        return text, False

    before = text.split(END_MARKER, 1)[0]

    # END直前の改行だけを除く。
    # 行頭・行末のスペースは削らない。
    if before.endswith("\n"):
        before = before[:-1]

    return before, True


def body_with_end_marker(body: Any) -> str:
    body_text = "" if body is None else str(body)

    if body_text:
        return body_text + "\n" + END_MARKER

    return END_MARKER


def reset_editor_for_new_variable() -> None:
    st.session_state.selected_var_id = None
    st.session_state.var_name = ""
    st.session_state.var_body = END_MARKER
    st.session_state.last_loaded_key = None


def load_variable_into_editor(var_id: str) -> None:
    target = get_current_target()
    if target is None:
        return

    variables = get_variables(target)
    raw = variables.get(var_id)

    if not (isinstance(raw, list) and len(raw) >= 2):
        return

    st.session_state.selected_var_id = var_id
    st.session_state.var_name = str(raw[0])
    st.session_state.var_body = body_with_end_marker(raw[1])
    st.session_state.last_loaded_key = make_loaded_key()


def make_loaded_key() -> str:
    return f"{st.session_state.target_index}|{st.session_state.mode}|{st.session_state.selected_var_id}"


def apply_variable_edit() -> None:
    target = get_current_target()

    if target is None:
        st.session_state.message = "対象が選択されていません。"
        return

    name = st.session_state.var_name.strip()
    if not name:
        st.session_state.message = "変数名を入力してください。"
        return

    value, has_end = parse_text_before_end(st.session_state.var_body)
    variables = get_variables(target)

    if st.session_state.mode == "新規作成":
        new_id = make_unique_variable_id(variables)
        variables[new_id] = [name, value]
        st.session_state.selected_var_id = new_id
        st.session_state.message = f"新規変数「{name}」を追加しました。"
    else:
        var_id = st.session_state.selected_var_id
        if not var_id or var_id not in variables:
            st.session_state.message = "編集する既存変数を選択してください。"
            return

        variables[var_id] = [name, value]
        st.session_state.message = f"既存変数「{name}」を更新しました。"

    if not has_end:
        st.session_state.var_body = st.session_state.var_body + "\n" + END_MARKER
        st.session_state.message += f"\n注意: {END_MARKER} がなかったため、末尾に自動追加しました。"

    st.session_state.download_bytes = None
    st.session_state.download_filename = None


def prepare_download() -> None:
    if st.session_state.project is None or st.session_state.original_sb3_bytes is None:
        st.session_state.message = "先にsb3ファイルをアップロードしてください。"
        return

    filename = st.session_state.original_filename or "project.sb3"
    stem = filename[:-4] if filename.lower().endswith(".sb3") else filename
    output_filename = f"{stem}_multiline.sb3"

    try:
        st.session_state.download_bytes = build_sb3_bytes(
            st.session_state.original_sb3_bytes,
            st.session_state.project,
        )
        st.session_state.download_filename = output_filename
        st.session_state.message = f"編集済みsb3を作成しました: {output_filename}"
    except Exception as e:
        st.session_state.message = f"保存に失敗しました: {e}"


# ============================================================
# 画面表示補助
# ============================================================

def show_message() -> None:
    if st.session_state.message:
        if "失敗" in st.session_state.message or "注意" in st.session_state.message:
            st.warning(st.session_state.message)
        else:
            st.success(st.session_state.message)


def show_space_note() -> None:
    st.info(
        "内容欄では、ENDより前の半角スペース・全角スペース・行頭スペース・行末スペースを保持します。"
    )


def inject_css() -> None:
    st.markdown(
        """
        <style>
        textarea {
            font-family: Consolas, "Courier New", monospace !important;
            white-space: pre !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


inject_css()


# ============================================================
# アプリ本体
# ============================================================

st.title("Scratch sb3 変数改行編集ツール V.0.1")
st.caption("Streamlit版：sb3内の変数に、改行やスペースを含む文字列を保存します。")

with st.expander("使い方", expanded=False):
    st.markdown(
        f"""
        1. `.sb3`ファイルをアップロードします。  
        2. 対象のステージまたはスプライトを選びます。  
        3. `新規作成` または `既存の変数` を選びます。  
        4. 内容欄の `{END_MARKER}` より前に、変数へ保存したい内容を入力します。  
        5. `変数に反映` を押します。  
        6. `sb3を作成` → `ダウンロード` の順に操作します。

        `{END_MARKER}` 行そのものと、それより後ろは保存されません。
        """
    )

show_space_note()

uploaded_file = st.file_uploader("1. sb3ファイルをアップロード", type=["sb3"])

if uploaded_file is not None:
    uploaded_bytes = uploaded_file.getvalue()
    uploaded_key = f"{uploaded_file.name}|{len(uploaded_bytes)}"

    if st.session_state.get("uploaded_key") != uploaded_key:
        try:
            project = read_project_json_from_sb3_bytes(uploaded_bytes)
            st.session_state.project = project
            st.session_state.original_sb3_bytes = uploaded_bytes
            st.session_state.original_filename = uploaded_file.name
            st.session_state.uploaded_key = uploaded_key
            st.session_state.target_index = 0
            st.session_state.mode = "新規作成"
            st.session_state.selected_var_id = None
            st.session_state.var_name = ""
            st.session_state.var_body = END_MARKER
            st.session_state.message = f"読み込み完了: {uploaded_file.name}"
            st.session_state.download_bytes = None
            st.session_state.download_filename = None
        except Exception as e:
            st.session_state.project = None
            st.session_state.original_sb3_bytes = None
            st.session_state.original_filename = None
            st.error(f"読み込みに失敗しました: {e}")

show_message()

if st.session_state.project is None:
    st.stop()

project = st.session_state.project
targets = get_targets(project)

if not targets:
    st.error("このsb3には targets が見つかりません。")
    st.stop()

st.divider()

# ============================================================
# 第1画面相当: 対象・モード選択
# ============================================================

st.subheader("2. 対象とモードを選択")

target_labels = [target_display(i, target) for i, target in enumerate(targets)]

st.session_state.target_index = st.selectbox(
    "対象を選択",
    options=list(range(len(targets))),
    format_func=lambda i: target_labels[i],
    index=min(st.session_state.target_index, len(targets) - 1),
)

previous_mode = st.session_state.mode
st.session_state.mode = st.selectbox(
    "モードを選択",
    options=["新規作成", "既存の変数"],
    index=0 if st.session_state.mode == "新規作成" else 1,
)

if previous_mode != st.session_state.mode:
    reset_editor_for_new_variable()

current_target = get_current_target()
assert current_target is not None
variables = get_variables(current_target)
options = variable_options(current_target)

st.divider()

# ============================================================
# 第2画面相当: 変数選択・編集
# ============================================================

st.subheader("3. 変数を編集")

st.markdown(
    f"**対象:** {target_display(st.session_state.target_index, current_target)}  \n"
    f"**モード:** {st.session_state.mode}"
)

if st.session_state.mode == "既存の変数":
    if not options:
        st.warning("この対象には既存変数がありません。新規作成モードを選んでください。")
        st.stop()

    option_ids = [var_id for _, var_id in options]

    if st.session_state.selected_var_id not in option_ids:
        st.session_state.selected_var_id = option_ids[0]
        load_variable_into_editor(st.session_state.selected_var_id)

    selected_var_id = st.selectbox(
        "既存変数を選択",
        options=option_ids,
        format_func=lambda var_id: dict(options).get(var_id, var_id),
        index=option_ids.index(st.session_state.selected_var_id),
    )

    if selected_var_id != st.session_state.selected_var_id:
        load_variable_into_editor(selected_var_id)

else:
    if st.session_state.last_loaded_key != make_loaded_key():
        # 新規作成画面に来たときに、古い既存変数の内容が残らないようにする。
        reset_editor_for_new_variable()
        st.session_state.last_loaded_key = make_loaded_key()

st.session_state.var_name = st.text_input(
    "変数名",
    value=st.session_state.var_name,
    placeholder="変数名を入力してください",
)

st.session_state.var_body = st.text_area(
    f"内容（{END_MARKER} より前だけ保存）",
    value=st.session_state.var_body,
    height=360,
    help="行頭・行末のスペースも保持します。END行そのものは保存しません。",
)

col1, col2 = st.columns([1, 2])

with col1:
    if st.button("変数に反映", type="primary", use_container_width=True):
        apply_variable_edit()
        st.rerun()

with col2:
    if st.button("sb3を作成", use_container_width=True):
        prepare_download()
        st.rerun()

if st.session_state.download_bytes is not None:
    st.download_button(
        label="編集済みsb3をダウンロード",
        data=st.session_state.download_bytes,
        file_name=st.session_state.download_filename,
        mime="application/octet-stream",
        use_container_width=True,
    )

st.divider()

with st.expander("現在の変数一覧を確認", expanded=False):
    if not options:
        st.write("変数はありません。")
    else:
        for label, var_id in options:
            raw = variables[var_id]
            name = raw[0]
            value = raw[1]
            st.markdown(f"**{name}**")
            st.code(str(value), language="text")
