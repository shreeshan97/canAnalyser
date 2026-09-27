# canAnalyser

PySide6 CAN bus receiver + multi-message TX generator.
Backend: `python-can` `candle` (FYSETC UCAN, `1d50:606f`) with virtual fallback.

## Quickstart
```bash
bash scripts/setup_venv.sh
bash scripts/run_virtual.sh   # no hardware
bash scripts/run.sh           # candle hardware, 500 kbps
```

See `doc/usage.md` for hardware/udev notes, `doc/protocol.md` for table/filter format.

## Tests
```bash
bash scripts/run_tests.sh   # pytest, offscreen Qt, virtual bus + fixture DBC
```
`tests/` covers DBC decode/encode, TX parsing, exporters, themes, the
RX worker's echo/error filtering, and the main window (trace, filter,
TX, entry table, clear, autoscroll) — 36 tests, no hardware needed.
