"""GUI tests (offscreen): trace, DBC decode, filter, TX, clear, autoscroll."""
import time

import pytest
import can
from unittest import mock
from PySide6.QtCore import Qt

from main_window import COLUMNS, MainWindow
from tests.conftest import DBC_PATH, DEMO_DBC_PATH


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


@pytest.mark.tx
def test_tx_timers_are_precise(win):
    from PySide6.QtCore import Qt
    assert win.cyclic.timerType() == Qt.PreciseTimer
    assert win.dbc_cyclic.timerType() == Qt.PreciseTimer
    win.tx_id.setText("100")
    win.tx_dlc.setValue(1)
    win.tx_data.setText("00")
    win.add_manual_entry()
    assert win.man_entries.start_all() == 1
    try:
        assert win.man_entries.entries[0]["timer"].timerType() == \
            Qt.PreciseTimer
    finally:
        win.man_entries.stop_all()


@pytest.mark.trace
def test_driver_time_reaches_record(win, qapp):
    win.view.setCurrentText("Raw")
    win.start()
    _pump(qapp, 0.3)
    peer = can.interface.Bus(interface="virtual", channel="pytest-gui",
                             receive_own_messages=False)
    sniffer = can.interface.Bus(interface="virtual", channel="pytest-gui",
                                receive_own_messages=False)
    try:
        peer.send(can.Message(arbitration_id=0x123, data=[7],
                              is_extended_id=False))
        got = sniffer.recv(timeout=2.0)
        assert got is not None
        _pump(qapp)
        rec = next(r for r in win.records if r["arb_id"] == 0x123)
        assert rec["ts_bus"] == got.timestamp
        assert abs(rec["ts_local"] - rec["ts_bus"]) < 2.0
    finally:
        peer.shutdown()
        sniffer.shutdown()


@pytest.mark.trace
def test_trace_copy_selected_rows(win, qapp):
    from PySide6.QtCore import QItemSelectionModel
    from PySide6.QtWidgets import QAbstractItemView, QApplication

    from main_window import COLUMNS, copy_table_selection
    win.view.setCurrentText("Raw")
    for arb in (0x100, 0x101, 0x102):
        win._append({"timestamp": 0.0, "local_ts": 1758982341.0 + arb,
                     "channel": "ch", "direction": "RX", "extended": False,
                     "arb_id": arb, "dlc": 1, "data": bytes([arb & 0xFF])})
    qapp.processEvents()
    assert win.table.selectionMode() == QAbstractItemView.ExtendedSelection
    model = win.table.selectionModel()
    for r in range(3):
        model.select(win.table.model().index(r, 0),
                     QItemSelectionModel.Select | QItemSelectionModel.Rows)
    assert copy_table_selection(win.table) == 3
    lines = QApplication.clipboard().text().split("\n")
    assert len(lines) == 3
    first = lines[0].split("\t")
    assert len(first) == len(COLUMNS)
    assert first[COLUMNS.index("ID")] == "0x100"
    assert first[COLUMNS.index("RX/TX")] == "RX"
    assert lines[2].split("\t")[COLUMNS.index("ID")] == "0x102"


@pytest.mark.entries
def test_entry_copy_selected_row(win, qapp):
    from PySide6.QtWidgets import QApplication

    from main_window import copy_table_selection
    win.tx_id.setText("100")
    win.tx_dlc.setValue(1)
    win.tx_data.setText("AB")
    win.add_manual_entry()
    qapp.processEvents()
    win.man_entries.table.selectRow(0)
    assert copy_table_selection(win.man_entries.table) == 1
    cells = QApplication.clipboard().text().split("\t")
    assert len(cells) == len(win.man_entries.COLS)
    assert cells[1] == "Manual"
    assert cells[2] == "0x100"


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
def test_default_size(win):
    assert (win.width(), win.height()) == (1280, 950)


@pytest.mark.ui
def test_window_follows_cursor_screen(qapp, monkeypatch):
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication

    from main_window import MainWindow
    primary = mock.Mock()
    primary.geometry.return_value = QRect(0, 0, 1920, 1080)
    monkeypatch.setattr(QApplication, "screenAt",
                        mock.Mock(return_value=primary))
    w1 = MainWindow(backend="virtual", channel="pytest-cursor1")
    try:
        assert (w1.pos().x(), w1.pos().y()) == (200, 30)
    finally:
        w1.close()
    second = mock.Mock()
    second.geometry.return_value = QRect(1920, 0, 1920, 1080)
    monkeypatch.setattr(QApplication, "screenAt",
                        mock.Mock(return_value=second))
    w2 = MainWindow(backend="virtual", channel="pytest-cursor2")
    try:
        assert (w2.pos().x(), w2.pos().y()) == (2120, 30)
    finally:
        w2.close()


