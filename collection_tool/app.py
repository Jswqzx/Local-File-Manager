import sys

from PyQt6.QtWidgets import QApplication

from .ui.main_window import MainWindow


def run() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    window = MainWindow()
    app.main_window = window
    window.show()
    window.raise_()
    window.activateWindow()
    return app.exec()
