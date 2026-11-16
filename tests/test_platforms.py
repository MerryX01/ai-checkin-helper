"""四个平台的签到判定：成功 / 幂等 / 需配置 / 失败 / dry-run。"""
import unittest
from unittest import mock

from signin.core.models import LoginState, Status
from signin.platforms import doubao, qoder, trae, workbuddy
from tests.support import make_client


class TraeTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch('signin.platforms.trae.login_state',
                             return_value=LoginState(False, message='未登录'))
        self.login = patcher.start()
        self.addCleanup(patcher.stop)

    def test_already_checked_in(self):
        client, calls = make_client([('ok', 200, b'{"code": 0, "checked_in": true, "credits": 150}')])
        res = trae.run(client, {'token': 'tok', 'device_id': 'd1'})
        self.assertEqual(res.status, Status.ALREADY)
        self.assertEqual(res.credits, 150)
        self.assertEqual(len(calls), 1, '已签到不应再发 claim')

    def test_claim_success(self):
        client, calls = make_client([
            ('ok', 200, b'{"code": 0, "checked_in": false, "credits": 100}'),
            ('ok', 200, b'{"code": 0, "credits": 100}'),
        ])
        res = trae.run(client, {'token': 'tok', 'device_id': 'd1'})
        self.assertEqual(res.status, Status.OK)
        self.assertEqual(len(calls), 2)
        self.assertIn('/trae/api/v2/ug/checkin_credits/claim', calls[1][1])

    def test_bad_device_code_hints_real_device_id(self):
        client, _ = make_client([
            ('ok', 200, b'{"code": 0, "checked_in": false}'),
            ('ok', 200, b'{"code": 9074, "message": "bad device"}'),
        ])
        res = trae.run(client, {'token': 'tok', 'device_id': 'uuid'})
        self.assertEqual(res.status, Status.FAILED)
        self.assertIn('9074', res.message)
        self.assertIn('设备号', res.message)

    def test_expired_token_needs_setup(self):
        client, _ = make_client([('ok', 401, b'{}')])
        res = trae.run(client, {'token': 'tok', 'device_id': 'd1'})
        self.assertEqual(res.status, Status.NEED_SETUP)
        self.assertIn('401', res.message)

    def test_gui_fallback_clicks_when_calibrated(self):
        clicks = []

        def clicker(window, x, y):
            clicks.append((window, x, y))
            return True

        section = {'gui_fallback': True,
                   'gui_click': {'window': 'Trae CN', 'x_ratio': 0.5, 'y_ratio': 0.9}}
        res = trae.run(None, section, clicker=clicker)
        self.assertEqual(res.status, Status.OK)
        self.assertEqual(clicks, [('Trae CN', 0.5, 0.9)])

    def test_gui_fallback_without_calibration_needs_setup(self):
        res = trae.run(None, {'gui_fallback': True})
        self.assertEqual(res.status, Status.NEED_SETUP)
        self.assertIn('校准', res.message)

    def test_token_from_client_login_state_is_used(self):
        client, calls = make_client([
            ('ok', 200, b'{"code": 0, "checked_in": true, "data": {"credits": 120}}'),
        ])
        self.login.return_value = LoginState(True, account='…8282',
                                             data={'token': 'jwt-1', 'device_id': 'dev-1'})
        res = trae.run(client, {})
        self.assertEqual(res.status, Status.ALREADY)
        self.assertEqual(res.credits, 120)
        self.assertEqual(calls[0][2].get('x-device-id'), 'dev-1')
        self.assertTrue(calls[0][2]['Authorization'].startswith('Cloud-IDE-JWT '))

    def test_dry_run_sends_nothing(self):
        client, calls = make_client([('ok', 200, b'{}')])
        res = trae.run(client, {'token': 'tok', 'device_id': 'd1'}, dry_run=True)
        self.assertEqual(res.status, Status.SKIPPED)
        self.assertEqual(calls, [])


class QoderTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch('signin.platforms.qoder.login_state',
                             return_value=LoginState(False, message='未登录'))
        self.login = patcher.start()
        self.addCleanup(patcher.stop)

    def test_claimable_campaign_claimed(self):
        client, calls = make_client([
            ('ok', 200, b'{"campaigns": [{"campaignId": "c1", "claimStatus": "CLAIMABLE", '
                        b'"actionType": "CLAIM_BENEFIT", "benefit": {"kind": "CREDITS", "amount": 100}}]}'),
            ('ok', 200, b'{"status": "CLAIMED", "benefit": {"amount": 100}}'),
        ])
        res = qoder.run(client, {'token': 'pt-1'})
        self.assertEqual(res.status, Status.OK)
        self.assertEqual(res.credits, 100)
        self.assertIn('/campaigns/c1/claim', calls[1][1])
        self.assertEqual(calls[0][2].get('Cosy-ClientType'), '10')

    def test_no_campaign_is_not_fake_success(self):
        client, _ = make_client([('ok', 200, b'{"campaigns": []}')])
        res = qoder.run(client, {'token': 'pt-1'})
        self.assertEqual(res.status, Status.SKIPPED)
        self.assertNotEqual(res.status, Status.ALREADY)

    def test_missing_login_needs_setup(self):
        res = qoder.run(None, {})
        self.assertEqual(res.status, Status.NEED_SETUP)
        self.assertIn('登录', res.message)

    def test_token_is_read_from_client_login_state(self):
        client, calls = make_client([
            ('ok', 200, b'{"campaigns": [{"campaignId": "c9", "claimStatus": "CLAIMABLE", '
                        b'"actionType": "CLAIM_BENEFIT", "benefit": {"kind": "CREDITS", "amount": 100}}]}'),
            ('ok', 200, b'{"status": "CLAIMED", "benefit": {"amount": 100}}'),
        ])
        self.login.return_value = LoginState(True, account='merry', data={'token': 'dt-1'})
        res = qoder.run(client, {})
        self.assertEqual(res.status, Status.OK)
        self.assertIn('/campaigns/c9/claim', calls[1][1])

    def test_expired_token_needs_setup(self):
        client, _ = make_client([('ok', 403, b'{}')])
        res = qoder.run(client, {'token': 'pt-1'})
        self.assertEqual(res.status, Status.NEED_SETUP)

    def test_dry_run_sends_nothing(self):
        client, calls = make_client([('ok', 200, b'{}')])
        res = qoder.run(client, {'token': 'pt-1'}, dry_run=True)
        self.assertEqual(res.status, Status.SKIPPED)
        self.assertEqual(calls, [])


class WorkBuddyTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch('signin.platforms.workbuddy.login_state',
                             return_value=LoginState(False, message='未登录'))
        self.login = patcher.start()
        self.addCleanup(patcher.stop)

    def test_missing_login_needs_setup(self):
        res = workbuddy.run(None, {})
        self.assertEqual(res.status, Status.NEED_SETUP)
        self.assertIn('登录', res.message)

    def test_token_from_client_is_used_as_bearer(self):
        client, calls = make_client([('ok', 200, b'{"ok": true}')])
        self.login.return_value = LoginState(True, account='merry', data={'token': 'at-1'})
        res = workbuddy.run(client, {})
        self.assertEqual(res.status, Status.OK)
        self.assertEqual(calls[0][2].get('Authorization'), 'Bearer at-1')

    def test_already_in_body_is_idempotent(self):
        client, _ = make_client([('ok', 200, '{"msg": "今天已签到"}'.encode())])
        res = workbuddy.run(client, {'cookie': 'sid=1'})
        self.assertEqual(res.status, Status.ALREADY)

    def test_already_as_error_code_is_idempotent(self):
        body = '{"code":10001,"msg":"今天已签到，请明天再来"}'.encode()
        client, _ = make_client([('ok', 400, body)])
        res = workbuddy.run(client, {'cookie': 'sid=1'})
        self.assertEqual(res.status, Status.ALREADY)

    def test_expired_login_needs_setup(self):
        client, _ = make_client([('ok', 401, b'{}')])
        res = workbuddy.run(client, {'cookie': 'sid=1'})
        self.assertEqual(res.status, Status.NEED_SETUP)
        self.assertIn('登录', res.message)

    def test_success(self):
        client, _ = make_client([('ok', 200, b'{"ok": true}')])
        res = workbuddy.run(client, {'cookie': 'sid=1'})
        self.assertEqual(res.status, Status.OK)

    def test_dry_run_sends_nothing(self):
        client, calls = make_client([('ok', 200, b'{}')])
        res = workbuddy.run(client, {'cookie': 'sid=1'}, dry_run=True)
        self.assertEqual(res.status, Status.SKIPPED)
        self.assertEqual(calls, [])


class DoubaoTest(unittest.TestCase):
    def test_missing_login_needs_setup(self):
        with mock.patch('signin.platforms.doubao.login_state',
                        return_value=LoginState(False, message='没读到登录 Cookie')):
            res = doubao.run(None, {})
        self.assertEqual(res.status, Status.NEED_SETUP)

    def test_login_state_makes_check_pass(self):
        with mock.patch('signin.platforms.doubao.login_state',
                        return_value=LoginState(True)):
            self.assertEqual(doubao.check({}), [])


if __name__ == '__main__':
    unittest.main()
