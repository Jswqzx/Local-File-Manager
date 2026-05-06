from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)


def show_rename_preview_dialog(
    parent: QWidget,
    rename_pairs: list[tuple[Path, Path]],
    skipped_paths: list[str],
) -> None:
    dialog = QDialog(parent)
    dialog.setWindowTitle("替换预览")
    dialog.resize(760, 520)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(8)

    summary = QLabel(
        f"可执行: {len(rename_pairs)} 项"
        + (f" | 跳过: {len(skipped_paths)} 项" if skipped_paths else "")
    )
    layout.addWidget(summary)

    preview_list = QListWidget()
    for source_path, target_path in rename_pairs:
        preview_list.addItem(f"{source_path.name} -> {target_path.name} | {source_path.parent}")
    if skipped_paths:
        preview_list.addItem("---- 以下项目将跳过 ----")
        for line in skipped_paths:
            preview_list.addItem(line)
    layout.addWidget(preview_list)

    close_button = QPushButton("关闭")
    close_button.clicked.connect(dialog.accept)
    layout.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignRight)

    dialog.exec()


def show_params_input_dialog(parent: QWidget, current_params: str) -> str | None:
    dialog = QDialog(parent)
    dialog.setWindowTitle("参数设置")
    dialog.resize(520, 320)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(8)

    params_input = QPlainTextEdit()
    params_input.setPlaceholderText("输入查询参数，例如 a=1&b=2 或多行 key=value")
    params_input.setPlainText(current_params)
    layout.addWidget(params_input)

    button_box = QDialogButtonBox()
    close_button = button_box.addButton("关闭", QDialogButtonBox.ButtonRole.AcceptRole)
    close_button.clicked.connect(dialog.accept)
    layout.addWidget(button_box)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None

    return params_input.toPlainText().strip()


def show_file_update_dialog(
    parent: QWidget,
    current_rows: list[dict[str, str]],
) -> list[dict[str, str]] | None:
    dialog = QDialog(parent)
    dialog.setWindowTitle("文件更新")
    dialog.resize(920, 460)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(8)

    table = QTableWidget(0, 3)
    table.setHorizontalHeaderLabels(["网站", "参数", "更新"])
    table.verticalHeader().setVisible(False)
    table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
    table.horizontalHeader().setStretchLastSection(False)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    layout.addWidget(table)

    source_rows = [
        {
            "url": row.get("url", "").strip(),
            "params": row.get("params", "").strip(),
        }
        for row in current_rows
    ]
    working_rows: list[dict[str, str]] = []

    def open_row_in_browser(row_index: int) -> None:
        if row_index >= len(working_rows):
            return
        url_text = _get_row_url(table, row_index)
        if not url_text:
            QMessageBox.warning(dialog, "提示", "请先输入网址。")
            return
        working_rows[row_index]["url"] = url_text
        full_url = build_url_with_params(url_text, working_rows[row_index].get("params", ""))
        if not QDesktopServices.openUrl(QUrl(full_url)):
            QMessageBox.warning(dialog, "提示", f"无法打开浏览器: {full_url}")

    def edit_row_params(row_index: int) -> None:
        if row_index >= len(working_rows):
            return
        result = show_params_input_dialog(dialog, working_rows[row_index].get("params", ""))
        if result is None:
            return
        working_rows[row_index]["params"] = result

    def append_row(url_text: str = "", params_text: str = "") -> None:
        row_index = table.rowCount()
        table.insertRow(row_index)
        working_rows.append({"url": url_text.strip(), "params": params_text.strip()})

        url_input = QLineEdit()
        url_input.setPlaceholderText("输入网址，例如 https://example.com/api")
        url_input.setText(url_text)
        url_input.editingFinished.connect(
            lambda row=row_index, input_widget=url_input: _sync_row_url(working_rows, row, input_widget)
        )
        table.setCellWidget(row_index, 0, url_input)

        params_button = QPushButton("参数")
        params_button.clicked.connect(lambda _=False, row=row_index: edit_row_params(row))
        table.setCellWidget(row_index, 1, params_button)

        update_button = QPushButton("更新")
        update_button.clicked.connect(lambda _=False, row=row_index: open_row_in_browser(row))
        table.setCellWidget(row_index, 2, update_button)
        table.setRowHeight(row_index, 38)

    for row in source_rows:
        append_row(row.get("url", ""), row.get("params", ""))
    if not working_rows:
        append_row()

    button_row = QHBoxLayout()
    add_button = QPushButton("添加")
    close_button = QPushButton("关闭")
    button_row.addWidget(add_button)
    button_row.addStretch()
    button_row.addWidget(close_button)
    layout.addLayout(button_row)

    add_button.clicked.connect(lambda: append_row())
    close_button.clicked.connect(dialog.accept)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None

    _sync_all_row_urls(table, working_rows)
    return [row for row in working_rows if row.get("url", "").strip()]


def _get_row_url(table: QTableWidget, row_index: int) -> str:
    url_input = table.cellWidget(row_index, 0)
    if isinstance(url_input, QLineEdit):
        return url_input.text().strip()
    return ""


def _sync_row_url(working_rows: list[dict[str, str]], row_index: int, url_input: QLineEdit) -> None:
    if row_index >= len(working_rows):
        return
    working_rows[row_index]["url"] = url_input.text().strip()


def _sync_all_row_urls(table: QTableWidget, working_rows: list[dict[str, str]]) -> None:
    for row_index in range(min(table.rowCount(), len(working_rows))):
        working_rows[row_index]["url"] = _get_row_url(table, row_index)


def build_url_with_params(url_text: str, params_text: str) -> str:
    parts = urlsplit(url_text)
    normalized_params = normalize_params_text(params_text)
    if not normalized_params:
        return url_text

    existing_query = parts.query
    query = f"{existing_query}&{normalized_params}" if existing_query else normalized_params
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def normalize_params_text(params_text: str) -> str:
    cleaned = params_text.strip().lstrip("?")
    if not cleaned:
        return ""

    if "\n" in cleaned and "&" not in cleaned:
        lines = [line.strip().lstrip("&?") for line in cleaned.splitlines() if line.strip()]
        return "&".join(lines)

    return cleaned
