"""GUI tests (offscreen): trace, DBC decode, filter, TX, clear, autoscroll."""
import time

import pytest
import can

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


def test_start_stop_and_status(win, qapp):
    assert win.bus is None
    win.start()
    assert win.bus is not None
    assert win.status_table.item(0, 2).text() == "ready"
    win.stop()
    assert win.bus is None
    assert win.status_table.item(0, 2).text() == "stopped"


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
        assert win.table.item(0, 9).text() == "01 02"
    finally:
        peer.shutdown()


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


def test_autoscroll_toggle(win):
    assert win.autoscroll
    win.btn_autoscroll.setChecked(False)
    assert not win.autoscroll
    assert win.btn_autoscroll.text() == "Autoscroll: OFF"
    win.btn_autoscroll.setChecked(True)
    assert win.autoscroll


def test_log_records_bus_open(win, qapp):
    win.start()
    assert any("bus open" in win.log_list.item(i).text()
               for i in range(win.log_list.count()))
