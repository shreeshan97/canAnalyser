"""Unit tests: RxWorker drops firmware TX-echoes and error frames."""
import can
import pytest

from rx_worker import RxWorker


class FakeBus:
    def __init__(self, msgs):
        self._msgs = list(msgs)
        self.calls = 0

    def recv(self, timeout=None):
        self.calls += 1
        if self._msgs:
            return self._msgs.pop(0)
        return None


def _msg(**kw):
    d = dict(arbitration_id=0x123, data=[1], is_extended_id=False,
             timestamp=1.0, is_rx=True, is_error_frame=False)
    d.update(kw)
    return can.Message(**d)


@pytest.mark.worker
def test_worker_forwards_only_real_frames():
    # Leading None ends the worker's startup drain; the rest hits the main loop.
    bus = FakeBus([None,
                   _msg(is_rx=False),                      # firmware echo
                   _msg(is_error_frame=True),               # bus fault
                   _msg(),                                  # real frame
                   ])
    got, err_counts = [], []
    w = RxWorker(bus, "ch")
    w.frame.connect(got.append)
    w.err_frame.connect(err_counts.append)
    orig_recv = bus.recv
    state = {"nones": 0}

    def recv(timeout=None):
        m = orig_recv(timeout)
        if m is None:
            state["nones"] += 1
            if state["nones"] >= 2:
                w.stop()
        return m
    bus.recv = recv
    w.run()
    assert len(got) == 1
    assert got[0]["arb_id"] == 0x123
    assert sum(err_counts) == 1


@pytest.mark.worker
def test_worker_batches_error_storm():
    # 50 error frames must arrive as a few batched emissions, not 50 signals.
    bus = FakeBus([None] + [_msg(is_error_frame=True)] * 50)
    err_counts = []
    w = RxWorker(bus, "ch")
    w.err_frame.connect(err_counts.append)
    orig_recv = bus.recv
    state = {"nones": 0}

    def recv(timeout=None):
        m = orig_recv(timeout)
        if m is None:
            state["nones"] += 1
            if state["nones"] >= 2:
                w.stop()
        return m
    bus.recv = recv
    w.run()
    assert sum(err_counts) == 50
    assert len(err_counts) < 50