@pytest.mark.ui
def test_bottom_tabs_flat(win):
    assert [win.tabs.tabText(i) for i in range(win.tabs.count())] == [
        "Manual Gen", "DBC Gen", "CAN Status", "Log"]


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

    from main_window import COL_WIDTHS, FLEX_WIDTHS
    assert COL_WIDTHS == {"Index": 40, "RX/TX": 50, "Type": 50,
                         "Channel": 75, "Sender": 75, "ID": 70, "DLC": 40,
                         "Timestamp": 160, "Data": 220}
    assert FLEX_WIDTHS == {"Name": 140, "Comment": 130}
    hdr = win.table.horizontalHeader()
    data_c = COLUMNS.index("Data")
    assert hdr.sectionResizeMode(data_c) == QHeaderView.Fixed
    assert win.table.columnWidth(data_c) == 220
    dec_c = COLUMNS.index("Decoded")
    assert hdr.sectionResizeMode(dec_c) == QHeaderView.Stretch
    for name in ("Name", "Comment"):
        c = COLUMNS.index(name)
        assert hdr.sectionResizeMode(c) == QHeaderView.Interactive
        assert win.table.columnWidth(c) == FLEX_WIDTHS[name]
    for c, col in enumerate(COLUMNS):
        if col in ("Decoded", "Name", "Comment"):
            continue
        assert hdr.sectionResizeMode(c) == QHeaderView.Fixed
        assert win.table.columnWidth(c) == COL_WIDTHS[col]


@pytest.mark.ui
def test_entry_tables_fixed_budget(win):
    import can
    from main_window import REGION_PX
    for entries in (win.man_entries, win.dbc_entries):
        assert entries.table.height() == REGION_PX["TXTABLE"] == 143
        for i in range(6):
            msg = can.Message(arbitration_id=0x100 + i, data=[i],
                              is_extended_id=False)
            assert entries.add_entry("Manual", "", msg, 100)
        assert entries.table.height() == 143


@pytest.mark.ui
def test_entry_action_bar_above_table(win):
    from PySide6.QtWidgets import QSplitter
    for entries in (win.man_entries, win.dbc_entries):
        lay = entries.layout()
        assert lay.itemAt(0).layout() is not None
        assert lay.itemAt(0).layout().indexOf(entries.btn_add) >= 0
        assert lay.indexOf(entries.table) > 0
    assert isinstance(win.split, QSplitter)
    assert win.split.indexOf(win.table) == 0
    assert win.split.indexOf(win.tabs) == 1


@pytest.mark.ui
def test_autoscroll_after_timestamps(win):
    central = win.centralWidget().layout()
    top = central.itemAt(0).layout()
    top_widgets = [top.itemAt(i).widget() for i in range(top.count())]
    filt = central.itemAt(1).layout()
    order = [filt.itemAt(i).widget() for i in range(filt.count())]
    assert win.btn_autoscroll not in top_widgets
    assert order.index(win.btn_autoscroll) == order.index(win.ts_mode) + 1


@pytest.mark.ui
def test_rx_fills_remainder_no_gap(win, qapp):
    qapp.processEvents()
    filled = sum(win.split.sizes()) + win.split.handleWidth()
    assert abs(filled - win.split.height()) <= 2


@pytest.mark.ui
def test_splitter_per_tab_dock_sizes(win, qapp):
    from tests.conftest import DEMO_DBC_PATH
    win.load_dbc(DEMO_DBC_PATH)
    win.dbc_msg.setCurrentText("ManySignals")
    qapp.processEvents()
    win.tabs.setCurrentIndex(0)
    qapp.processEvents()
    man_dock = win.split.sizes()[1]
    assert man_dock == win._dock_need(0)
    assert man_dock < 300
    win.tabs.setCurrentIndex(1)
    qapp.processEvents()
    dbc_dock = win.split.sizes()[1]
    assert dbc_dock == win._dock_need(1)
    assert dbc_dock > man_dock
    total = sum(win.split.sizes())
    assert dbc_dock <= int(total * 0.65) + 1
    win.tabs.setCurrentIndex(0)
    qapp.processEvents()
    assert win.split.sizes()[1] == man_dock
    win.clear_dbc()
    qapp.processEvents()
    win.tabs.setCurrentIndex(1)
    qapp.processEvents()
    assert win.split.sizes()[1] == win._dock_need(1) < dbc_dock
    frozen = win.split.sizes()[1]
    win.tabs.setCurrentIndex(2)
    qapp.processEvents()
    assert win.split.sizes()[1] == frozen
    win.tabs.setCurrentIndex(3)
    qapp.processEvents()
    assert win.split.sizes()[1] == frozen


