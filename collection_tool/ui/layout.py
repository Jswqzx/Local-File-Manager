from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)


def build_main_layout(window: QWidget) -> QWidget:
    container = QWidget(window)
    root_layout = QVBoxLayout(container)
    root_layout.setContentsMargins(12, 8, 12, 10)
    root_layout.setSpacing(6)

    build_controls_layout(window, root_layout)
    build_action_row(window, root_layout)
    build_status_label(window, root_layout)
    build_results_splitter(window, root_layout)

    return container


def build_controls_layout(window: QWidget, root_layout: QVBoxLayout) -> None:
    controls = QGridLayout()
    controls.setHorizontalSpacing(8)
    controls.setVerticalSpacing(6)

    path_label = QLabel("目标路径")
    window.path_input = QLineEdit()
    window.path_input.setPlaceholderText("选择要扫描的目录")
    window.browse_button = QPushButton("选择路径")
    window.scan_button = QPushButton("扫描")

    regex_label = QLabel("正则筛选")
    window.regex_input = QLineEdit()
    window.regex_input.setPlaceholderText("支持 *.jpg 或 regex:^src|\\.py$")
    window.recursive_checkbox = QCheckBox("递归扫描子目录")
    window.recursive_checkbox.setChecked(True)

    controls.addWidget(path_label, 0, 0)
    controls.addWidget(window.path_input, 0, 1)
    controls.addWidget(window.browse_button, 0, 2)
    controls.addWidget(window.scan_button, 0, 3)
    controls.addWidget(regex_label, 1, 0)
    controls.addWidget(window.regex_input, 1, 1, 1, 2)
    controls.addWidget(window.recursive_checkbox, 1, 3)
    controls.setColumnStretch(1, 1)
    root_layout.addLayout(controls)


def build_action_row(window: QWidget, root_layout: QVBoxLayout) -> None:
    action_row = QHBoxLayout()
    action_row.setSpacing(6)
    window.refresh_button = QPushButton("刷新结果")
    window.delete_button = QPushButton("删除选中项")
    window.show_files_button = QPushButton("返回当前分组")
    window.url_params_button = QPushButton("文件更新")
    window.select_all_folders_checkbox = QCheckBox("全选文件夹")
    window.select_all_files_checkbox = QCheckBox("全选文件")
    window.find_input = QLineEdit()
    window.find_input.setPlaceholderText("原字符串")
    window.replace_input = QLineEdit()
    window.replace_input.setPlaceholderText("替换为")
    window.preview_button = QPushButton("预览替换")
    window.rename_button = QPushButton("替换文件名")

    action_row.addWidget(window.refresh_button)
    action_row.addWidget(window.delete_button)
    action_row.addWidget(window.show_files_button)
    action_row.addWidget(window.url_params_button)
    action_row.addWidget(window.select_all_folders_checkbox)
    action_row.addWidget(window.select_all_files_checkbox)
    action_row.addWidget(window.find_input)
    action_row.addWidget(window.replace_input)
    action_row.addWidget(window.preview_button)
    action_row.addWidget(window.rename_button)
    action_row.addStretch()
    root_layout.addLayout(action_row)


def build_status_label(window: QWidget, root_layout: QVBoxLayout) -> None:
    window.status_label = QLabel("请选择一个目录后开始扫描。")
    window.status_label.setStyleSheet("color: #555; margin: 0; padding: 0;")
    window.status_label.setContentsMargins(0, 0, 0, 0)
    window.status_label.setMaximumHeight(18)
    root_layout.addWidget(window.status_label)


def build_results_splitter(window: QWidget, root_layout: QVBoxLayout) -> None:
    splitter = QSplitter(Qt.Orientation.Horizontal)

    nav_panel = QWidget()
    nav_layout = QVBoxLayout(nav_panel)
    nav_layout.setContentsMargins(0, 0, 0, 0)
    nav_layout.setSpacing(6)
    nav_title = QLabel("分类导航")
    nav_title.setStyleSheet("font-weight: 600;")
    window.group_tree = QTreeWidget()
    window.group_tree.setColumnCount(2)
    window.group_tree.setHeaderLabels(["分组", "数量"])
    window.group_tree.setUniformRowHeights(True)
    nav_layout.addWidget(nav_title)
    nav_layout.addWidget(window.group_tree)

    detail_panel = QWidget()
    detail_layout = QVBoxLayout(detail_panel)
    detail_layout.setContentsMargins(0, 0, 0, 0)
    detail_layout.setSpacing(6)
    window.detail_title = QLabel("结果明细")
    window.detail_title.setStyleSheet("font-weight: 600;")
    window.results_tree = QTreeWidget()
    window.results_tree.setColumnCount(4)
    window.results_tree.setHeaderLabels(["名称", "类别", "文件类型", "相对路径"])
    window.results_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
    window.results_tree.setUniformRowHeights(True)
    window.results_tree.setAlternatingRowColors(True)
    detail_layout.addWidget(window.detail_title)
    detail_layout.addWidget(window.results_tree)

    splitter.addWidget(nav_panel)
    splitter.addWidget(detail_panel)
    splitter.setStretchFactor(0, 0)
    splitter.setStretchFactor(1, 1)
    splitter.setSizes([280, 860])
    root_layout.addWidget(splitter)
