"""Unit tests: DbcManager load/decode/encode against the fixture DBC."""
import pytest

from dbc_manager import DbcError, DbcManager
from tests.conftest import DBC_PATH


@pytest.fixture()
def dbc():
    d = DbcManager()
    assert d.load(DBC_PATH) == 2
    return d


@pytest.mark.dbc
def test_load_and_names(dbc):
    assert dbc.loaded
    assert dbc.message_names() == ["EngineData", "ControlCmd"]


@pytest.mark.dbc
def test_load_bad_path():
    with pytest.raises(DbcError):
        DbcManager().load("/nonexistent/x.dbc")


@pytest.mark.dbc
def test_sender_and_name(dbc):
    assert dbc.sender_of(291) == "Engine"
    assert dbc.name_of(291) == "EngineData"
    assert dbc.name_of(999) == ""
    assert dbc.sender_of(999) == ""


@pytest.mark.dbc
def test_decode_known_bytes(dbc):
    dec = dbc.decode(291, bytes([0x00, 0x19, 0x5A, 0, 0, 0, 0, 0]))
    assert dec["RPM"] == pytest.approx(800.0)
    assert dec["CoolantTemp"] == 50


@pytest.mark.dbc
def test_decode_unknown_id(dbc):
    assert dbc.decode(999, b"\x00") is None


@pytest.mark.dbc
def test_decode_short_data_returns_none(dbc):
    assert dbc.decode(291, b"\x00") is None


@pytest.mark.dbc
def test_encode_roundtrip(dbc):
    arb_id, raw = dbc.encode("ControlCmd", {"GearReq": 3, "Enable": 1})
    assert arb_id == 0x200
    dec = dbc.decode(0x200, raw)
    assert dec["GearReq"] == 3
    assert dec["Enable"] == 1


@pytest.mark.dbc
def test_encode_unknown_message(dbc):
    with pytest.raises(DbcError):
        dbc.encode("Nope", {})


@pytest.mark.dbc
def test_fmt_signals():
    assert DbcManager.fmt_signals(None) == ""
    assert DbcManager.fmt_signals({}) == ""
    s = DbcManager.fmt_signals({"RPM": 800.0, "GearReq": 3})
    assert s == "RPM=800.000, GearReq=3"
