import re
import shutil
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog, QMainWindow, QMessageBox, QTreeWidgetItem

from ..models import EntryRecord
from ..services import (
    GroupKey,
    build_filter_pattern,
    build_groups,
    build_rename_plan,
    collect_entries,
    format_size,
    is_path_within,
)
from ..storage import load_file_update_rows, save_file_update_rows
from .dialogs import show_file_update_dialog, show_rename_preview_dialog
from .layout import build_main_layout
from .results_view import (
    collect_selected_paths,
    find_group_item,
    populate_group_tree,
    populate_results_tree,
    toggle_select_current_results_by_kind,
    update_select_all_checkbox_state,
)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Collection Tool")
        self.resize(980, 640)

        self.selected_path: Path | None = None
        self.entries: list[EntryRecord] = []
        self.grouped_entries: dict[GroupKey, list[EntryRecord]] = {}
        self.detail_override_folder: Path | None = None
        self.detail_override_entries: list[EntryRecord] | None = None
        self.detail_override_title: str | None = None
        self.updating_select_all_checkboxes = False
        self.request_rows: list[dict[str, str]] = load_file_update_rows()

        self.setCentralWidget(build_main_layout(self))
        self.connect_signals()

    def connect_signals(self) -> None:
        self.browse_button.clicked.connect(self.choose_directory)
        self.scan_button.clicked.connect(self.scan_entries)
        self.refresh_button.clicked.connect(self.scan_entries)
        self.delete_button.clicked.connect(self.delete_selected_entries)
        self.show_files_button.clicked.connect(self.show_selected_folder_files)
        self.url_params_button.clicked.connect(self.open_url_params_dialog)
        self.preview_button.clicked.connect(self.preview_selected_renames)
        self.rename_button.clicked.connect(self.rename_selected_entries)
        self.regex_input.returnPressed.connect(self.scan_entries)
        self.regex_input.textChanged.connect(self.scan_entries_live)
        self.recursive_checkbox.toggled.connect(self.scan_entries_live)
        self.group_tree.itemSelectionChanged.connect(self.update_detail_view)
        self.results_tree.itemSelectionChanged.connect(self.update_select_all_checkbox_state)
        self.results_tree.itemDoubleClicked.connect(self.handle_results_tree_double_click)
        self.select_all_folders_checkbox.toggled.connect(
            lambda checked: self.toggle_select_current_results_by_kind("Folder", checked)
        )
        self.select_all_files_checkbox.toggled.connect(
            lambda checked: self.toggle_select_current_results_by_kind("File", checked)
        )

    def choose_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "选择目录",
            self.path_input.text() or str(Path.home()),
        )
        if not selected:
            return

        self.path_input.setText(selected)
        self.scan_entries()

    def scan_entries(self) -> None:
        self.scan_entries_with_feedback(show_warning=True)

    def scan_entries_live(self, *_args: object) -> None:
        self.scan_entries_with_feedback(show_warning=False)

    def scan_entries_with_feedback(self, show_warning: bool) -> None:
        current_group_key = self.get_current_group_key()
        override_folder = self.detail_override_folder
        base_path = self.path_input.text().strip()
        if not base_path:
            if show_warning:
                self.show_warning("请先选择目录。")
            return

        root = Path(base_path).expanduser()
        if not root.exists() or not root.is_dir():
            if show_warning:
                self.show_warning("所选路径不存在，或不是目录。")
            return

        regex_text = self.regex_input.text().strip()
        pattern: re.Pattern[str] | None = None
        if regex_text:
            try:
                pattern = build_filter_pattern(regex_text)
            except re.error as exc:
                if show_warning:
                    self.show_warning(f"筛选表达式无效: {exc}")
                else:
                    self.status_label.setText(f"筛选表达式无效: {exc}")
                return

        self.selected_path = root
        self.entries = collect_entries(root, pattern, self.recursive_checkbox.isChecked())
        self.grouped_entries = build_groups(self.entries)
        self.populate_group_tree(current_group_key)
        if override_folder is not None and override_folder.exists() and override_folder.is_dir():
            self.show_folder_files_in_results(override_folder)
        self.update_status()

    def populate_group_tree(self, current_group_key: GroupKey | None = None) -> None:
        populate_group_tree(self.group_tree, self.grouped_entries, current_group_key)

    def update_detail_view(self) -> None:
        item = self.group_tree.currentItem()
        if item is None:
            return

        self.detail_override_folder = None
        self.detail_override_entries = None
        self.detail_override_title = None
        group_key = item.data(0, Qt.ItemDataRole.UserRole)
        entries = self.grouped_entries.get(group_key, [])
        self.populate_results_tree(entries, item.text(0))

    def populate_results_tree(self, entries: list[EntryRecord], title: str) -> None:
        populate_results_tree(self.results_tree, self.detail_title, entries, title)
        self.update_select_all_checkbox_state()

    def handle_results_tree_double_click(self, item: QTreeWidgetItem, column: int) -> None:
        del column
        path_value = item.data(0, Qt.ItemDataRole.UserRole)
        if not path_value:
            return

        folder_path = Path(path_value)
        if not folder_path.is_dir():
            return

        self.show_folder_files_in_results(folder_path)

    def show_folder_files_in_results(self, folder_path: Path) -> None:
        folder_files = [
            entry
            for entry in self.entries
            if entry.kind == "File" and is_path_within(entry.path, folder_path)
        ]
        folder_files.sort(key=lambda entry: entry.relative_path)

        self.detail_override_folder = folder_path
        self.detail_override_entries = folder_files
        self.detail_override_title = f"{folder_path.name} 下的所有文件"
        self.populate_results_tree(folder_files, self.detail_override_title)

    def update_status(self) -> None:
        folder_count = len(self.grouped_entries.get(("Folder", "All"), []))
        file_count = len(self.grouped_entries.get(("File", "All"), []))
        total_size = sum(entry.size_bytes for entry in self.entries)
        root_text = str(self.selected_path) if self.selected_path else "-"
        self.status_label.setText(
            "当前目录: "
            f"{root_text} | 文件夹: {folder_count} | 文件: {file_count} | "
            f"总计: {len(self.entries)} | 占用空间: {format_size(total_size)}"
        )

    def delete_selected_entries(self) -> None:
        selected_paths = self.get_selected_paths()
        if not selected_paths:
            self.show_warning("请先选择要删除的文件或文件夹。")
            return

        message = "确认删除以下项目？\n\n" + "\n".join(str(path) for path in selected_paths)
        reply = QMessageBox.question(
            self,
            "确认删除",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        failures: list[str] = []
        for path in sorted(selected_paths, key=lambda item: len(item.parts), reverse=True):
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                elif path.exists():
                    path.unlink()
            except OSError as exc:
                failures.append(f"{path}: {exc}")

        self.scan_entries()

        if failures:
            self.show_warning("以下项目删除失败:\n\n" + "\n".join(failures))
            return

        QMessageBox.information(self, "删除完成", f"已删除 {len(selected_paths)} 个项目。")

    def rename_selected_entries(self) -> None:
        rename_pairs, skipped_paths = self.resolve_rename_plan()
        if rename_pairs is None:
            return

        if not rename_pairs:
            message = "没有可执行的重命名项。"
            if skipped_paths:
                message += "\n\n已跳过:\n" + "\n".join(skipped_paths)
            self.show_warning(message)
            return

        preview_lines = [f"{src.name} -> {dst.name}" for src, dst in rename_pairs]
        message = "确认执行以下文件名替换？\n\n" + "\n".join(preview_lines[:20])
        if len(preview_lines) > 20:
            message += f"\n... 其余 {len(preview_lines) - 20} 项未展开"
        if skipped_paths:
            message += "\n\n以下项目会跳过:\n" + "\n".join(skipped_paths[:10])
            if len(skipped_paths) > 10:
                message += f"\n... 其余 {len(skipped_paths) - 10} 项未展开"

        reply = QMessageBox.question(
            self,
            "确认替换文件名",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        failures: list[str] = []
        for source_path, target_path in sorted(
            rename_pairs,
            key=lambda pair: len(pair[0].parts),
            reverse=True,
        ):
            try:
                source_path.rename(target_path)
            except OSError as exc:
                failures.append(f"{source_path} -> {target_path}: {exc}")

        self.scan_entries()

        if failures:
            self.show_warning("以下项目重命名失败:\n\n" + "\n".join(failures))
            return

        QMessageBox.information(self, "替换完成", f"已重命名 {len(rename_pairs)} 个项目。")

    def preview_selected_renames(self) -> None:
        rename_pairs, skipped_paths = self.resolve_rename_plan()
        if rename_pairs is None:
            return

        show_rename_preview_dialog(self, rename_pairs, skipped_paths)

    def open_url_params_dialog(self) -> None:
        result = show_file_update_dialog(self, self.request_rows)
        if result is None:
            return

        self.request_rows = result
        save_file_update_rows(self.request_rows)

        if self.request_rows:
            configured_params = sum(1 for row in self.request_rows if row.get("params", "").strip())
            self.status_label.setText(
                f"已保存文件更新配置: {len(self.request_rows)} 个网址"
                + (f" | 已配置参数 {configured_params} 项" if configured_params else "")
            )
        else:
            self.status_label.setText("已清空文件更新配置。")

    def show_selected_folder_files(self) -> None:
        item = self.group_tree.currentItem()
        if item is None:
            return

        self.detail_override_folder = None
        self.detail_override_entries = None
        self.detail_override_title = None
        group_key = item.data(0, Qt.ItemDataRole.UserRole)
        entries = self.grouped_entries.get(group_key, [])
        self.populate_results_tree(entries, item.text(0))

    def resolve_rename_plan(self) -> tuple[list[tuple[Path, Path]], list[str]] | tuple[None, None]:
        source_text = self.find_input.text()
        target_text = self.replace_input.text()
        if not source_text:
            self.show_warning("请输入要替换的原字符串。")
            return None, None

        selected_paths = self.get_selected_paths()
        if not selected_paths:
            self.show_warning("请先选择要重命名的文件或文件夹。")
            return None, None

        return build_rename_plan(selected_paths, source_text, target_text)

    def get_selected_paths(self) -> list[Path]:
        return collect_selected_paths(self.results_tree)

    def toggle_select_current_results_by_kind(self, kind: str, checked: bool) -> None:
        if self.updating_select_all_checkboxes:
            return

        toggle_select_current_results_by_kind(self.results_tree, kind, checked)
        self.update_select_all_checkbox_state()

    def update_select_all_checkbox_state(self) -> None:
        self.updating_select_all_checkboxes = True
        update_select_all_checkbox_state(
            self.results_tree,
            self.select_all_folders_checkbox,
            self.select_all_files_checkbox,
        )
        self.updating_select_all_checkboxes = False

    def get_current_group_key(self) -> GroupKey | None:
        item = self.group_tree.currentItem()
        if item is None:
            return None
        return item.data(0, Qt.ItemDataRole.UserRole)

    def find_group_item(self, group_key: GroupKey | None) -> QTreeWidgetItem | None:
        return find_group_item(self.group_tree, group_key)

    def show_warning(self, message: str) -> None:
        QMessageBox.warning(self, "提示", message)
