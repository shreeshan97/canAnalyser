"""Main window: RX trace + bottom tabs (Generator/Status/Log) + menubar."""
import datetime
import os
import time

import can
from PySide6.QtCore import QThread, QTimer, Qt
from PySide6.QtGui import QAction, QActionGroup, QIcon
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QCheckBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QMainWindow, QMessageBox, QPushButton, QSpinBox,
    QStatusBar, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)
from PySide6.QtWidgets import QAbstractItemView, QHeaderView

from can_backend import data_to_str, list_candle_devices, open_bus, parse_tx_fields
from dbc_manager import DbcError, DbcManager
from exporter import export_asc, export_csv
from rx_worker import RxWorker
from theme import apply_theme

VERSION = "v0.1.0"
COLUMNS = ["Index", "Timestamp", "Channel", "RX/TX", "Type", "ID",
           "Sender", "DLC", "Data", "Name", "Decoded", "Comment"]
# Exact fixed widths (px @1280 window); Data stretches over the remainder.
COL_WIDTHS = {"Index": 40, "RX/TX": 50, "Type": 50, "Channel": 75,
              "Sender": 75, "ID": 70, "DLC": 40, "Timestamp": 160,
              "Name": 140, "Decoded": 140, "Comment": 130}
MAX_ROWS = 5000


class SetupDialog(QDialog):
    def __init__(self, parent, backend, channel, bitrate, loop_back):
        super().__init__(parent)
        self.setWindowTitle("Setup Interface")
        self.setMinimumSize(460, 300)
        self.backend = QComboBox()
        self.backend.addItems(["candle", "virtual", "socketcan"])
        self.backend.setCurrentText(backend)
        self.channel = QLineEdit(str(channel))
        self.bitrate = QComboBox()
        for b in ["125000", "250000", "500000", "1000000"]:
            self.bitrate.addItem(b)
        self.bitrate.setCurrentText(str(bitrate))
        self.loop_back = QCheckBox("Silicon loop-back (candle, no wiring)")
        self.loop_back.setChecked(loop_back)
        self.loop_back.setToolTip("Off when TX/RX are physically wired together")
        form = QFormLayout(self)
        form.addRow("Backend", self.backend)
        form.addRow("Channel", self.channel)
        form.addRow("Bitrate", self.bitrate)
        form.addRow(self.loop_back)
        info = QLabel(list_candle_devices())
        info.setWordWrap(True)
        info.setAlignment(Qt.AlignTop)
        info.setMinimumHeight(48)
        self.lbl_devices = QLabel("Devices")
        self.lbl_devices.setAlignment(Qt.AlignTop)
        form.addRow(self.lbl_devices, info)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def values(self):
        return (self.backend.currentText(), self.channel.text(),
                int(self.bitrate.currentText()), self.loop_back.isChecked())


