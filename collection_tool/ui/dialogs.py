import json
import atexit
import re
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


_SHARED_BROWSER_SESSIONS: dict[bool, dict[str, object]] = {}


def close_shared_browser_sessions() -> None:
    for session in _SHARED_BROWSER_SESSIONS.values():
        context = session.get("context")
        browser = session.get("browser")
        playwright = session.get("playwright")
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass
    _SHARED_BROWSER_SESSIONS.clear()


atexit.register(close_shared_browser_sessions)


class FetchRowDispatcher(QObject):
    start_fetch = pyqtSignal(str, object, str)
    shutdown = pyqtSignal()


class FetchRowWorker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(int, int, object)
    failed = pyqtSignal(str, str)

    @pyqtSlot(str, object, str)
    def run_fetch(self, full_url: str, child_rules: object, purpose: str) -> None:
        self.progress.emit(0, 0, f"正在请求入口页: {full_url}")

        try:
            html_text = fetch_html(full_url)
        except Exception as exc:
            self.failed.emit("入口页获取失败", f"获取 HTML 失败: {exc}")
            return

        rules = child_rules if isinstance(child_rules, list) else []
        matched_results = parse_links_by_rules(
            html_text,
            full_url,
            rules,
            purpose=purpose,
            progress_callback=self._emit_progress,
        )

        parsed_links: list[str] = []
        seen_links: set[str] = set()
        total_pages = 0
        for result in matched_results:
            total_pages += count_result_pages(result)
            for link in flatten_result_links(result):
                if not isinstance(link, str) or link in seen_links:
                    continue
                seen_links.add(link)
                parsed_links.append(link)

        self.finished.emit(total_pages, len(parsed_links), collect_resource_records(matched_results, purpose))

    @pyqtSlot()
    def shutdown_worker(self) -> None:
        close_shared_browser_sessions()

    def _emit_progress(self, current: int, total: int, message: str) -> None:
        self.progress.emit(current, total, message)


def show_rename_preview_dialog(
    parent: QWidget,
    rename_pairs: list[tuple[Path, Path]],
    skipped_paths: list[str],
) -> None:
    dialog = QDialog(parent)
    dialog.setWindowTitle("重命名预览")
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
    params_input.setPlaceholderText(
        "输入查询参数，例如 s=keyword 或 a=1&b=2；规则里的 page_url_template 可用 {params} 复用这里的值"
    )
    params_input.setPlainText(current_params)
    layout.addWidget(params_input)

    button_row = QHBoxLayout()
    save_button = QPushButton("保存")
    close_button = QPushButton("关闭")
    button_row.addStretch()
    button_row.addWidget(save_button)
    button_row.addWidget(close_button)
    layout.addLayout(button_row)

    save_button.clicked.connect(dialog.accept)
    close_button.clicked.connect(dialog.reject)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None

    return params_input.toPlainText().strip()


def show_html_filter_dialog(parent: QWidget) -> dict[str, object] | None:
    dialog = QDialog(parent)
    dialog.setWindowTitle("导出 HTML 设置")
    dialog.resize(420, 320)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(8)

    tip_label = QLabel("输入目标网址，并勾选需要过滤的内容后保存导出。")
    layout.addWidget(tip_label)

    url_input = QLineEdit()
    url_input.setPlaceholderText("输入需要导出 HTML 的目标网址")
    layout.addWidget(url_input)

    comment_checkbox = QCheckBox("过滤 HTML 注释")
    comment_checkbox.setChecked(True)
    script_checkbox = QCheckBox("过滤 JS script 标签")
    script_checkbox.setChecked(True)
    style_checkbox = QCheckBox("过滤 style 标签")
    style_checkbox.setChecked(True)
    stylesheet_checkbox = QCheckBox("过滤 CSS link 标签")
    stylesheet_checkbox.setChecked(True)
    noscript_checkbox = QCheckBox("过滤 noscript 标签")
    noscript_checkbox.setChecked(True)

    layout.addWidget(comment_checkbox)
    layout.addWidget(script_checkbox)
    layout.addWidget(style_checkbox)
    layout.addWidget(stylesheet_checkbox)
    layout.addWidget(noscript_checkbox)

    button_row = QHBoxLayout()
    save_button = QPushButton("保存")
    close_button = QPushButton("关闭")
    button_row.addStretch()
    button_row.addWidget(save_button)
    button_row.addWidget(close_button)
    layout.addLayout(button_row)

    save_button.clicked.connect(dialog.accept)
    close_button.clicked.connect(dialog.reject)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None

    export_url = url_input.text().strip()
    if not export_url:
        QMessageBox.warning(parent, "提示", "请输入目标网址。")
        return None

    return {
        "url": export_url,
        "remove_comments": comment_checkbox.isChecked(),
        "remove_scripts": script_checkbox.isChecked(),
        "remove_styles": style_checkbox.isChecked(),
        "remove_stylesheets": stylesheet_checkbox.isChecked(),
        "remove_noscript": noscript_checkbox.isChecked(),
    }


def show_file_update_dialog(
    parent: QWidget,
    current_rows: list[dict[str, object]],
    current_rules: dict[str, list[dict[str, str]]],
) -> tuple[list[dict[str, object]], dict[str, list[dict[str, str]]]] | None:
    dialog = QDialog(parent)
    dialog.setWindowTitle("文件更新")
    dialog.resize(920, 460)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(8)

    table = QTableWidget(0, 2)
    table.setHorizontalHeaderLabels(["网站", "资源"])
    table.verticalHeader().setVisible(False)
    table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
    table.horizontalHeader().setStretchLastSection(False)
    table.horizontalHeader().setSectionResizeMode(0, table.horizontalHeader().ResizeMode.Stretch)
    table.horizontalHeader().setSectionResizeMode(1, table.horizontalHeader().ResizeMode.ResizeToContents)
    table.horizontalHeader().setSectionResizeMode(2, table.horizontalHeader().ResizeMode.ResizeToContents)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setCurrentCell(0, 0)
    layout.addWidget(table)

    progress_status = QLabel("等待开始更新")
    layout.addWidget(progress_status)

    progress_bar = QProgressBar()
    progress_bar.setRange(0, 1)
    progress_bar.setValue(0)
    layout.addWidget(progress_bar)

    source_rows = [
        {
            "url": str(row.get("url", "")).strip(),
            "params": str(row.get("params", "")).strip(),
            "resources": normalize_resource_items(row.get("resources", [])),
            "resources_by_param": {
                str(params_text).strip(): normalize_resource_items(items)
                for params_text, items in row.get("resources_by_param", {}).items()
                if str(params_text).strip() and isinstance(items, list)
            },
        }
        for row in current_rows
    ]
    working_rows: list[dict[str, object]] = []
    working_rules = {
        entry_url: normalize_child_rules(items)
        for entry_url, items in current_rules.items()
    }
    fetch_state = {"running": False}
    fetch_thread = QThread(dialog)
    fetch_worker = FetchRowWorker()
    fetch_dispatcher = FetchRowDispatcher()
    fetch_worker.moveToThread(fetch_thread)
    fetch_dispatcher.start_fetch.connect(fetch_worker.run_fetch)
    fetch_dispatcher.shutdown.connect(fetch_worker.shutdown_worker)
    fetch_thread.start()

    def update_fetch_progress(current: int, total: int, message: str) -> None:
        progress_status.setText(message)
        if total <= 0:
            progress_bar.setRange(0, 0)
        else:
            progress_bar.setRange(0, total)
            progress_bar.setValue(max(0, min(current, total)))

    def handle_fetch_finished(total_pages: int, link_count: int, _: object) -> None:
        fetch_state["running"] = False
        progress_bar.setRange(0, max(1, total_pages))
        progress_bar.setValue(max(1, total_pages))
        progress_status.setText(f"抓取完成，共 {total_pages} 页，{link_count} 个链接")

    def handle_fetch_failed(status_text: str, detail_text: str) -> None:
        fetch_state["running"] = False
        progress_bar.setRange(0, 1)
        progress_bar.setValue(0)
        progress_status.setText(status_text)
        QMessageBox.warning(dialog, "提示", detail_text)

    fetch_worker.progress.connect(update_fetch_progress)
    fetch_worker.finished.connect(handle_fetch_finished)
    fetch_worker.failed.connect(handle_fetch_failed)

    def fetch_row_html(row_index: int) -> None:
        if fetch_state["running"]:
            QMessageBox.information(dialog, "提示", "当前已有抓取任务在运行，请等待完成后再试。")
            return

        if row_index >= len(working_rows):
            return

        url_text = _get_row_url(table, row_index)
        if not url_text:
            QMessageBox.warning(dialog, "提示", "请先输入网站。")
            return

        working_rows[row_index]["url"] = url_text
        full_url = build_url_with_params(url_text, working_rows[row_index].get("params", ""))
        fetch_state["running"] = True
        update_fetch_progress(0, 0, f"正在请求入口页: {full_url}")
        fetch_dispatcher.start_fetch.emit(full_url, working_rules.get(url_text, []), "")

    def export_row_html() -> None:
        filter_options = show_html_filter_dialog(dialog)
        if filter_options is None:
            return

        full_url = str(filter_options.get("url", "")).strip()
        if not full_url:
            QMessageBox.warning(dialog, "提示", "请先输入目标网址。")
            return

        suggested_name = build_default_export_filename(full_url)
        save_path, _ = QFileDialog.getSaveFileName(
            dialog,
            "保存 HTML 文本",
            suggested_name,
            "Text Files (*.txt);;All Files (*)",
        )
        if not save_path:
            return

        progress_status.setText(f"正在获取并导出 HTML: {full_url}")
        progress_bar.setRange(0, 0)
        QApplication.processEvents()

        try:
            html_text = fetch_html(full_url)
            filtered_html = clean_html_for_output(html_text, filter_options)
            Path(save_path).write_text(filtered_html, encoding="utf-8")
        except Exception as exc:
            progress_bar.setRange(0, 1)
            progress_bar.setValue(0)
            progress_status.setText("HTML 导出失败")
            QMessageBox.warning(dialog, "提示", f"导出 HTML 失败: {exc}")
            return

        progress_bar.setRange(0, 1)
        progress_bar.setValue(1)
        progress_status.setText(f"HTML 已导出到: {save_path}")
        QMessageBox.information(dialog, "完成", f"HTML 已保存到:\n{save_path}")

    def open_row_resources(row_index: int) -> None:
        if row_index >= len(working_rows):
            return
        show_resource_dialog(
            dialog,
            working_rows[row_index],
            working_rules.get(str(working_rows[row_index].get("url", "")).strip(), []),
        )

    def append_row(
        url_text: str = "",
        params_text: str = "",
        resources: object = None,
        resources_by_param: object = None,
    ) -> None:
        row_index = table.rowCount()
        table.insertRow(row_index)
        working_rows.append(
            {
                "url": url_text.strip(),
                "params": params_text.strip(),
                "resources": normalize_resource_items(resources),
                "resources_by_param": (
                    {
                        str(key).strip(): normalize_resource_items(value)
                        for key, value in resources_by_param.items()
                        if str(key).strip() and isinstance(value, list)
                    }
                    if isinstance(resources_by_param, dict)
                    else {}
                ),
            }
        )

        url_input = QLineEdit()
        url_input.setPlaceholderText("输入入口网站，例如 https://example.com/search")
        url_input.setText(url_text)
        url_input.editingFinished.connect(
            lambda row=row_index, input_widget=url_input: _sync_row_url(working_rows, row, input_widget)
        )
        table.setCellWidget(row_index, 0, url_input)

        resource_button = QPushButton("资源")
        resource_button.clicked.connect(lambda _=False, row=row_index: open_row_resources(row))
        table.setCellWidget(row_index, 1, resource_button)

        table.setRowHeight(row_index, 38)

    for row in source_rows:
        append_row(
            row.get("url", ""),
            row.get("params", ""),
            row.get("resources", []),
            row.get("resources_by_param", {}),
        )
    if not working_rows:
        append_row()

    button_row = QHBoxLayout()
    add_button = QPushButton("添加")
    rules_button = QPushButton("规则")
    export_html_button = QPushButton("导出HTML")
    save_button = QPushButton("保存")
    close_button = QPushButton("关闭")
    button_row.addWidget(add_button)
    button_row.addWidget(rules_button)
    button_row.addWidget(export_html_button)
    button_row.addStretch()
    button_row.addWidget(save_button)
    button_row.addWidget(close_button)
    layout.addLayout(button_row)

    add_button.clicked.connect(lambda: append_row())
    rules_button.clicked.connect(
        lambda: open_site_rules_dialog(dialog, table, working_rows, working_rules)
    )
    export_html_button.clicked.connect(export_row_html)
    save_button.clicked.connect(dialog.accept)
    close_button.clicked.connect(dialog.reject)

    def cleanup_fetch_worker() -> None:
        if fetch_thread.isRunning():
            fetch_dispatcher.shutdown.emit()
            fetch_thread.quit()
            fetch_thread.wait(5000)

    dialog.finished.connect(cleanup_fetch_worker)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None

    _sync_all_row_urls(table, working_rows)
    filtered_rows = [row for row in working_rows if row.get("url", "").strip()]
    valid_urls = {row["url"] for row in filtered_rows}
    filtered_rules = {
        entry_url: normalize_child_rules(items)
        for entry_url, items in working_rules.items()
        if entry_url in valid_urls
    }
    return filtered_rows, filtered_rules


