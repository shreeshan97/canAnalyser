# Usage

## Install (no sudo on this host)
```bash
bash scripts/setup_venv.sh        # uses ~/.local/bin/virtualenv
```

## First launch on Mint/Ubuntu: missing `libxcb-cursor0`
Qt6 xcb needs it, and there is no sudo. One-time user-space fix (already
applied on this machine, `run.sh` picks it up automatically):
```bash
mkdir -p /tmp/qtextract && apt download libxcb-cursor0  # wrapper drops a tar.gz
tar xzf libxcb-cursor0.tar.gz -C /tmp/qtextract
dpkg-deb -x $(find /tmp/qtextract -name '*.deb') ~/.local/qtlibs/
```
`scripts/run.sh` / `run_virtual.sh` prepend
`~/.local/qtlibs/usr/lib/x86_64-linux-gnu` to `LD_LIBRARY_PATH`.

## Run
```bash
bash scripts/run_virtual.sh       # virtual bus, receive_own_messages=True
bash scripts/run.sh               # candle ch 0 @500k normal mode; add --loop-back for self-test
.venv/bin/python src/main.py --help
```

## Hardware (FYSETC UCAN, VID:PID 1d50:606f, gs_usb)
- Appears as candle device, serial e.g. `003500465446571320343032`.
- If device shows in `lsusb` but app reports none / access denied, it is a udev
  permission issue: `ATTRS{idVendor}=="1d50", ATTRS{idProduct}=="606f", MODE="0666"`
  in `/etc/udev/rules.d/99-candle.rules`, reload rules, unplug/replug.
- Default is normal mode (`loop_back` off): TX/RX are physically wired together
  so the loop is done by hardware. Tick "Silicon loop-back" in Setup (or pass
  `--loop-back`) only for a wiring-free internal self-test.

## UI
- Start/Stop opens/closes the bus and reader thread; Setup Interface sets
  backend, bitrate, channel, loop-back.
- Start greys out Start/Setup (Stop blacks in) and back; same for the
  Measurement menu. Setup refuses while running ("Stop first").
- View Aggregated collapses same ID+direction into one row; Raw appends all.
- Timestamps Delta = seconds since first frame with microseconds (local
  receipt clock, monotonic across midnight); Absolute = local wall-clock
  24h with microseconds (`HH:MM:SS.ffffff`, wraps at midnight).
- Filter matches ID hex, data hex, or DBC name/signal text.
- Autoscroll toggle (toolbar + View menu, default ON).
- Bottom tabs: Generator with inner Manual | DBC tabs, each with its own
  transmissions table underneath (own Add/Remove/Send/Start/Stop bar,
  per-row On checkbox and editable interval; Manual TX defaults to DLC 8);
  CAN Status is a compact card hugging its content with 50% column air
  (backend/channel/state/Rx/Tx/Err); Log (timestamped events).
- Window opens 1280x950 at (200, 100) (1000x650 minimum); trace table
  takes the stretch; entry tables are 204px inside a 350px bottom dock.
- Menus: File (Load DBC, Export CSV/ASC, Exit), Measurement (Start/Stop),
  View (Autoscroll, Theme System/Light/Dark, Clear), Trace, Generator,
  Help → About (v0.1.0).

## DBC mode
- File → Load DBC (or Load DBC... button). RX rows gain Sender/Name/Decoded
  columns; the DBC generator offers a message picker + signal editors with
  range limits; DLC is automatic. Works with any `.dbc`.
- Export: CSV takes all columns incl. decoded text (filter applied) with
  Timestamp always as wall-clock plus an extra Epoch column (both from the
  local receipt clock, independent of the Delta/Absolute display mode);
  ASC writes Vector-compatible `(ts) ch id#data` lines with epoch times
  for replay elsewhere.
