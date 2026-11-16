"""HTTP 层重试与「HTTP 200 但业务失败」识别。"""
import unittest

from tests.support import make_client


class HttpTest(unittest.TestCase):
    def test_retries_network_error_then_succeeds(self):
        c, calls = make_client([
            ('raise', ConnectionError('boom')),
            ('raise', ConnectionError('boom')),
            ('ok', 200, b'{"code": 0}'),
        ])
        res = c.request('POST', 'https://example.com/x', json_body={'a': 1})
        self.assertEqual(len(calls), 3)
        self.assertTrue(res.ok)
        self.assertEqual(res.json, {'code': 0})

    def test_no_retry_on_401(self):
        c, calls = make_client([('ok', 401, b'unauthed')])
        res = c.request('GET', 'https://example.com/y')
        self.assertEqual(len(calls), 1)
        self.assertFalse(res.ok)
        self.assertEqual(res.status, 401)

    def test_retries_5xx(self):
        c, calls = make_client([
            ('ok', 502, b'bad gateway'),
            ('ok', 200, b'ok'),
        ])
        res = c.request('POST', 'https://example.com/z')
        self.assertEqual(len(calls), 2)
        self.assertTrue(res.ok)

    def test_business_code_in_http_200_detected(self):
        c, _ = make_client([('ok', 200, b'{"code": 9074, "message": "busy"}')])
        res = c.request('POST', 'https://example.com/c', json_body={},
                        is_success=lambda body: body.get('code') == 0)
        self.assertFalse(res.ok)
        self.assertEqual(res.json['code'], 9074)

    def test_is_success_true_case(self):
        c, _ = make_client([('ok', 200, b'{"code": 0}')])
        res = c.request('POST', 'https://example.com/d',
                        is_success=lambda body: body.get('code') == 0)
        self.assertTrue(res.ok)

    def test_json_body_serialised_and_headers_merged(self):
        c, calls = make_client([('ok', 200, b'{}')])
        c.request('POST', 'https://example.com/e', headers={'X-A': '1'},
                  json_body={'req_source': 1})
        method, url, headers, data = calls[0]
        self.assertEqual(method, 'POST')
        self.assertEqual(headers['X-A'], '1')
        self.assertEqual(headers['Content-Type'], 'application/json')
        self.assertEqual(data, b'{"req_source": 1}')

    def test_exhausted_retries_returns_failed_result(self):
        c, calls = make_client([
            ('raise', ConnectionError('a')),
            ('raise', ConnectionError('b')),
            ('raise', ConnectionError('c')),
        ], retries=3)
        res = c.request('GET', 'https://example.com/f')
        self.assertEqual(len(calls), 3)
        self.assertFalse(res.ok)
        self.assertIn('c', res.error)


if __name__ == '__main__':
    unittest.main()
