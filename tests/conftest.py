"""Shared fixtures: src on path, offscreen Qt app, example DBC path."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

DBC_PATH = os.path.join(ROOT, "tests", "data", "example.dbc")
DEMO_DBC_PATH = os.path.join(ROOT, "dbc", "demo.dbc")


@pytest.fixture(scope="session")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
