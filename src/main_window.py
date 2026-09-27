"""Main window: RX trace + bottom tabs (Generator/Status/Log) + menubar."""
import os
import time

import can
from PySide6.QtCore import QThread, QTimer, Qt
from PySide6.QtGui import QAction, QActionGroup, QIcon
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QCheckBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QMainWindow, QMessageBox, QPushButton, QSpinBox,
    QSplitter, QStatusBar, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from can_backend import data_to_str, list_candle_devices, open_bus, parse_tx_fields
from dbc_manager import DbcError, DbcManager
from exporter import export_asc, export_csv
from rx_worker import RxWorker
from theme import apply_theme

VERSION = "v0.1.0"
COLUMNS = ["Index", "Timestamp", "Channel", "RX/TX", "Type", "ID",
           "Sender", "Name", "DLC", "Data", "Decoded", "Comment"]
MAX_ROWS = 5000


class SetupDialog(QDialog):
    def __init__(self, parent, backend, channel, bitrate, loop_back):
        super().__init__(parent)
        self.setWindowTitle("Setup Interface")
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
        form.addRow("Devices", info)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def values(self):
        return (self.backend.currentText(), self.channel.text(),
                int(self.bitrate.currentText()), self.loop_back.isChecked())


class MainWindow(QMainWindow):
    def __init__(self, backend="candle", channel=0, bitrate=500000,
                 loop_back=False):
        super().__init__()
        self.setWindowTitle(f"canAnalyser {VERSION}")
        self.resize(1150, 750)
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
        self.t0 = None
        self.agg = {}  # (arb_id, direction) -> row
        self.records: list[dict] = []
        self.rx_count = 0
        self.tx_count = 0
        self.err_count = 0
        self.autoscroll = True
        self.theme_mode = "system"
        self.dbc = DbcManager()
        self.sig_editors = {}
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
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._generator_tab(), "Generator")
        self.tabs.addTab(self._status_tab(), "CAN Status")
        self.tabs.addTab(self._log_tab(), "Log")
        self.tabs.setMaximumHeight(260)
        layout.addWidget(self.tabs)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("idle — press Start")

    def _generator_tab(self):
        split = QSplitter(Qt.Vertical)
        split.addWidget(self._manual_group())
        split.addWidget(self._dbc_group())
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(split)
        return w

    def _manual_group(self):
        box = QGroupBox("Manual (raw)")
        lay = QHBoxLayout(box)
        lay.addWidget(QLabel("ID (Hex):"))
        self.tx_id = QLineEdit("123")
        self.tx_id.setMaximumWidth(80)
        lay.addWidget(self.tx_id)
        lay.addWidget(QLabel("DLC:"))
        self.tx_dlc = QSpinBox()
        self.tx_dlc.setRange(0, 8)
        self.tx_dlc.setValue(6)
        lay.addWidget(self.tx_dlc)
        lay.addWidget(QLabel("Data:"))
        self.tx_data = QLineEdit("00 00 00 00 00 00")
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
        return box

    def _dbc_group(self):
        box = QGroupBox("DBC")
        lay = QVBoxLayout(box)
        top = QHBoxLayout()
        self.dbc_msg = QComboBox()
        self.dbc_msg.setEnabled(False)
        self.dbc_msg.currentTextChanged.connect(self._rebuild_signal_editors)
        top.addWidget(QLabel("Message:"))
        top.addWidget(self.dbc_msg, 1)
        self.dbc_dlc = QLabel("DLC: -")
        top.addWidget(self.dbc_dlc)
        top.addWidget(QLabel("Interval ms:"))
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
        self.dbc_sig_layout.addRow(QLabel("Load a DBC file to edit signals."))
        lay.addWidget(self.dbc_signals)
        return box

    def _status_tab(self):
        self.status_table = QTableWidget(1, 6)
        self.status_table.setHorizontalHeaderLabels(
            ["Backend", "Channel", "State", "Rx", "Tx", "Err"])
        self.status_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.status_table.verticalHeader().setVisible(False)
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.status_table)
        return w

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

        help_m = m.addMenu("&Help")
        a = QAction("About", self)
        a.triggered.connect(self.about)
        help_m.addAction(a)

    def _build_timers(self):
        self.cyclic = QTimer(self)
        self.cyclic.timeout.connect(self.send_once)
        self.dbc_cyclic = QTimer(self)
        self.dbc_cyclic.timeout.connect(self.dbc_send_once)

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
            "CANGaroo-style CAN receiver + TX generator.<br><br>"
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

    # ---- bus control ----
    def channel_label(self):
        return f"{self.backend}-ch{self.channel}"

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
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.log_msg(
            f"bus open: {self.backend} ch={self.channel} "
            f"{self.bitrate}bps loop_back={self.loop_back}")
        self._status()

    def stop(self):
        self.stop_cyclic()
        self.dbc_stop_cyclic()
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
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
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

    def on_err_frame(self):
        self.err_count += 1
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
        if self.t0 is None:
            self.t0 = local
        if self.ts_mode.currentText() == "Delta":
            ts_str = f"{local - self.t0:.4f}"
        else:
            ts_str = f"{fr['timestamp']:.4f}" if fr["timestamp"] else f"{local:.4f}"
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
            probe = {"arb_id": arb, "id": id_txt, "data": cells[9],
                     "name": cells[7], "decoded": cells[10], "sender": cells[6]}
            self.table.setRowHidden(row, not self._matches_rec(probe))

    def _rebuild_view(self):
        self.agg.clear()
        self.table.setRowCount(0)

    def clear(self):
        self.table.setRowCount(0)
        self.agg.clear()
        self.records.clear()
        self.index = 0
        self.t0 = None
        self.rx_count = self.tx_count = self.err_count = 0
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

    def _transmit(self, msg: can.Message) -> bool:
        if self.bus is None:
            QMessageBox.information(self, "TX", "Press Start first.")
            return False
        try:
            self.bus.send(msg)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "TX failed", str(e))
            self.log_msg(f"TX failed: {e}")
            return False
        self._append({"timestamp": time.time(), "local_ts": time.time(),
                      "channel": self.channel_label(),
                      "direction": "TX", "extended": msg.is_extended_id,
                      "arb_id": msg.arbitration_id, "dlc": len(msg.data),
                      "data": bytes(msg.data)})
        return True

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
    def _current_dbc_tx(self):
        name = self.dbc_msg.currentText()
        if not name:
            QMessageBox.information(self, "DBC TX", "Load a DBC file first.")
            return None
        values = {sn: box.value() for sn, box in self.sig_editors.items()}
        try:
            arb_id, raw = self.dbc.encode(name, values)
        except DbcError as e:
            QMessageBox.warning(self, "DBC TX", str(e))
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
