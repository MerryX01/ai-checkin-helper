"""豆包：真实任务面板 / 领取接口（客户端 Cookie 自动读取）。"""
import unittest

from signin.core.models import Status
from signin.platforms import doubao

DETAIL = {"code": 0, "data": {
    "tasks": [{
        "task_kind": "daily_signin",
        "daily_checkin": {
            "checked_in_today": False,
            "continuous_days": 7,
            "reward": {"reward_amount": 400, "reward_type": "quota_grant"},
            "total_days": 3,
        },
    }],
    "progress": {"total_amount": 200},
}}

DETAIL_DONE = {"code": 0, "data": {
    "tasks": [{
        "task_kind": "daily_signin",
        "daily_checkin": {
            "checked_in_today": True,
            "continuous_days": 8,
            "reward": {"reward_amount": 400, "reward_type": "quota_grant"},
            "total_days": 4,
        },
    }],
}}


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status = status
        self.json = payload
        self.text = ""
        self.ok = 200 <= status < 300

    def snippet(self, limit=200):
        return ""


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def _next(self):
        return self.responses.pop(0)

    def post(self, url, headers=None, params=None, json_body=None, data=None):
        self.calls.append(("POST", url, headers or {}, json_body))
        return self._next()


class RunTest(unittest.TestCase):
    def setUp(self):
        self.section = {"cookie": "sessionid=abc; sid_tt=abc"}

    def test_claim_success_verified_and_reports_reward(self):
        client = FakeClient([
            FakeResponse(200, DETAIL),
            FakeResponse(200, {"code": 0, "data": {"checked_in": True, "reward_amount": 400}}),
            FakeResponse(200, DETAIL_DONE),
        ])
        result = doubao.run(client, self.section)
        self.assertEqual(result.status, Status.OK)
        self.assertEqual(result.credits, 400)
        self.assertIn("400", result.message)
        self.assertIn("pc_incentive_task_mvp_v3", str(client.calls[0][3]))

    def test_already_checked_in(self):
        result = doubao.run(FakeClient([FakeResponse(200, DETAIL_DONE)]), self.section)
        self.assertEqual(result.status, Status.ALREADY)
        self.assertEqual(result.credits, 400)

    def test_no_activity_is_honest_skip(self):
        client = FakeClient([
            FakeResponse(200, DETAIL),
            FakeResponse(200, {"code": 710010702, "msg": "系统错误"}),
            FakeResponse(200, {"code": 710010702, "msg": "系统错误"}),
        ])
        result = doubao.run(client, self.section)
        self.assertEqual(result.status, Status.SKIPPED)
        self.assertIn("没有可领取", result.message)
        self.assertNotIn("成功", result.message)
        self.assertIn("item/reward/claim", client.calls[1][1])

    def test_expired_cookie_needs_setup(self):
        result = doubao.run(FakeClient([FakeResponse(200, {"code": 710012001, "msg": "登录已过期"})]),
                            self.section)
        self.assertEqual(result.status, Status.NEED_SETUP)
        self.assertIn("登录", result.message)

    def test_no_daily_signin_task_is_reported(self):
        payload = {"code": 0, "data": {"tasks": [{"task_kind": "chat_activity"}]}}
        result = doubao.run(FakeClient([FakeResponse(200, payload)]), self.section)
        self.assertEqual(result.status, Status.SKIPPED)
        self.assertIn("没有每日签到任务", result.message)

    def test_missing_cookie_needs_setup(self):
        from unittest import mock
        from signin.core.models import LoginState
        with mock.patch.object(doubao, "login_state",
                               return_value=LoginState(False, message="没读到登录 Cookie")):
            result = doubao.run(FakeClient([]), {})
        self.assertEqual(result.status, Status.NEED_SETUP)


class CookieParseTest(unittest.TestCase):
    def test_cookie_accepts_32_byte_prefix_and_filters_binary(self):
        from unittest import mock
        with mock.patch.object(doubao.secrets, "decrypt_blob",
                               return_value=b"\x00" * 32 + b"abc123"):
            value = doubao._cookie_value(None, "", b"v10" + b"\x00" * 12)
        self.assertEqual(value, "abc123")
        cookie = doubao.build_cookie([("sessionid", value), ("bad", "中文")])
        self.assertEqual(cookie, "sessionid=abc123")


if __name__ == "__main__":
    unittest.main()
