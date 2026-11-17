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
            "last_checkin_date": "2026-10-28",
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

    def test_feishu_account_uses_bubble_checkin_once(self):
        """飞书/企业登录态只探一次气泡签到，明确说“没有活动”，不再误报确认中。"""
        client = FakeClient([
            FakeResponse(200, DETAIL),
            FakeResponse(200, {"code": 710010702, "msg": "系统错误"}),
        ])
        result = doubao.run(client, {"cookie": "sessionid=abc; LARK_SUITE_ACCESS_TOKEN=xyz"})
        self.assertEqual(result.status, Status.SKIPPED)
        self.assertIn("企业", result.message)
        self.assertIn("个人", result.message)
        self.assertIn("2026-10-28", result.message)
        self.assertNotIn("确认中", result.message)
        self.assertEqual(len(client.calls), 2)
        self.assertIn("landing/checkin", client.calls[-1][1])
        self.assertTrue(result.detail.get("work_account"))
        self.assertTrue(result.detail.get("no_activity"))

    def test_has_biz_token_false_is_not_enough_to_be_work_account(self):
        self.assertFalse(doubao.is_work_account("sessionid=abc; has_biz_token=false"))
        self.assertFalse(doubao.is_work_account("sessionid=abc"))
        # feishu_dpop_keypair 是密钥残留：个人号点过「免费用豆包工作」后也会一直带着
        # （实测 2026-11），不能当企业登录依据。
        self.assertFalse(doubao.is_work_account("sessionid=abc; feishu_dpop_keypair=xyz"))
        # 企业登录的有效凭证：LARK 会话 token / has_biz_token=true。
        self.assertTrue(doubao.is_work_account("sessionid=abc; LARK_SUITE_ACCESS_TOKEN=xyz"))
        self.assertTrue(doubao.is_work_account("sessionid=abc; LARK_SUITE_DPOP=xyz"))
        self.assertTrue(doubao.is_work_account("sessionid=abc; has_biz_token=true"))

    def test_pending_claim_message_points_to_client_ui(self):
        """领取受理但一直「确认中」时，不再引导空等重试，如实说明并发到客户端验证。"""
        pending = {"code": 0, "data": {"biz_error": {"code": 3, "message": "领取结果确认中，请稍后重试"},
                                       "task_status": 0}}
        no_activity = {"code": 710010702, "msg": "系统错误"}
        client = FakeClient([
            FakeResponse(200, DETAIL),
            FakeResponse(200, pending),
            FakeResponse(200, DETAIL),   # _confirm 回读 1
            FakeResponse(200, DETAIL),   # _confirm 回读 2
            FakeResponse(200, DETAIL),   # _confirm 回读 3
            FakeResponse(200, no_activity),
        ])
        result = doubao.run(client, self.section)
        self.assertEqual(result.status, Status.SKIPPED)
        self.assertIn("确认中", result.message)
        self.assertIn("豆包客户端", result.message)
        self.assertNotIn("过几分钟可再点一次", result.message)


class LockedProfileTest(unittest.TestCase):
    """客户端运行时独占 Cookies 库：要给出准确提示，而不是误导性的「先去登录」。"""

    def test_locked_profiles_report_client_running(self):
        from pathlib import Path
        from unittest import mock
        from signin.core.models import LoginState
        with mock.patch.object(doubao, "_user_data_dir", return_value=Path("X:/fake")), \
             mock.patch.object(doubao.secrets, "master_key", return_value=None), \
             mock.patch.object(doubao, "_profiles",
                               return_value=[Path("X:/fake/Profile 3"), Path("X:/fake/Default")]), \
             mock.patch.object(doubao, "_read_profile_cookie",
                               side_effect=[("locked", "", ""), ("empty", "", "")]):
            state = doubao.login_state()
        self.assertFalse(state.ok)
        self.assertIn("豆包客户端正在运行", state.message)
        self.assertIn("Profile 3", state.message)
        # 只要有一个 profile 能读，就不报「被占用」
        with mock.patch.object(doubao, "_user_data_dir", return_value=Path("X:/fake")), \
             mock.patch.object(doubao.secrets, "master_key", return_value=None), \
             mock.patch.object(doubao, "_profiles",
                               return_value=[Path("X:/fake/Profile 3"), Path("X:/fake/Default")]), \
             mock.patch.object(doubao, "_read_profile_cookie",
                               side_effect=[("locked", "", ""),
                                            ("ok", "sessionid=abc", "abc123")]):
            state = doubao.login_state()
        self.assertTrue(state.ok)
        self.assertEqual(state.data["profile"], "Default")


class CookieExpiryTest(unittest.TestCase):
    def test_session_cookies_never_expire(self):
        self.assertFalse(doubao._expired(0))
        self.assertFalse(doubao._expired(None))

    def test_expired_and_live_chrome_timestamps(self):
        now = doubao._chrome_now()
        self.assertTrue(doubao._expired(int((now - 3600) * 1_000_000), now))
        self.assertFalse(doubao._expired(int((now + 3600) * 1_000_000), now))


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
