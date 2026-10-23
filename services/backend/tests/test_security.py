import time

from hcwave.core.security import mask_phone, normalize_phone, sign_payload, verify_payload


def test_normalize_phone():
    assert normalize_phone("98470 12345") == "+919847012345"
    assert normalize_phone("09847012345") == "+919847012345"
    assert normalize_phone("919847012345") == "+919847012345"
    assert normalize_phone("+1 (425) 555-0100") == "+14255550100"


def test_mask_phone():
    assert mask_phone("+919847012345") == "+91******2345"


def test_signed_payload_roundtrip_and_tamper():
    token = sign_payload("k", {"rid": "1"}, 60)
    assert verify_payload("k", token)["rid"] == "1"
    assert verify_payload("other", token) is None
    assert verify_payload("k", token[:-2] + "xx") is None


def test_signed_payload_expiry():
    token = sign_payload("k", {"rid": "1"}, -1)
    time.sleep(0.01)
    assert verify_payload("k", token) is None
