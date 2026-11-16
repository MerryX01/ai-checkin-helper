"""登录态读取：Buffer 解码、应用目录查找、平台凭证解析。"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from signin.core import secrets
from signin.core.models import LoginState
from signin.platforms import qoder, workbuddy


class PayloadTest(unittest.TestCase):
    def test_buffer_text_is_decoded(self):
        raw = b"\x01\x02\x03"
        value = json.dumps({"type": "Buffer", "data": list(raw)}).encode()
        self.assertEqual(secrets._payload_of(value), raw)

    def test_plain_text_is_passed_through(self):
        self.assertEqual(secrets._payload_of("hello"), b"hello")

    def test_broken_json_falls_back_to_raw(self):
        self.assertEqual(secrets._payload_of(b"[1,2"), b"[1,2")


class AppDirTest(unittest.TestCase):
    def test_finds_directory_case_insensitively(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "codebuddy cn").mkdir()
            with mock.patch.dict(os.environ, {"APPDATA": tmp, "LOCALAPPDATA": tmp}):
                found = secrets.app_dir(("CodeBuddy CN",))
            self.assertEqual(found, Path(tmp, "codebuddy cn"))

    def test_missing_directory_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"APPDATA": tmp, "LOCALAPPDATA": tmp}):
                self.assertIsNone(secrets.app_dir(("NothingHere",)))


class QoderLoginTest(unittest.TestCase):
    def test_token_and_account_are_parsed(self):
        doc = {"token": "dt-abc", "refreshToken": "drt-1", "expiresAt": "2026-11-19T00:00:00Z",
               "user": {"nickname": "Merry"}}
        with mock.patch.object(secrets, "app_dir", return_value=Path("C:/fake")), \
                mock.patch.object(secrets, "master_key", return_value=b"\x00" * 32), \
                mock.patch.object(secrets, "read_encrypted_json", return_value=doc), \
                mock.patch.object(Path, "exists", return_value=True):
            state = qoder.login_state()
        self.assertTrue(state.ok)
        self.assertEqual(state.account, "Merry")
        self.assertEqual(state.data["token"], "dt-abc")

    def test_missing_client_dir_is_reported(self):
        with mock.patch.object(secrets, "app_dir", return_value=None):
            state = qoder.login_state()
        self.assertFalse(state.ok)
        self.assertIn("Qoder 客户端", state.message)

    def test_detect_login_never_raises(self):
        with mock.patch.object(qoder.SPEC, "login_state", side_effect=OSError("boom")):
            state = qoder.SPEC.detect_login()
        self.assertFalse(state.ok)
        self.assertIn("boom", state.message)


class WorkBuddyLoginTest(unittest.TestCase):
    def test_access_token_is_parsed(self):
        doc = {"account": {"nickname": "Merry", "uid": "u1"},
               "auth": {"accessToken": "at-1", "refreshToken": "rt-1", "expiresAt": "2026-12-01"}}
        with mock.patch.object(secrets, "app_dir", return_value=Path("C:/fake")), \
                mock.patch.object(secrets, "read_vscdb_secret", return_value=doc):
            state = workbuddy.login_state()
        self.assertTrue(state.ok)
        self.assertEqual(state.account, "Merry")
        self.assertEqual(state.data["token"], "at-1")

    def test_logged_out_is_reported(self):
        with mock.patch.object(secrets, "app_dir", return_value=Path("C:/fake")), \
                mock.patch.object(secrets, "read_vscdb_secret", return_value=None):
            state = workbuddy.login_state()
        self.assertFalse(state.ok)
        self.assertIn("登录", state.message)


if __name__ == '__main__':
    unittest.main()
