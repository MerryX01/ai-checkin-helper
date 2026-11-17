"""额度看板：真实响应形状、诚实缺省、今日收益合并。"""
import unittest
from unittest.mock import patch

from signin.core.models import CheckinResult, LoginState, Status
from signin.platforms import doubao, qoder, trae, workbuddy
from signin.services import quota as quota_service


class FakeResponse:
    def __init__(self, status=200, payload=None, text=""):
        self.status = status
        self.json = payload
        self.text = text or ""
        self.ok = 200 <= status < 300

    def snippet(self, limit=200):
        return self.text[:limit]


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def _next(self):
        if not self.responses:
            raise AssertionError("没有更多假响应了")
        return self.responses.pop(0)

    def get(self, url, headers=None, params=None):
        self.calls.append(("GET", url, headers or {}))
        return self._next()

    def post(self, url, headers=None, params=None, json_body=None, data=None):
        self.calls.append(("POST", url, headers or {}))
        return self._next()


QODER_USAGE = {
    "displayMode": "qoder",
    "qoderUsage": {
        "userId": "01a15783-2901-78f3-a0cb-8bf7226207e8",
        "userType": "personal_standard",
        "usageType": "credits",
        "totalUsagePercentage": 0.89,
        "isQuotaExceeded": False,
        "expiresAt": 253402214400000,
        "refreshAt": 253402214400000,
        "userQuota": {"total": 0, "used": 0, "remaining": 0, "percentage": 0, "unit": "credits"},
        "addOnQuota": {"total": 1900, "used": 1697, "remaining": 203, "percentage": 0.89,
                       "unit": "credits", "detailUrl": "https://qoder.cn/account/usage"},
    },
}

TRAE_USAGE = {
    "balance_summary": [{"source": 1, "total_balance": 602.5}],
    "is_credits_billing": True,
    "is_dollar_usage_billing": False,
    "total_balance": 602.5,
    "usage_summary": {"consumed_amount": 497.5, "consumption_ratio": 0.45227272727272727,
                      "total_amount": 1100},
    "user_entitlement_pack_list": [
        {"display_desc": "免费", "expire_time": 1796054399,
         "entitlement_base_info": {"quota": {"solo_agent_parallel_limit": 2}}},
        {"display_desc": "每月登录赠送", "expire_time": 1796054399,
         "entitlement_base_info": {"product_extra": {"package_extra": {"quota": {"credits_limit": 500}}}}},
    ],
}

WORKBUDDY_USAGE = {
    "code": 0,
    "msg": "OK",
    "data": {
        "Packages": [
            {"PackageCode": "TCACA_code_007", "CycleTotalCapacity": "2412",
             "CycleRemainCapacity": "394.45000161", "CycleUsedCapacity": "2017.54999839",
             "CapacityUnit": "credits"},
            {"PackageCode": "TCACA_code_008", "CycleTotalCapacity": "500",
             "CycleRemainCapacity": "0", "CycleUsedCapacity": "500", "CapacityUnit": "credits"},
        ],
        "TotalCredits": "394.45000161",
        "SubscriptionPackageName": "体验版",
        "IsPaidUser": False,
        "CreditGroups": [
            {"Kind": "plan_base", "Name": "套餐基础积分", "CycleTotalCapacity": "500",
             "CycleRemainCapacity": "0", "CycleUsedCapacity": "500", "CapacityUnit": "credits"},
            {"Kind": "benefit", "Name": "平台奖励积分", "CycleTotalCapacity": "2412",
             "CycleRemainCapacity": "394.45000161", "CycleUsedCapacity": "2017.54999839",
             "CapacityUnit": "credits"},
        ],
    },
}

WORKBUDDY_STATUS = {
    "code": 0,
    "msg": "OK",
    "data": {
        "active": True,
        "today_checked_in": True,
        "streak_days": 17,
        "daily_credit": 100,
        "today_credit": 100,
        "total_credits": 1700,
        "checkin_dates": ["2026-11-17", "2026-11-16"],
        "week_checkin_days": 2,
        "activity_name": "Buddy应用",
        "end_time": "2026-12-31 23:59:59",
    },
}

