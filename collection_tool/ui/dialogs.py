import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
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
    layout.addWidget(table)

    source_rows = [
        {"url": row.get("url", "").strip(), "params": row.get("params", "").strip()}
        for row in current_rows
    ]
    working_rows: list[dict[str, str]] = []
    working_rules = {
        entry_url: normalize_child_rules(items)
        for entry_url, items in current_rules.items()
    }

    def fetch_row_html(row_index: int) -> None:
        if row_index >= len(working_rows):
            return

        url_text = _get_row_url(table, row_index)
        if not url_text:
            QMessageBox.warning(dialog, "提示", "请先输入网站。")
            return

        working_rows[row_index]["url"] = url_text
        full_url = build_url_with_params(url_text, working_rows[row_index].get("params", ""))

        try:
            html_text = fetch_html(full_url)
        except Exception as exc:
            QMessageBox.warning(dialog, "提示", f"获取 HTML 失败: {exc}")
            return

        cleaned_html = clean_html_for_output(html_text)
        matched_results = parse_links_by_rules(
            cleaned_html,
            full_url,
            working_rules.get(url_text, []),
        )

        print(f"\n===== HTML START: {full_url} =====")
        print(cleaned_html)
        print(f"===== HTML END: {full_url} =====\n")

        if not matched_results:
            print(f"===== PARSED LINKS: {full_url} =====")
            print("No matched rules or no links extracted.")
            print(f"===== PARSED LINKS END: {full_url} =====\n")
            return

        print(f"===== PARSED LINKS: {full_url} =====")
        for result in matched_results:
            print(f"[{result['site_name']}]")
            print(f"match_url={result['match_url'] or '(empty)'}")
            if result["links"]:
                for link in result["links"]:
                    print(link)
            else:
                print("No links extracted.")
        print(f"===== PARSED LINKS END: {full_url} =====\n")

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
    save_button = QPushButton("保存")
    close_button = QPushButton("关闭")
    button_row.addWidget(add_button)
    button_row.addWidget(rules_button)
    button_row.addStretch()
    button_row.addWidget(save_button)
    button_row.addWidget(close_button)
    layout.addLayout(button_row)

    add_button.clicked.connect(lambda: append_row())
    rules_button.clicked.connect(
        lambda: open_site_rules_dialog(dialog, table, working_rows, working_rules)
    )
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

    tip_label = QLabel("先按入口网站展开，再为该入口网站添加子网站规则。子网站配置用 JSON 描述解析逻辑。")
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

    def rebuild_tree() -> None:
        rules_tree.clear()
        for entry_url in entry_urls:
            entry_item = QTreeWidgetItem([entry_url, "", ""])
            entry_item.setData(0, Qt.ItemDataRole.UserRole, ("entry", entry_url, None))
            rules_tree.addTopLevelItem(entry_item)
            entry_item.setExpanded(True)

            for index, child_rule in enumerate(working_rules.get(entry_url, [])):
                child_name = child_rule.get("site_name", "") or f"子网站 {index + 1}"
                child_item = QTreeWidgetItem([child_name, child_rule.get("match_url", ""), ""])
                child_item.setData(0, Qt.ItemDataRole.UserRole, ("child", entry_url, index))
                entry_item.addChild(child_item)

                config_button = QPushButton("配置")
                config_button.clicked.connect(
                    lambda _=False, item=child_item: configure_child_rule(item)
                )
                rules_tree.setItemWidget(child_item, 2, config_button)

        rules_tree.expandAll()
        rules_tree.resizeColumnToContents(0)
        rules_tree.resizeColumnToContents(1)

    def configure_child_rule(child_item: QTreeWidgetItem) -> None:
        data = child_item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data[0] != "child":
            return

        entry_url = data[1]
        rule_index = data[2]
        child_rule = working_rules[entry_url][rule_index]
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
            QMessageBox.warning(dialog, "提示", "请先选择一个入口网站。")
            return

        data = current_item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        entry_url = data[1]
        site_name, ok = QInputDialog.getText(dialog, "添加子网站", "子网站名称")
        if not ok:
            return

        working_rules.setdefault(entry_url, []).append(
            {
                "site_name": site_name.strip() or f"子网站 {len(working_rules.get(entry_url, [])) + 1}",
                "match_url": "",
                "rule_json": '{\n  "step": 1,\n  "target": "article.item-list",\n  "link_selector": "a",\n  "attr": "href"\n}',
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

        entry_url = data[1]
        rule_index = data[2]
        del working_rules[entry_url][rule_index]
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
    match_url_input.setPlaceholderText("可留空，或填写 URL 关键字用于匹配当前页面")
    form_layout.addRow("子网站名称", site_name_input)
    form_layout.addRow("URL 匹配", match_url_input)
    layout.addLayout(form_layout)

    json_input = QPlainTextEdit()
    json_input.setPlaceholderText(
        '{\n'
        '  "step": 1,\n'
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
        '  "target": "article.item-list",\n'
        '  "link_selector": "h2.post-box-title a",\n'
        '  "attr": "href"\n'
        '}\n\n'
        "也支持简写:\n"
        '{step:1,target:<article class="item-list">,link_selector:"a",attr:"href"}\n\n'
        "参数说明:\n"
        "step\n"
        "  当前步骤编号。当前版本主要用于标记步骤，后续可接多步流程。\n\n"
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
        "match_url\n"
        "  这不是 JSON 内字段，而是上方单独填写的 URL 匹配条件。\n"
        "  当当前页面 URL 包含这段文字时，才会使用这条规则。\n"
        "  可以留空，表示不限制。\n\n"
        "常见组合:\n"
        "1. 提取列表里的详情页链接\n"
        '   {"step":1,"next_step":2,"target":"article.item-list","link_selector":"h2.post-box-title a","attr":"href"}\n\n'
        "2. target 本身就是链接\n"
        '   {"step":1,"target":"a.download-link","attr":"href","use_target_directly":true}\n\n'
        "3. 提取标题文字\n"
        '   {"step":1,"target":"article.item-list","link_selector":"h2.post-box-title a","attr":"text"}'
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
            parse_rule_text(rule_json_text)
        except ValueError as exc:
            QMessageBox.warning(parent, "提示", f"规则格式无效: {exc}")
            return None

    return (
        site_name_input.text().strip(),
        match_url_input.text().strip(),
        rule_json_text,
    )


def normalize_child_rules(items: list[dict[str, str]]) -> list[dict[str, str]]:
    normalized_items: list[dict[str, str]] = []
    for item in items:
        normalized_items.append(
            {
                "site_name": str(item.get("site_name", "")).strip(),
                "match_url": str(item.get("match_url", "")).strip(),
                "rule_json": str(item.get("rule_json", "")).strip(),
            }
        )
    return normalized_items


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


def clean_html_for_output(html_text: str) -> str:
    cleaned = re.sub(r"<!--.*?-->", "", html_text, flags=re.DOTALL)
    cleaned = re.sub(r"<script\b[^>]*>.*?</script>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<style\b[^>]*>.*?</style>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(
        r"<link\b[^>]*rel=[\"']?stylesheet[\"']?[^>]*>",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"<noscript\b[^>]*>.*?</noscript>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"\n\s*\n+", "\n\n", cleaned)
    return cleaned.strip()


def parse_links_by_rules(
    html_text: str,
    page_url: str,
    child_rules: list[dict[str, str]],
) -> list[dict[str, object]]:
    soup = BeautifulSoup(html_text, "html.parser")
    matched_results: list[dict[str, object]] = []

    for child_rule in normalize_child_rules(child_rules):
        match_url = child_rule.get("match_url", "")
        if match_url and match_url not in page_url:
            continue

        rule_text = child_rule.get("rule_json", "")
        if not rule_text:
            continue

        try:
            rule = parse_rule_text(rule_text)
        except ValueError:
            continue

        links = extract_links_from_rule(soup, page_url, rule)
        matched_results.append(
            {
                "site_name": child_rule.get("site_name", "") or "未命名子网站",
                "match_url": match_url,
                "links": links,
            }
        )

    return matched_results


def parse_rule_text(rule_text: str) -> dict[str, object]:
    try:
        parsed = json.loads(rule_text)
    except json.JSONDecodeError:
        parsed = parse_relaxed_rule_text(rule_text)

    if not isinstance(parsed, dict):
        raise ValueError("规则内容必须是一个对象。")
    return parsed


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
