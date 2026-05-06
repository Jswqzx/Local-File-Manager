from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
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


def show_url_params_dialog(
    parent: QWidget,
    current_url: str,
    current_params: str,
) -> tuple[str, str] | None:
    dialog = QDialog(parent)
    dialog.setWindowTitle("网址与参数")
    dialog.resize(680, 420)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(8)

    form_layout = QFormLayout()
    form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

    url_input = QLineEdit()
    url_input.setPlaceholderText("https://example.com/api")
    url_input.setText(current_url)

    params_input = QPlainTextEdit()
    params_input.setPlaceholderText("输入查询参数，例如 a=1&b=2 或多行 key=value")
    params_input.setPlainText(current_params)

    form_layout.addRow("网址", url_input)
    form_layout.addRow("参数", params_input)
    layout.addLayout(form_layout)

    button_box = QDialogButtonBox()
    open_browser_button = button_box.addButton("在浏览器打开", QDialogButtonBox.ButtonRole.ActionRole)
    close_button = button_box.addButton("关闭", QDialogButtonBox.ButtonRole.AcceptRole)
    close_button.clicked.connect(dialog.accept)
    layout.addWidget(button_box)

    def open_in_browser() -> None:
        url_text = url_input.text().strip()
        if not url_text:
            QMessageBox.warning(dialog, "提示", "请先输入网址。")
            return

        full_url = build_url_with_params(url_text, params_input.toPlainText().strip())
        if not QDesktopServices.openUrl(QUrl(full_url)):
            QMessageBox.warning(dialog, "提示", f"无法打开浏览器: {full_url}")

    open_browser_button.clicked.connect(open_in_browser)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None

    return url_input.text().strip(), params_input.toPlainText().strip()


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