@pytest.mark.ui
def test_dlc_defaults_to_eight(win):
    assert win.tx_dlc.value() == 8
    assert win.tx_data.text() == "00 00 00 00 00 00 00 00"


@pytest.mark.ui
def test_dbc_signals_hidden_when_empty(win, qapp):
    assert win.dbc_sig_region.isHidden()
    assert win.dbc.load(DBC_PATH) == 2
    win._rebuild_signal_editors("ControlCmd")
    qapp.processEvents()
    assert not win.dbc_sig_region.isHidden()
    assert win.dbc_sig_grid.rowCount() > 0
    win._rebuild_signal_editors("")
    qapp.processEvents()
    assert win.dbc_sig_region.isHidden()


@pytest.mark.ui
def test_status_table_fixed_widths(win, qapp):
    from PySide6.QtWidgets import QHeaderView

    from main_window import STATUS_COLS, STATUS_WIDTHS
    assert STATUS_WIDTHS == {"Backend": 130, "Channel": 110, "State": 110,
                             "Rx": 82, "Tx": 82, "Err": 84}
    t = win.status_table
    qapp.processEvents()
    hdr = t.horizontalHeader()
    for c, col in enumerate(STATUS_COLS):
        assert hdr.sectionResizeMode(c) == QHeaderView.Fixed
        assert t.columnWidth(c) == STATUS_WIDTHS[col]
    assert t.width() == 600
    assert t.height() < 120
    win.rx_count, win.tx_count = 12345678, 87654321
    win.channel = "a-very-long-channel-name"
    win._status(force=True)
    qapp.processEvents()
    for c, col in enumerate(STATUS_COLS):
        assert t.columnWidth(c) == STATUS_WIDTHS[col]
    assert t.width() == 600
    assert t.horizontalScrollBar().maximum() == 0


@pytest.mark.trace
def test_timestamp_delta_is_per_id_inter_arrival(win):
    import re
    win.view.setCurrentText("Raw")
    win.ts_mode.setCurrentText("Delta")

    def rx(arb, at):
        win._append({"timestamp": 0.0, "local_ts": at,
                     "channel": "ch", "direction": "RX", "extended": False,
                     "arb_id": arb, "dlc": 1, "data": bytes([0])})
    ts = COLUMNS.index("Timestamp")
    t0 = 1758982341.0
    rx(0x123, t0)
    rx(0x124, t0 + 5.0)
    rx(0x123, t0 + 0.1)
    rx(0x123, t0 + 0.3005)
    got = [win.table.item(r, ts).text() for r in range(4)]
    assert all(re.fullmatch(r"\d+\.\d{6}", v) for v in got)
    assert got[0] == "0.000000"
    assert got[1] == "0.000000"
    assert got[2] == "0.100000"
    assert got[3] == "0.200500"


@pytest.mark.trace
def test_timestamp_delta_resets_on_clear(win):
    win.view.setCurrentText("Raw")
    win.ts_mode.setCurrentText("Delta")
    win._append({"timestamp": 0.0, "local_ts": 1758982341.0,
                 "channel": "ch", "direction": "RX", "extended": False,
                 "arb_id": 0x123, "dlc": 1, "data": bytes([0])})
    win.clear()
    win._append({"timestamp": 0.0, "local_ts": 1758982441.0,
                 "channel": "ch", "direction": "RX", "extended": False,
                 "arb_id": 0x123, "dlc": 1, "data": bytes([0])})
    ts = COLUMNS.index("Timestamp")
    assert win.table.item(0, ts).text() == "0.000000"


