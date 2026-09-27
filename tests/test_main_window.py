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
    t = win.man_entries
    assert t.start_all() == 1
    _pump(qapp, 0.5)
    entry = t.entries[0]
    assert entry["timer"] is None or not entry["timer"].isActive()
    assert entry.get("fails", 0) >= 3


@pytest.mark.ui
def test_default_and_minimum_size(win):
    assert (win.width(), win.height()) == (1280, 950)
    assert (win.pos().x(), win.pos().y()) == (200, 30)
    assert win.minimumWidth() == 1000
    assert win.minimumHeight() == 650


@pytest.mark.ui
def test_generator_inner_tabs(win):
    assert [win.gen_tabs.tabText(i) for i in range(win.gen_tabs.count())] == [
        "Manual", "DBC"]


@pytest.mark.ui
def test_theme_repaints_bottom_tabs(win, qapp):
    """Stylesheet tab bars once kept rendering dark after switching to
    light (palette alone looked fine). Assert rendered pixels."""
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication
    win.resize(1280, 950)
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
    assert brightness(640, 760) > 128  # entry table (was stuck dark)


@pytest.mark.entries
def test_add_manual_entry_and_send(win, qapp):
    win.start()
    _pump(qapp, 0.3)
    win.tx_id.setText("100")
    win.tx_dlc.setValue(1)
    win.tx_data.setText("AB")
    win.tx_interval.setValue(100)
    win.add_manual_entry()
    t = win.man_entries
    assert len(t.entries) == 1
    assert t.table.rowCount() == 1
    assert t.table.item(0, 1).text() == "Manual"
    assert t.table.item(0, 2).text() == "0x100"
    t.table.setCurrentCell(0, 0)
    assert t.send_selected()
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
    t = win.dbc_entries
    assert len(t.entries) == 1
    assert t.table.item(0, 1).text() == "DBC"
    assert "GearReq" in t.table.item(0, 4).text()
    n = t.start_all()
    assert n == 1
    _pump(qapp, 0.4)
    tx_after_start = win.tx_count
    assert tx_after_start >= 2
    # Uncheck On -> timer stops, count freezes
    t.table.item(0, 0).setCheckState(Qt.Unchecked)
    frozen = win.tx_count
    _pump(qapp, 0.3)
    assert win.tx_count == frozen
    t.stop_all()
    t.table.setCurrentCell(0, 0)
    assert t.remove_selected()
    assert len(t.entries) == 0
    assert t.table.rowCount() == 0


@pytest.mark.entries
def test_entry_interval_validation(win):
    win.tx_id.setText("100")
    win.tx_dlc.setValue(1)
    win.tx_data.setText("00")
    win.add_manual_entry()
    t = win.man_entries
    assert t.entries[0]["interval"] == 100
    t.table.item(0, 5).setText("bogus")
    assert t.table.item(0, 5).text() == "100"
    assert t.entries[0]["interval"] == 100
    t.table.item(0, 5).setText("250")
    assert t.entries[0]["interval"] == 250


@pytest.mark.ui
def test_trace_column_pixels(win):
    from PySide6.QtWidgets import QHeaderView

    from main_window import COL_WIDTHS
    assert COL_WIDTHS == {"Index": 40, "RX/TX": 50, "Type": 50,
                         "Channel": 75, "Sender": 75, "ID": 70, "DLC": 40,
                         "Timestamp": 160, "Name": 140, "Decoded": 140,
                         "Comment": 130}
    hdr = win.table.horizontalHeader()
    data_c = COLUMNS.index("Data")
    assert hdr.sectionResizeMode(data_c) == QHeaderView.Stretch
    for c, col in enumerate(COLUMNS):
        if col == "Data":
            continue
        assert hdr.sectionResizeMode(c) == QHeaderView.Fixed
        assert win.table.columnWidth(c) == COL_WIDTHS[col]


@pytest.mark.ui
def test_entry_tables_share_height(win):
    assert win.man_entries.table.height() == 204
    assert win.dbc_entries.table.height() == 204


@pytest.mark.ui
def test_dlc_defaults_to_eight(win):
    assert win.tx_dlc.value() == 8
    assert win.tx_data.text() == "00 00 00 00 00 00 00 00"


@pytest.mark.ui
def test_dbc_signals_hidden_when_empty(win, qapp):
    # isHidden (not isVisible: ancestor DBC tab starts unselected)
    assert win.dbc_signals.isHidden()
    assert win.dbc.load(DBC_PATH) == 2
    win._rebuild_signal_editors("ControlCmd")
    qapp.processEvents()
    assert not win.dbc_signals.isHidden()
    assert win.dbc_sig_layout.rowCount() > 0
    win._rebuild_signal_editors("")
    qapp.processEvents()
    assert win.dbc_signals.isHidden()


