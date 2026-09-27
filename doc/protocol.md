# Table / TX format

## RX columns
`Index | Timestamp | Channel | RX/TX | Type | ID | Sender | DLC | Data | Name | Decoded | Comment`
- Type: `STD.` (11-bit) or `EXT.` (29-bit).
- ID: `0x123` / `0x12345678`.
- Data is the wide stretch column; RX/TX, ID, DLC stay compact.
- Sender/Name/Decoded come from the loaded DBC (blank without one);
  Decoded is `SIGNAL=value, ...` in physical units. Comment is reserved.

## Simple TX panel
- ID (Hex): e.g. `123`; DLC 0..8; Data: hex bytes separated by space/comma
  (shorter than DLC is zero-padded, longer is truncated).
- Send Once transmits one frame; Start/Stop Cyclic uses Interval ms QTimer.
- TX frames are echoed into the table as `TX` rows; bus frames appear as `RX`.