def open_site_rules_dialog(
    parent: QWidget,
    source_table: QTableWidget,
    working_rows: list[dict[str, object]],
    working_rules: dict[str, list[dict[str, str]]],
) -> None:
    _sync_all_row_urls(source_table, working_rows)
    entry_urls = [row.get("url", "").strip() for row in working_rows if row.get("url", "").strip()]
    if not entry_urls:
        QMessageBox.warning(parent, "提示", "请先至少添加一个入口网站。")
        return

    result = show_site_rules_dialog(parent, entry_urls, working_rules)
    if result is None:
        return

    working_rules.clear()
    working_rules.update(result)


def show_site_rules_dialog(
    parent: QWidget,
    entry_urls: list[str],
    current_rules: dict[str, list[dict[str, object]]],
) -> dict[str, list[dict[str, object]]] | None:
    dialog = QDialog(parent)
    dialog.setWindowTitle("规则配置")
    dialog.resize(980, 560)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(8)

    tip_label = QLabel("先按入口网站展开。选中任意网址节点后，可在该节点下添加直属子网站规则。抓取时只会按当前节点匹配下一级，再继续向下处理。")
    tip_label.setWordWrap(True)
    layout.addWidget(tip_label)

    rules_tree = QTreeWidget()
    rules_tree.setColumnCount(4)
    rules_tree.setHeaderLabels(["入口网站 / 子网站", "URL 匹配", "Purpose", "配置"])
    rules_tree.setAlternatingRowColors(True)
    layout.addWidget(rules_tree)

    working_rules = {
        entry_url: normalize_child_rules(current_rules.get(entry_url, []))
        for entry_url in entry_urls
    }

    def build_rule_item(
        parent_item: QTreeWidgetItem,
        node_rule: dict[str, object],
        path: tuple[int, ...],
    ) -> None:
        child_name = str(node_rule.get("site_name", "")).strip() or f"子网站 {path[-1] + 1}"
        child_item = QTreeWidgetItem(
            [
                child_name,
                str(node_rule.get("match_url", "")).strip(),
                str(node_rule.get("purpose", "")).strip(),
                "",
            ]
        )
        child_item.setData(0, Qt.ItemDataRole.UserRole, ("child", path))
        parent_item.addChild(child_item)

        config_button = QPushButton("配置")
        config_button.clicked.connect(
            lambda _=False, item=child_item: configure_child_rule(item)
        )
        rules_tree.setItemWidget(child_item, 3, config_button)

        for child_index, nested_rule in enumerate(get_child_rule_children(node_rule)):
            build_rule_item(child_item, nested_rule, path + (child_index,))

    def rebuild_tree() -> None:
        rules_tree.clear()
        for entry_url in entry_urls:
            entry_item = QTreeWidgetItem([entry_url, "", ""])
            entry_item.setData(0, Qt.ItemDataRole.UserRole, ("entry", entry_url, None))
            rules_tree.addTopLevelItem(entry_item)
            entry_item.setExpanded(True)

            for index, child_rule in enumerate(working_rules.get(entry_url, [])):
                build_rule_item(entry_item, child_rule, (index,))

        rules_tree.expandAll()
        rules_tree.resizeColumnToContents(0)
        rules_tree.resizeColumnToContents(1)

    def configure_child_rule(child_item: QTreeWidgetItem) -> None:
        data = child_item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data[0] != "child":
            return

        parent_item = child_item.parent()
        if parent_item is None:
            return
        entry_data = parent_item
        while entry_data.parent() is not None:
            entry_data = entry_data.parent()
        top_level_data = entry_data.data(0, Qt.ItemDataRole.UserRole)
        if not top_level_data or top_level_data[0] != "entry":
            return

        entry_url = top_level_data[1]
        path = data[1]
        child_rule = get_rule_by_path(working_rules.get(entry_url, []), path)
        result = show_rule_json_dialog(
            dialog,
            child_rule.get("site_name", ""),
            child_rule.get("match_url", ""),
            child_rule.get("purpose", ""),
            child_rule.get("rule_json", ""),
        )
        if result is None:
            return

        site_name, match_url, purpose, rule_json = result
        child_rule["site_name"] = site_name
        child_rule["match_url"] = match_url
        child_rule["purpose"] = purpose
        child_rule["rule_json"] = rule_json
        rebuild_tree()

    def add_child_site() -> None:
        current_item = rules_tree.currentItem()
        if current_item is None:
            QMessageBox.warning(dialog, "提示", "请先选择一个网址节点。")
            return

        data = current_item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        if data[0] == "entry":
            entry_url = data[1]
            target_children = working_rules.setdefault(entry_url, [])
        elif data[0] == "child":
            top_level_item = current_item
            while top_level_item.parent() is not None:
                top_level_item = top_level_item.parent()
            top_level_data = top_level_item.data(0, Qt.ItemDataRole.UserRole)
            if not top_level_data or top_level_data[0] != "entry":
                return
            entry_url = top_level_data[1]
            parent_rule = get_rule_by_path(working_rules.get(entry_url, []), data[1])
            target_children = get_child_rule_children(parent_rule)
        else:
            return

        site_name, ok = QInputDialog.getText(dialog, "添加子网站", "子网站名称")
        if not ok:
            return

        target_children.append(
            {
                "site_name": site_name.strip() or f"子网站 {len(target_children) + 1}",
                "match_url": "",
                "purpose": "",
                "rule_json": '{\n  "step": 1,\n  "fetch_mode": "background",\n  "target": "article.item-list",\n  "link_selector": "a",\n  "attr": "href"\n}',
                "children": [],
            }
        )
        rebuild_tree()

    def remove_child_site() -> None:
        current_item = rules_tree.currentItem()
        if current_item is None:
            QMessageBox.warning(dialog, "提示", "请先选择一个子网站。")
            return

        data = current_item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data[0] != "child":
            QMessageBox.warning(dialog, "提示", "请先选择一个子网站。")
            return

        top_level_item = current_item
        while top_level_item.parent() is not None:
            top_level_item = top_level_item.parent()
        top_level_data = top_level_item.data(0, Qt.ItemDataRole.UserRole)
        if not top_level_data or top_level_data[0] != "entry":
            return

        entry_url = top_level_data[1]
        remove_rule_by_path(working_rules.get(entry_url, []), data[1])
        rebuild_tree()

    button_row = QHBoxLayout()
    add_child_button = QPushButton("添加子网站")
    remove_child_button = QPushButton("删除子网站")
    save_button = QPushButton("保存")
    close_button = QPushButton("关闭")
    button_row.addWidget(add_child_button)
    button_row.addWidget(remove_child_button)
    button_row.addStretch()
    button_row.addWidget(save_button)
    button_row.addWidget(close_button)
    layout.addLayout(button_row)

    add_child_button.clicked.connect(add_child_site)
    remove_child_button.clicked.connect(remove_child_site)
    save_button.clicked.connect(dialog.accept)
    close_button.clicked.connect(dialog.reject)

    rebuild_tree()

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None

    return {entry_url: normalize_child_rules(items) for entry_url, items in working_rules.items()}


