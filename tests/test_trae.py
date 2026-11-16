"""Trae 登录信封解密：用同一套格式造一份密文，确认能解开并校验。"""
import base64
import hashlib
import json
import unittest
from unittest import mock

from signin.core.aesgcm import _encrypt_block, _expand_key
from signin.platforms import trae


def _cbc_encrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    round_keys, nr = _expand_key(key)
    prev, out = iv, bytearray()
    for offset in range(0, len(data), 16):
        block = bytes(a ^ b for a, b in zip(data[offset:offset + 16], prev))
        enc = _encrypt_block(block, round_keys, nr)
        out += enc
        prev = enc
    return bytes(out)


def _pad(raw: bytes) -> bytes:
    n = 16 - len(raw) % 16
    return raw + bytes([n]) * n


def make_envelope(payload: dict, header: bytes = None) -> str:
    header = header or trae.HEADER_AES
    expr = b"trae-test-nonce-0123456789abcdef"[:32]
    salt = bytes(a ^ b for a, b in zip(trae.SALT_A, trae.SALT_B))
    derived = hashlib.sha512(hashlib.sha512(expr).digest() + salt).digest()
    body = json.dumps(payload).encode()
    plain = hashlib.sha512(body).digest() + body
    cipher = _cbc_encrypt(derived[:16], derived[16:32], _pad(plain))
    return base64.b64encode(header + expr + cipher).decode()


class EnvelopeTest(unittest.TestCase):
    def test_envelope_roundtrip(self):
        text = trae.decrypt_storage_value(make_envelope({"token": "jwt-abc", "userId": 42}))
        self.assertIn("jwt-abc", text)

    def test_private_header_roundtrip(self):
        salt = bytes(a ^ b for a, b in zip(trae.SALT_C, trae.SALT_D))
        expr = b"trae-private-nonce-0123456789abc"[:32]
        derived = hashlib.sha512(hashlib.sha512(expr).digest() + salt).digest()
        body = json.dumps({"accessToken": "jwt-x"}).encode()
        plain = hashlib.sha512(body).digest() + body
        cipher = _cbc_encrypt(derived[:16], derived[16:32], _pad(plain))
        value = base64.b64encode(trae.HEADER_AES_PRIVATE + expr + cipher).decode()
        self.assertIn("jwt-x", trae.decrypt_storage_value(value))

    def test_unknown_header_is_rejected(self):
        with self.assertRaises(ValueError):
            trae.decrypt_storage_value(base64.b64encode(b"\x00" * 120).decode())

    def test_jwt_claim_reads_data_id(self):
        payload = base64.urlsafe_b64encode(json.dumps({"data": {"id": "123"}}).encode()).decode().rstrip("=")
        self.assertEqual(trae._jwt_claim(f"a.{payload}.b"), "123")


class PickTest(unittest.TestCase):
    def test_desktop_credential_wins(self):
        with mock.patch.object(trae, "_from_storage", return_value=[
            {"token": "a.b.c", "device_id": "dev", "account": "1", "source": "Trae CN"}]), \
                mock.patch.object(trae, "_from_cli", return_value=[
                    {"token": "x.y.z", "device_id": "", "account": "1", "source": "~/.trae-cn"}]):
            items = trae.find_credentials()
        self.assertEqual(items[0]["device_id"], "dev")

    def test_login_state_reports_account_tail(self):
        with mock.patch.object(trae, "_from_storage", return_value=[
                {"token": "a.b.c", "device_id": "dev", "account": "1234500008282", "source": "Trae CN"}]), \
                mock.patch.object(trae, "_from_cli", return_value=[]):
            state = trae.login_state()
        self.assertTrue(state.ok)
        self.assertIn("8282", state.account)


if __name__ == '__main__':
    unittest.main()
