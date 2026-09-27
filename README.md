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
bash scripts/run_tests.sh            # everything (41 tests)
bash scripts/run_tests.sh -m entries # one feature: dbc backend exporter
                                     # theme worker trace decode tx
                                     # entries failsafe ui
bash scripts/run_tests.sh tests/test_theme.py  # one file
```
`tests/` covers DBC decode/encode, TX parsing, exporters, themes, the
RX worker's echo/error filtering, and the main window (trace, filter,
TX, per-tab entry tables, clear, autoscroll) — 40 tests, no hardware needed.
