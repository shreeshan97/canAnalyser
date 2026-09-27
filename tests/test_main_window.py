"""GUI tests (offscreen): trace, DBC decode, filter, TX, clear, autoscroll."""
import time

import pytest
import can
from unittest import mock
from PySide6.QtCore import Qt

from main_window import COLUMNS, MainWindow
from tests.conftest import DBC_PATH


@pytest.fixture()
def win(qapp):
    w = MainWindow(backend="virtual", channel="pytest-gui")
    w.show()
    yield w
    w.stop()
    w.close()


def _pump(qapp, secs=0.6):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.02)


@pytest.mark.trace
def test_start_stop_and_status(win, qapp):
    assert win.bus is None
    win.start()
    assert win.bus is not None
    assert win.status_table.item(0, 2).text() == "ready"
    win.stop()
    assert win.bus is None
    assert win.status_table.item(0, 2).text() == "stopped"


@pytest.mark.trace
def test_rx_row_and_counts(win, qapp):
    win.view.setCurrentText("Raw")
    win.start()
    _pump(qapp, 0.3)
    peer = can.interface.Bus(interface="virtual", channel="pytest-gui",
                             receive_own_messages=False)
    try:
        peer.send(can.Message(arbitration_id=0x123, data=[1, 2],
                              is_extended_id=False))
        _pump(qapp)
        assert win.rx_count == 1
        assert win.table.rowCount() == 1
        assert win.table.item(0, 5).text() == "0x123"
        assert win.table.item(0, 8).text() == "01 02"
    finally:
        peer.shutdown()


@pytest.mark.decode
def test_dbc_decode_columns(win, qapp):
    assert win.dbc.load(DBC_PATH) == 2
    win.view.setCurrentText("Raw")
    win.start()
    _pump(qapp, 0.3)
    peer = can.interface.Bus(interface="virtual", channel="pytest-gui",
                             receive_own_messages=False)
    try:
        peer.send(can.Message(
            arbitration_id=291,
            data=[0x00, 0x19, 0x5A, 0, 0, 0, 0, 0], is_extended_id=False))
        _pump(qapp)
        row = win.table.rowCount() - 1
        cols = {COLUMNS[c]: win.table.item(row, c).text()
                for c in range(len(COLUMNS))}
        assert cols["Name"] == "EngineData"
        assert cols["Sender"] == "Engine"
        assert "RPM=800" in cols["Decoded"]
    finally:
        peer.shutdown()


@pytest.mark.tx
def test_manual_tx_appends_tx_row(win, qapp):
    win.start()
    _pump(qapp, 0.3)
    win.tx_id.setText("100")
    win.tx_dlc.setValue(1)
    win.tx_data.setText("AB")
    win.send_once()
    assert win.tx_count == 1
    # Own echo (is_rx=False on virtual, firmware echo on candle) is
    # suppressed by design — the local TX row already represents the send.
    _pump(qapp)
    assert win.rx_count == 0
    # A peer's frame still arrives as RX.
    peer = can.interface.Bus(interface="virtual", channel="pytest-gui",
                             receive_own_messages=False)
    try:
        peer.send(can.Message(arbitration_id=0x100, data=[0xAB],
                              is_extended_id=False))
        _pump(qapp)
        assert win.rx_count == 1
    finally:
        peer.shutdown()


@pytest.mark.trace
def test_filter_hides_and_restores(win, qapp):
    win.view.setCurrentText("Raw")
    win.start()
    _pump(qapp, 0.3)
    peer = can.interface.Bus(interface="virtual", channel="pytest-gui",
                             receive_own_messages=False)
    try:
        peer.send(can.Message(arbitration_id=0x123, data=[0],
                              is_extended_id=False))
        _pump(qapp)
        assert win.table.rowCount() == 1
        win.filter_edit.setText("ZZNOMATCH")
        assert win.table.isRowHidden(0)
        win.filter_edit.setText("123")
        assert not win.table.isRowHidden(0)
    finally:
        peer.shutdown()


@pytest.mark.trace
def test_clear_resets(win, qapp):
    win.view.setCurrentText("Raw")
    win.start()
    _pump(qapp, 0.3)
    peer = can.interface.Bus(interface="virtual", channel="pytest-gui",
                             receive_own_messages=False)
    try:
        peer.send(can.Message(arbitration_id=0x123, data=[0],
                              is_extended_id=False))
        _pump(qapp)
        assert win.table.rowCount() == 1
        win.clear()
        assert win.table.rowCount() == 0
        assert (win.rx_count, win.tx_count, win.err_count) == (0, 0, 0)
    finally:
        peer.shutdown()


@pytest.mark.ui
def test_autoscroll_toggle(win):
    assert win.autoscroll
    win.btn_autoscroll.setChecked(False)
    assert not win.autoscroll
    assert win.btn_autoscroll.text() == "Autoscroll: OFF"
    win.btn_autoscroll.setChecked(True)
    assert win.autoscroll


@pytest.mark.trace
def test_log_records_bus_open(win, qapp):
    win.start()
    assert any("bus open" in win.log_list.item(i).text()
               for i in range(win.log_list.count()))


class FailingBus:
    """Bus whose send always raises: simulates error-state hardware."""
    def send(self, msg, timeout=None):
        import can
        raise can.CanError("bus off")

    def shutdown(self):
        pass


