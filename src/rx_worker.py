"""Reader worker: polls bus.recv() off the GUI thread."""
import time

from PySide6.QtCore import QObject, Signal


class RxWorker(QObject):
    frame = Signal(dict)
    error = Signal(str)
    finished = Signal()

    def __init__(self, bus, channel_label: str):
        super().__init__()
        self._bus = bus
        self._label = channel_label
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        try:
            while self._bus.recv(timeout=0.05) is not None:  # drain stale
                pass
            while self._running:
                try:
                    msg = self._bus.recv(timeout=0.1)
                except Exception as e:  # noqa: BLE001
                    self.error.emit(str(e))
                    break
                if msg is None:
                    continue
                if not msg.is_rx:
                    # Firmware TX-echo (candle loopback hands back our own
                    # frame with is_rx=False ~200us before the real looped-back
                    # copy). The GUI already draws its own local TX row, so
                    # drop the echo to avoid double RX rows per send.
                    continue
                self.frame.emit({
                    "timestamp": msg.timestamp,
                    "local_ts": time.time(),
                    "channel": self._label,
                    "direction": "RX",
                    "extended": msg.is_extended_id,
                    "arb_id": msg.arbitration_id,
                    "dlc": msg.dlc,
                    "data": bytes(msg.data),
                })
        finally:
            self.finished.emit()
