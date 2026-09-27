"""Trace export: CSV (spreadsheet) and Vector ASC (replay in other tools)."""
import csv
import datetime


def _wall_clock(ts_local: float) -> str:
    return datetime.datetime.fromtimestamp(ts_local).strftime("%H:%M:%S.%f")


def export_csv(path: str, columns: list[str], records: list[dict]) -> int:
    """Timestamp column always exports local wall-clock (24h + microseconds);
    the appended Epoch column carries the numeric epoch for correlation.
    Both derive from the record's ts_local, independent of the live
    Delta/Absolute display mode."""
    header = list(columns) + ["Epoch"]
    keys = [c.lower().replace("/", "_") for c in columns]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in records:
            row = []
            for k in keys:
                if k == "timestamp" and r.get("ts_local"):
                    row.append(_wall_clock(r["ts_local"]))
                else:
                    row.append(r.get(k, ""))
            ts = r.get("ts_local") or 0.0
            row.append(f"{ts:.6f}")
            w.writerow(row)
    return len(records)


def export_asc(path: str, records: list[dict]) -> int:
    """Classic-CAN RX/TX rows only; error rows carry no bus data.

    Times are ts_local (wall-clock epoch): ts_bus is device-uptime or
    monotonic on some backends (e.g. candle), so it is not a valid
    absolute timestamp for replay correlation."""
    n = 0
    with open(path, "w") as f:
        f.write(f"date {datetime.datetime.now():%a %b %d %I:%M:%S %p %Y}\n")
        f.write("base hex  timestamps absolute\n// auto-exported by canAnalyser\n")
        for r in records:
            if r.get("direction") not in ("RX", "TX"):
                continue
            data = r.get("data_bytes", r.get("data", b"")) or b""
            f.write(f"({r.get('ts_local', 0.0):.4f}) {r.get('channel', 1)} "
                    f"{r.get('arb_id', 0):X}#{bytes(data).hex()}\n")
            n += 1
    return n
