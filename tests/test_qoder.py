"""Qoder：真实活动接口（gateway + Cosy-ClientType）与领取判定。"""
import copy
import unittest

from signin.core.models import Status
from signin.platforms import qoder


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


CAMPAIGN_TODAY = {
    "claimable": True,
    "campaigns": [
        {
            "campaignId": "01a1e029-3407-73db-9dbc-c987364578f6",
            "campaignKey": "act-20261116-448",
            "actionType": "CLAIM_BENEFIT",
            "claimStatus": "CLAIMABLE",
            "benefit": {"kind": "CREDITS", "amount": 100,
                        "validity": {"mode": "RELATIVE_DAYS", "days": 30}},
        },
        {
            "campaignId": "01a159a1-b0aa-79de-8c28-c61c1d3201c9",
            "actionType": "VIEW_DETAILS",
            "claimStatus": "CLAIMED",
        },
    ],
}


class TriggerTest(unittest.TestCase):
    """真实响应里状态字段叫 claimStatus、动作叫 actionType，必须能认出来。"""

    def test_finds_claimable_campaign_in_real_shape(self):
        found = qoder._find_claimable(CAMPAIGN_TODAY)
        self.assertEqual(found, ("01a1e029-3407-73db-9dbc-c987364578f6", 100))

    def test_ignores_promo_campaign(self):
        payload = {"campaigns": [CAMPAIGN_TODAY["campaigns"][1]]}
        self.assertIsNone(qoder._find_claimable(payload))

    def test_claimed_campaign_is_recognised(self):
        payload = {"campaigns": [copy.deepcopy(CAMPAIGN_TODAY["campaigns"][0])]}
        payload["campaigns"][0]["claimStatus"] = "CLAIMED"
        self.assertEqual(qoder._claimed_amount(payload), 100)


class RunTest(unittest.TestCase):
    def setUp(self):
        self.section = {"base_url": "https://gateway.qoder.com.cn", "token": "dt-abc"}

    def test_claim_success_reports_amount_and_verifies(self):
        client = FakeClient([
            FakeResponse(200, CAMPAIGN_TODAY),
            FakeResponse(200, {"status": "CLAIMED", "replayed": False, "benefit": {"amount": 100}}),
        ])
        result = qoder.run(client, self.section)
        self.assertEqual(result.status, Status.OK)
        self.assertEqual(result.credits, 100)
        self.assertIn("100", result.message)
        self.assertEqual(client.calls[0][0], "GET")
        self.assertEqual(client.calls[1][0], "POST")
        self.assertIn("/campaigns/01a1e029-3407-73db-9dbc-c987364578f6/claim", client.calls[1][1])

    def test_every_request_carries_cosy_client_type(self):
        client = FakeClient([
            FakeResponse(200, CAMPAIGN_TODAY),
            FakeResponse(200, {"status": "CLAIMED", "benefit": {"amount": 100}}),
        ])
        qoder.run(client, self.section)
        for _, _, headers in client.calls:
            self.assertEqual(headers.get("Cosy-ClientType"), "10")

    def test_already_claimed_returns_already_with_credits(self):
        payload = {"campaigns": [copy.deepcopy(CAMPAIGN_TODAY["campaigns"][0])]}
        payload["campaigns"][0]["claimStatus"] = "CLAIMED"
        result = qoder.run(FakeClient([FakeResponse(200, payload)]), self.section)
        self.assertEqual(result.status, Status.ALREADY)
        self.assertEqual(result.credits, 100)

    def test_no_campaign_is_not_a_fake_success(self):
        result = qoder.run(FakeClient([FakeResponse(200, {"campaigns": [], "claimable": False})]),
                           self.section)
        self.assertNotEqual(result.status, Status.OK)
        self.assertNotEqual(result.status, Status.ALREADY)
        self.assertIn("没有", result.message)

    def test_replayed_claim_is_treated_as_already(self):
        client = FakeClient([
            FakeResponse(200, CAMPAIGN_TODAY),
            FakeResponse(200, {"status": "CLAIMED", "replayed": True, "benefit": {"amount": 100}}),
        ])
        result = qoder.run(client, self.section)
        self.assertEqual(result.status, Status.ALREADY)


if __name__ == "__main__":
    unittest.main()
