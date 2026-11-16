"""执行编排：注册表驱动、异常隔离、退出码与汇总表。"""
import unittest

from signin.core.models import CheckinResult, Status
from signin.services import runner
from tests.support import make_client


def cfg_with(**sections):
    cfg = {k: {'enabled': False} for k in ('trae', 'qoder', 'workbuddy', 'doubao')}
    for key, section in sections.items():
        cfg[key] = section
    cfg['runtime'] = {'timeout': 20, 'retries': 3, 'backoff': 1.0}
    return cfg


class RunnerTest(unittest.TestCase):
    def test_only_enabled_platforms_run(self):
        cfg = cfg_with(
            trae={'enabled': True, 'token': 'tok', 'device_id': 'd1'},
            workbuddy={'enabled': True, 'cookie': 'sid=1'},
        )
        client, _ = make_client([
            ('ok', 200, b'{"code": 0, "checked_in": true, "credits": 150}'),
            ('ok', 500, b'boom'),
            ('ok', 500, b'boom'),
            ('ok', 500, b'boom'),
        ])
        results = runner.run_all(cfg, client=client)
        by_name = {r.platform: r for r in results}
        self.assertEqual(len(results), 2)
        self.assertEqual(by_name['trae'].status, Status.ALREADY)
        self.assertEqual(by_name['workbuddy'].status, Status.FAILED)

    def test_only_filter(self):
        cfg = cfg_with(
            trae={'enabled': True, 'token': 'tok', 'device_id': 'd1'},
            workbuddy={'enabled': True, 'cookie': 'sid=1'},
        )
        client, calls = make_client([('ok', 200, b'{"code": 0, "checked_in": true}')])
        results = runner.run_all(cfg, client=client, only=['trae'])
        self.assertEqual([r.platform for r in results], ['trae'])
        self.assertEqual(len(calls), 1)

    def test_execute_order_follows_registry(self):
        cfg = cfg_with(
            workbuddy={'enabled': True, 'cookie': 'sid=1'},
            trae={'enabled': True, 'token': 'tok', 'device_id': 'd1'},
        )
        seen = []
        client, _ = make_client([
            ('ok', 200, b'{"code": 0, "checked_in": true, "credits": 1}'),
            ('already', 400, b'{"code": 10001, "msg": "already checked in"}'),
        ])
        results = runner.run_all(cfg, client=client, on_result=lambda r: seen.append(r.platform))
        self.assertEqual(seen, ['trae', 'workbuddy'], '执行顺序应与注册顺序一致')
        self.assertEqual([r.platform for r in results], ['trae', 'workbuddy'])

    def test_platform_exception_isolated(self):
        cfg = cfg_with(trae={'enabled': True, 'token': 'tok', 'device_id': 'd1'},
                       qoder={'enabled': True, 'token': 'pt-1'})

        def boom(client, section, dry_run=False):
            raise RuntimeError('kaboom')

        from unittest import mock
        with mock.patch.object(runner.platforms.get('trae'), 'run', boom):
            client, _ = make_client([('ok', 200, b'{"campaigns": []}')])
            results = runner.run_all(cfg, client=client)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].status, Status.FAILED)
        self.assertIn('kaboom', results[0].message)
        self.assertEqual(results[1].status, Status.SKIPPED)

    def test_exit_code(self):
        self.assertEqual(runner.exit_code([CheckinResult('a', Status.OK)]), 0)
        self.assertEqual(runner.exit_code([CheckinResult('a', Status.NEED_SETUP)]), 0)
        self.assertEqual(runner.exit_code([CheckinResult('a', Status.FAILED)]), 1)

    def test_summary_lists_platforms_and_totals(self):
        results = [CheckinResult('trae', Status.OK, 'ok', 150),
                   CheckinResult('doubao', Status.NEED_SETUP, '缺配置')]
        text = runner.summary(results)
        self.assertIn('Trae', text)
        self.assertIn('豆包', text)
        self.assertIn('合计 2 个平台', text)
        self.assertIn('需配置 1', text)

    def test_summary_when_nothing_enabled(self):
        self.assertIn('没有启用', runner.summary([]))


if __name__ == '__main__':
    unittest.main()