def show_rule_json_dialog(
    parent: QWidget,
    current_name: str,
    current_match_url: str,
    current_purpose: str,
    current_rule_json: str,
) -> tuple[str, str, str, str] | None:
    dialog = QDialog(parent)
    dialog.setWindowTitle("JSON 规则")
    dialog.resize(1100, 760)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(8)

    form_layout = QFormLayout()
    site_name_input = QLineEdit(current_name)
    site_name_input.setPlaceholderText("例如 搜索结果页")
    match_url_input = QLineEdit(current_match_url)
    match_url_input.setPlaceholderText("可留空，支持普通文本、* 通配符、regex:正则")
    purpose_input = QLineEdit(current_purpose)
    purpose_input.setPlaceholderText("例如 resource_sync / download_resolve")
    form_layout.addRow("子网站名称", site_name_input)
    form_layout.addRow("URL 匹配", match_url_input)
    form_layout.addRow("Purpose", purpose_input)
    layout.addLayout(form_layout)

    json_input = QPlainTextEdit()
    json_input.setPlaceholderText(
        '{\n'
        '  "step": 1,\n'
        '  "fetch_mode": "background",\n'
        '  "target": "article.item-list",\n'
        '  "link_selector": "h2.post-box-title a",\n'
        '  "attr": "href",\n'
        '  "resource_name_selector": "h1.entry-title",\n'
        '  "resource_name_attr": "text"\n'
        '}'
    )
    json_input.setPlainText(current_rule_json)
    json_input.setMinimumHeight(340)
    layout.addWidget(json_input)

    help_title = QLabel("JSON 说明")
    layout.addWidget(help_title)

    help_layout = QHBoxLayout()
    help_text = QPlainTextEdit()
    help_text.setReadOnly(True)
    help_tree = QTreeWidget()
    help_tree.setHeaderHidden(True)
    help_tree.setMaximumWidth(320)
    help_tree.setMinimumWidth(260)
    populate_rule_help_tree(help_tree)
    help_tree.expandAll()

    help_tree.currentItemChanged.connect(
        lambda current, _previous: help_text.setPlainText(
            str(current.data(0, Qt.ItemDataRole.UserRole) or "") if current is not None else ""
        )
    )

    help_text.setMinimumHeight(260)
    help_layout.addWidget(help_tree)
    help_layout.addWidget(help_text, 1)
    layout.addLayout(help_layout, 1)

    if help_tree.topLevelItemCount() > 0:
        first_item = help_tree.topLevelItem(0)
        if first_item is not None and first_item.childCount() > 0:
            help_tree.setCurrentItem(first_item.child(0))
        else:
            help_tree.setCurrentItem(first_item)

    button_row = QHBoxLayout()
    save_button = QPushButton("保存")
    close_button = QPushButton("关闭")
    button_row.addStretch()
    button_row.addWidget(save_button)
    button_row.addWidget(close_button)
    layout.addLayout(button_row)

    save_button.clicked.connect(dialog.accept)
    close_button.clicked.connect(dialog.reject)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None

    rule_json_text = json_input.toPlainText().strip()
    if rule_json_text:
        try:
            validate_rule_config(parse_rule_text(rule_json_text))
        except ValueError as exc:
            QMessageBox.warning(parent, "提示", f"规则格式无效: {exc}")
            return None

    return (
        site_name_input.text().strip(),
        match_url_input.text().strip(),
        purpose_input.text().strip(),
        rule_json_text,
    )


def normalize_child_rules(items: list[dict[str, object]]) -> list[dict[str, object]]:
    normalized_items: list[dict[str, object]] = []
    for item in items:
        normalized_items.append(
            {
                "site_name": str(item.get("site_name", "")).strip(),
                "match_url": str(item.get("match_url", "")).strip(),
                "purpose": str(item.get("purpose", "")).strip(),
                "rule_json": str(item.get("rule_json", "")).strip(),
                "children": normalize_child_rules(item.get("children", []))
                if isinstance(item.get("children", []), list)
                else [],
            }
        )
    return normalized_items


def get_child_rule_children(rule_item: dict[str, object]) -> list[dict[str, object]]:
    children = rule_item.get("children")
    if isinstance(children, list):
        return children
    normalized_children: list[dict[str, object]] = []
    rule_item["children"] = normalized_children
    return normalized_children


def populate_rule_help_tree(help_tree: QTreeWidget) -> None:
    help_tree.clear()

    modules = [
        (
            "网站",
            [
                (
                    "基础抓取",
                    "模块: 网站\n\n"
                    "字段:\n"
                    "step\n  当前步骤编号。\n\n"
                    "fetch_mode\n  抓取方式。background 为后台请求，browser 为浏览器模拟操作。\n\n"
                    "next_step\n  下一步步骤编号，可留空。\n\n"
                    "Purpose\n  在规则编辑窗口中单独填写，不在 JSON 内。\n"
                    "  用于标记规则用途，例如 resource_sync、download_resolve。\n\n"
                    "target / link_selector / attr\n"
                    "  网站内容提取配置，推荐直接写在根级。\n\n"
                    "resource_name_selector / resource_name_attr\n"
                    "  可选。用于抓取资源名称。\n"
                    "  resource_name_selector 填资源名称对应的 CSS 选择器。\n"
                    "  resource_name_attr 默认 text，也可填 title、content 等属性名。\n\n"
                    "示例:\n"
                    '{\n'
                    '  "step": 1,\n'
                    '  "fetch_mode": "background",\n'
                    '  "target": "article.item-list",\n'
                    '  "link_selector": "h2.post-box-title a",\n'
                    '  "attr": "href",\n'
                    '  "resource_name_selector": "h1.entry-title",\n'
                    '  "resource_name_attr": "text"\n'
                    '}',
                ),
                (
                    "提取字段",
                    "模块: 网站\n\n"
                    "字段:\n"
                    "target\n  必填。先选中当前页面中的目标区域，可写 CSS 选择器或 HTML 标签片段。\n\n"
                    "link_selector\n  可选。默认 a。在 target 内继续查找的元素。\n\n"
                    "attr\n  可选。默认 href。常见值: href、src、text。\n\n"
                    "resource_name_selector\n"
                    "  可选。资源名称节点的 CSS 选择器。\n\n"
                    "resource_name_attr\n"
                    "  可选。默认 text。资源名称取值方式，常见值: text、title、content。\n\n"
                    "use_target_directly\n"
                    "  可选。true 时直接把 target 命中的元素本身作为取值对象。\n\n"
                    "示例:\n"
                    '{\n'
                    '  "target": "a.download-link",\n'
                    '  "attr": "href",\n'
                    '  "resource_name_selector": "h1.entry-title",\n'
                    '  "resource_name_attr": "text",\n'
                    '  "use_target_directly": true\n'
                    '}',
                ),
                (
                    "URL匹配",
                    "模块: 网站匹配\n\n"
                    "上方单独填写的 URL 匹配条件和 Purpose 都不在 JSON 内。\n\n"
                    "支持:\n"
                    "1. 普通文本: URL 包含指定片段时命中。\n"
                    "2. 通配符: 使用 * 匹配任意长度字符。\n"
                    "3. 正则: 以 regex: 开头。\n\n"
                    "Purpose 用法示例:\n"
                    "resource_sync\n"
                    "download_resolve\n\n"
                    "示例:\n"
                    "www.sample.com/page/*/?s=*\n\n"
                    "regex:^https://example\\.com/page/\\d+/\\?s=[^&]+$",
                ),
            ],
        ),
        (
            "分页",
            [
                (
                    "分页配置",
                    "模块: 分页 / page_option\n\n"
                    "建议把所有分页字段都放进 page_option。\n\n"
                    "字段:\n"
                    "enabled\n  可选。true 时启用分页。\n  如果填写了 page_url_template 和 page_number_selector，也会自动启用。\n\n"
                    "page_url_template\n  必填。必须包含 {page}。可选使用 {params} 复用入口参数。\n\n"
                    "start_page\n  可选。默认 1。\n\n"
                    "page_number_selector\n  必填。分页栏页码节点的 CSS 选择器。\n\n"
                    "page_number_attr\n  可选。默认 text，也可填 href。\n\n"
                    "page_number_regex\n  可选。默认 \\\\d+。\n\n"
                    "max_page_limit\n  可选。默认 200。\n\n"
                    "示例:\n"
                    '{\n'
                    '  "step": 1,\n'
                    '  "fetch_mode": "background",\n'
                    '  "target": "article.item-list",\n'
                    '  "link_selector": "h2.post-box-title a",\n'
                    '  "attr": "href",\n'
                    '  "page_option": {\n'
                    '    "enabled": true,\n'
                    '    "page_url_template": "https://example.com/page/{page}/?{params}",\n'
                    '    "start_page": 1,\n'
                    '    "page_number_selector": ".pagination a.page, .pagination span.current",\n'
                    '    "page_number_attr": "text",\n'
                    '    "page_number_regex": "\\\\d+",\n'
                    '    "max_page_limit": 200\n'
                    "  }\n"
                    '}',
                ),
                (
                    "入口参数复用",
                    "模块: 分页 / page_option\n\n"
                    "入口网站“参数”按钮中填写的查询串，可以在 page_url_template 中通过 {params} 复用。\n\n"
                    "参数示例:\n"
                    "s=keyword\n\n"
                    "分页模板示例:\n"
                    "https://misskon.com/page/{page}/?{params}\n\n"
                    "生成结果:\n"
                    "https://misskon.com/page/2/?s=keyword",
                ),
            ],
        ),
        (
            "浏览器",
            [
                (
                    "浏览器配置",
                    "模块: 浏览器 / browser_option\n\n"
                    "仅在 fetch_mode=browser 时使用。\n\n"
                    "适用场景:\n"
                    "1. 目标页面依赖 JavaScript 执行后才出现内容。\n"
                    "2. 需要点击按钮后才显示下一步内容或发生跳转。\n"
                    "3. 页面存在倒计时、继续按钮、验证按钮、动态加载列表等前端交互。\n"
                    "4. background 模式拿不到最终 HTML 或最终链接时。\n\n"
                    "不适合的场景:\n"
                    "1. 页面必须人工完成受限验证码，程序无法代替人工输入验证码。\n"
                    "2. 站点使用强人机验证且必须通过真实交互后才放行。\n\n"
                    "字段:\n"
                    "headless\n"
                    "  可选。默认 false。\n"
                    "  false: 显示浏览器窗口，便于观察页面是否真的完成跳转或点击。\n"
                    "  true: 无头模式，适合流程已稳定后的自动运行。\n\n"
                    "actions\n  可选。数组，按顺序执行浏览器动作。\n"
                    "  程序会先打开 page_url，再依次执行 actions，最后再按 target/link_selector/attr 提取内容。\n"
                    "  支持类型: click、wait_for_selector、wait_for_load、sleep。\n\n"
                    "动作说明:\n"
                    "click\n"
                    "  点击匹配 selector 的第一个元素。\n"
                    "  常用字段:\n"
                    "  type: 固定写 click\n"
                    "  selector: 必填，CSS 选择器\n"
                    "  timeout_ms: 可选，默认 30000\n"
                    "  wait_after_ms: 可选，点击后额外等待毫秒数\n\n"
                    "wait_for_selector\n"
                    "  等待某个元素出现或进入指定状态。\n"
                    "  常用字段:\n"
                    "  type: 固定写 wait_for_selector\n"
                    "  selector: 必填，CSS 选择器\n"
                    "  state: 可选，默认 visible，可用值通常是 attached、visible、hidden、detached\n"
                    "  timeout_ms: 可选，默认 30000\n\n"
                    "wait_for_load\n"
                    "  等待页面加载状态。\n"
                    "  常用字段:\n"
                    "  type: 固定写 wait_for_load\n"
                    "  state: 可选，默认 networkidle，也可写 domcontentloaded、load\n"
                    "  timeout_ms: 可选，默认 30000\n\n"
                    "sleep\n"
                    "  强制等待一段时间，适合页面没有稳定选择器、只能粗略等待时使用。\n"
                    "  常用字段:\n"
                    "  type: 固定写 sleep\n"
                    "  duration_ms: 可选，默认 1000\n\n"
                    "推荐顺序:\n"
                    "1. wait_for_load 或 wait_for_selector，先确认页面已加载。\n"
                    "2. click，执行继续、验证、展开、加载更多等动作。\n"
                    "3. wait_for_selector / wait_for_load / sleep，等待点击后的新内容或跳转完成。\n"
                    "4. 最后再用 target/link_selector/attr 提取结果。\n\n"
                    "常见用法:\n"
                    "1. 点击“继续”按钮后进入下载页。\n"
                    "2. 点击“加载更多”后再抓新出现的链接。\n"
                    "3. 在短链跳转页等待按钮出现、点击、再等待最终跳转。\n\n"
                    "人机验证跳板页说明:\n"
                    "如果详情页里的下载按钮有时会跳到中间验证页，例如 ouo.io，再由该页面跳转到最终下载页，\n"
                    "可以给中间页单独配置一个 browser 规则。\n"
                    "通常做法是：先等待按钮出现，再点击，再等待跳转完成，最后从当前页面 URL 或页面内容继续提取。\n\n"
                    "示例:\n"
                    '{\n'
                    '  "step": 1,\n'
                    '  "fetch_mode": "browser",\n'
                    '  "target": "article.item-list",\n'
                    '  "link_selector": "h2.post-box-title a",\n'
                    '  "attr": "href",\n'
                    '  "browser_option": {\n'
                    '    "headless": false,\n'
                    '    "actions": [\n'
                    '      {\n'
                    '        "type": "click",\n'
                    '        "selector": "button.load-more",\n'
                    '        "wait_after_ms": 1500\n'
                    "      },\n"
                    '      {\n'
                    '        "type": "wait_for_selector",\n'
                    '        "selector": "article.item-list"\n'
                    "      }\n"
                    "    ]\n"
                    "  }\n"
                    '}\n\n'
                    "短链验证跳转示例:\n"
                    '{\n'
                    '  "step": 1,\n'
                    '  "fetch_mode": "browser",\n'
                    '  "target": "a",\n'
                    '  "attr": "href",\n'
                    '  "browser_option": {\n'
                    '    "headless": false,\n'
                    '    "actions": [\n'
                    '      {\n'
                    '        "type": "wait_for_load",\n'
                    '        "state": "domcontentloaded"\n'
                    "      },\n"
                    '      {\n'
                    '        "type": "wait_for_selector",\n'
                    '        "selector": "a, button"\n'
                    "      },\n"
                    '      {\n'
                    '        "type": "click",\n'
                    '        "selector": "a, button",\n'
                    '        "wait_after_ms": 3000\n'
                    "      },\n"
                    '      {\n'
                    '        "type": "wait_for_load",\n'
                    '        "state": "networkidle"\n'
                    "      }\n"
                    "    ]\n"
                    "  }\n"
                    '}',
                ),
            ],
        ),
    ]

    for module_name, items in modules:
        module_item = QTreeWidgetItem([module_name])
        help_tree.addTopLevelItem(module_item)
        for child_name, child_text in items:
            child_item = QTreeWidgetItem([child_name])
            child_item.setData(0, Qt.ItemDataRole.UserRole, child_text)
            module_item.addChild(child_item)