DOUBAO_QUOTA = {
    "code": 0,
    "data": {
        "current_subscription": {"display": {"product_name": "个人订阅", "short_name": "免费体验"}},
        "incentive_quota_section": {
            "entitlement_count": 1,
            "usage_exhausted": False,
            "window_limit_groups": [{
                "feature_group": "doubao_activity_reward_quota",
                "feature_group_name": "活动赠送额度",
                "window_limits": [{
                    "end_time": 1795759534787, "item_type": 0,
                    "less_than_one_percent": True, "start_time": 0,
                    "total_amount": "200", "used_amount": "<1",
                    "used_percent": 0, "window_type": 3,
                }],
            }],
        },
        "member_info": {"hasActiveSubscription": False, "usr_type": 1},
    },
}

DOUBAO_RECORDS = {
    "code": 0,
    "data": {
        "has_more": False,
        "records": [{
            "amount": "200", "create_time_ms": 1793167535000, "record_id": "7701595890402610454",
            "task_code": "daily_signin", "task_name": "每日签到", "unit": "POINT",
        }],
    },
}


class ModelTest(unittest.TestCase):
    def test_percent_and_formatted_amount(self):
        snap = quota_service.QuotaSnapshot("qoder", Status.OK, balance=203, total=1900, used=1697)
        self.assertAlmostEqual(snap.percent, 0.8931578947, places=5)
        self.assertEqual(snap.fmt_balance(), "203")

    def test_no_total_means_no_percent(self):
        snap = quota_service.QuotaSnapshot("x", Status.OK, balance=12)
        self.assertIsNone(snap.percent)


class QoderQuotaTest(unittest.TestCase):
    def test_real_usage_shape_and_headers(self):
        client = FakeClient([FakeResponse(payload=QODER_USAGE)])
        snap = qoder.quota(client, {"base_url": "https://gateway.qoder.com.cn", "token": "dt-abc"})
        self.assertEqual(snap.status, Status.OK)
        self.assertEqual(snap.balance, 203)
        self.assertEqual(snap.total, 1900)
        self.assertEqual(snap.used, 1697)
        self.assertEqual(snap.unit, "credits")
        self.assertAlmostEqual(snap.percent, 0.89, places=2)
        headers = client.calls[0][2]
        self.assertEqual(headers["Authorization"], "Bearer dt-abc")
        self.assertEqual(headers["Cosy-ClientType"], "10")

    def test_missing_login_is_need_setup(self):
        client = FakeClient([])
        with patch.object(qoder, "login_state", return_value=LoginState(False, message="not logged in")):
            snap = qoder.quota(client, {"base_url": "https://gateway.qoder.com.cn"})
        self.assertEqual(snap.status, Status.NEED_SETUP)
        self.assertIsNone(snap.balance)

    def test_401_is_need_setup(self):
        client = FakeClient([FakeResponse(status=401, payload={"code": 401})])
        snap = qoder.quota(client, {"base_url": "https://gateway.qoder.com.cn", "token": "dt-abc"})
        self.assertEqual(snap.status, Status.NEED_SETUP)


class TraeQuotaTest(unittest.TestCase):
    def test_real_usage_shape_and_body(self):
        client = FakeClient([FakeResponse(payload=TRAE_USAGE)])
        snap = trae.quota(client, {"base_url": "https://api.trae.cn", "token": "jwt", "device_id": "dev"})
        self.assertEqual(snap.status, Status.OK)
        self.assertEqual(snap.balance, 602.5)
        self.assertEqual(snap.total, 1100)
        self.assertEqual(snap.used, 497.5)
        self.assertAlmostEqual(snap.percent, 0.4522727273, places=5)
        self.assertTrue(any("每月登录赠送" in value for _, value in snap.details))

    def test_missing_login_is_need_setup(self):
        client = FakeClient([])
        with patch.object(trae, "login_state", return_value=LoginState(False, message="not logged in")):
            snap = trae.quota(client, {"base_url": "https://api.trae.cn"})
        self.assertEqual(snap.status, Status.NEED_SETUP)


