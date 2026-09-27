"""Light/dark/system theme via Fusion palette (no per-widget stylesheets)."""
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette, QColor
from PySide6.QtCore import Qt


def apply_theme(app: QApplication, mode: str) -> str:
    """mode: system|light|dark. Returns effective mode."""
    app.setStyle("Fusion")
    if mode == "system":
        scheme = app.styleHints().colorScheme()
        effective = "dark" if scheme == Qt.ColorScheme.Dark else "light"
    else:
        effective = mode
    if effective == "dark":
        dark = QPalette()
        dark.setColor(QPalette.Window, QColor(53, 53, 53))
        dark.setColor(QPalette.WindowText, Qt.white)
        dark.setColor(QPalette.Base, QColor(35, 35, 35))
        dark.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
        dark.setColor(QPalette.Text, Qt.white)
        dark.setColor(QPalette.Button, QColor(53, 53, 53))
        dark.setColor(QPalette.ButtonText, Qt.white)
        dark.setColor(QPalette.Highlight, QColor(42, 130, 218))
        dark.setColor(QPalette.HighlightedText, Qt.white)
        app.setPalette(dark)
    else:
        app.setPalette(app.style().standardPalette())
    return effective
