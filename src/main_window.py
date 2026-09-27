"""Main window: RX table (CANGaroo-style) + simple TX generator."""
import time

import can
from PySide6.QtCore import QThread, QTimer, Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QCheckBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QSpinBox, QStatusBar, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from can_backend import data_to_str, list_candle_devices, open_bus, parse_tx_fields
from rx_worker import RxWorker

COLUMNS = ["Index", "Timestamp", "Channel", "RX/TX", "Type", "ID", "DLC", "Data"]
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
        self.setWindowTitle("canAnalyser")
        self.resize(1100, 700)
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
        self.rx_count = 0
        self.tx_count = 0
        self.err_count = 0
        self._build_ui()
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
        top.addWidget(self.btn_start)
        top.addWidget(self.btn_stop)
        top.addWidget(self.btn_setup)
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
        self.filter_edit.setPlaceholderText("e.g. 123")
        self.filter_edit.textChanged.connect(self._apply_filter)
        filt.addWidget(self.filter_edit)
        layout.addLayout(filt)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        tx = QHBoxLayout()
        tx.addWidget(QLabel("ID (Hex):"))
        self.tx_id = QLineEdit("123")
        self.tx_id.setMaximumWidth(80)
        tx.addWidget(self.tx_id)
        tx.addWidget(QLabel("DLC:"))
        self.tx_dlc = QSpinBox()
        self.tx_dlc.setRange(0, 8)
        self.tx_dlc.setValue(6)
        tx.addWidget(self.tx_dlc)
        tx.addWidget(QLabel("Data:"))
        self.tx_data = QLineEdit("00 00 00 00 00 00")
        tx.addWidget(self.tx_data, 1)
        tx.addWidget(QLabel("Interval ms:"))
        self.tx_interval = QSpinBox()
        self.tx_interval.setRange(10, 10000)
        self.tx_interval.setValue(100)
        tx.addWidget(self.tx_interval)
        self.btn_send = QPushButton("Send Once")
        self.btn_cyclic = QPushButton("Start Cyclic")
        self.btn_cyclic_stop = QPushButton("Stop Cyclic")
        self.btn_cyclic_stop.setEnabled(False)
        self.btn_send.clicked.connect(self.send_once)
        self.btn_cyclic.clicked.connect(self.start_cyclic)
        self.btn_cyclic_stop.clicked.connect(self.stop_cyclic)
        tx.addWidget(self.btn_send)
        tx.addWidget(self.btn_cyclic)
        tx.addWidget(self.btn_cyclic_stop)
        layout.addLayout(tx)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("idle — press Start")

    def _build_timers(self):
        self.cyclic = QTimer(self)
        self.cyclic.timeout.connect(self.send_once)

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
            return
        self.thread = QThread(self)
        self.worker = RxWorker(self.bus, self.channel_label())
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.frame.connect(self.on_frame)
        self.worker.error.connect(lambda m: self.statusBar().showMessage(m))
        self.worker.err_frame.connect(self.on_err_frame)
        self.worker.finished.connect(self.thread.quit)
        self.thread.start()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.statusBar().showMessage(
            f"running: {self.backend} ch={self.channel} {self.bitrate}bps")

    def stop(self):
        self.stop_cyclic()
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
        self.statusBar().showMessage(
            f"stopped — RX={self.rx_count} TX={self.tx_count} ERR={self.err_count}")

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
    def _matches(self, arb_id, data_str):
        f = self.filter_edit.text().strip().lower()
        if not f:
            return True
        return f in f"{arb_id:x}" or f in data_str.lower()

    def on_frame(self, fr: dict):
        self._append(fr)

    def on_err_frame(self):
        self.err_count += 1
        self._status()

    def _status(self):
        self.statusBar().showMessage(
            f"RX={self.rx_count} TX={self.tx_count} ERR={self.err_count}")

    def _append(self, fr: dict):
        # Delta uses the local receipt clock so TX echoes (time.time()) and
        # bus frames (device-clock msg.timestamp, e.g. candle uptime) mix safely.
        local = fr.get("local_ts") or fr["timestamp"] or time.time()
        if self.t0 is None:
            self.t0 = local
        if self.ts_mode.currentText() == "Delta":
            ts_str = f"{local - self.t0:.4f}"
        else:
            ts_str = f"{fr['timestamp']:.4f}" if fr["timestamp"] else f"{local:.4f}"
        typ = "EXT." if fr["extended"] else "STD."
        id_str = f"0x{fr['arb_id']:X}"
        data_str = data_to_str(fr["data"])
        if not self._matches(fr["arb_id"], data_str):
            return
        if fr["direction"] == "RX":
            self.rx_count += 1
        else:
            self.tx_count += 1
        key = (fr["arb_id"], fr["direction"])
        if self.view.currentText() == "Aggregated" and key in self.agg:
            row = self.agg[key]
            self._set_row(row, self.index, ts_str, fr, typ, id_str, data_str)
        else:
            row = self.table.rowCount()
            if row >= MAX_ROWS:
                self.table.removeRow(0)
                self.agg = {k: v - 1 for k, v in self.agg.items()}
                row = MAX_ROWS - 1
            self.index += 1
            self.table.insertRow(row)
            self._set_row(row, self.index, ts_str, fr, typ, id_str, data_str)
            if self.view.currentText() == "Aggregated":
                self.agg[key] = row
        self.table.scrollToBottom()
        self._status()

    def _set_row(self, row, idx, ts_str, fr, typ, id_str, data_str):
        vals = [str(idx), ts_str, fr["channel"], fr["direction"],
                typ, id_str, str(fr["dlc"]), data_str]
        for c, v in enumerate(vals):
            self.table.setItem(row, c, QTableWidgetItem(v))
        self.table.setRowHidden(row, False)

    def _apply_filter(self):
        f = self.filter_edit.text().strip().lower()
        for r in range(self.table.rowCount()):
            id_item = self.table.item(r, 5)
            data_item = self.table.item(r, 7)
            txt = f"{id_item.text() if id_item else ''} {data_item.text() if data_item else ''}".lower()
            self.table.setRowHidden(r, f not in txt)

    def _rebuild_view(self):
        self.agg.clear()
        # Simplest correct rebuild: clear rows; new frames re-populate.
        self.table.setRowCount(0)

    def clear(self):
        self.table.setRowCount(0)
        self.agg.clear()
        self.index = 0
        self.t0 = None
        self.rx_count = self.tx_count = self.err_count = 0

    # ---- TX path ----
    def _current_tx(self):
        try:
            arb_id, data = parse_tx_fields(
                self.tx_id.text(), self.tx_dlc.value(), self.tx_data.text())
        except ValueError as e:
            QMessageBox.warning(self, "TX", f"Bad TX field: {e}")
            return None
        return can.Message(arbitration_id=arb_id, data=data,
                           is_extended_id=arb_id > 0x7FF)

    def send_once(self):
        msg = self._current_tx()
        if msg is None:
            return
        if self.bus is None:
            QMessageBox.information(self, "TX", "Press Start first.")
            return
        try:
            self.bus.send(msg)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "TX failed", str(e))
            return
        self._append({"timestamp": time.time(), "local_ts": time.time(),
                      "channel": self.channel_label(),
                      "direction": "TX", "extended": msg.is_extended_id,
                      "arb_id": msg.arbitration_id, "dlc": len(msg.data),
                      "data": bytes(msg.data)})

    def start_cyclic(self):
        self.cyclic.start(self.tx_interval.value())
        self.btn_cyclic.setEnabled(False)
        self.btn_cyclic_stop.setEnabled(True)

    def stop_cyclic(self):
        if self.cyclic.isActive():
            self.cyclic.stop()
        self.btn_cyclic.setEnabled(True)
        self.btn_cyclic_stop.setEnabled(False)