@pytest.mark.trace
def test_timestamp_absolute_is_wall_clock(win):
    import datetime
    import re
    win.view.setCurrentText("Raw")
    win.ts_mode.setCurrentText("Absolute")
    win._append({"timestamp": 12.5,
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
        assert dlg.minimumHeight() == 0
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
    monkeypatch.setattr("main_window.open_bus",
                        mock.Mock(side_effect=RuntimeError("no bus")))
    with pytest.raises(AssertionError):
        win.start()
    assert win.bus is None
    assert win.btn_start.isEnabled()
    assert not win.btn_stop.isEnabled()


@pytest.mark.dbc
def test_menu_load_dbc_actions_open_dialog(win, qapp, monkeypatch):
    from tests.conftest import DEMO_DBC_PATH
    monkeypatch.setattr("main_window.QFileDialog.getOpenFileName",
                        lambda *a, **k: (DEMO_DBC_PATH, ""))
    win.act_load_dbc.trigger()
    qapp.processEvents()
    assert win.dbc.loaded
    win.clear_dbc()
    qapp.processEvents()
    win.act_gen_load_dbc.trigger()
    qapp.processEvents()
    assert win.dbc.loaded


@pytest.mark.dbc
def test_dbc_toggle_button_flips_label_and_action(win, qapp, monkeypatch):
    monkeypatch.setattr("main_window.QFileDialog.getOpenFileName",
                        lambda *a, **k: (DEMO_DBC_PATH, ""))
    assert win.btn_dbc.text() == "Load DBC..."
    assert not win.act_clear_dbc.isEnabled()
    win.toggle_dbc()
    qapp.processEvents()
    assert win.dbc.loaded
    assert win.btn_dbc.text() == "Clear DBC"
    assert not win.act_load_dbc.isEnabled()
    assert win.act_clear_dbc.isEnabled()
    assert not win.act_gen_load_dbc.isEnabled()
    assert win.act_gen_clear_dbc.isEnabled()
    win.toggle_dbc()
    qapp.processEvents()
    assert not win.dbc.loaded
    assert win.btn_dbc.text() == "Load DBC..."
    assert win.act_load_dbc.isEnabled()
    assert not win.act_clear_dbc.isEnabled()
    win.toggle_dbc()
    qapp.processEvents()
    assert win.dbc.loaded
    assert win.btn_dbc.text() == "Clear DBC"


@pytest.mark.dbc
def test_clear_dbc_stops_and_deletes_dbc_entries(win, qapp):
    win.tx_id.setText("100")
    win.tx_dlc.setValue(1)
    win.tx_data.setText("00")
    win.add_manual_entry()
    win.load_dbc(DEMO_DBC_PATH)
    qapp.processEvents()
    win.add_dbc_entry()
    assert len(win.dbc_entries.entries) == 1
    assert win.dbc_entries.start_all() == 1
    win.clear_dbc()
    qapp.processEvents()
    assert not win.dbc.loaded
    assert win.lbl_dbc.text() == "no DBC"
    assert win.dbc_msg.count() == 0
    assert not win.dbc_msg.isEnabled()
    assert win.dbc_dlc.text() == "DLC: -"
    assert win.sig_editors == {}
    assert win.dbc_sig_region.isHidden()
    assert win.dbc_entries.entries == []
    assert win.dbc_entries.table.rowCount() == 0
    assert len(win.man_entries.entries) == 1
    win.load_dbc(DEMO_DBC_PATH)
    qapp.processEvents()
    assert win.dbc.loaded
    assert win.btn_dbc.text() == "Clear DBC"


@pytest.mark.dbc
def test_signal_editors_two_column_fixed(win, qapp):
    from main_window import GAP, REGION_PX
    win.tabs.setCurrentIndex(1)
    qapp.processEvents()
    win.load_dbc(DEMO_DBC_PATH)
    for name in ("ControlCmd", "EngineData", "ManySignals"):
        win.dbc_msg.setCurrentText(name)
        qapp.processEvents()
        signals = len(win.dbc.get_message(name).signals)
        cols = REGION_PX["SIGCOLS"]
        rows = (signals + cols - 1) // cols
        assert len(win.sig_editors) == signals
        for i, box in enumerate(win.sig_editors.values()):
            r, c, _rs, _cs = win.dbc_sig_grid.getItemPosition(
                win.dbc_sig_grid.indexOf(box))
            er, ec = divmod(i, cols)
            assert (r, c) == (er, 2 * ec + 1)
        assert win.dbc_sig_region.height() == (
            rows * REGION_PX["SIGROW"] + (rows - 1) * GAP)
