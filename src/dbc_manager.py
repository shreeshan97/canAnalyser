"""DBC wrapper around cantools: load, decode RX, encode TX."""


class DbcError(Exception):
    pass


class DbcManager:
    def __init__(self):
        self.db = None
        self.path = ""

    def load(self, path: str) -> int:
        import cantools
        try:
            self.db = cantools.database.load_file(path)
        except Exception as e:  # noqa: BLE001
            raise DbcError(f"cannot parse {path!r}: {e}") from e
        self.path = path
        return len(self.db.messages)

    def unload(self):
        self.db = None
        self.path = ""

    @property
    def loaded(self) -> bool:
        return self.db is not None

    def message_names(self) -> list[str]:
        return [m.name for m in self.db.messages] if self.db else []

    def get_message(self, name: str):
        if not self.db:
            return None
        try:
            return self.db.get_message_by_name(name)
        except KeyError:
            return None

    def message_by_id(self, arb_id: int):
        """Single O(1) lookup (cantools keeps a frame-ID index); None if
        unloaded or unknown."""
        if not self.db:
            return None
        try:
            return self.db.get_message_by_frame_id(arb_id)
        except KeyError:
            return None

    def sender_of(self, arb_id: int) -> str:
        m = self.message_by_id(arb_id)
        if m is None or not m.senders:
            return ""
        return ",".join(m.senders)

    def name_of(self, arb_id: int) -> str:
        m = self.message_by_id(arb_id)
        return m.name if m is not None else ""

    def decode(self, arb_id: int, data: bytes) -> dict | None:
        """Return {signal: physical_value} or None if unknown/undecodable."""
        m = self.message_by_id(arb_id)
        if m is None:
            return None
        try:
            return m.decode(bytes(data), decode_choices=False)
        except Exception:  # noqa: BLE001
            return None

    def encode(self, name: str, values: dict) -> tuple[int, bytes]:
        m = self.get_message(name)
        if m is None:
            raise DbcError(f"unknown message {name!r}")
        try:
            raw = m.encode(values)
        except Exception as e:  # noqa: BLE001
            raise DbcError(f"encode {name!r}: {e}") from e
        return m.frame_id, bytes(raw)

    @staticmethod
    def fmt_signals(sig: dict | None) -> str:
        if not sig:
            return ""
        parts = []
        for k, v in sig.items():
            parts.append(f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}")
        return ", ".join(parts)
