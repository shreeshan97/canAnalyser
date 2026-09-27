import pytest
"""Unit tests: CSV and ASC exporters."""
from exporter import export_asc, export_csv


def _rec(**kw):
    r = {"index": 1, "timestamp": "0.0001", "channel": "virtual-chx",
         "rx_tx": "RX", "type": "STD.", "id": "0x123", "sender": "Engine",
         "name": "EngineData", "dlc": "8", "data": "00 19",
         "decoded": "RPM=800.000", "comment": "",
         "ts_bus": 99.0, "ts_local": 123.456, "direction": "RX",
         "arb_id": 0x123, "data_bytes": bytes([0x00, 0x19])}
    r.update(kw)
    return r


COLS = ["Index", "Timestamp", "Channel", "RX/TX", "Type", "ID", "Sender",
        "Name", "DLC", "Data", "Decoded", "Comment"]


@pytest.mark.exporter
def test_csv_headers_and_rows(tmp_path):
    import datetime
    import re
    p = str(tmp_path / "t.csv")
    assert export_csv(p, COLS, [_rec(), _rec(index=2)]) == 2
    lines = open(p).read().splitlines()
    assert lines[0] == ",".join(COLS + ["Epoch"])
    assert "EngineData" in lines[1]
    cells = lines[1].split(",")
    ts_cell = cells[COLS.index("Timestamp")]  # wall-clock, not display mode
    assert re.fullmatch(r"\d{2}:\d{2}:\d{2}\.\d{6}", ts_cell)
    assert ts_cell == datetime.datetime.fromtimestamp(123.456).strftime(
        "%H:%M:%S.%f")
    assert cells[-1] == "123.456000"  # numeric epoch
    assert len(lines) == 3


@pytest.mark.exporter
def test_asc_format(tmp_path):
    p = str(tmp_path / "t.asc")
    recs = [_rec(), _rec(direction="TX", rx_tx="TX"),
            _rec(direction="??", rx_tx="??")]
    assert export_asc(p, recs) == 2  # non bus rows skipped
    txt = open(p).read()
    assert txt.startswith("date ")
    assert "123#0019" in txt
    assert "(123.4560)" in txt  # ts_local epoch, not ts_bus uptime