@pytest.mark.failsafe
def test_failing_cyclic_auto_stops_without_modals(win, qapp, monkeypatch):
    # If a modal ever appears the test would hang; fail loudly instead.
    boom = AssertionError("modal popup during cyclic!")
    monkeypatch.setattr(
        "main_window.QMessageBox",
        mock.Mock(critical=mock.Mock(side_effect=boom),
                  information=mock.Mock(side_effect=boom),
                  warning=mock.Mock(side_effect=boom)))
    win.bus = FailingBus()
    win.tx_id.setText("100")
    win.tx_dlc.setValue(1)
    win.tx_data.setText("00")
    win.tx_interval.setValue(10)
    win.start_cyclic()
    _pump(qapp, 0.5)
    assert not win.cyclic.isActive()
    assert any("auto-stopped" in win.log_list.item(i).text()
               for i in range(win.log_list.count()))


@pytest.mark.failsafe
def test_failing_entry_auto_stops(win, qapp):
    win.bus = FailingBus()
    win.tx_id.setText("100")
    win.tx_dlc.setValue(1)
    win.tx_data.setText("00")
    win.add_manual_entry()
    win.start_all_entries()
    _pump(qapp, 0.5)
    entry = win.entries[0]
    assert entry["timer"] is None or not entry["timer"].isActive()
    assert entry.get("fails", 0) >= 3


@pytest.mark.ui
def test_default_and_minimum_size(win):
    assert (win.width(), win.height()) == (1280, 800)
    assert win.minimumWidth() == 1000
    assert win.minimumHeight() == 650


@pytest.mark.ui
def test_generator_inner_tabs(win):
    assert [win.gen_tabs.tabText(i) for i in range(win.gen_tabs.count())] == [
        "Manual", "DBC"]


@pytest.mark.ui
def test_theme_roundtrip_restores_light(win, qapp):
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication
    win.set_theme("dark")
    dark = QApplication.instance().palette().color(QPalette.Window).name()
    win.set_theme("light")
    light = QApplication.instance().palette().color(QPalette.Window).name()
    assert dark != light
    assert win.theme_mode == "light"


@pytest.mark.ui
def test_theme_repaints_bottom_tabs(win, qapp):
    """Stylesheet tab bars once kept rendering dark after switching to
    light (palette alone looked fine). Assert rendered pixels."""
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication
    win.resize(1280, 800)
    win.add_manual_entry()
    qapp.processEvents()
    QApplication.instance().processEvents()
    from theme import apply_theme
    apply_theme(QApplication.instance(), "dark")
    qapp.processEvents()
    apply_theme(QApplication.instance(), "light")
    qapp.processEvents()

    def brightness(x, y):
        c = QColor(win.grab().toImage().pixel(x, y))
        return (c.red() + c.green() + c.blue()) // 3

    assert brightness(640, 200) > 128  # trace area
    assert brightness(640, 620) > 128  # generator tabs (was stuck dark)
    assert brightness(640, 720) > 128  # entry table (was stuck dark)


@pytest.mark.entries
def test_add_manual_entry_and_send(win, qapp):
    win.start()
    _pump(qapp, 0.3)
    win.tx_id.setText("100")
    win.tx_dlc.setValue(1)
    win.tx_data.setText("AB")
    win.tx_interval.setValue(100)
    win.add_manual_entry()
    assert len(win.entries) == 1
    assert win.entry_table.rowCount() == 1
    assert win.entry_table.item(0, 1).text() == "Manual"
    assert win.entry_table.item(0, 2).text() == "0x100"
    win.entry_table.setCurrentCell(0, 0)
    win.send_selected_entry()
    assert win.tx_count == 1


@pytest.mark.entries
def test_add_dbc_entry_and_cyclic(win, qapp):
    assert win.dbc.load(DBC_PATH) == 2
    win.dbc_msg.clear()
    win.dbc_msg.addItems(win.dbc.message_names())
    win.dbc_msg.setEnabled(True)
    win._rebuild_signal_editors("ControlCmd")
    win.start()
    _pump(qapp, 0.3)
    win.dbc_msg.setCurrentText("ControlCmd")
    win.sig_editors["GearReq"].setValue(2)
    win.dbc_interval.setValue(50)
    win.add_dbc_entry()
    assert len(win.entries) == 1
    assert win.entry_table.item(0, 1).text() == "DBC"
    assert "GearReq" in win.entry_table.item(0, 4).text()
    win.start_all_entries()
    _pump(qapp, 0.4)
    tx_after_start = win.tx_count
    assert tx_after_start >= 2
    # Uncheck On -> timer stops, count freezes
    win.entry_table.item(0, 0).setCheckState(Qt.Unchecked)
    frozen = win.tx_count
    _pump(qapp, 0.3)
    assert win.tx_count == frozen
    win.stop_all_entries()
    win.entry_table.setCurrentCell(0, 0)
    win.remove_selected_entry()
    assert len(win.entries) == 0
    assert win.entry_table.rowCount() == 0


@pytest.mark.entries
def test_entry_interval_validation(win):
    win.tx_id.setText("100")
    win.tx_dlc.setValue(1)
    win.tx_data.setText("00")
    win.add_manual_entry()
    assert win.entries[0]["interval"] == 100
    win.entry_table.item(0, 5).setText("bogus")
    assert win.entry_table.item(0, 5).text() == "100"
    assert win.entries[0]["interval"] == 100
    win.entry_table.item(0, 5).setText("250")
    assert win.entries[0]["interval"] == 250
