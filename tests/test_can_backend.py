"""Unit tests: TX field parsing, formatting, virtual bus open/roundtrip."""
import pytest
import can

from can_backend import data_to_str, open_bus, parse_tx_fields


@pytest.mark.backend
def test_parse_basic():
    assert parse_tx_fields("123", 6, "00 00 00 00 00 00") == (0x123, [0] * 6)


@pytest.mark.backend
def test_parse_0x_prefix_comma_sep():
    assert parse_tx_fields("0x7FF", 2, "AA, BB, CC") == (0x7FF, [0xAA, 0xBB])


@pytest.mark.backend
def test_parse_empty_data_zero_pads():
    assert parse_tx_fields("1", 8, "") == (1, [0] * 8)


@pytest.mark.backend
def test_parse_dlc_zero():
    assert parse_tx_fields("100", 0, "FF") == (0x100, [])


@pytest.mark.backend
def test_parse_bad_id():
    with pytest.raises(ValueError):
        parse_tx_fields("ZZZ", 1, "00")


@pytest.mark.backend
def test_data_to_str():
    assert data_to_str([0, 171, 255]) == "00 AB FF"
    assert data_to_str(b"") == ""


@pytest.mark.backend
def test_open_bus_unknown_backend():
    with pytest.raises(ValueError):
        open_bus("nope", 0, 500000)


@pytest.mark.backend
def test_virtual_roundtrip():
    bus = open_bus("virtual", "pytest-rt", 500000)
    try:
        while bus.recv(timeout=0.05) is not None:
            pass
        bus.send(can.Message(arbitration_id=0x123, data=[1, 2, 3],
                             is_extended_id=False))
        rx = bus.recv(timeout=1.0)
        assert rx is not None
        assert rx.arbitration_id == 0x123
        assert bytes(rx.data) == bytes([1, 2, 3])
    finally:
        bus.shutdown()