def get_rule_by_path(rule_items: list[dict[str, object]], path: tuple[int, ...]) -> dict[str, object]:
    current_items = rule_items
    current_rule: dict[str, object] | None = None
    for index in path:
        current_rule = current_items[index]
        current_items = get_child_rule_children(current_rule)
    if current_rule is None:
        raise IndexError("规则路径无效。")
    return current_rule


def remove_rule_by_path(rule_items: list[dict[str, object]], path: tuple[int, ...]) -> None:
    if not path:
        return
    if len(path) == 1:
        del rule_items[path[0]]
        return
    parent_rule = get_rule_by_path(rule_items, path[:-1])
    del get_child_rule_children(parent_rule)[path[-1]]


def _get_row_url(table: QTableWidget, row_index: int) -> str:
    url_input = table.cellWidget(row_index, 0)
    if isinstance(url_input, QLineEdit):
        return url_input.text().strip()
    return ""


def _sync_row_url(working_rows: list[dict[str, object]], row_index: int, url_input: QLineEdit) -> None:
    if row_index >= len(working_rows):
        return
    working_rows[row_index]["url"] = url_input.text().strip()


def _sync_all_row_urls(table: QTableWidget, working_rows: list[dict[str, object]]) -> None:
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


def fetch_html(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        },
    )
    with urlopen(request, timeout=30) as response:
        raw_data = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        try:
            return raw_data.decode(charset)
        except UnicodeDecodeError:
            return raw_data.decode("utf-8", errors="replace")


def build_default_export_filename(url_text: str) -> str:
    parts = urlsplit(url_text)
    host = parts.netloc or "page"
    path_text = parts.path.strip("/").replace("/", "_")
    file_stem = f"{host}_{path_text}" if path_text else host
    safe_name = re.sub(r'[\\/:*?"<>|]+', "_", file_stem).strip("._") or "page"
    return f"{safe_name}.txt"


