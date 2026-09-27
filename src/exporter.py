"""Trace export: CSV (spreadsheet) and Vector ASC (replay in other tools)."""
import csv
import datetime


def export_csv(path: str, columns: list[str], records: list[dict]) -> int:
    keys = [c.lower().replace("/", "_") for c in columns]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(columns)
        for r in records:
            w.writerow([r.get(k, "") for k in keys])
    return len(records)


def export_asc(path: str, records: list[dict]) -> int:
    """Classic-CAN RX/TX rows only; error rows carry no bus data."""
    n = 0
    with open(path, "w") as f:
        f.write(f"date {datetime.datetime.now():%a %b %d %I:%M:%S %p %Y}\n")
        f.write("base hex  timestamps absolute\n// auto-exported by canAnalyser\n")
        for r in records:
            if r.get("direction") not in ("RX", "TX"):
                continue
            data = r.get("data_bytes", r.get("data", b"")) or b""
            f.write(f"({r.get('ts_bus', 0.0):.4f}) {r.get('channel', 1)} "
                    f"{r.get('arb_id', 0):X}#{bytes(data).hex()}\n")
            n += 1
    return n
