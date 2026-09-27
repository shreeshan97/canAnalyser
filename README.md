# canAnalyser

PySide6 CAN receiver + simple TX generator, styled after CANGaroo.
Backend: `python-can` `candle` (FYSETC UCAN, `1d50:606f`) with virtual fallback.

## Quickstart
```bash
bash scripts/setup_venv.sh
bash scripts/run_virtual.sh   # no hardware
bash scripts/run.sh           # candle hardware, 500 kbps
```

See `doc/usage.md` for hardware/udev notes, `doc/protocol.md` for table/filter format.
