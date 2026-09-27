"""Light/dark/system theme via Fusion palette (no per-widget stylesheets)."""
import os
import shutil
import subprocess

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette, QColor
from PySide6.QtCore import Qt

_cached_system = None


def _gtk_theme_is_dark() -> bool | None:
    """Ask the desktop (Cinnamon/MATE/GNOME) which GTK theme is active.
    Returns True/False, or None if undetectable."""
    global _cached_system
    env = os.environ.get("GTK_THEME", "")
    if env:
        return "dark" in env.lower()
    if shutil.which("gsettings") is None:
        return None
    keys = ["org.cinnamon.desktop.interface",
            "org.mate.interface",
            "org.gnome.desktop.interface"]
    for schema in keys:
        try:
            out = subprocess.run(
                ["gsettings", "get", schema, "gtk-theme"],
                capture_output=True, text=True, timeout=3).stdout.lower()
            if out.strip().strip("'"):
                return "dark" in out
        except (OSError, subprocess.SubprocessError):
            continue
    try:
        out = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
            capture_output=True, text=True, timeout=3).stdout.lower()
        if "prefer-dark" in out:
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def detect_system_theme(app: QApplication) -> str:
    """Best-effort OS theme: Qt hint first, desktop GTK theme as fallback."""
    scheme = app.styleHints().colorScheme()
    if scheme == Qt.ColorScheme.Dark:
        return "dark"
    if scheme == Qt.ColorScheme.Light:
        return "light"
    # Unknown (e.g. platform theme stripped so our palette wins) -> ask desktop.
    is_dark = _gtk_theme_is_dark()
    if is_dark is not None:
        return "dark" if is_dark else "light"
    return "light"


def apply_theme(app: QApplication, mode: str) -> str:
    """mode: system|light|dark. Returns effective mode."""
    app.setStyle("Fusion")
    effective = detect_system_theme(app) if mode == "system" else mode
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
    # Widgets carrying a stylesheet (our constant-width tab bars) do not
    # reliably repaint on a bare palette swap: a subtree can keep rendering
    # the old theme (seen: bottom tabs stuck dark in light mode). Force a
    # full unpolish/polish pass so every widget picks up the new palette.
    for widget in app.allWidgets():
        try:
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()
        except (RuntimeError, AttributeError):
            continue
    return effective
