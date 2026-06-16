"""Quant Chart - application entry point."""
import sys

from PyQt6.QtWidgets import QApplication

from core.styles import MAIN_STYLESHEET
from views.menu.menu import MenuWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Quant Chart")
    app.setStyleSheet(MAIN_STYLESHEET)
    window = MenuWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