class EntryTable(QWidget):
    """One transmissions table + button bar, owned by a generator tab."""

    COLS = ["On", "Type", "ID", "Name", "Payload", "Interval (ms)"]
    MAX_ENTRIES = 16
    TABLE_HEIGHT = 204  # entry tables share one height in both tabs

    def __init__(self, parent, add_label, add_fn, transmit_fn, log_fn):
        super().__init__(parent)
        self._add_fn = add_fn
        self._transmit = transmit_fn
        self._log = log_fn
        self.entries: list[dict] = []
        self._updating = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setEditTriggers(
            QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setFixedHeight(self.TABLE_HEIGHT)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemChanged.connect(self._item_changed)
        lay.addWidget(self.table)
        lay.addSpacing(4)
        btns = QHBoxLayout()
        self.btn_add = QPushButton(add_label)
        self.btn_remove = QPushButton("Remove")
        self.btn_send = QPushButton("Send Selected Once")
        self.btn_start = QPushButton("Start All")
        self.btn_stop = QPushButton("Stop All")
        self.btn_add.clicked.connect(self._add_fn)
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_send.clicked.connect(self.send_selected)
        self.btn_start.clicked.connect(self.start_all)
        self.btn_stop.clicked.connect(self.stop_all)
        for b in (self.btn_add, self.btn_remove, self.btn_send,
                  self.btn_start, self.btn_stop):
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addLayout(btns)

    def add_entry(self, kind, name, msg, interval, payload=""):
        if len(self.entries) >= self.MAX_ENTRIES:
            return False
        entry = {"kind": kind, "name": name, "msg": msg,
                 "interval": interval, "enabled": True, "fails": 0,
                 "timer": None,
                 "payload": payload or data_to_str(msg.data)}
        self.entries.append(entry)
        row = self.table.rowCount()
        self._updating = True
        try:
            self.table.insertRow(row)
            on = QTableWidgetItem()
            on.setFlags(on.flags() | Qt.ItemIsUserCheckable)
            on.setCheckState(Qt.Checked)
            self.table.setItem(row, 0, on)
            self.table.setItem(row, 1, QTableWidgetItem(kind))
            self.table.setItem(
                row, 2, QTableWidgetItem(f"0x{msg.arbitration_id:X}"))
            self.table.setItem(row, 3, QTableWidgetItem(name))
            self.table.setItem(row, 4, QTableWidgetItem(entry["payload"]))
            self.table.setItem(row, 5, QTableWidgetItem(str(interval)))
        finally:
            self._updating = False
        return True

    def selected(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.entries):
            return row, self.entries[row]
        return None, None

    def remove_selected(self):
        row, entry = self.selected()
        if entry is None:
            return False
        self._timer_off(entry)
        del self.entries[row]
        self._updating = True
        try:
            self.table.removeRow(row)
        finally:
            self._updating = False
        return True

    def send_selected(self):
        _, entry = self.selected()
        if entry is not None:
            self._send_entry(entry)
            return True
        return False

    def start_all(self):
        n = 0
        for e in self.entries:
            if e["enabled"]:
                self._timer_on(e)
                n += 1
        return n

    def stop_all(self):
        for e in self.entries:
            self._timer_off(e)

    def _item_changed(self, item):
        if self._updating:
            return
        row = item.row()
        if not 0 <= row < len(self.entries):
            return
        entry = self.entries[row]
        if item.column() == 0:
            entry["enabled"] = item.checkState() == Qt.Checked
            if entry["enabled"]:
                self._timer_on(entry)
            else:
                self._timer_off(entry)
        elif item.column() == 5:
            try:
                iv = int(item.text())
                assert 10 <= iv <= 10000
            except (ValueError, AssertionError):
                self._updating = True
                try:
                    item.setText(str(entry["interval"]))
                finally:
                    self._updating = False
                return
            entry["interval"] = iv
            if entry["timer"] is not None and entry["timer"].isActive():
                entry["timer"].start(iv)

    def _timer_on(self, entry):
        if not entry["enabled"]:
            return
        if entry["timer"] is None:
            t = QTimer(self)
            t.timeout.connect(lambda e=entry: self._send_entry(e))
            entry["timer"] = t
        entry["timer"].start(entry["interval"])

    def _timer_off(self, entry):
        if entry["timer"] is not None and entry["timer"].isActive():
            entry["timer"].stop()

    def _send_entry(self, entry):
        if not entry["enabled"]:
            return
        if self._transmit(entry["msg"]):
            entry["fails"] = 0
        else:
            entry["fails"] += 1
            if entry["fails"] >= 3:
                self._timer_off(entry)
                self._log(
                    f"entry 0x{entry['msg'].arbitration_id:X} auto-stopped: "
                    "TX failing, bus may be in error state")


class MainWindow(QMainWindow):
    def __init__(self, backend="candle", channel=0, bitrate=500000,
                 loop_back=False):
        super().__init__()
        self.setWindowTitle(f"canAnalyser {VERSION}")
        self.resize(1280, 950)
        self.move(200, 30)
        self.setMinimumSize(1000, 650)
        icon = os.path.join(os.path.dirname(__file__), "..", "assets", "icon.png")
        if os.path.exists(icon):
            self.setWindowIcon(QIcon(icon))
        self.backend = backend
        self.channel = channel
        self.bitrate = bitrate
        self.loop_back = loop_back
        self.bus = None
        self.thread = None
        self.worker = None
        self.index = 0
        self._last_seen = {}  # (arb_id, direction) -> local_ts of previous frame
        self.agg = {}  # (arb_id, direction) -> row
        self.records: list[dict] = []
        self.rx_count = 0
        self.tx_count = 0
        self.err_count = 0
        self._tx_fail = {"manual": 0, "dbc": 0}  # per-source fail streaks
        self.autoscroll = True
        self.theme_mode = "system"
        self.dbc = DbcManager()
        self.sig_editors = {}
        self._tx_fail = {"manual": 0, "dbc": 0}
        self._last_decode_failed = False
        self._last_errstorm = 0.0
        self._build_ui()
        self._build_menus()
        self._build_timers()

    # ---- UI ----
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        top = QHBoxLayout()
        self.btn_start = QPushButton("Start")
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        self.btn_setup = QPushButton("Setup Interface...")
        self.btn_start.clicked.connect(self.start)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_setup.clicked.connect(self.setup_dialog)
        self.btn_autoscroll = QPushButton("Autoscroll: ON")
        self.btn_autoscroll.setCheckable(True)
        self.btn_autoscroll.setChecked(True)
        self.btn_autoscroll.toggled.connect(self._set_autoscroll)
        self.btn_dbc = QPushButton("Load DBC...")
        self.btn_dbc.clicked.connect(self.load_dbc)
        self.lbl_dbc = QLabel("no DBC")
        top.addWidget(self.btn_start)
        top.addWidget(self.btn_stop)
        top.addWidget(self.btn_setup)
        top.addWidget(self.btn_autoscroll)
        top.addWidget(self.btn_dbc)
        top.addWidget(self.lbl_dbc)
        top.addStretch(1)
        layout.addLayout(top)

        filt = QHBoxLayout()
        filt.addWidget(QLabel("View:"))
        self.view = QComboBox()
        self.view.addItems(["Aggregated", "Raw"])
        self.view.currentTextChanged.connect(self._rebuild_view)
        filt.addWidget(self.view)
        filt.addWidget(QLabel("Timestamps:"))
        self.ts_mode = QComboBox()
        self.ts_mode.addItems(["Delta", "Absolute"])
        filt.addWidget(self.ts_mode)
        filt.addStretch(1)
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.clicked.connect(self.clear)
        filt.addWidget(self.btn_clear)
        filt.addWidget(QLabel("Filter:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("e.g. 123 or RPM")
        self.filter_edit.textChanged.connect(self._apply_filter)
        filt.addWidget(self.filter_edit)
        layout.addLayout(filt)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        hdr = self.table.horizontalHeader()
        for c, col in enumerate(COLUMNS):
            if col == "Data":
                hdr.setSectionResizeMode(c, QHeaderView.Stretch)
            elif col in COL_WIDTHS:
                hdr.setSectionResizeMode(c, QHeaderView.Fixed)
                self.table.setColumnWidth(c, COL_WIDTHS[col])
            else:
                hdr.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("QTabBar::tab { width: 150px; }")
        self.tabs.addTab(self._generator_tab(), "Generator")
        self.tabs.addTab(self._status_tab(), "CAN Status")
        self.tabs.addTab(self._log_tab(), "Log")
        self.tabs.setMaximumHeight(350)
        layout.addWidget(self.tabs)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("idle — press Start")

    def _generator_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        self.gen_tabs = QTabWidget()
        self.gen_tabs.setStyleSheet("QTabBar::tab { width: 120px; }")
        man = QWidget()
        man_lay = QVBoxLayout(man)
        man_lay.setContentsMargins(0, 0, 0, 0)
        man_lay.setSpacing(4)
        man_lay.addWidget(self._manual_group())
        self.man_entries = EntryTable(
            self, "Add Manual", self.add_manual_entry,
            lambda msg: self._transmit(msg, quiet=True), self.log_msg)
        man_lay.addWidget(self.man_entries)
        dbc = QWidget()
        dbc_lay = QVBoxLayout(dbc)
        dbc_lay.setContentsMargins(0, 0, 0, 0)
        dbc_lay.setSpacing(4)
        dbc_lay.addWidget(self._dbc_group())
        self.dbc_entries = EntryTable(
            self, "Add DBC", self.add_dbc_entry,
            lambda msg: self._transmit(msg, quiet=True), self.log_msg)
        dbc_lay.addWidget(self.dbc_entries)
        self.gen_tabs.addTab(man, "Manual")
        self.gen_tabs.addTab(dbc, "DBC")
        lay.addWidget(self.gen_tabs)
        return w

    def _active_entries(self):
        return self.man_entries if self.gen_tabs.currentIndex() == 0 \
            else self.dbc_entries

    def _manual_group(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(QLabel("ID (Hex):"))
        self.tx_id = QLineEdit("123")
        self.tx_id.setMaximumWidth(80)
        lay.addWidget(self.tx_id)
        lay.addWidget(QLabel("DLC:"))
        self.tx_dlc = QSpinBox()
        self.tx_dlc.setRange(0, 8)
        self.tx_dlc.setValue(8)
        lay.addWidget(self.tx_dlc)
        lay.addWidget(QLabel("Data:"))
        self.tx_data = QLineEdit("00 00 00 00 00 00 00 00")
        lay.addWidget(self.tx_data, 1)
        lay.addWidget(QLabel("Interval ms:"))
        self.tx_interval = QSpinBox()
        self.tx_interval.setRange(10, 10000)
        self.tx_interval.setValue(100)
        lay.addWidget(self.tx_interval)
        self.btn_send = QPushButton("Send Once")
        self.btn_cyclic = QPushButton("Start Cyclic")
        self.btn_cyclic_stop = QPushButton("Stop Cyclic")
        self.btn_cyclic_stop.setEnabled(False)
        self.btn_send.clicked.connect(self.send_once)
        self.btn_cyclic.clicked.connect(self.start_cyclic)
        self.btn_cyclic_stop.clicked.connect(self.stop_cyclic)
        lay.addWidget(self.btn_send)
        lay.addWidget(self.btn_cyclic)
        lay.addWidget(self.btn_cyclic_stop)
        return w

    def _dbc_group(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        top = QHBoxLayout()
        lbl_msg = QLabel("Message:")
        lbl_msg.setAlignment(Qt.AlignVCenter)
        self.dbc_msg = QComboBox()
        self.dbc_msg.setEnabled(False)
        self.dbc_msg.currentTextChanged.connect(self._rebuild_signal_editors)
        top.addWidget(lbl_msg)
        top.addWidget(self.dbc_msg, 1)
        self.dbc_dlc = QLabel("DLC: -")
        self.dbc_dlc.setAlignment(Qt.AlignVCenter)
        top.addWidget(self.dbc_dlc)
        lbl_iv = QLabel("Interval ms:")
        lbl_iv.setAlignment(Qt.AlignVCenter)
        top.addWidget(lbl_iv)
        self.dbc_interval = QSpinBox()
        self.dbc_interval.setRange(10, 10000)
        self.dbc_interval.setValue(100)
        top.addWidget(self.dbc_interval)
        self.btn_dbc_send = QPushButton("Send Once")
        self.btn_dbc_cyclic = QPushButton("Start Cyclic")
        self.btn_dbc_cyclic_stop = QPushButton("Stop Cyclic")
        self.btn_dbc_cyclic_stop.setEnabled(False)
        self.btn_dbc_send.clicked.connect(self.dbc_send_once)
        self.btn_dbc_cyclic.clicked.connect(self.dbc_start_cyclic)
        self.btn_dbc_cyclic_stop.clicked.connect(self.dbc_stop_cyclic)
        top.addWidget(self.btn_dbc_send)
        top.addWidget(self.btn_dbc_cyclic)
        top.addWidget(self.btn_dbc_cyclic_stop)
        lay.addLayout(top)
        self.dbc_signals = QWidget()
        self.dbc_sig_layout = QFormLayout(self.dbc_signals)
        self.dbc_signals.setVisible(False)  # shown once signal rows exist
        lay.addWidget(self.dbc_signals)
        return w

    def _status_tab(self):
        self.status_table = QTableWidget(1, 6)
        self.status_table.setHorizontalHeaderLabels(
            ["Backend", "Channel", "State", "Rx", "Tx", "Err"])
        self.status_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.status_table.verticalHeader().setVisible(False)
        self.status_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        self.status_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.status_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        top.addWidget(self.status_table)
        top.addStretch(1)
        lay.addLayout(top)
        lay.addStretch(1)
        self._fit_status_table()  # hug content: no dead grid, no clipping
        return w

    def _fit_status_table(self):
        """Pin the status table's outer rect to its content width/height.

        Columns get 50% extra air (width only); height stays header + row.
        """
        t = self.status_table
        t.resizeColumnsToContents()
        w = 2 * t.frameWidth()
        for c in range(t.columnCount()):
            w += int(t.columnWidth(c) * 1.5)
        h = (t.horizontalHeader().sizeHint().height() + t.rowHeight(0)
             + 2 * t.frameWidth())
        t.setFixedSize(w, h)

    def _log_tab(self):
        self.log_list = QListWidget()
        self.log_list.setFont(self.font())
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.log_list)
        return w

    def _build_menus(self):
        m = self.menuBar()
        file_m = m.addMenu("&File")
        a = QAction("Load DBC...", self)
        a.triggered.connect(self.load_dbc)
        file_m.addAction(a)
        a = QAction("Export Trace (CSV)...", self)
        a.triggered.connect(self.export_csv)
        file_m.addAction(a)
        a = QAction("Export Trace (ASC)...", self)
        a.triggered.connect(self.export_asc)
        file_m.addAction(a)
        file_m.addSeparator()
        a = QAction("Exit", self)
        a.triggered.connect(self.close)
        file_m.addAction(a)

        meas = m.addMenu("&Measurement")
        self.act_start = QAction("Start", self)
        self.act_start.setShortcut("F5")
        self.act_start.triggered.connect(self.start)
        meas.addAction(self.act_start)
        self.act_stop = QAction("Stop", self)
        self.act_stop.setShortcut("Shift+F5")
        self.act_stop.triggered.connect(self.stop)
        meas.addAction(self.act_stop)

        view = m.addMenu("&View")
        self.act_autoscroll = QAction("Autoscroll", self, checkable=True)
        self.act_autoscroll.setChecked(True)
        self.act_autoscroll.toggled.connect(self._set_autoscroll)
        view.addAction(self.act_autoscroll)
        theme_m = view.addMenu("Theme")
        grp = QActionGroup(self)
        for mode in ("system", "light", "dark"):
            a = QAction(mode.capitalize(), self, checkable=True)
            a.setChecked(mode == "system")
            a.triggered.connect(lambda _c, mm=mode: self.set_theme(mm))
            grp.addAction(a)
            theme_m.addAction(a)
        a = QAction("Clear Trace", self)
        a.triggered.connect(self.clear)
        view.addAction(a)

        trace = m.addMenu("&Trace")
        a = QAction("Clear", self)
        a.triggered.connect(self.clear)
        trace.addAction(a)
        a = QAction("Focus Filter", self)
        a.setShortcut("Ctrl+F")
        a.triggered.connect(lambda: self.filter_edit.setFocus())
        trace.addAction(a)

        gen = m.addMenu("&Generator")
        a = QAction("Manual: Send Once", self)
        a.triggered.connect(self.send_once)
        gen.addAction(a)
        self.act_man_cyc = QAction("Manual: Start Cyclic", self)
        self.act_man_cyc.triggered.connect(self.toggle_manual_cyclic)
        gen.addAction(self.act_man_cyc)
        a = QAction("DBC: Send Once", self)
        a.triggered.connect(self.dbc_send_once)
        gen.addAction(a)
        self.act_dbc_cyc = QAction("DBC: Start Cyclic", self)
        self.act_dbc_cyc.triggered.connect(self.toggle_dbc_cyclic)
        gen.addAction(self.act_dbc_cyc)
        gen.addSeparator()
        a = QAction("Add Manual Entry", self)
        a.triggered.connect(self.add_manual_entry)
        gen.addAction(a)
        a = QAction("Add DBC Entry", self)
        a.triggered.connect(self.add_dbc_entry)
        gen.addAction(a)
        a = QAction("Send Selected Entry Once", self)
        a.triggered.connect(lambda: self._active_entries().send_selected())
        gen.addAction(a)
        a = QAction("Start All Entries (this tab)", self)
        a.triggered.connect(self._start_all_visible)
        gen.addAction(a)
        a = QAction("Stop All Entries (this tab)", self)
        a.triggered.connect(self._stop_all_visible)
        gen.addAction(a)
        self._sync_bus_buttons()  # initial stopped state incl. menu acts

    def _start_all_visible(self):
        if self.bus is None:
            QMessageBox.information(self, "TX", "Press Start first.")
            return
        n = self._active_entries().start_all()
        self.log_msg(f"cyclic started for {n} entries")

    def _stop_all_visible(self):
        self._active_entries().stop_all()

        help_m = m.addMenu("&Help")
        a = QAction("About", self)
        a.triggered.connect(self.about)
        help_m.addAction(a)

    def _build_timers(self):
        self.cyclic = QTimer(self)
        self.cyclic.timeout.connect(self._manual_cyclic_tick)
        self.dbc_cyclic = QTimer(self)
        self.dbc_cyclic.timeout.connect(self._dbc_cyclic_tick)

    def _manual_cyclic_tick(self):
        msg = self._current_tx()
        if msg is None:
            self.stop_cyclic()
            return
        self._note_cyclic_result(self._transmit(msg, quiet=True),
                                 self.stop_cyclic, "Manual", "manual")

    def _dbc_cyclic_tick(self):
        msg = self._current_dbc_tx(quiet=True)
        if msg is None:
            self.dbc_stop_cyclic()
            return
        self._note_cyclic_result(self._transmit(msg, quiet=True),
                                 self.dbc_stop_cyclic, "DBC", "dbc")

    # ---- log ----
    def log_msg(self, text: str):
        self.log_list.addItem(f"{time.strftime('%H:%M:%S')}  {text}")
        self.log_list.scrollToBottom()

    # ---- theme ----
    def set_theme(self, mode: str):
        from PySide6.QtWidgets import QApplication
        self.theme_mode = mode
        eff = apply_theme(QApplication.instance(), mode)
        self.log_msg(f"theme: {eff}")

    def about(self):
        from PySide6 import __version__ as pyside_v
        from PySide6.QtCore import qVersion
        QMessageBox.about(
            self, "About canAnalyser",
            f"<b>canAnalyser {VERSION}</b><br>"
            "CAN bus receiver + multi-message TX generator.<br><br>"
            f"PySide {pyside_v}, Qt {qVersion()}<br>"
            "Backend: python-can (candle FYSETC UCAN / virtual / socketcan), "
            "DBC via cantools.<br>"
            "License: GPL-2.0.")

    # ---- autoscroll ----
    def _set_autoscroll(self, on: bool):
        self.autoscroll = on
        self.btn_autoscroll.setChecked(on)
        self.btn_autoscroll.setText(f"Autoscroll: {'ON' if on else 'OFF'}")
        self.act_autoscroll.setChecked(on)

    # ---- DBC ----
    def load_dbc(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load DBC file", "", "DBC files (*.dbc);;All files (*)")
        if not path:
            return
        try:
            n = self.dbc.load(path)
        except DbcError as e:
            QMessageBox.critical(self, "DBC", str(e))
            self.log_msg(f"DBC load failed: {e}")
            return
        names = self.dbc.message_names()
        self.dbc_msg.clear()
        self.dbc_msg.addItems(names)
        self.dbc_msg.setEnabled(bool(names))
        self.lbl_dbc.setText(f"{os.path.basename(path)} ({n} msgs)")
        self.log_msg(f"DBC loaded: {path} ({n} messages)")
        self._rebuild_signal_editors(self.dbc_msg.currentText())

    def _rebuild_signal_editors(self, name: str):
        while self.dbc_sig_layout.rowCount():
            self.dbc_sig_layout.removeRow(0)
        self.sig_editors = {}
        self.dbc_signals.setVisible(False)  # collapse gap when nothing to edit
        if not name:
            return
        msg = self.dbc.get_message(name)
        if msg is None:
            return
        self.dbc_dlc.setText(f"DLC: {msg.length}")
        for s in msg.signals:
            lo = float(s.minimum) if s.minimum is not None else -1e9
            hi = float(s.maximum) if s.maximum is not None else 1e9
            box = QDoubleSpinBox()
            box.setRange(lo, hi)
            box.setDecimals(3)
            box.setValue(max(lo, min(hi, 0.0)))
            unit = f" [{s.unit}]" if s.unit else ""
            self.dbc_sig_layout.addRow(f"{s.name}{unit}:", box)
            self.sig_editors[s.name] = box
        self.dbc_signals.setVisible(bool(self.sig_editors))

    # ---- bus control ----
    def channel_label(self):
        return f"{self.backend}-ch{self.channel}"

    def _sync_bus_buttons(self):
        """Grey out Start/Setup (and menu Start) while running, Stop (and
        menu Stop) while stopped."""
        running = self.bus is not None
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.btn_setup.setEnabled(not running)
        if hasattr(self, "act_start"):
            self.act_start.setEnabled(not running)
            self.act_stop.setEnabled(running)

    def start(self):
        if self.bus is not None:
            return
        try:
            self.bus = open_bus(self.backend, self.channel,
                                self.bitrate, self.loop_back)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Bus error", str(e))
            self.log_msg(f"bus open failed: {e}")
            return
        self.thread = QThread(self)
        self.worker = RxWorker(self.bus, self.channel_label())
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.frame.connect(self.on_frame)
        self.worker.error.connect(self.log_msg)
        self.worker.err_frame.connect(self.on_err_frame)
        self.worker.finished.connect(self.thread.quit)
        self.thread.start()
        self._sync_bus_buttons()
        self.log_msg(
            f"bus open: {self.backend} ch={self.channel} "
            f"{self.bitrate}bps loop_back={self.loop_back}")
        self._status()

    def stop(self):
        self.stop_cyclic()
        self.dbc_stop_cyclic()
        self.man_entries.stop_all()
        self.dbc_entries.stop_all()
        if self.worker:
            self.worker.stop()
        if self.thread:
            self.thread.quit()
            self.thread.wait(2000)
        self.thread = self.worker = None
        if self.bus:
            try:
                self.bus.shutdown()
            except Exception:  # noqa: BLE001
                pass
        self.bus = None
        self._sync_bus_buttons()
        self.log_msg("bus closed")
        self._status(prefix="stopped — ")

    def closeEvent(self, event):  # noqa: N802
        self.stop()
        super().closeEvent(event)

    def setup_dialog(self):
        if self.bus is not None:
            QMessageBox.information(self, "Setup", "Stop first, then change setup.")
            return
        dlg = SetupDialog(self, self.backend, self.channel,
                          self.bitrate, self.loop_back)
        if dlg.exec() == QDialog.Accepted:
            b, ch, br, lb = dlg.values()
            self.backend = b
            self.channel = int(ch) if ch.isdigit() and b == "candle" else ch
            self.bitrate = br
            self.loop_back = lb

    # ---- RX path ----
    def _matches_rec(self, r: dict) -> bool:
        f = self.filter_edit.text().strip().lower()
        if not f:
            return True
        hay = " ".join(str(r.get(k, "")) for k in
                       ("id", "data", "name", "decoded", "sender")).lower()
        return f in hay or f in f"{r.get('arb_id', 0):x}"

    def on_frame(self, fr: dict):
        self._append(fr)

    def on_err_frame(self, count=1):
        self.err_count += count
        now = time.monotonic()
        if now - self._last_errstorm > 1.0:
            self._last_errstorm = now
            self.log_msg(f"error frames on bus (total ERR={self.err_count})")
        self._status()

    def _status(self, prefix=""):
        self.statusBar().showMessage(
            f"{prefix}RX={self.rx_count} TX={self.tx_count} ERR={self.err_count}")
        state = "ready" if self.bus else "stopped"
        for c, v in enumerate([self.backend, str(self.channel), state,
                               str(self.rx_count), str(self.tx_count),
                               str(self.err_count)]):
            self.status_table.setItem(0, c, QTableWidgetItem(v))
        self._fit_status_table()  # track growing counters, never clip

    def _decode_info(self, arb_id, data: bytes):
        sender = self.dbc.sender_of(arb_id)
        name = self.dbc.name_of(arb_id)
        sig = self.dbc.decode(arb_id, data)
        if sig is None and not name:
            self._last_decode_failed = False
            return sender, name, ""
        if sig is None:
            self._last_decode_failed = True
            return sender, name, ""
        self._last_decode_failed = False
        return sender, name, DbcManager.fmt_signals(sig)

    def _append(self, fr: dict):
        local = fr.get("local_ts") or fr["timestamp"] or time.time()
        key = (fr["arb_id"], fr["direction"])
        prev = self._last_seen.get(key)
        self._last_seen[key] = local
        if self.ts_mode.currentText() == "Delta":
            # Per-ID inter-arrival: gap since the previous frame with the
            # same ID + direction. First sighting reads 0 (no interval yet).
            ts_str = f"{(local - prev) if prev is not None else 0.0:.6f}"
        else:
            ts_str = datetime.datetime.fromtimestamp(local).strftime(
                "%H:%M:%S.%f")
        typ = "EXT." if fr["extended"] else "STD."
        id_str = f"0x{fr['arb_id']:X}"
        data = bytes(fr["data"])
        data_str = data_to_str(data)
        sender, name, decoded = self._decode_info(fr["arb_id"], data)
        if not sender:
            sender = fr["channel"]
        if self._last_decode_failed:
            self.log_msg(f"decode failed: {id_str} len={len(data)}")
        rec = {"index": self.index + 1, "timestamp": ts_str,
               "channel": fr["channel"],
               "rx_tx": fr["direction"], "type": typ, "id": id_str,
               "sender": sender, "name": name, "dlc": str(fr["dlc"]),
               "data": data_str, "decoded": decoded, "comment": "",
               "ts_bus": fr["timestamp"] or 0.0, "ts_local": local,
               "direction": fr["direction"], "arb_id": fr["arb_id"],
               "data_bytes": data}
        if not self._matches_rec(rec):
            return
        self.records.append(rec)
        if len(self.records) > MAX_ROWS:
            self.records.pop(0)
        if fr["direction"] == "RX":
            self.rx_count += 1
        else:
            self.tx_count += 1
        key = (fr["arb_id"], fr["direction"])
        if self.view.currentText() == "Aggregated" and key in self.agg:
            self._set_row(self.agg[key], rec)
        else:
            row = self.table.rowCount()
            if row >= MAX_ROWS:
                self.table.removeRow(0)
                self.agg = {k: v - 1 for k, v in self.agg.items()}
                row = MAX_ROWS - 1
            self.index += 1
            rec["index"] = self.index
            self.table.insertRow(row)
            self._set_row(row, rec)
            if self.view.currentText() == "Aggregated":
                self.agg[key] = row
        if self.autoscroll:
            self.table.scrollToBottom()
        self._status()

    def _set_row(self, row, rec):
        for c, col in enumerate(COLUMNS):
            key = col.lower().replace("/", "_")
            self.table.setItem(row, c, QTableWidgetItem(str(rec.get(key, ""))))
        self.table.setRowHidden(row, False)

    def _apply_filter(self):
        # Re-evaluate hiding per table row against record content.
        for row in range(self.table.rowCount()):
            cells = [self.table.item(row, c).text() if self.table.item(row, c) else ""
                     for c in range(len(COLUMNS))]
            id_txt = cells[5]
            try:
                arb = int(id_txt.replace("0x", ""), 16)
            except ValueError:
                arb = -1
            probe = {"arb_id": arb, "id": id_txt, "data": cells[8],
                     "name": cells[9], "decoded": cells[10], "sender": cells[6]}
            self.table.setRowHidden(row, not self._matches_rec(probe))

    def _rebuild_view(self):
        self.agg.clear()
        self.table.setRowCount(0)

    def clear(self):
        self.table.setRowCount(0)
        self.agg.clear()
        self.records.clear()
        self.index = 0
        self._last_seen.clear()
        self.rx_count = self.tx_count = self.err_count = 0
        self._tx_fail = {"manual": 0, "dbc": 0}
        self._status()

    # ---- TX path (manual) ----
    def _current_tx(self):
        try:
            arb_id, data = parse_tx_fields(
                self.tx_id.text(), self.tx_dlc.value(), self.tx_data.text())
        except ValueError as e:
            QMessageBox.warning(self, "TX", f"Bad TX field: {e}")
            return None
        return can.Message(arbitration_id=arb_id, data=data,
                           is_extended_id=arb_id > 0x7FF)

    def _transmit(self, msg: can.Message, quiet=False, source="manual") -> bool:
        """Send one frame. Timer-driven callers must pass quiet=True so a
        failing bus can never stack modal dialogs over the Stop button."""
        if self.bus is None:
            if not quiet:
                QMessageBox.information(self, "TX", "Press Start first.")
            return False
        try:
            self.bus.send(msg)
        except Exception as e:  # noqa: BLE001
            self._tx_fail[source] = self._tx_fail.get(source, 0) + 1
            self.log_msg(f"TX failed ({self._tx_fail[source]}x): {e}")
            if not quiet:
                QMessageBox.critical(self, "TX failed", str(e))
            return False
        self._tx_fail[source] = 0
        self._append({"timestamp": time.time(), "local_ts": time.time(),
                      "channel": self.channel_label(),
                      "direction": "TX", "extended": msg.is_extended_id,
                      "arb_id": msg.arbitration_id, "dlc": len(msg.data),
                      "data": bytes(msg.data)})
        return True

    def _note_cyclic_result(self, ok: bool, stop_fn, label: str, source: str):
        if ok:
            return
        if self._tx_fail.get(source, 0) >= 3:
            stop_fn()
            self.log_msg(f"{label} cyclic auto-stopped: TX failing, "
                         "bus may be in error state")
            self._status()

    def send_once(self):
        msg = self._current_tx()
        if msg is not None:
            self._transmit(msg)

    def start_cyclic(self):
        self.cyclic.start(self.tx_interval.value())
        self.btn_cyclic.setEnabled(False)
        self.btn_cyclic_stop.setEnabled(True)
        self.act_man_cyc.setText("Manual: Stop Cyclic")

    def stop_cyclic(self):
        if self.cyclic.isActive():
            self.cyclic.stop()
        self.btn_cyclic.setEnabled(True)
        self.btn_cyclic_stop.setEnabled(False)
        self.act_man_cyc.setText("Manual: Start Cyclic")

    def toggle_manual_cyclic(self):
        if self.cyclic.isActive():
            self.stop_cyclic()
        else:
            self.start_cyclic()

    # ---- TX path (DBC) ----
    def _current_dbc_tx(self, quiet=False):
        name = self.dbc_msg.currentText()
        if not name:
            if not quiet:
                QMessageBox.information(self, "DBC TX", "Load a DBC file first.")
            return None
        values = {sn: box.value() for sn, box in self.sig_editors.items()}
        try:
            arb_id, raw = self.dbc.encode(name, values)
        except DbcError as e:
            if not quiet:
                QMessageBox.warning(self, "DBC TX", str(e))
            else:
                self.log_msg(f"DBC TX encode failed: {e}")
            return None
        return can.Message(arbitration_id=arb_id, data=list(raw),
                           is_extended_id=arb_id > 0x7FF)

    def dbc_send_once(self):
        msg = self._current_dbc_tx()
        if msg is not None:
            self._transmit(msg)

    def dbc_start_cyclic(self):
        if not self.dbc_msg.currentText():
            QMessageBox.information(self, "DBC TX", "Load a DBC file first.")
            return
        self.dbc_cyclic.start(self.dbc_interval.value())
        self.btn_dbc_cyclic.setEnabled(False)
        self.btn_dbc_cyclic_stop.setEnabled(True)
        self.act_dbc_cyc.setText("DBC: Stop Cyclic")

    def dbc_stop_cyclic(self):
        if self.dbc_cyclic.isActive():
            self.dbc_cyclic.stop()
        self.btn_dbc_cyclic.setEnabled(True)
        self.btn_dbc_cyclic_stop.setEnabled(False)
        self.act_dbc_cyc.setText("DBC: Start Cyclic")

    def toggle_dbc_cyclic(self):
        if self.dbc_cyclic.isActive():
            self.dbc_stop_cyclic()
        else:
            self.dbc_start_cyclic()

    # ---- multi-message entry table ----
    MAX_ENTRIES = 16

    def add_manual_entry(self):
        msg = self._current_tx()
        if msg is None:
            return
        if self.man_entries.add_entry(
                "Manual", "", msg, self.tx_interval.value()):
            self.log_msg(f"manual entry added: {hex(msg.arbitration_id)} "
                         f"@{self.tx_interval.value()}ms")
        else:
            QMessageBox.information(self, "Entries", "Entry table is full (16).")

    def add_dbc_entry(self):
        name = self.dbc_msg.currentText()
        if not name:
            QMessageBox.information(self, "DBC", "Load a DBC file first.")
            return
        msg = self._current_dbc_tx()
        if msg is None:
            return
        summary = DbcManager.fmt_signals(
            {sn: box.value() for sn, box in self.sig_editors.items()})
        if self.dbc_entries.add_entry(
                "DBC", name, msg, self.dbc_interval.value(), payload=summary):
            self.log_msg(f"DBC entry added: {name} "
                         f"@{self.dbc_interval.value()}ms")
        else:
            QMessageBox.information(self, "Entries", "Entry table is full (16).")

    # ---- export ----
    def _filtered_records(self):
        return [r for r in self.records if self._matches_rec(r)]

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export trace as CSV", "trace.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            n = export_csv(path, COLUMNS, self._filtered_records())
        except OSError as e:
            QMessageBox.critical(self, "Export", str(e))
            return
        self.log_msg(f"exported {n} rows to {path} (CSV)")
        self._status()

    def export_asc(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export trace as ASC", "trace.asc", "ASC (*.asc)")
        if not path:
            return
        try:
            n = export_asc(path, self._filtered_records())
        except OSError as e:
            QMessageBox.critical(self, "Export", str(e))
            return
        self.log_msg(f"exported {n} frames to {path} (ASC)")
        self._status()
