# Table / TX format

## RX columns
`Index | Timestamp | Channel | RX/TX | Type | ID | Sender | DLC | Data | Name | Decoded | Comment`
- Fixed widths (px): Index 40, RX/TX 50, Type 50, Channel 75,
  Sender 75, ID 70, DLC 40, Timestamp 160, Data 220.
- Name (140) and Comment (130) start at defaults but are user-draggable
  (Interactive); Decoded stretches over the remainder (~210px @1280).
- Type: `STD.` (11-bit) or `EXT.` (29-bit). ID: `0x123` / `0x12345678`.
- Sender/Name/Decoded come from the loaded DBC (blank without one);
  Decoded is `SIGNAL=value, ...` in physical units. Comment is reserved.

## Manual TX (Manual Gen tab)
- ID (Hex): e.g. `123` (IDs above `0x7FF` send as extended frames);
  DLC 0..8 (default 8); Data: hex bytes separated by space/comma
  (shorter than DLC is zero-padded, longer is truncated).
- Send Once transmits one frame; Start/Stop Cyclic uses Interval ms.
- TX frames appear in the table as local `TX` rows (firmware TX-echoes
  are dropped, never double-counted); bus frames appear as `RX`.

## Multi-message entries
- Add Manual / Add DBC captures the current fields into the tab's
  transmissions table (max 16 entries): per-row On checkbox, editable
  interval 10–10000 ms, Send Selected Once, Start/Stop All.
- Entry timers send quietly and auto-stop after 3 consecutive TX fails.
- DBC entries snapshot the current signal values as the payload summary.