class WorkBuddyQuotaTest(unittest.TestCase):
    def test_real_resource_summary(self):
        client = FakeClient([FakeResponse(payload=WORKBUDDY_USAGE)])
        snap = workbuddy.quota(client, {"base_url": "https://www.codebuddy.cn", "token": "tok"})
        self.assertEqual(snap.status, Status.OK)
        self.assertAlmostEqual(snap.balance, 394.45000161)
        self.assertEqual(snap.total, 2912)
        self.assertAlmostEqual(snap.used, 2517.54999839)
        self.assertTrue(any("套餐基础积分" in label for label, _ in snap.details))

    def test_code_nonzero_is_failed(self):
        client = FakeClient([FakeResponse(payload={"code": 10001, "msg": "未登录"})])
        snap = workbuddy.quota(client, {"base_url": "https://www.codebuddy.cn", "token": "tok"})
        self.assertEqual(snap.status, Status.FAILED)


class DoubaoQuotaTest(unittest.TestCase):
    def test_summary_and_records(self):
        client = FakeClient([FakeResponse(payload=DOUBAO_QUOTA), FakeResponse(payload=DOUBAO_RECORDS)])
        snap = doubao.quota(client, {"cookie": "sessionid=x", "seed": "seed"})
        self.assertEqual(snap.status, Status.OK)
        self.assertEqual(snap.total, 200)
        self.assertIsNone(snap.balance)
        self.assertEqual(snap.fmt_balance(), "≥199")
        self.assertEqual(snap.used, 0)
        self.assertEqual(snap.used_text, "<1")
        self.assertTrue(any("每日签到" in value for _, value in snap.details))
        self.assertIn("不足 1", snap.message)
        self.assertEqual(snap.fmt_today(), "—")

    def test_feishu_account_marks_no_qualification(self):
        client = FakeClient([FakeResponse(payload=DOUBAO_QUOTA), FakeResponse(payload=DOUBAO_RECORDS)])
        snap = doubao.quota(client, {"cookie": "sessionid=x; LARK_SUITE_ACCESS_TOKEN=y", "seed": "s"})
        self.assertEqual(snap.status, Status.OK)
        self.assertEqual(snap.fmt_today(), "无资格")
        self.assertIn("企业", snap.message)
        self.assertIn("工作版", snap.message)
        self.assertTrue(any(label == "账号类型" for label, _ in snap.details))

    def test_personal_account_leftover_keypair_is_not_enterprise(self):
        """个人号残留 feishu_dpop_keypair 不再被误判成企业登录态（实测 2026-11）。"""
        client = FakeClient([FakeResponse(payload=DOUBAO_QUOTA), FakeResponse(payload=DOUBAO_RECORDS)])
        snap = doubao.quota(client, {"cookie": "sessionid=x; feishu_dpop_keypair=y", "seed": "s"})
        self.assertEqual(snap.status, Status.OK)
        self.assertEqual(snap.fmt_today(), "—")
        self.assertNotIn("企业", snap.message)

    def test_today_record_sets_today_earned(self):
        import datetime
        today_ms = int(datetime.datetime.now().timestamp() * 1000)
        records = {"code": 0, "data": {"records": [
            {"amount": "200", "create_time_ms": today_ms,
             "task_code": "daily_signin", "task_name": "每日签到", "unit": "POINT"},
        ]}}
        client = FakeClient([FakeResponse(payload=DOUBAO_QUOTA), FakeResponse(payload=records)])
        snap = doubao.quota(client, {"cookie": "sessionid=x", "seed": "seed"})
        self.assertEqual(snap.today_earned, 200)
        self.assertEqual(snap.fmt_today(), "+200")

    def test_missing_cookie_is_need_setup(self):
        client = FakeClient([])
        with patch.object(doubao, "login_state", return_value=LoginState(False, message="not logged in")):
            snap = doubao.quota(client, {})
        self.assertEqual(snap.status, Status.NEED_SETUP)


