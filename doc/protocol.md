# Table / TX format

## RX columns
`Index | Timestamp | Channel | RX/TX | Type | ID | Sender | Name | DLC | Data | Decoded | Comment`
- Type: `STD.` (11-bit) or `EXT.` (29-bit).
- ID: `0x123` / `0x12345678`.
- Data: space-separated hex bytes, e.g. `00 00 00 00 00 00`, max 8 (classic CAN).
- Sender/Name/Decoded come from the loaded DBC (blank without one);
  Decoded is `SIGNAL=value, ...` in physical units. Comment is reserved.

## Simple TX panel
- ID (Hex): e.g. `123`; DLC 0..8; Data: hex bytes separated by space/comma
  (shorter than DLC is zero-padded, longer is truncated).
- Send Once transmits one frame; Start/Stop Cyclic uses Interval ms QTimer.
- TX frames are echoed into the table as `TX` rows; bus frames appear as `RX`.
