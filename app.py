"""
Scratch sb3 変数改行編集ツール Streamlit版

機能:
- ブラウザ上で .sb3 ファイルをアップロード
- ステージ／スプライトをリストから選択
- 「新規作成」または「既存の変数」を選択
- 既存変数の場合、変数名だけをリストに表示して選択
- 既存変数の内部IDは画面に表示しない
- 既存変数の場合、古い内容を複数行テキストエリアに表示して編集
- 本文入力欄の直下に、編集不可の END 行を固定表示
- END 部分にはカーソルが移動しない
- 本文入力欄の内容だけを変数値として保存
- 半角スペース・全角スペース・行頭スペース・行末スペースを保持
- 編集済み .sb3 をブラウザからダウンロード

ボタン色の変化:
- 初期状態: 「変数に反映」が明るい色、「sb3を作成」は控えめな色
- 「変数に反映」後: 「変数に反映」が控えめな色、「sb3を作成」が明るい色
- 「sb3を作成」後: 「sb3を作成」が控えめな色、「編集済みsb3をダウンロード」が明るい色
- 「編集済みsb3をダウンロード」後: ダウンロードボタンが控えめな色になり、「現在の変数一覧を確認」を青色で表示

実行方法:
1. このファイルを app.py などの名前で保存
2. 必要ライブラリをインストール
   pip install streamlit
3. 起動
   streamlit run app.py

注意:
- END 行は保存終了位置を示す目印です。
- END 行は編集できない固定表示です。
- END 行そのものは変数には保存されません。
- 本文入力欄のスペースは、行頭・行末を含めてそのまま保存されます。
- Scratch の .sb3 は ZIP 形式です。
- 本ツールは ZIP 内の project.json の variables を編集します。
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
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
        "uploaded_key": None,
        "uploader_reset_count": 0,
        "target_index": 0,
        "mode": "新規作成",
        "selected_var_id": None,
        "var_name": "",
        "var_body": "",
        "last_loaded_key": None,
        "message": "",
        "download_bytes": None,
        "download_filename": None,
        "edit_applied": False,
        "sb3_created": False,
        "sb3_downloaded": False,
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
    """
    既存変数選択欄に表示する文字列。
    変数IDは表示せず、変数名だけを返す。
    """
    if isinstance(raw, list) and len(raw) >= 2:
        return str(raw[0])

    return "未対応形式"


def variable_options(target: dict[str, Any]) -> list[tuple[str, str]]:
    """
    返り値は [(表示名, 変数ID), ...]。
    表示名は変数名だけ、内部処理は変数IDで行う。
    """
    variables = get_variables(target)
    options = []

    for var_id, raw in variables.items():
        if isinstance(raw, list) and len(raw) >= 2:
            options.append((variable_display(var_id, raw), var_id))

    return options


def parse_text_body(text: str) -> str:
    """
    本文入力欄の内容をそのまま変数値として取り出す。

    重要:
    - END_MARKER は編集不可の固定表示として別に表示する。
    - strip() や rstrip() は使わない。
    - 半角スペース、全角スペース、行頭スペース、行末スペースを保持する。
    """
    return text


def body_for_editor(body: Any) -> str:
    """
    既存変数の本文だけを編集欄に戻す。
    END_MARKER は編集不可の固定表示として別に表示する。
    """
    return "" if body is None else str(body)


def reset_editor_for_new_variable() -> None:
    st.session_state.selected_var_id = None
    st.session_state.var_name = ""
    st.session_state.var_body = ""
    st.session_state.last_loaded_key = None


def make_loaded_key() -> str:
    return f"{st.session_state.target_index}|{st.session_state.mode}|{st.session_state.selected_var_id}"


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
    st.session_state.var_body = body_for_editor(raw[1])
    st.session_state.last_loaded_key = make_loaded_key()


def apply_variable_edit() -> None:
    target = get_current_target()

    if target is None:
        st.session_state.message = "対象が選択されていません。"
        return

    name = st.session_state.var_name.strip()
    if not name:
        st.session_state.message = "変数名を入力してください。"
        return

    value = parse_text_body(st.session_state.var_body)
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

    st.session_state.download_bytes = None
    st.session_state.download_filename = None
    st.session_state.edit_applied = True
    st.session_state.sb3_created = False
    st.session_state.sb3_downloaded = False


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
        st.session_state.sb3_created = True
        st.session_state.sb3_downloaded = False
        st.session_state.message = f"編集済みsb3を作成しました: {output_filename}"
    except Exception as e:
        st.session_state.message = f"保存に失敗しました: {e}"


def mark_downloaded() -> None:
    st.session_state.sb3_downloaded = True


def reset_all_settings() -> None:
    """設定を初期化して、1. sb3ファイルをアップロードの状態に戻す。"""
    st.session_state.project = None
    st.session_state.original_sb3_bytes = None
    st.session_state.original_filename = None
    st.session_state.uploaded_key = None
    st.session_state.uploader_reset_count += 1
    st.session_state.target_index = 0
    st.session_state.mode = "新規作成"
    st.session_state.selected_var_id = None
    st.session_state.var_name = ""
    st.session_state.var_body = ""
    st.session_state.last_loaded_key = None
    st.session_state.message = "設定を初期化しました。1. sb3ファイルをアップロードからやり直してください。"
    st.session_state.download_bytes = None
    st.session_state.download_filename = None
    st.session_state.edit_applied = False
    st.session_state.sb3_created = False
    st.session_state.sb3_downloaded = False


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
        "本文入力欄では、半角スペース・全角スペース・行頭スペース・行末スペースを保持します。"
    )


def inject_css() -> None:
    st.markdown(
        """
        <style>
        textarea {
            font-family: Consolas, "Courier New", monospace !important;
            white-space: pre !important;
        }
        div[data-testid="stTextInput"] input:disabled {
            font-family: Consolas, "Courier New", monospace !important;
            color: #333333 !important;
            -webkit-text-fill-color: #333333 !important;
            background-color: #f3f4f6 !important;
            opacity: 1 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


inject_css()


# ============================================================
# アプリ本体
# ============================================================

st.markdown('<a id="top"></a>', unsafe_allow_html=True)
st.title("Scratch sb3 変数改行編集ツール V.0.1")
st.caption("Streamlit版：sb3内の変数に、改行やスペースを含む文字列を保存します。")

with st.expander("使い方", expanded=False):
    st.markdown(
        f"""
        1. `.sb3`ファイルをアップロードします。  
        2. 対象のステージまたはスプライトを選びます。  
        3. `新規作成` または `既存の変数` を選びます。  
        4. 本文入力欄に、変数へ保存したい内容を入力します。  
        5. 本文入力欄の直下にある `{END_MARKER}` は固定表示で、カーソルは移動しません。  
        6. `変数に反映` を押します。  
        7. `sb3を作成` → `編集済みsb3をダウンロード` の順に操作します。

        `{END_MARKER}` 行そのものは保存されません。
        """
    )

show_space_note()
st.caption(f"終了記号 {END_MARKER} は本文入力欄の直下に固定表示され、編集できません。")

uploaded_file = st.file_uploader(
    "1. sb3ファイルをアップロード",
    type=["sb3"],
    key=f"sb3_uploader_{st.session_state.uploader_reset_count}",
)

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
            st.session_state.var_body = ""
            st.session_state.message = f"読み込み完了: {uploaded_file.name}"
            st.session_state.download_bytes = None
            st.session_state.download_filename = None
            st.session_state.edit_applied = False
            st.session_state.sb3_created = False
            st.session_state.sb3_downloaded = False
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
    st.session_state.edit_applied = False
    st.session_state.sb3_created = False
    st.session_state.sb3_downloaded = False

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
    id_to_label = {var_id: label for label, var_id in options}

    if st.session_state.selected_var_id not in option_ids:
        st.session_state.selected_var_id = option_ids[0]
        load_variable_into_editor(st.session_state.selected_var_id)

    selected_var_id = st.selectbox(
        "既存変数を選択",
        options=option_ids,
        format_func=lambda var_id: id_to_label.get(var_id, ""),
        index=option_ids.index(st.session_state.selected_var_id),
    )

    if selected_var_id != st.session_state.selected_var_id:
        load_variable_into_editor(selected_var_id)
        st.session_state.edit_applied = False
        st.session_state.sb3_created = False
        st.session_state.sb3_downloaded = False

else:
    if st.session_state.last_loaded_key != make_loaded_key():
        reset_editor_for_new_variable()
        st.session_state.last_loaded_key = make_loaded_key()

st.session_state.var_name = st.text_input(
    "変数名",
    value=st.session_state.var_name,
    placeholder="変数名を入力してください",
)

st.session_state.var_body = st.text_area(
    "内容（この欄に入力した本文だけ保存）",
    value=st.session_state.var_body,
    height=360,
    help="行頭・行末のスペースも保持します。終了記号そのものは保存しません。",
)

st.text_input(
    "終了記号（固定・編集不可）",
    value=END_MARKER,
    disabled=True,
)

col1, col2 = st.columns([1, 2])

apply_button_type = "secondary" if st.session_state.edit_applied else "primary"
create_button_type = "secondary" if st.session_state.sb3_created else (
    "primary" if st.session_state.edit_applied else "secondary"
)

with col1:
    if st.button("変数に反映", type=apply_button_type, use_container_width=True):
        apply_variable_edit()
        st.rerun()

with col2:
    if st.button("sb3を作成", type=create_button_type, use_container_width=True):
        prepare_download()
        st.rerun()

if st.session_state.download_bytes is not None:
    download_button_type = "secondary" if st.session_state.sb3_downloaded else (
        "primary" if st.session_state.sb3_created else "secondary"
    )

    st.download_button(
        label="編集済みsb3をダウンロード",
        data=st.session_state.download_bytes,
        file_name=st.session_state.download_filename,
        mime="application/octet-stream",
        type=download_button_type,
        use_container_width=True,
        on_click=mark_downloaded,
    )

st.divider()

if st.session_state.sb3_downloaded:
    st.markdown(
        '<span style="color:#1f77b4; font-weight:700; font-size:1.05rem;">現在の変数一覧を確認</span>',
        unsafe_allow_html=True,
    )

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

st.divider()

if st.button("（設定を初期化して）1. sb3ファイルをアップロードに戻る", use_container_width=True):
    reset_all_settings()
    st.markdown('<meta http-equiv="refresh" content="0; url=#top">', unsafe_allow_html=True)
    st.rerun()