def clean_html_for_output(
    html_text: str,
    filter_options: dict[str, bool] | None = None,
) -> str:
    options = filter_options or {
        "remove_comments": True,
        "remove_scripts": True,
        "remove_styles": True,
        "remove_stylesheets": True,
        "remove_noscript": True,
    }
    cleaned = html_text
    if options.get("remove_comments", False):
        cleaned = re.sub(r"<!--.*?-->", "", cleaned, flags=re.DOTALL)
    if options.get("remove_scripts", False):
        cleaned = re.sub(r"<script\b[^>]*>.*?</script>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    if options.get("remove_styles", False):
        cleaned = re.sub(r"<style\b[^>]*>.*?</style>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    if options.get("remove_stylesheets", False):
        cleaned = re.sub(
            r"<link\b[^>]*rel=[\"']?stylesheet[\"']?[^>]*>",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
    if options.get("remove_noscript", False):
        cleaned = re.sub(r"<noscript\b[^>]*>.*?</noscript>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"\n\s*\n+", "\n\n", cleaned)
    return cleaned.strip()


def parse_links_by_rules(
    html_text: str,
    page_url: str,
    child_rules: list[dict[str, object]],
    purpose: str = "",
    progress_callback: Callable[[int, int, str], None] | None = None,
    level: int = 0,
) -> list[dict[str, object]]:
    indent = "  " * level
    active_rules = resolve_active_child_rules(page_url, child_rules, purpose=purpose)
    total_rules = len(active_rules)

    if total_rules == 0:
        print(f"{indent}当前页面：{page_url}")
        print(f"{indent}下一级没有命中任何规则")
        return []

    return execute_rules_for_page(
        page_url,
        active_rules,
        purpose=purpose,
        progress_callback=progress_callback,
        level=level,
        html_text=html_text,
    )


def resolve_active_child_rules(
    page_url: str,
    child_rules: list[dict[str, object]],
    purpose: str = "",
) -> list[dict[str, object]]:
    normalized_rules = normalize_child_rules(child_rules)
    normalized_purpose = purpose.strip()

    purpose_matched_rules = [
        child_rule
        for child_rule in normalized_rules
        if str(child_rule.get("purpose", "")).strip() == normalized_purpose
    ]
    if normalized_purpose and purpose_matched_rules:
        candidate_rules = purpose_matched_rules
    elif normalized_purpose:
        candidate_rules = [
            child_rule
            for child_rule in normalized_rules
            if not str(child_rule.get("purpose", "")).strip()
        ]
    else:
        candidate_rules = normalized_rules

    specific_matches: list[tuple[tuple[int, int, int], dict[str, object]]] = []
    generic_rules: list[dict[str, object]] = []

    for child_rule in candidate_rules:
        match_url = child_rule.get("match_url", "")
        if match_url:
            if rule_matches_page_url(match_url, page_url):
                specific_matches.append((get_match_url_priority(match_url), child_rule))
            continue
        generic_rules.append(child_rule)

    if specific_matches:
        best_priority = max(priority for priority, _ in specific_matches)
        return [
            child_rule
            for priority, child_rule in specific_matches
            if priority == best_priority
        ]
    return generic_rules


def execute_rules_for_page(
    page_url: str,
    active_rules: list[dict[str, object]],
    purpose: str = "",
    progress_callback: Callable[[int, int, str], None] | None = None,
    level: int = 0,
    html_text: str | None = None,
) -> list[dict[str, object]]:
    indent = "  " * level
    matched_results: list[dict[str, object]] = []
    total_rules = len(active_rules)
    cached_html_text = html_text

    for rule_index, child_rule in enumerate(active_rules, start=1):
        match_url = child_rule.get("match_url", "")
        site_name = child_rule.get("site_name", "") or "未命名子网站"
        page_title = extract_html_title(cached_html_text)

        rule_text = child_rule.get("rule_json", "")
        if not rule_text:
            print(f"{indent}当前页面：{page_url}")
            print(f"{indent}匹配规则：{str(match_url).strip() or '未设置'} 匹配成功")
            print(f"{indent}规则为空，当前页面按最终结果保留")
            print(f"{indent}当前层结果：")
            print(f"{indent}[\n{indent}  {page_url}\n{indent}]")
            matched_results.append(
                {
                    "site_name": site_name,
                    "match_url": match_url,
                    "page_url": page_url,
                    "page_title": page_title,
                    "resource_records": [],
                    "links": [page_url],
                    "page_count": 1,
                    "children": [],
                }
            )
            continue

        try:
            rule = parse_rule_text(rule_text)
        except ValueError as exc:
            print(f"{indent}当前页面：{page_url}")
            print(f"{indent}规则 {rule_index}/{total_rules} - {site_name} - 规则解析失败：{exc}")
            continue

        resource_name = page_title
        def report_rule_progress(current: int, total: int, message: str) -> None:
            if progress_callback is None:
                return
            progress_callback(
                current,
                total,
                f"规则 {rule_index}/{total_rules} - {site_name} - {message}",
            )

        try:
            fetch_mode = get_fetch_mode(rule)
            if fetch_mode == "browser":
                collection_result = collect_links_from_browser_rule(
                    page_url,
                    rule,
                    progress_callback=report_rule_progress,
                )
            else:
                if cached_html_text is None:
                    try:
                        cached_html_text = fetch_html(page_url)
                        page_title = extract_html_title(cached_html_text)
                    except Exception as exc:
                        print(f"{indent}当前页面：{page_url}")
                        print(f"{indent}规则 {rule_index}/{total_rules} - {site_name} - 页面请求失败：{exc}")
                        continue
                collection_result = collect_links_from_rule_across_pages(
                    cached_html_text,
                    page_url,
                    rule,
                    progress_callback=report_rule_progress,
                )
                resource_name = extract_resource_name_from_rule(
                    BeautifulSoup(cached_html_text, "html.parser"),
                    page_url,
                    rule,
                ) or page_title
        except ValueError as exc:
            print(f"{indent}当前页面：{page_url}")
            print(f"{indent}规则 {rule_index}/{total_rules} - {site_name} - 规则执行失败：{exc}")
            continue
        if fetch_mode == "browser":
            resource_name = str(collection_result.get("resource_name", "")).strip() or page_title
        collected_links = collection_result["links"]
        collected_page_count = parse_int_value(collection_result["page_count"], 0)
        html_tag_match_count = parse_int_value(collection_result.get("html_tag_match_count"), 0)
        match_rule_text = str(match_url).strip() or "未设置"
        match_status = (
            "匹配成功"
            if not match_url or rule_matches_page_url(str(match_url), page_url)
            else "匹配失败"
        )
        formatted_links = (
            "[\n"
            + "\n".join(f"{indent}  {link}" for link in collected_links)
            + f"\n{indent}]"
            if collected_links
            else "[]"
        )
        print(f"{indent}当前页面：{page_url}")
        print(f"{indent}匹配规则：{match_rule_text} {match_status}")
        print(f"{indent}HTML标签匹配成功数：{html_tag_match_count}")
        print(f"{indent}页数：{collected_page_count}")
        print(f"{indent}抓取链接总数：{len(collected_links)}")
        if html_tag_match_count == 0:
            print(f"{indent}规则已命中，但没有匹配到任何HTML标签")
        print(f"{indent}当前层结果：")
        print(f"{indent}{formatted_links}" if collected_links else f"{indent}[]")
        matched_results.append(
            {
                "site_name": site_name,
                "match_url": match_url,
                "page_url": page_url,
                "page_title": page_title,
                "resource_name": resource_name,
                "resource_records": collection_result.get("resource_records", []),
                "links": collected_links,
                "page_count": collected_page_count,
                "children": collect_child_rule_results(
                    collected_links,
                    get_child_rule_children(child_rule),
                    site_name,
                    page_url,
                    collected_page_count,
                    purpose=purpose,
                    progress_callback=report_rule_progress,
                    level=level + 1,
                ),
            }
        )

    return matched_results


def collect_child_rule_results(
    parent_links: list[str],
    child_rules: list[dict[str, object]],
    parent_site_name: str,
    parent_page_url: str,
    parent_page_count: int,
    purpose: str = "",
    progress_callback: Callable[[int, int, str], None] | None = None,
    level: int = 0,
) -> list[dict[str, object]]:
    if not parent_links or not child_rules:
        return []

    child_results: list[dict[str, object]] = []
    seen_page_urls: set[str] = set()
    total_links = len(parent_links)

    for link_index, link_url in enumerate(parent_links, start=1):
        if link_url in seen_page_urls:
            continue
        seen_page_urls.add(link_url)

        indent = "  " * level
        print(f"{indent}正在匹配下一级页面：{link_url}")

        if progress_callback is not None:
            progress_callback(link_index, total_links, f"正在匹配下一级: {link_url}")

        active_rules = resolve_active_child_rules(link_url, child_rules, purpose=purpose)
        if not active_rules:
            print(f"{indent}当前页面：{link_url}")
            print(f"{indent}下一级没有命中任何规则")
            continue

        matched_results = execute_rules_for_page(
            link_url,
            active_rules,
            purpose=purpose,
            progress_callback=progress_callback,
            level=level,
        )
        child_results.extend(matched_results)

    return child_results


def flatten_result_links(result: dict[str, object]) -> list[str]:
    flattened_links: list[str] = []
    child_page_urls = {
        str(child_result.get("page_url", "")).strip()
        for child_result in result.get("children", [])
        if isinstance(child_result, dict) and str(child_result.get("page_url", "")).strip()
    }

    for link in result.get("links", []):
        if isinstance(link, str):
            if link in child_page_urls:
                continue
            flattened_links.append(link)
    for child_result in result.get("children", []):
        if isinstance(child_result, dict):
            flattened_links.extend(flatten_result_links(child_result))
    return flattened_links


def normalize_resource_items(items: object) -> list[dict[str, str]]:
    if not isinstance(items, list):
        return []

    normalized_items: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        detail_url = str(item.get("detail_url", "")).strip()
        download_url = str(item.get("download_url", "")).strip()
        if not (name or detail_url or download_url):
            continue
        normalized_items.append(
            {
                "name": name,
                "detail_url": detail_url,
                "download_url": download_url,
            }
        )
    return normalized_items


def build_resource_name(page_title: str, page_url: str) -> str:
    cleaned_title = page_title.strip()
    if cleaned_title:
        return cleaned_title

    path = urlsplit(page_url).path.rstrip("/")
    if path:
        return path.rsplit("/", 1)[-1]
    return page_url.strip()


def extract_resource_name_from_rule(
    soup: BeautifulSoup,
    page_url: str,
    rule: dict[str, object],
) -> str:
    site_config = get_site_config(rule)
    selector = str(
        site_config.get("resource_name_selector", rule.get("resource_name_selector", ""))
    ).strip()
    if not selector:
        return ""

    attr_name = str(
        site_config.get("resource_name_attr", rule.get("resource_name_attr", "text"))
    ).strip() or "text"

    try:
        candidate_node = soup.select_one(selector)
    except Exception:
        return ""
    if candidate_node is None:
        return ""

    return extract_rule_value(candidate_node, attr_name).strip()


def extract_html_title(html_text: str | None) -> str:
    if not html_text:
        return ""
    try:
        title_node = BeautifulSoup(html_text, "html.parser").title
    except Exception:
        return ""
    if title_node is None:
        return ""
    return title_node.get_text(strip=True)


def collect_resource_records(
    matched_results: list[dict[str, object]],
    purpose: str = "",
) -> list[dict[str, str]]:
    resource_items: list[dict[str, str]] = []
    seen_items: set[tuple[str, str]] = set()
    normalized_purpose = purpose.strip()

    def visit_result(result: dict[str, object]) -> None:
        page_url = str(result.get("page_url", "")).strip()
        explicit_resource_name = str(result.get("resource_name", "")).strip()
        page_title = explicit_resource_name or str(result.get("page_title", "")).strip()
        direct_links = [link for link in result.get("links", []) if isinstance(link, str) and link.strip()]
        children = [
            child_result
            for child_result in result.get("children", [])
            if isinstance(child_result, dict)
        ]

        if normalized_purpose == "resource_sync":
            for resource_item in normalize_resource_items(result.get("resource_records", [])):
                resource_name = str(resource_item.get("name", "")).strip()
                detail_url = str(resource_item.get("detail_url", "")).strip()
                item_key = (detail_url, "")
                if not resource_name or not detail_url or item_key in seen_items:
                    continue
                seen_items.add(item_key)
                resource_items.append(
                    {
                        "name": resource_name,
                        "detail_url": detail_url,
                        "download_url": "",
                    }
                )

        if children and len(direct_links) <= 1 and page_url:
            final_links: list[str] = []
            seen_final_links: set[str] = set()
            for child_result in children:
                for link in flatten_result_links(child_result):
                    cleaned_link = str(link).strip()
                    if not cleaned_link or cleaned_link in seen_final_links:
                        continue
                    seen_final_links.add(cleaned_link)
                    final_links.append(cleaned_link)

            resource_name = build_resource_name(page_title, page_url)
            for download_url in final_links:
                item_key = (page_url, download_url)
                if item_key in seen_items:
                    continue
                seen_items.add(item_key)
                resource_items.append(
                    {
                        "name": resource_name,
                        "detail_url": page_url,
                        "download_url": download_url,
                    }
                )

        for child_result in children:
            visit_result(child_result)

    for matched_result in matched_results:
        if isinstance(matched_result, dict):
            visit_result(matched_result)

    return resource_items


def show_resource_detail_dialog(parent: QWidget, resource_item: dict[str, str]) -> None:
    dialog = QDialog(parent)
    dialog.setWindowTitle("资源详情")
    dialog.resize(760, 260)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(8)

    form_layout = QFormLayout()

    name_input = QLineEdit(str(resource_item.get("name", "")).strip())
    name_input.setReadOnly(True)
    form_layout.addRow("资源名称", name_input)

    detail_input = QLineEdit(str(resource_item.get("detail_url", "")).strip())
    detail_input.setReadOnly(True)
    form_layout.addRow("资源详细页面网址", detail_input)

    download_input = QLineEdit(str(resource_item.get("download_url", "")).strip())
    download_input.setReadOnly(True)
    form_layout.addRow("资源下载网址", download_input)

    layout.addLayout(form_layout)

    close_button = QPushButton("关闭")
    close_button.clicked.connect(dialog.accept)
    layout.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignRight)

    dialog.exec()


def show_resource_dialog(
    parent: QWidget,
    row_data: dict[str, object],
    child_rules: list[dict[str, str]],
) -> None:
    dialog = QDialog(parent)
    dialog.setWindowTitle("资源")
    dialog.resize(920, 520)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(8)

    content_row = QHBoxLayout()
    content_row.setSpacing(8)
    layout.addLayout(content_row)

    left_panel = QVBoxLayout()
    left_panel.setSpacing(8)
    content_row.addLayout(left_panel, 2)

    params_table = QTableWidget(0, 1)
    params_table.setHorizontalHeaderLabels(["参数"])
    params_table.verticalHeader().setVisible(False)
    params_table.horizontalHeader().setStretchLastSection(True)
    params_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    params_table.setSelectionMode(QTableWidget.SelectionMode.MultiSelection)
    params_table.setEditTriggers(
        QTableWidget.EditTrigger.DoubleClicked
        | QTableWidget.EditTrigger.EditKeyPressed
        | QTableWidget.EditTrigger.AnyKeyPressed
    )
    left_panel.addWidget(params_table)

    params_button_row = QHBoxLayout()
    sync_resources_button = QPushButton("同步资源")
    resolve_links_button = QPushButton("补全链接")
    add_params_button = QPushButton("添加")
    delete_params_button = QPushButton("删除")
    params_button_row.addWidget(sync_resources_button)
    params_button_row.addWidget(resolve_links_button)
    params_button_row.addWidget(add_params_button)
    params_button_row.addWidget(delete_params_button)
    params_button_row.addStretch()
    left_panel.addLayout(params_button_row)

    resource_panel = QVBoxLayout()
    resource_panel.setSpacing(6)
    content_row.addLayout(resource_panel, 3)

    resource_count_label = QLabel("资源数量: 0")
    resource_panel.addWidget(resource_count_label)

    resource_list = QListWidget()
    resource_panel.addWidget(resource_list)

    progress_status = QLabel("等待加载资源")
    layout.addWidget(progress_status)

    progress_bar = QProgressBar()
    progress_bar.setRange(0, 1)
    progress_bar.setValue(0)
    layout.addWidget(progress_bar)

    fetch_state = {"running": False}
    resources_cache: dict[str, list[dict[str, str]]] = {
        str(params_text).strip(): normalize_resource_items(items)
        for params_text, items in row_data.get("resources_by_param", {}).items()
        if str(params_text).strip() and isinstance(items, list)
    }
    fetch_thread = QThread(dialog)
    fetch_worker = FetchRowWorker()
    fetch_dispatcher = FetchRowDispatcher()
    fetch_worker.moveToThread(fetch_thread)
    fetch_dispatcher.start_fetch.connect(fetch_worker.run_fetch)
    fetch_dispatcher.shutdown.connect(fetch_worker.shutdown_worker)
    fetch_thread.start()

    def current_params_texts() -> list[str]:
        selected_rows = sorted({item.row() for item in params_table.selectedItems()})
        params_texts: list[str] = []
        for row_index in selected_rows:
            item = params_table.item(row_index, 0)
            if item is None:
                continue
            params_texts.append(item.text().strip())
        return params_texts

    def current_primary_params_text() -> str:
        params_texts = current_params_texts()
        return params_texts[0] if params_texts else ""

    def sync_row_data_from_table() -> None:
        params_items: list[str] = []
        all_resources: list[dict[str, str]] = []
        seen_resource_keys: set[tuple[str, str, str]] = set()
        resources_by_param: dict[str, list[dict[str, str]]] = {}
        for row_index in range(params_table.rowCount()):
            item = params_table.item(row_index, 0)
            if item is None:
                continue
            params_text = item.text().strip()
            params_items.append(params_text)
            param_resources = normalize_resource_items(resources_cache.get(params_text, []))
            resources_by_param[params_text] = param_resources
            for resource_item in param_resources:
                resource_key = (
                    resource_item.get("name", ""),
                    resource_item.get("detail_url", ""),
                    resource_item.get("download_url", ""),
                )
                if resource_key in seen_resource_keys:
                    continue
                seen_resource_keys.add(resource_key)
                all_resources.append(resource_item)

        row_data["params"] = "\n".join(params_items).strip()
        row_data["resources"] = all_resources
        row_data["resources_by_param"] = resources_by_param

    def append_params_row(params_text: str = "") -> int:
        row_index = params_table.rowCount()
        params_table.insertRow(row_index)
        params_item = QTableWidgetItem(params_text)
        params_table.setItem(row_index, 0, params_item)
        params_table.setRowHeight(row_index, 36)
        resources_cache.setdefault(params_text.strip(), [])
        return row_index

    def update_progress(current: int, total: int, message: str) -> None:
        progress_status.setText(message)
        if total <= 0:
            progress_bar.setRange(0, 0)
        else:
            progress_bar.setRange(0, total)
            progress_bar.setValue(max(0, min(current, total)))

    def populate_resource_list(resources: list[dict[str, str]]) -> None:
        resource_list.clear()
        resource_count_label.setText(f"资源数量: {len(resources)}")
        for resource_item in resources:
            resource_list.addItem(resource_item.get("name", ""))
        if not resources:
            resource_list.addItem("当前参数暂无资源")

    def handle_fetch_finished(total_pages: int, link_count: int, resources: object) -> None:
        fetch_state["running"] = False
        progress_bar.setRange(0, max(1, total_pages))
        progress_bar.setValue(max(1, total_pages))
        progress_status.setText(f"抓取完成，共 {total_pages} 页，{link_count} 个链接")
        normalized_resources = normalize_resource_items(resources)
        params_text = current_primary_params_text()
        resources_cache[params_text] = normalized_resources
        sync_row_data_from_table()
        handle_params_selected()

    def handle_fetch_failed(status_text: str, detail_text: str) -> None:
        fetch_state["running"] = False
        progress_bar.setRange(0, 1)
        progress_bar.setValue(0)
        progress_status.setText(status_text)
        QMessageBox.warning(dialog, "提示", detail_text)

    fetch_worker.progress.connect(update_progress)
    fetch_worker.finished.connect(handle_fetch_finished)
    fetch_worker.failed.connect(handle_fetch_failed)

    def fetch_resources(purpose: str = "") -> None:
        if fetch_state["running"]:
            return
        url_text = str(row_data.get("url", "")).strip()
        params_text = current_primary_params_text()
        if not url_text:
            QMessageBox.warning(dialog, "提示", "请先输入网站。")
            return
        full_url = build_url_with_params(url_text, params_text)
        fetch_state["running"] = True
        update_progress(0, 0, f"正在请求入口页: {full_url}")
        fetch_dispatcher.start_fetch.emit(full_url, child_rules, purpose)

    def handle_params_changed(_: QTableWidgetItem) -> None:
        for row_index in range(params_table.rowCount()):
            item = params_table.item(row_index, 0)
            if item is None:
                continue
            params_text = item.text().strip()
            resources_cache.setdefault(params_text, [])
        sync_row_data_from_table()

    def handle_params_selected() -> None:
        params_texts = current_params_texts()
        aggregated_resources: list[dict[str, str]] = []
        seen_resource_keys: set[tuple[str, str, str]] = set()
        for params_text in params_texts:
            for resource_item in resources_cache.get(params_text, []):
                resource_key = (
                    resource_item.get("name", ""),
                    resource_item.get("detail_url", ""),
                    resource_item.get("download_url", ""),
                )
                if resource_key in seen_resource_keys:
                    continue
                seen_resource_keys.add(resource_key)
                aggregated_resources.append(resource_item)

        progress_status.setText("已加载本地资源" if aggregated_resources else "当前参数暂无已保存资源")
        progress_bar.setRange(0, 1)
        progress_bar.setValue(1 if aggregated_resources else 0)
        populate_resource_list(aggregated_resources)

    def show_selected_resource(item_index: int) -> None:
        params_texts = current_params_texts()
        resources: list[dict[str, str]] = []
        seen_resource_keys: set[tuple[str, str, str]] = set()
        for params_text in params_texts:
            for resource_item in resources_cache.get(params_text, []):
                resource_key = (
                    resource_item.get("name", ""),
                    resource_item.get("detail_url", ""),
                    resource_item.get("download_url", ""),
                )
                if resource_key in seen_resource_keys:
                    continue
                seen_resource_keys.add(resource_key)
                resources.append(resource_item)
        if item_index < 0 or item_index >= len(resources):
            return
        show_resource_detail_dialog(dialog, resources[item_index])

    def add_params_row() -> None:
        row_index = append_params_row("")
        params_table.selectRow(row_index)
        params_table.editItem(params_table.item(row_index, 0))
        sync_row_data_from_table()

    def delete_selected_params_rows() -> None:
        selected_rows = sorted({item.row() for item in params_table.selectedItems()})
        if not selected_rows:
            QMessageBox.information(dialog, "提示", "请先选择要删除的参数。")
            return

        params_texts = []
        for row_index in selected_rows:
            item = params_table.item(row_index, 0)
            if item is None:
                continue
            params_texts.append(item.text().strip())

        confirm_text = "\n".join(params_texts) if params_texts else "空参数"
        result = QMessageBox.question(
            dialog,
            "确认删除",
            f"确认删除以下参数？\n{confirm_text}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return

        for row_index in reversed(selected_rows):
            item = params_table.item(row_index, 0)
            params_text = item.text().strip() if item is not None else ""
            params_table.removeRow(row_index)
            resources_cache.pop(params_text, None)

        if params_table.rowCount() == 0:
            append_params_row("")

        params_table.selectRow(0)
        sync_row_data_from_table()
        handle_params_selected()

    def sync_resources() -> None:
        fetch_resources("resource_sync")

    def resolve_links() -> None:
        fetch_resources("download_resolve")

    params_table.itemChanged.connect(handle_params_changed)
    params_table.itemSelectionChanged.connect(handle_params_selected)
    sync_resources_button.clicked.connect(sync_resources)
    resolve_links_button.clicked.connect(resolve_links)
    add_params_button.clicked.connect(add_params_row)
    delete_params_button.clicked.connect(delete_selected_params_rows)
    resource_list.itemDoubleClicked.connect(
        lambda item: show_selected_resource(resource_list.row(item))
    )

    initial_params_text = str(row_data.get("params", "")).strip()
    initial_params = [item.strip() for item in initial_params_text.splitlines()]
    if not initial_params:
        initial_params = [""]
    for params_text in initial_params:
        append_params_row(params_text)
    initial_resources_by_param = {
        str(params_text).strip(): normalize_resource_items(items)
        for params_text, items in row_data.get("resources_by_param", {}).items()
        if str(params_text).strip() and isinstance(items, list)
    }
    if initial_resources_by_param:
        resources_cache.update(initial_resources_by_param)
    else:
        initial_resources = normalize_resource_items(row_data.get("resources", []))
        if initial_params:
            resources_cache[initial_params[0]] = initial_resources

    params_table.selectRow(0)
    sync_row_data_from_table()
    handle_params_selected()

    def cleanup_fetch_worker() -> None:
        if fetch_thread.isRunning():
            fetch_dispatcher.shutdown.emit()
            fetch_thread.quit()
            fetch_thread.wait(5000)

    dialog.finished.connect(cleanup_fetch_worker)
    dialog.exec()


def count_result_pages(result: dict[str, object]) -> int:
    total_pages = parse_int_value(result.get("page_count"), 0)
    for child_result in result.get("children", []):
        if isinstance(child_result, dict):
            total_pages += count_result_pages(child_result)
    return total_pages


def rule_matches_page_url(match_url: str, page_url: str) -> bool:
    candidates = build_match_url_candidates(page_url)
    if match_url.startswith("regex:"):
        pattern_text = match_url[6:].strip()
        if not pattern_text:
            return False
        try:
            pattern = re.compile(pattern_text)
        except re.error:
            return False
        return any(pattern.search(candidate) for candidate in candidates)

    if "*" in match_url:
        pattern = re.compile(wildcard_match_url_to_regex(match_url))
        return any(pattern.fullmatch(candidate) for candidate in candidates)

    return any(match_url in candidate for candidate in candidates)


def build_match_url_candidates(page_url: str) -> list[str]:
    normalized_page_url = page_url.strip()
    no_scheme_page_url = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", "", normalized_page_url)
    candidates = [normalized_page_url]
    if no_scheme_page_url != normalized_page_url:
        candidates.append(no_scheme_page_url)
    return candidates


def wildcard_match_url_to_regex(match_url: str) -> str:
    escaped = re.escape(match_url)
    return "^" + escaped.replace(r"\*", ".*") + "$"


def get_match_url_priority(match_url: str) -> tuple[int, int, int]:
    if match_url.startswith("regex:"):
        pattern_text = match_url[6:].strip()
        regex_meta_chars = sum(1 for char in pattern_text if char in ".^$+?{}[]|()\\")
        return (3, len(pattern_text) - regex_meta_chars, -regex_meta_chars)

    wildcard_count = match_url.count("*")
    if wildcard_count > 0:
        literal_length = len(match_url.replace("*", ""))
        return (2, literal_length, -wildcard_count)

    return (1, len(match_url), 0)


def parse_rule_text(rule_text: str) -> dict[str, object]:
    try:
        parsed = json.loads(rule_text)
    except json.JSONDecodeError:
        parsed = parse_relaxed_rule_text(rule_text)

    if not isinstance(parsed, dict):
        raise ValueError("规则内容必须是一个对象。")
    return parsed


def validate_rule_config(rule: dict[str, object]) -> None:
    fetch_mode = get_fetch_mode(rule)
    if fetch_mode not in {"background", "browser"}:
        raise ValueError('fetch_mode 只支持 "background" 或 "browser"。')

    if fetch_mode == "browser":
        validate_browser_actions(get_browser_actions(rule))
        if get_pagination_config(rule)["enabled"]:
            raise ValueError("fetch_mode=browser 暂不支持 pagination_enabled。")

    pagination_config = get_pagination_config(rule)
    if not pagination_config["enabled"]:
        return

    page_url_template = str(pagination_config["page_url_template"])
    if not page_url_template or "{page}" not in page_url_template:
        raise ValueError("启用自动翻页时，page_url_template 必须包含 {page} 占位。")

    page_number_selector = str(pagination_config["page_number_selector"])
    if not page_number_selector:
        raise ValueError("启用自动翻页时，page_number_selector 不能为空。")

    try:
        re.compile(str(pagination_config["page_number_regex"]))
    except re.error as exc:
        raise ValueError(f"page_number_regex 无效: {exc}") from exc

    start_page = int(pagination_config["start_page"])
    max_page_limit = int(pagination_config["max_page_limit"])
    if start_page < 1:
        raise ValueError("start_page 不能小于 1。")
    if max_page_limit < start_page:
        raise ValueError("max_page_limit 不能小于 start_page。")


def get_fetch_mode(rule: dict[str, object]) -> str:
    return str(rule.get("fetch_mode", "background")).strip().lower() or "background"


def get_rule_module(rule: dict[str, object], module_name: str) -> dict[str, object]:
    value = rule.get(module_name)
    return value if isinstance(value, dict) else {}


def get_site_config(rule: dict[str, object]) -> dict[str, object]:
    return get_rule_module(rule, "site_option")


def get_browser_config(rule: dict[str, object]) -> dict[str, object]:
    return get_rule_module(rule, "browser_option")


def validate_browser_actions(actions: object) -> None:
    if actions in (None, ""):
        return
    if not isinstance(actions, list):
        raise ValueError("browser_actions 必须是数组。")

    supported_types = {"click", "wait_for_selector", "wait_for_load", "sleep"}
    for index, action in enumerate(actions, start=1):
        if not isinstance(action, dict):
            raise ValueError(f"browser_actions 第 {index} 项必须是对象。")
        action_type = str(action.get("type", "")).strip().lower()
        if action_type not in supported_types:
            raise ValueError(
                f'browser_actions 第 {index} 项 type 只支持 {", ".join(sorted(supported_types))}。'
            )
        if action_type in {"click", "wait_for_selector"} and not str(action.get("selector", "")).strip():
            raise ValueError(f"browser_actions 第 {index} 项缺少 selector。")


def get_pagination_config(rule: dict[str, object]) -> dict[str, object]:
    page_option = get_rule_module(rule, "page_option")
    page_url_template = str(page_option.get("page_url_template", rule.get("page_url_template", ""))).strip()
    page_number_selector = str(page_option.get("page_number_selector", rule.get("page_number_selector", ""))).strip()
    auto_enabled = bool(page_url_template and page_number_selector)
    return {
        "enabled": bool(page_option.get("enabled", rule.get("pagination_enabled", auto_enabled))),
        "page_url_template": page_url_template,
        "start_page": max(1, parse_int_value(page_option.get("start_page", rule.get("start_page")), 1)),
        "page_number_selector": page_number_selector,
        "page_number_attr": str(page_option.get("page_number_attr", rule.get("page_number_attr", "text"))).strip() or "text",
        "page_number_regex": str(page_option.get("page_number_regex", rule.get("page_number_regex", r"\d+"))).strip() or r"\d+",
        "max_page_limit": max(1, parse_int_value(page_option.get("max_page_limit", rule.get("max_page_limit")), 200)),
    }


def get_browser_actions(rule: dict[str, object]) -> object:
    browser_config = get_browser_config(rule)
    actions = browser_config.get("actions")
    if actions not in (None, ""):
        return actions
    return rule.get("browser_actions")


def parse_int_value(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def parse_bool_value(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    return default


def parse_relaxed_rule_text(rule_text: str) -> dict[str, object]:
    text = rule_text.strip()
    if not text.startswith("{") or not text.endswith("}"):
        raise ValueError("规则需要使用 { ... } 包裹。")

    inner = text[1:-1].strip()
    if not inner:
        return {}

    result: dict[str, object] = {}
    for part in split_relaxed_fields(inner):
        if ":" not in part:
            raise ValueError(f"字段缺少冒号: {part}")
        key_text, value_text = part.split(":", 1)
        key = key_text.strip().strip('"').strip("'")
        if not key:
            raise ValueError("字段名不能为空。")
        result[key] = parse_relaxed_value(value_text.strip())

    return result


def split_relaxed_fields(text: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    quote: str | None = None
    depth = 0

    for char in text:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue

        if char in {"'", '"'}:
            quote = char
            current.append(char)
            continue

        if char in "{[":
            depth += 1
        elif char in "}]":
            depth = max(depth - 1, 0)

        if char == "," and depth == 0:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
            continue

        current.append(char)

    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def parse_relaxed_value(value_text: str) -> object:
    if not value_text:
        return ""

    if value_text.startswith("{") and value_text.endswith("}"):
        try:
            parsed_object = json.loads(value_text)
        except json.JSONDecodeError:
            parsed_object = parse_relaxed_rule_text(value_text)
        return parsed_object

    if value_text.startswith("[") and value_text.endswith("]"):
        try:
            return json.loads(value_text)
        except json.JSONDecodeError:
            return value_text

    if value_text.startswith(('"', "'")) and value_text.endswith(('"', "'")):
        return value_text[1:-1]

    lowered = value_text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None

    if re.fullmatch(r"-?\d+", value_text):
        return int(value_text)
    if re.fullmatch(r"-?\d+\.\d+", value_text):
        return float(value_text)

    return value_text


def get_shared_browser_session(headless: bool) -> dict[str, object]:
    session = _SHARED_BROWSER_SESSIONS.get(headless)
    if session is not None:
        return session

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ValueError(
            "browser 模式需要先安装 playwright：pip install playwright，然后执行 playwright install"
        ) from exc

    playwright = sync_playwright().start()
    browser = None
    launch_errors: list[str] = []
    for launch_label, launch_kwargs in (
        ("Edge", {"channel": "msedge", "headless": headless}),
        ("Chrome", {"channel": "chrome", "headless": headless}),
        ("Playwright Chromium", {"headless": headless}),
    ):
        try:
            browser = playwright.chromium.launch(**launch_kwargs)
            break
        except PlaywrightError as exc:
            launch_errors.append(f"{launch_label}: {exc}")

    if browser is None:
        playwright.stop()
        raise ValueError("；".join(launch_errors))

    context = browser.new_context()
    session = {
        "playwright": playwright,
        "browser": browser,
        "context": context,
    }
    _SHARED_BROWSER_SESSIONS[headless] = session
    return session


def collect_links_from_browser_rule(
    initial_page_url: str,
    rule: dict[str, object],
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict[str, object]:
    validate_rule_config(rule)

    try:
        from playwright.sync_api import Error as PlaywrightError
    except ImportError as exc:
        raise ValueError(
            "browser 模式需要先安装 playwright：pip install playwright，然后执行 playwright install"
        ) from exc

    actions = get_browser_actions(rule)
    action_list = actions if isinstance(actions, list) else []
    browser_config = get_browser_config(rule)
    headless = bool(browser_config.get("headless", rule.get("browser_headless", False)))

    if progress_callback is not None:
        progress_callback(0, max(1, len(action_list) + 2), "正在启动浏览器")

    try:
        session = get_shared_browser_session(headless)
        context = session["context"]
        page = context.new_page()
        try:
            page.goto(initial_page_url, wait_until="domcontentloaded", timeout=30000)

            total_steps = max(1, len(action_list) + 2)
            if progress_callback is not None:
                progress_callback(1, total_steps, "页面已打开")

            for index, action in enumerate(action_list, start=1):
                run_browser_action(page, action)
                if progress_callback is not None:
                    action_type = str(action.get("type", "")).strip().lower() or "unknown"
                    progress_callback(index + 1, total_steps, f"已执行浏览器动作: {action_type}")

            html_text = page.content()
            final_page_url = page.url
        finally:
            page.close()
    except PlaywrightError as exc:
        raise ValueError(f"浏览器模式执行失败: {exc}") from exc
    except ValueError:
        raise

    soup = BeautifulSoup(html_text, "html.parser")
    extraction_result = extract_links_from_rule(soup, final_page_url, rule)
    resource_name = extract_resource_name_from_rule(soup, final_page_url, rule)
    if progress_callback is not None:
        progress_callback(total_steps, total_steps, "浏览器规则抓取完成")
    return {
        "links": extraction_result["links"],
        "page_count": 1,
        "html_tag_match_count": extraction_result["html_tag_match_count"],
        "resource_name": resource_name,
        "resource_records": extraction_result.get("resource_records", []),
    }


def run_browser_action(page: object, action: dict[str, object]) -> None:
    action_type = str(action.get("type", "")).strip().lower()
    timeout_ms = max(0, parse_int_value(action.get("timeout_ms"), 30000))
    optional = parse_bool_value(action.get("optional", False), False)

    try:
        if action_type == "click":
            selector = str(action.get("selector", "")).strip()
            no_wait_after = parse_bool_value(action.get("no_wait_after", False), False)
            page.locator(selector).first.click(timeout=timeout_ms, no_wait_after=no_wait_after)
            wait_after_ms = max(0, parse_int_value(action.get("wait_after_ms"), 0))
            if wait_after_ms > 0:
                page.wait_for_timeout(wait_after_ms)
            return

        if action_type == "wait_for_selector":
            selector = str(action.get("selector", "")).strip()
            state = str(action.get("state", "visible")).strip() or "visible"
            page.wait_for_selector(selector, state=state, timeout=timeout_ms)
            return

        if action_type == "wait_for_load":
            state = str(action.get("state", "networkidle")).strip() or "networkidle"
            page.wait_for_load_state(state=state, timeout=timeout_ms)
            return

        if action_type == "sleep":
            duration_ms = max(0, parse_int_value(action.get("duration_ms"), 1000))
            page.wait_for_timeout(duration_ms)
            return
    except Exception:
        if optional:
            return
        raise

    raise ValueError(f"不支持的浏览器动作类型: {action_type}")


def collect_links_from_rule_across_pages(
    initial_html_text: str,
    initial_page_url: str,
    rule: dict[str, object],
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict[str, object]:
    validate_rule_config(rule)
    pagination_config = get_pagination_config(rule)
    if not pagination_config["enabled"]:
        soup = BeautifulSoup(initial_html_text, "html.parser")
        extraction_result = extract_links_from_rule(soup, initial_page_url, rule)
        if progress_callback is not None:
            progress_callback(1, 1, "当前规则无需翻页")
        return {
            "links": extraction_result["links"],
            "page_count": 1,
            "html_tag_match_count": extraction_result["html_tag_match_count"],
            "resource_records": extraction_result.get("resource_records", []),
        }

    start_page = int(pagination_config["start_page"])
    max_page_limit = int(pagination_config["max_page_limit"])
    pending_pages: list[int] = [start_page]
    queued_pages: set[int] = {start_page}
    visited_pages: set[int] = set()
    known_max_page = start_page
    all_links: list[str] = []
    seen_links: set[str] = set()
    total_html_tag_match_count = 0
    all_resource_records: list[dict[str, str]] = []
    seen_resource_records: set[tuple[str, str]] = set()

    while pending_pages:
        page_number = pending_pages.pop(0)
        queued_pages.discard(page_number)
        if page_number in visited_pages or page_number > max_page_limit:
            continue

        if page_number == start_page:
            page_url = initial_page_url
            html_text = initial_html_text
        else:
            page_url = build_page_url(
                str(pagination_config["page_url_template"]),
                page_number,
                initial_page_url,
            )
            try:
                html_text = fetch_html(page_url)
            except Exception:
                continue

        visited_pages.add(page_number)
        soup = BeautifulSoup(html_text, "html.parser")
        extraction_result = extract_links_from_rule(soup, page_url, rule)
        total_html_tag_match_count += parse_int_value(
            extraction_result["html_tag_match_count"],
            0,
        )
        for link in extraction_result["links"]:
            if link in seen_links:
                continue
            seen_links.add(link)
            all_links.append(link)
        for resource_item in normalize_resource_items(extraction_result.get("resource_records", [])):
            item_key = (
                str(resource_item.get("detail_url", "")).strip(),
                str(resource_item.get("name", "")).strip(),
            )
            if not item_key[0] or not item_key[1] or item_key in seen_resource_records:
                continue
            seen_resource_records.add(item_key)
            all_resource_records.append(resource_item)

        visible_max_page = extract_visible_max_page(soup, pagination_config)
        if visible_max_page is None:
            if progress_callback is not None:
                progress_callback(
                    len(visited_pages),
                    max(len(visited_pages), known_max_page),
                    f"已抓取第 {page_number} 页",
                )
            continue

        capped_max_page = min(visible_max_page, max_page_limit)
        if progress_callback is not None:
            progress_callback(
                len(visited_pages),
                max(len(visited_pages), capped_max_page),
                f"已抓取第 {page_number} 页，共 {capped_max_page} 页",
            )
        if capped_max_page <= known_max_page:
            continue

        for next_page in range(known_max_page + 1, capped_max_page + 1):
            if next_page in visited_pages or next_page in queued_pages:
                continue
            pending_pages.append(next_page)
            queued_pages.add(next_page)
        known_max_page = capped_max_page

    if progress_callback is not None:
        progress_callback(len(visited_pages), len(visited_pages), "当前规则抓取完成")
    return {
        "links": all_links,
        "page_count": len(visited_pages),
        "html_tag_match_count": total_html_tag_match_count,
        "resource_records": all_resource_records,
    }


def build_page_url(page_url_template: str, page_number: int, current_page_url: str) -> str:
    if "{page}" not in page_url_template:
        raise ValueError("page_url_template 必须包含 {page} 占位。")

    current_parts = urlsplit(current_page_url)
    current_params = normalize_params_text(current_parts.query)
    formatted_template = page_url_template.format(
        page=page_number,
        params=current_params,
    )
    page_url = urljoin(current_page_url, formatted_template)

    if "{params}" in page_url_template or not current_params:
        return page_url

    page_parts = urlsplit(page_url)
    if page_parts.query:
        return page_url

    return urlunsplit(
        (
            page_parts.scheme,
            page_parts.netloc,
            page_parts.path,
            current_params,
            page_parts.fragment,
        )
    )


def extract_visible_max_page(soup: BeautifulSoup, pagination_config: dict[str, object]) -> int | None:
    page_number_selector = str(pagination_config["page_number_selector"])
    if not page_number_selector:
        return None

    page_number_attr = str(pagination_config["page_number_attr"])
    page_number_regex = str(pagination_config["page_number_regex"])
    try:
        pattern = re.compile(page_number_regex)
    except re.error:
        pattern = re.compile(r"\d+")

    nodes = soup.select(page_number_selector)
    if not nodes:
        fallback_selector = page_number_selector
        while " " in fallback_selector and not nodes:
            fallback_selector = fallback_selector.rsplit(" ", 1)[0].strip()
            if not fallback_selector:
                break
            nodes = soup.select(fallback_selector)

    max_page: int | None = None
    for node in nodes:
        raw_value = extract_rule_value(node, page_number_attr)
        if not raw_value:
            continue
        for match in pattern.findall(raw_value):
            page_number = parse_int_value(match, 0)
            if page_number < 1:
                continue
            if max_page is None or page_number > max_page:
                max_page = page_number
    return max_page


def extract_links_from_rule(soup: BeautifulSoup, page_url: str, rule: dict[str, object]) -> dict[str, object]:
    site_config = get_site_config(rule)
    target_selector = normalize_target_selector(str(site_config.get("target", rule.get("target", ""))).strip())
    if not target_selector:
        return {"links": [], "html_tag_match_count": 0, "resource_records": []}

    link_selector = str(site_config.get("link_selector", rule.get("link_selector", "a"))).strip() or "a"
    attr_name = str(site_config.get("attr", rule.get("attr", "href"))).strip() or "href"
    use_target_directly = bool(site_config.get("use_target_directly", rule.get("use_target_directly", False)))
    resource_name_selector = str(
        site_config.get("resource_name_selector", rule.get("resource_name_selector", ""))
    ).strip()
    resource_name_attr = str(
        site_config.get("resource_name_attr", rule.get("resource_name_attr", "text"))
    ).strip() or "text"

    links: list[str] = []
    seen_links: set[str] = set()
    html_tag_match_count = 0
    resource_records: list[dict[str, str]] = []
    seen_resource_records: set[tuple[str, str]] = set()

    for target_node in soup.select(target_selector):
        candidate_nodes = [target_node] if use_target_directly else target_node.select(link_selector)
        for candidate_node in candidate_nodes:
            value = extract_rule_value(candidate_node, attr_name)
            if not value:
                continue
            html_tag_match_count += 1
            full_link = urljoin(page_url, value)
            if full_link in seen_links:
                continue
            seen_links.add(full_link)
            links.append(full_link)
            resource_name = ""
            if resource_name_selector:
                if not use_target_directly and resource_name_selector == link_selector:
                    resource_name = extract_rule_value(candidate_node, resource_name_attr).strip()
                else:
                    resource_node = target_node.select_one(resource_name_selector)
                    if resource_node is not None:
                        resource_name = extract_rule_value(resource_node, resource_name_attr).strip()
            if resource_name:
                item_key = (full_link, resource_name)
                if item_key not in seen_resource_records:
                    seen_resource_records.add(item_key)
                    resource_records.append(
                        {
                            "name": resource_name,
                            "detail_url": full_link,
                            "download_url": "",
                        }
                    )

    return {
        "links": links,
        "html_tag_match_count": html_tag_match_count,
        "resource_records": resource_records,
    }


def normalize_target_selector(target: str) -> str:
    if not target:
        return ""
    if not target.startswith("<"):
        return target

    fragment = BeautifulSoup(target, "html.parser").find()
    if fragment is None or not getattr(fragment, "name", ""):
        return target

    selector = fragment.name
    fragment_id = fragment.get("id")
    if fragment_id:
        selector += f"#{fragment_id}"

    classes = fragment.get("class", [])
    for class_name in classes:
        selector += f".{class_name}"

    return selector


def extract_rule_value(candidate_node: object, attr_name: str) -> str:
    if attr_name == "text":
        return candidate_node.get_text(strip=True)
    return str(candidate_node.get(attr_name, "")).strip()
