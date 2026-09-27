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
def test_dark_disabled_buttons_render_dimmer(qapp):
    """Regression: the dark palette once stamped full-bright colors into the
    Disabled group, so a greyed-out Start looked identical to enabled."""
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication, QPushButton
    app = QApplication.instance()
    apply_theme(app, "dark")
    qapp.processEvents()
    on = QPushButton("Start")
    off = QPushButton("Start")
    off.setEnabled(False)
    on.show()
    off.show()
    qapp.processEvents()

    def luminance(w):
        img = w.grab().toImage()
        tot = n = 0
        for x in range(0, img.width(), 4):
            for y in range(0, img.height(), 4):
                c = QColor(img.pixel(x, y))
                tot += c.red() + c.green() + c.blue()
                n += 1
        return tot / max(n, 1)

    assert luminance(off) < luminance(on) * 0.9
    on.close()
    off.close()
    apply_theme(app, "light")


