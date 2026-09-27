# Table / TX format

## RX columns
`Index | Timestamp | Channel | RX/TX | Type | ID | Sender | DLC | Data | Name | Decoded | Comment`
- Fixed widths (px @1280 window): Index 40, RX/TX 40, Type 40,
  Channel 60, Sender 60, ID 70, DLC 40, Timestamp/Name/Decoded/Comment
  130 each; Data stretches over the remainder (~390px).
- Type: `STD.` (11-bit) or `EXT.` (29-bit). ID: `0x123` / `0x12345678`.
- Sender/Name/Decoded come from the loaded DBC (blank without one);
  Decoded is `SIGNAL=value, ...` in physical units. Comment is reserved.

## Simple TX panel
- ID (Hex): e.g. `123`; DLC 0..8; Data: hex bytes separated by space/comma
  (shorter than DLC is zero-padded, longer is truncated).
- Send Once transmits one frame; Start/Stop Cyclic uses Interval ms QTimer.
- TX frames are echoed into the table as `TX` rows; bus frames appear as `RX`.
