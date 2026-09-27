"""Reader worker: polls bus.recv() off the GUI thread."""
import time

from PySide6.QtCore import QObject, Signal


class RxWorker(QObject):
    frame = Signal(dict)
    error = Signal(str)
    err_frame = Signal(int)  # batched count, emitted at most every 250ms
    finished = Signal()

    ERR_BATCH_S = 0.25

    def __init__(self, bus, channel_label: str):
        super().__init__()
        self._bus = bus
        self._label = channel_label
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        pending_errs = 0
        last_flush = time.monotonic()

        def flush_errs(force=False):
            nonlocal pending_errs, last_flush
            now = time.monotonic()
            if pending_errs and (force or now - last_flush >= self.ERR_BATCH_S):
                self.err_frame.emit(pending_errs)
                pending_errs = 0
                last_flush = now

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
                    flush_errs()
                    continue
                if msg.is_error_frame:
                    # Bus fault signalling (e.g. lone node in normal mode:
                    # no peer to ACK). Count it, keep it out of the table.
                    # Batched: a storm is thousands/sec and must not flood
                    # the GUI event queue and freeze Stop handling.
                    pending_errs += 1
                    flush_errs()
                    continue
                if not msg.is_rx:
                    # Firmware TX-echo (candle loopback hands back our own
                    # frame with is_rx=False ~200us before the real looped-back
                    # copy). The GUI already draws its own local TX row, so
                    # drop the echo to avoid double RX rows per send.
                    continue
                flush_errs()
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
            flush_errs(force=True)
            self.finished.emit()
