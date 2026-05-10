import json
import re
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
from PyQt6.QtCore import Qt
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
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


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
    params_input.setPlaceholderText("输入查询参数，例如 a=1&b=2 或多行 key=value")
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
    current_rows: list[dict[str, str]],
    current_rules: dict[str, list[dict[str, str]]],
) -> tuple[list[dict[str, str]], dict[str, list[dict[str, str]]]] | None:
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
        {"url": row.get("url", "").strip(), "params": row.get("params", "").strip()}
        for row in current_rows
    ]
    working_rows: list[dict[str, str]] = []
    working_rules = {
        entry_url: normalize_child_rules(items)
        for entry_url, items in current_rules.items()
    }

    def update_fetch_progress(current: int, total: int, message: str) -> None:
        progress_status.setText(message)
        if total <= 0:
            progress_bar.setRange(0, 0)
        else:
            progress_bar.setRange(0, total)
            progress_bar.setValue(max(0, min(current, total)))
        QApplication.processEvents()

    def fetch_row_html(row_index: int) -> None:
        if row_index >= len(working_rows):
            return

        url_text = _get_row_url(table, row_index)
        if not url_text:
            QMessageBox.warning(dialog, "提示", "请先输入网站。")
            return

        working_rows[row_index]["url"] = url_text
        full_url = build_url_with_params(url_text, working_rows[row_index].get("params", ""))
        update_fetch_progress(0, 0, f"正在请求入口页: {full_url}")

        try:
            html_text = fetch_html(full_url)
        except Exception as exc:
            progress_bar.setRange(0, 1)
            progress_bar.setValue(0)
            progress_status.setText("入口页获取失败")
            QMessageBox.warning(dialog, "提示", f"获取 HTML 失败: {exc}")
            return

        matched_results = parse_links_by_rules(
            html_text,
            full_url,
            working_rules.get(url_text, []),
            progress_callback=update_fetch_progress,
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

        print(f"===== PARSED LINKS: {full_url} =====")
        print(json.dumps(parsed_links, ensure_ascii=False, indent=2))
        print(f"总页数: {total_pages}")
        print(f"总链接数: {len(parsed_links)}")
        print(f"===== PARSED LINKS END: {full_url} =====\n")
        progress_bar.setRange(0, max(1, total_pages))
        progress_bar.setValue(max(1, total_pages))
        progress_status.setText(f"抓取完成，共 {total_pages} 页，{len(parsed_links)} 个链接")

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
        url_input.setPlaceholderText("输入入口网站，例如 https://example.com/search")
        url_input.setText(url_text)
        url_input.editingFinished.connect(
            lambda row=row_index, input_widget=url_input: _sync_row_url(working_rows, row, input_widget)
        )
        table.setCellWidget(row_index, 0, url_input)

        params_button = QPushButton("参数")
        params_button.clicked.connect(lambda _=False, row=row_index: edit_row_params(row))
        table.setCellWidget(row_index, 1, params_button)

        update_button = QPushButton("更新")
        update_button.clicked.connect(lambda _=False, row=row_index: fetch_row_html(row))
        table.setCellWidget(row_index, 2, update_button)

        table.setRowHeight(row_index, 38)

    for row in source_rows:
        append_row(row.get("url", ""), row.get("params", ""))
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
    working_rows: list[dict[str, str]],
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
    current_rules: dict[str, list[dict[str, str]]],
) -> dict[str, list[dict[str, str]]] | None:
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
    rules_tree.setColumnCount(3)
    rules_tree.setHeaderLabels(["入口网站 / 子网站", "URL 匹配", "配置"])
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
        child_item = QTreeWidgetItem([child_name, str(node_rule.get("match_url", "")).strip(), ""])
        child_item.setData(0, Qt.ItemDataRole.UserRole, ("child", path))
        parent_item.addChild(child_item)

        config_button = QPushButton("配置")
        config_button.clicked.connect(
            lambda _=False, item=child_item: configure_child_rule(item)
        )
        rules_tree.setItemWidget(child_item, 2, config_button)

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
            child_rule.get("rule_json", ""),
        )
        if result is None:
            return

        site_name, match_url, rule_json = result
        child_rule["site_name"] = site_name
        child_rule["match_url"] = match_url
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
    current_rule_json: str,
) -> tuple[str, str, str] | None:
    dialog = QDialog(parent)
    dialog.setWindowTitle("JSON 规则")
    dialog.resize(760, 520)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(8)

    form_layout = QFormLayout()
    site_name_input = QLineEdit(current_name)
    site_name_input.setPlaceholderText("例如 搜索结果页")
    match_url_input = QLineEdit(current_match_url)
    match_url_input.setPlaceholderText("可留空，支持普通文本、* 通配符、regex:正则")
    form_layout.addRow("子网站名称", site_name_input)
    form_layout.addRow("URL 匹配", match_url_input)
    layout.addLayout(form_layout)

    json_input = QPlainTextEdit()
    json_input.setPlaceholderText(
        '{\n'
        '  "step": 1,\n'
        '  "fetch_mode": "background",\n'
        '  "target": "article.item-list",\n'
        '  "link_selector": "h2.post-box-title a",\n'
        '  "attr": "href"\n'
        '}'
    )
    json_input.setPlainText(current_rule_json)
    layout.addWidget(json_input)

    help_title = QLabel("可选参数说明")
    layout.addWidget(help_title)

    help_text = QPlainTextEdit()
    help_text.setReadOnly(True)
    help_text.setPlainText(
        "示例:\n"
        '{\n'
        '  "step": 1,\n'
        '  "fetch_mode": "background",\n'
        '  "target": "article.item-list",\n'
        '  "link_selector": "h2.post-box-title a",\n'
        '  "attr": "href"\n'
        '}\n\n'
        "也支持简写:\n"
        '{step:1,fetch_mode:"background",target:<article class="item-list">,link_selector:"a",attr:"href"}\n\n'
        "参数说明:\n"
        "step\n"
        "  当前步骤编号。当前版本主要用于标记步骤，后续可接多步流程。\n\n"
        "fetch_mode\n"
        "  可选。默认 background。\n"
        "  background: 后台请求 HTML 后按规则提取。\n"
        "  browser: 打开浏览器页面，按 browser_actions 模拟操作后再提取。\n\n"
        "next_step\n"
        "  可选。下一步步骤编号。\n"
        "  当前版本先保留这个字段，方便你按多步流程先写规则。\n"
        "  后续接入自动流程调度时，会根据它决定下一步访问和解析。\n\n"
        "target\n"
        "  必填。先用它选中当前页面里的目标区域。\n"
        "  可以写 CSS 选择器，例如 article.item-list。\n"
        "  也可以写标签片段，例如 <article class=\"item-list\">，程序会自动转成选择器。\n\n"
        "link_selector\n"
        "  可选。默认是 a。\n"
        "  在 target 选中的区域里继续查找哪个元素。\n"
        "  例如 h2.post-box-title a、a.download-link、img.cover。\n\n"
        "attr\n"
        "  可选。默认是 href。\n"
        "  指定从 link_selector 找到的元素上取哪个值。\n"
        "  常见值:\n"
        "  href: 提取链接地址\n"
        "  src: 提取图片地址\n"
        "  text: 提取元素文本\n\n"
        "use_target_directly\n"
        "  可选。true / false，默认 false。\n"
        "  false 时，会先找到 target，再在里面用 link_selector 找元素。\n"
        "  true 时，直接把 target 命中的元素本身作为取值对象。\n"
        "  适合 target 本身就是 a、img 这类目标标签的情况。\n\n"
        "browser_actions\n"
        "  仅在 fetch_mode=browser 时使用，可选。\n"
        "  是一个数组，按顺序执行浏览器动作。\n"
        "  支持 type: click、wait_for_selector、wait_for_load、sleep。\n"
        "  click / wait_for_selector 需要 selector。\n"
        "  sleep 使用 duration_ms。\n"
        "  click 可选 wait_after_ms，点击后额外等待。\n\n"
        "browser_headless\n"
        "  可选。默认 false。\n"
        "  false 会显示浏览器窗口，true 为无头模式。\n\n"
        "match_url\n"
        "  这不是 JSON 内字段，而是上方单独填写的 URL 匹配条件。\n"
        "  支持三种写法:\n"
        "  1. 普通文本: 当前页面 URL 包含这段文字时命中。\n"
        "  2. 通配符: 使用 * 匹配任意长度字符，例如 www.sample.com/page/*/?s=*。\n"
        "  3. 正则: 以 regex: 开头，例如 regex:^www\\.sample\\.com/page/\\d+/\\?s=[^&]+$。\n"
        "  可以留空，表示通用规则。\n"
        "  当多条特定规则同时命中时，会优先执行更具体的那条规则。\n\n"
        "pagination_enabled\n"
        "  可选。true 时启用自动翻页抓取。\n\n"
        "page_url_template\n"
        "  启用分页时必填，使用 {page} 作为页码占位。\n"
        "  例如 https://example.com/page/{page}/?\n\n"
        "start_page\n"
        "  可选。起始页码，默认 1。\n\n"
        "page_number_selector\n"
        "  启用分页时必填。分页栏页码节点的 CSS 选择器。\n\n"
        "page_number_attr\n"
        "  可选。默认 text，也可以填 href。\n\n"
        "page_number_regex\n"
        "  可选。默认 \\\\d+，用于从分页节点内容里提取页码。\n\n"
        "max_page_limit\n"
        "  可选。默认 200，防止循环抓取过多页。\n\n"
        "常见组合:\n"
        "1. 后台请求提取列表里的详情页链接\n"
        '   {\n'
        '     "step": 1,\n'
        '     "fetch_mode": "background",\n'
        '     "next_step": 2,\n'
        '     "target": "article.item-list",\n'
        '     "link_selector": "h2.post-box-title a",\n'
        '     "attr": "href"\n'
        '   }\n\n'
        "2. target 本身就是链接\n"
        '   {\n'
        '     "step": 1,\n'
        '     "fetch_mode": "background",\n'
        '     "target": "a.download-link",\n'
        '     "attr": "href",\n'
        '     "use_target_directly": true\n'
        '   }\n\n'
        "3. 自动翻页提取链接\n"
        '   {\n'
        '     "step": 1,\n'
        '     "fetch_mode": "background",\n'
        '     "target": "article.item-list",\n'
        '     "link_selector": "h2.post-box-title a",\n'
        '     "attr": "href",\n'
        '     "pagination_enabled": true,\n'
        '     "page_url_template": "https://example.com/page/{page}/?",\n'
        '     "start_page": 1,\n'
        '     "page_number_selector": ".pagination a, .pagination span",\n'
        '     "page_number_attr": "text",\n'
        '     "page_number_regex": "\\\\d+",\n'
        '     "max_page_limit": 200\n'
        '   }\n\n'
        "4. 打开浏览器点击后再提取链接\n"
        '   {\n'
        '     "step": 1,\n'
        '     "fetch_mode": "browser",\n'
        '     "browser_headless": false,\n'
        '     "browser_actions": [\n'
        '       {\n'
        '         "type": "click",\n'
        '         "selector": "button.load-more",\n'
        '         "wait_after_ms": 1500\n'
        '       },\n'
        '       {\n'
        '         "type": "wait_for_selector",\n'
        '         "selector": "article.item-list"\n'
        '       }\n'
        '     ],\n'
        '     "target": "article.item-list",\n'
        '     "link_selector": "h2.post-box-title a",\n'
        '     "attr": "href"\n'
        '   }\n\n'
        "5. 提取标题文字\n"
        '   {\n'
        '     "step": 1,\n'
        '     "fetch_mode": "background",\n'
        '     "target": "article.item-list",\n'
        '     "link_selector": "h2.post-box-title a",\n'
        '     "attr": "text"\n'
        '   }'
    )
    help_text.setMinimumHeight(260)
    layout.addWidget(help_text)

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
        rule_json_text,
    )


