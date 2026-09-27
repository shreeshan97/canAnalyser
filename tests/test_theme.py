import pytest
"""Unit tests: theme switching (offscreen)."""
from PySide6.QtWidgets import QApplication

from theme import apply_theme, detect_system_theme


@pytest.mark.theme
def test_themes(qapp):
    app = QApplication.instance()
    assert apply_theme(app, "light") == "light"
    assert apply_theme(app, "dark") == "dark"
    assert apply_theme(app, "system") in ("light", "dark")


@pytest.mark.theme
def test_system_detection_matches_desktop(qapp):
    # This host runs Mint-Y-Dark-Grey: system must resolve dark here.
    assert detect_system_theme(QApplication.instance()) == "dark"


@pytest.mark.theme
def test_explicit_modes_ignore_desktop(qapp):
    app = QApplication.instance()
    assert apply_theme(app, "light") == "light"
    assert apply_theme(app, "dark") == "dark"
