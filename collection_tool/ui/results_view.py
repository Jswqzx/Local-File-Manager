from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox, QLabel, QTreeWidget, QTreeWidgetItem

from ..models import EntryRecord
from ..services import GroupKey


def populate_group_tree(
    group_tree: QTreeWidget,
    grouped_entries: dict[GroupKey, list[EntryRecord]],
    current_group_key: GroupKey | None = None,
) -> None:
    group_tree.clear()

    all_entries = grouped_entries.get(("All", "All"), [])
    all_item = QTreeWidgetItem(["全部结果", str(len(all_entries))])
    all_item.setData(0, Qt.ItemDataRole.UserRole, ("All", "All"))
    group_tree.addTopLevelItem(all_item)

    folder_root = add_group_root(group_tree, grouped_entries, "文件夹", "Folder")
    file_root = add_group_root(group_tree, grouped_entries, "文件", "File")

    group_tree.expandAll()
    target_item = find_group_item(group_tree, current_group_key) if current_group_key else None
    group_tree.setCurrentItem(target_item or all_item)

    if folder_root is not None:
        folder_root.setExpanded(True)
    if file_root is not None:
        file_root.setExpanded(True)


def add_group_root(
    group_tree: QTreeWidget,
    grouped_entries: dict[GroupKey, list[EntryRecord]],
    title: str,
    kind: str,
) -> QTreeWidgetItem:
    total_entries = grouped_entries.get((kind, "All"), [])
    root_item = QTreeWidgetItem([title, str(len(total_entries))])
    root_item.setData(0, Qt.ItemDataRole.UserRole, (kind, "All"))
    group_tree.addTopLevelItem(root_item)

    child_keys = sorted(key for key in grouped_entries.keys() if key[0] == kind and key[1] != "All")
    for _, type_label in child_keys:
        grouped_type_entries = grouped_entries[(kind, type_label)]
        child = QTreeWidgetItem([type_label, str(len(grouped_type_entries))])
        child.setData(0, Qt.ItemDataRole.UserRole, (kind, type_label))
        root_item.addChild(child)

    return root_item


def populate_results_tree(
    results_tree: QTreeWidget,
    detail_title: QLabel,
    entries: list[EntryRecord],
    title: str,
) -> None:
    results_tree.clear()
    for entry in entries:
        row = QTreeWidgetItem(
            [
                entry.path.name,
                entry.kind,
                entry.type_label,
                entry.relative_path,
            ]
        )
        row.setData(0, Qt.ItemDataRole.UserRole, str(entry.path))
        results_tree.addTopLevelItem(row)

    detail_title.setText(f"结果明细: {title} ({len(entries)})")
    for column in range(results_tree.columnCount()):
        results_tree.resizeColumnToContents(column)


def collect_selected_paths(results_tree: QTreeWidget) -> list[Path]:
    paths: list[Path] = []
    for item in results_tree.selectedItems():
        path_value = item.data(0, Qt.ItemDataRole.UserRole)
        if path_value:
            paths.append(Path(path_value))

    unique_paths = []
    seen: set[Path] = set()
    for path in paths:
        if path not in seen:
            seen.add(path)
            unique_paths.append(path)
    return unique_paths


def toggle_select_current_results_by_kind(results_tree: QTreeWidget, kind: str, checked: bool) -> None:
    results_tree.blockSignals(True)
    for index in range(results_tree.topLevelItemCount()):
        item = results_tree.topLevelItem(index)
        if item.text(1) == kind:
            item.setSelected(checked)
    results_tree.blockSignals(False)


def update_select_all_checkbox_state(
    results_tree: QTreeWidget,
    select_all_folders_checkbox: QCheckBox,
    select_all_files_checkbox: QCheckBox,
) -> None:
    folder_total = 0
    folder_selected = 0
    file_total = 0
    file_selected = 0

    for index in range(results_tree.topLevelItemCount()):
        item = results_tree.topLevelItem(index)
        if item.text(1) == "Folder":
            folder_total += 1
            if item.isSelected():
                folder_selected += 1
        elif item.text(1) == "File":
            file_total += 1
            if item.isSelected():
                file_selected += 1

    select_all_folders_checkbox.setEnabled(folder_total > 0)
    select_all_folders_checkbox.setChecked(folder_total > 0 and folder_selected == folder_total)
    select_all_files_checkbox.setEnabled(file_total > 0)
    select_all_files_checkbox.setChecked(file_total > 0 and file_selected == file_total)


def find_group_item(group_tree: QTreeWidget, group_key: GroupKey | None) -> QTreeWidgetItem | None:
    if group_key is None:
        return None

    for index in range(group_tree.topLevelItemCount()):
        root_item = group_tree.topLevelItem(index)
        if root_item.data(0, Qt.ItemDataRole.UserRole) == group_key:
            return root_item

        for child_index in range(root_item.childCount()):
            child_item = root_item.child(child_index)
            if child_item.data(0, Qt.ItemDataRole.UserRole) == group_key:
                return child_item
    return None
