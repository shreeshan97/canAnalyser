# Usage

## Install (no sudo on this host)
```bash
bash scripts/setup_venv.sh        # uses ~/.local/bin/virtualenv
```

## Run
```bash
bash scripts/run_virtual.sh       # virtual bus, receive_own_messages=True
bash scripts/run.sh               # candle ch 0 @500k; add --bitrate/--loop-back off
.venv/bin/python src/main.py --help
```

## Hardware (FYSETC UCAN, VID:PID 1d50:606f, gs_usb)
- Appears as candle device, serial e.g. `003500465446571320343032`.
- If device shows in `lsusb` but app reports none / access denied, it is a udev
  permission issue: `ATTRS{idVendor}=="1d50", ATTRS{idProduct}=="606f", MODE="0666"`
  in `/etc/udev/rules.d/99-candle.rules`, reload rules, unplug/replug.
- Default test: internal `loop_back=True`, no wiring needed (same as canTest01.py).

## UI
- Start/Stop opens/closes the bus and reader thread; Setup Interface sets
  backend, bitrate, channel, loop-back.
- View Aggregated collapses same ID+direction into one row; Raw appends all.
- Timestamps Delta = seconds since first frame; Absolute = bus timestamp.
- Filter matches ID hex (e.g. `123`) or data hex substring.
