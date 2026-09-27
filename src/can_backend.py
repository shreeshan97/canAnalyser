"""Backend helpers: open python-can buses, parse TX fields."""
import can


def open_bus(backend: str, channel, bitrate: int, loop_back: bool = True):
    if backend == "candle":
        if isinstance(channel, str) and channel.isdigit():
            channel = int(channel)
        return can.interface.Bus(
            interface="candle", channel=channel if channel != "" else 0,
            bitrate=bitrate, loop_back=loop_back,
        )
    if backend == "virtual":
        return can.interface.Bus(
            interface="virtual", channel=str(channel or "test"),
            receive_own_messages=True,
        )
    if backend == "socketcan":
        return can.interface.Bus(
            interface="socketcan", channel=str(channel or "can0"),
        )
    raise ValueError(f"unknown backend: {backend}")


def list_candle_devices() -> str:
    try:
        import candle_api
    except ImportError:
        return "candle_api not installed"
    try:
        devs = candle_api.list_device()
    except Exception as e:  # noqa: BLE001
        return f"list failed: {e!r} (likely udev perms for 1d50:606f)"
    if not devs:
        return "No candle devices (or access denied — check udev 1d50:606f)."
    return "\n".join(
        f"serial={d.serial_number} channels={len(d)}" for d in devs
    )


def parse_tx_fields(id_hex: str, dlc: int, data_hex: str):
    arb_id = int(id_hex.strip().lower().replace("0x", ""), 16)
    raw = data_hex.replace(",", " ").split()
    data = [int(b, 16) & 0xFF for b in raw if b]
    data = (data + [0] * dlc)[:dlc]
    return arb_id, data


def data_to_str(data: bytes | list) -> str:
    return " ".join(f"{b:02X}" for b in bytes(data))