def normalize_child_rules(items: list[dict[str, object]]) -> list[dict[str, object]]:
    normalized_items: list[dict[str, object]] = []
    for item in items:
        normalized_items.append(
            {
                "site_name": str(item.get("site_name", "")).strip(),
                "match_url": str(item.get("match_url", "")).strip(),
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
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> list[dict[str, object]]:
    matched_results: list[dict[str, object]] = []
    normalized_rules = normalize_child_rules(child_rules)
    specific_matches: list[tuple[tuple[int, int, int], dict[str, object]]] = []
    generic_rules: list[dict[str, object]] = []

    for child_rule in normalized_rules:
        match_url = child_rule.get("match_url", "")
        if match_url:
            if rule_matches_page_url(match_url, page_url):
                specific_matches.append((get_match_url_priority(match_url), child_rule))
            continue
        generic_rules.append(child_rule)

    if specific_matches:
        best_priority = max(priority for priority, _ in specific_matches)
        active_rules = [
            child_rule
            for priority, child_rule in specific_matches
            if priority == best_priority
        ]
    else:
        active_rules = generic_rules
    total_rules = len(active_rules)

    for rule_index, child_rule in enumerate(active_rules, start=1):
        match_url = child_rule.get("match_url", "")

        rule_text = child_rule.get("rule_json", "")
        if not rule_text:
            continue

        try:
            rule = parse_rule_text(rule_text)
        except ValueError:
            continue

        site_name = child_rule.get("site_name", "") or "未命名子网站"

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
                collection_result = collect_links_from_rule_across_pages(
                    html_text,
                    page_url,
                    rule,
                    progress_callback=report_rule_progress,
                )
        except ValueError:
            continue
        matched_results.append(
            {
                "site_name": site_name,
                "match_url": match_url,
                "links": collection_result["links"],
                "page_count": collection_result["page_count"],
                "children": collect_child_rule_results(
                    collection_result["links"],
                    get_child_rule_children(child_rule),
                    site_name,
                    page_url,
                    parse_int_value(collection_result["page_count"], 0),
                    progress_callback=report_rule_progress,
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
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> list[dict[str, object]]:
    if not parent_links or not child_rules:
        return []

    print("===== CHILD MATCH INPUT START =====")
    print(f"入口网站: {parent_site_name}")
    print(f"页面地址: {parent_page_url}")
    print(f"总页数: {parent_page_count}")
    print("链接数组:")
    print(json.dumps(parent_links, ensure_ascii=False, indent=2))
    print("===== CHILD MATCH INPUT END =====\n")

    child_results: list[dict[str, object]] = []
    seen_page_urls: set[str] = set()
    total_links = len(parent_links)

    for link_index, link_url in enumerate(parent_links, start=1):
        if link_url in seen_page_urls:
            continue
        seen_page_urls.add(link_url)

        if progress_callback is not None:
            progress_callback(link_index, total_links, f"正在匹配下一级: {link_url}")

        try:
            html_text = fetch_html(link_url)
        except Exception:
            continue

        matched_results = parse_links_by_rules(
            html_text,
            link_url,
            child_rules,
            progress_callback=progress_callback,
        )
        child_results.extend(matched_results)

    return child_results


def flatten_result_links(result: dict[str, object]) -> list[str]:
    flattened_links: list[str] = []
    for link in result.get("links", []):
        if isinstance(link, str):
            flattened_links.append(link)
    for child_result in result.get("children", []):
        if isinstance(child_result, dict):
            flattened_links.extend(flatten_result_links(child_result))
    return flattened_links


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
        validate_browser_actions(rule.get("browser_actions"))
        if bool(rule.get("pagination_enabled", False)):
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
    return {
        "enabled": bool(rule.get("pagination_enabled", False)),
        "page_url_template": str(rule.get("page_url_template", "")).strip(),
        "start_page": max(1, parse_int_value(rule.get("start_page"), 1)),
        "page_number_selector": str(rule.get("page_number_selector", "")).strip(),
        "page_number_attr": str(rule.get("page_number_attr", "text")).strip() or "text",
        "page_number_regex": str(rule.get("page_number_regex", r"\d+")).strip() or r"\d+",
        "max_page_limit": max(1, parse_int_value(rule.get("max_page_limit"), 200)),
    }


def parse_int_value(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
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


def collect_links_from_browser_rule(
    initial_page_url: str,
    rule: dict[str, object],
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict[str, object]:
    validate_rule_config(rule)

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ValueError(
            "browser 模式需要先安装 playwright：pip install playwright，然后执行 playwright install"
        ) from exc

    actions = rule.get("browser_actions")
    action_list = actions if isinstance(actions, list) else []
    headless = bool(rule.get("browser_headless", False))

    if progress_callback is not None:
        progress_callback(0, max(1, len(action_list) + 2), "正在启动浏览器")

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            page = browser.new_page()
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
            browser.close()
    except PlaywrightError as exc:
        raise ValueError(f"浏览器模式执行失败: {exc}") from exc

    soup = BeautifulSoup(html_text, "html.parser")
    links = extract_links_from_rule(soup, final_page_url, rule)
    if progress_callback is not None:
        progress_callback(total_steps, total_steps, "浏览器规则抓取完成")
    return {"links": links, "page_count": 1}


def run_browser_action(page: object, action: dict[str, object]) -> None:
    action_type = str(action.get("type", "")).strip().lower()
    timeout_ms = max(0, parse_int_value(action.get("timeout_ms"), 30000))

    if action_type == "click":
        selector = str(action.get("selector", "")).strip()
        page.locator(selector).first.click(timeout=timeout_ms)
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
        links = extract_links_from_rule(soup, initial_page_url, rule)
        if progress_callback is not None:
            progress_callback(1, 1, "当前规则无需翻页")
        return {"links": links, "page_count": 1}

    start_page = int(pagination_config["start_page"])
    max_page_limit = int(pagination_config["max_page_limit"])
    pending_pages: list[int] = [start_page]
    queued_pages: set[int] = {start_page}
    visited_pages: set[int] = set()
    known_max_page = start_page
    all_links: list[str] = []
    seen_links: set[str] = set()

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
        page_links = extract_links_from_rule(soup, page_url, rule)
        for link in page_links:
            if link in seen_links:
                continue
            seen_links.add(link)
            all_links.append(link)

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
    return {"links": all_links, "page_count": len(visited_pages)}


def build_page_url(page_url_template: str, page_number: int, current_page_url: str) -> str:
    if "{page}" not in page_url_template:
        raise ValueError("page_url_template 必须包含 {page} 占位。")
    return urljoin(current_page_url, page_url_template.format(page=page_number))


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

    max_page: int | None = None
    for node in soup.select(page_number_selector):
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


def extract_links_from_rule(soup: BeautifulSoup, page_url: str, rule: dict[str, object]) -> list[str]:
    target_selector = normalize_target_selector(str(rule.get("target", "")).strip())
    if not target_selector:
        return []

    link_selector = str(rule.get("link_selector", "a")).strip() or "a"
    attr_name = str(rule.get("attr", "href")).strip() or "href"
    use_target_directly = bool(rule.get("use_target_directly", False))

    links: list[str] = []
    seen_links: set[str] = set()

    for target_node in soup.select(target_selector):
        candidate_nodes = [target_node] if use_target_directly else target_node.select(link_selector)
        for candidate_node in candidate_nodes:
            value = extract_rule_value(candidate_node, attr_name)
            if not value:
                continue
            full_link = urljoin(page_url, value)
            if full_link in seen_links:
                continue
            seen_links.add(full_link)
            links.append(full_link)

    return links


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