class WorkBuddyStatusQuotaTest(unittest.TestCase):
    def test_status_credit_is_merged_even_without_a_checkin_run(self):
        client = FakeClient([FakeResponse(payload=WORKBUDDY_USAGE),
                             FakeResponse(payload=WORKBUDDY_STATUS)])
        snap = workbuddy.quota(client, {"base_url": "https://www.codebuddy.cn", "token": "tok"})
        self.assertEqual(snap.status, Status.OK)
        self.assertEqual(snap.today_earned, 100)
        self.assertEqual(snap.fmt_today(), "+100")
        self.assertTrue(any("连续签到" == label for label, _ in snap.details))
        self.assertTrue(any("今日签到" == label for label, _ in snap.details))


class TodayTextTest(unittest.TestCase):
    def test_today_text_is_used_when_no_amount(self):
        snap = quota_service.QuotaSnapshot("workbuddy", Status.ALREADY, today_text="已签")
        self.assertEqual(snap.fmt_today(), "已签")
        self.assertEqual(snap.as_dict()["today_text"], "已签")

    def test_amount_wins_over_text(self):
        snap = quota_service.QuotaSnapshot("workbuddy", Status.OK, today_earned=100,
                                           today_text="已签")
        self.assertEqual(snap.fmt_today(), "+100")

    def test_skipped_no_activity_becomes_unqualified(self):
        class Spec:
            key = "doubao"

            def quota(self, client, section):
                return quota_service.QuotaSnapshot("doubao", Status.OK, balance=1)

        results = {"doubao": CheckinResult("doubao", Status.SKIPPED,
                                          detail={"no_activity": True})}
        got = quota_service.collect({"doubao": {}}, client=FakeClient([]),
                                    specs=[Spec()], results=results)
        self.assertEqual(got[0].fmt_today(), "无资格")

    def test_already_without_credit_shows_signed(self):
        class Spec:
            key = "workbuddy"

            def quota(self, client, section):
                return quota_service.QuotaSnapshot("workbuddy", Status.OK, balance=1)

        results = {"workbuddy": CheckinResult("workbuddy", Status.ALREADY)}
        got = quota_service.collect({"workbuddy": {}}, client=FakeClient([]),
                                    specs=[Spec()], results=results)
        self.assertEqual(got[0].fmt_today(), "已签")


class CollectTest(unittest.TestCase):
    def test_merge_today_earned_only_for_success(self):
        snapshots = [
            quota_service.QuotaSnapshot("qoder", Status.OK, balance=203, total=1900),
            quota_service.QuotaSnapshot("trae", Status.OK, balance=602.5, total=1100),
        ]
        results = {
            "qoder": CheckinResult("qoder", Status.ALREADY, credits=100),
            "trae": CheckinResult("trae", Status.SKIPPED, credits=999),
        }

        class FakeSpec:
            def __init__(self, key):
                self.key = key

            def quota(self, client, section):
                return snapshots[0] if self.key == "qoder" else snapshots[1]

        cfg = {"qoder": {}, "trae": {}}
        got = quota_service.collect(cfg, client=FakeClient([]), specs=[FakeSpec("qoder"), FakeSpec("trae")],
                                    results=results)
        self.assertEqual(got[0].today_earned, 100)
        self.assertIsNone(got[1].today_earned)
        self.assertEqual(got[0].today_earned, 100)

    def test_single_platform_error_does_not_break_others(self):
        class Spec:
            def __init__(self, key, boom=False):
                self.key = key
                self.boom = boom

            def quota(self, client, section):
                if self.boom:
                    raise RuntimeError("boom")
                return quota_service.QuotaSnapshot(self.key, Status.OK, balance=1)

        got = quota_service.collect({"a": {}, "b": {}}, client=FakeClient([]),
                                    specs=[Spec("a", True), Spec("b")])
        self.assertEqual(got[0].status, Status.FAILED)
        self.assertEqual(got[1].status, Status.OK)

    def test_summary_has_honest_missing_values(self):
        snap = quota_service.QuotaSnapshot("doubao", Status.OK, balance=200, total=200,
                                           used=0, unit="credits")
        text = quota_service.summary([snap])
        self.assertIn("豆包", text)
        self.assertIn("200", text)
        self.assertIn("—", text)


if __name__ == "__main__":
    unittest.main()
