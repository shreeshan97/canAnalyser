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