@pytest.mark.ui
def test_status_table_hugs_content(win, qapp):
    t = win.status_table
    qapp.processEvents()
    base = t.width()
    assert base < 600  # airy card, not full tab width
    assert t.height() < 120  # header + single row, no phantom rows
    # Columns carry 50% extra air over content width (same formula as code).
    t.resizeColumnsToContents()
    expected = 2 * t.frameWidth() + sum(
        int(t.columnWidth(c) * 1.5) for c in range(t.columnCount()))
    assert base == expected
    win.rx_count, win.tx_count = 12345678, 87654321
    win._status()
    qapp.processEvents()
    assert t.width() >= base  # tracks growing counters
    assert t.horizontalScrollBar().maximum() == 0  # never clips


@pytest.mark.trace
def test_timestamp_delta_has_microseconds(win):
    import re
    win.view.setCurrentText("Raw")
    win.ts_mode.setCurrentText("Delta")
    win._append({"timestamp": 0.0, "local_ts": 1758982341.5,
                 "channel": "ch", "direction": "RX", "extended": False,
                 "arb_id": 0x123, "dlc": 1, "data": bytes([0])})
    win._append({"timestamp": 0.0, "local_ts": 1758982341.500123,
                 "channel": "ch", "direction": "RX", "extended": False,
                 "arb_id": 0x124, "dlc": 1, "data": bytes([0])})
    ts = COLUMNS.index("Timestamp")
    assert re.fullmatch(r"\d+\.\d{6}", win.table.item(0, ts).text())
    assert win.table.item(0, ts).text() == "0.000000"
    assert win.table.item(1, ts).text() == "0.000123"


@pytest.mark.trace
def test_timestamp_absolute_is_wall_clock(win):
    import datetime
    import re
    win.view.setCurrentText("Raw")
    win.ts_mode.setCurrentText("Absolute")
    win._append({"timestamp": 12.5,  # bus/uptime junk must not leak through
                 "local_ts": 1758982341.5,
                 "channel": "ch", "direction": "RX", "extended": False,
                 "arb_id": 0x123, "dlc": 1, "data": bytes([0])})
    ts = COLUMNS.index("Timestamp")
    got = win.table.item(0, ts).text()
    assert re.fullmatch(r"\d{2}:\d{2}:\d{2}\.\d{6}", got)
    assert got == datetime.datetime.fromtimestamp(1758982341.5).strftime(
        "%H:%M:%S.%f")


@pytest.mark.ui
def test_setup_dialog_compact_and_aligned(win, qapp):
    from PySide6.QtCore import Qt

    from main_window import SetupDialog
    dlg = SetupDialog(win, "virtual", "test", 500000, False)
    try:
        assert dlg.minimumWidth() == 460
        assert dlg.minimumHeight() == 300
        assert dlg.lbl_devices.alignment() & Qt.AlignTop
    finally:
        dlg.close()


@pytest.mark.ui
def test_bus_buttons_sync_with_state(win, qapp):
    assert win.btn_start.isEnabled()
    assert not win.btn_stop.isEnabled()
    assert win.btn_setup.isEnabled()
    assert win.act_start.isEnabled()
    assert not win.act_stop.isEnabled()
    win.start()
    _pump(qapp, 0.3)
    assert not win.btn_start.isEnabled()
    assert win.btn_stop.isEnabled()
    assert not win.btn_setup.isEnabled()
    assert not win.act_start.isEnabled()
    assert win.act_stop.isEnabled()
    win.stop()
    assert win.btn_start.isEnabled()
    assert not win.btn_stop.isEnabled()
    assert win.btn_setup.isEnabled()
    assert win.act_start.isEnabled()
    assert not win.act_stop.isEnabled()


@pytest.mark.failsafe
def test_failed_open_keeps_start_enabled(win, qapp, monkeypatch):
    boom = AssertionError("modal popup in test!")
    monkeypatch.setattr(
        "main_window.QMessageBox",
        mock.Mock(critical=mock.Mock(side_effect=boom),
                  information=mock.Mock(side_effect=boom),
                  warning=mock.Mock(side_effect=boom)))
    # Failure path must not pop modals and must leave stopped-state buttons.
    monkeypatch.setattr("main_window.open_bus",
                        mock.Mock(side_effect=RuntimeError("no bus")))
    with pytest.raises(AssertionError):
        win.start()
    assert win.bus is None
    assert win.btn_start.isEnabled()
    assert not win.btn_stop.isEnabled()
