"""界面与配置之间的纯逻辑：表单映射、校验、命令拼装（全部由注册表驱动）。"""
import json
import os
import unittest
from unittest import mock

from signin import platforms
from signin.core import config
from signin.core.models import LoginState
from signin.services import settings


def _form(**over):
    form = settings.form_from_config(config.DEFAULTS)
    form.update(over)
    return form


class FormTest(unittest.TestCase):
    def test_form_covers_all_platforms(self):
        form = settings.form_from_config(config.DEFAULTS)
        for p in platforms.keys():
            self.assertIn(p, form['enabled'])
            self.assertIsInstance(form[p], dict)

    def test_toggle_platform_flips_only_one(self):
        form = settings.form_from_config(config.DEFAULTS)
        form['enabled'] = {p: False for p in platforms.keys()}
        self.assertTrue(settings.toggle_platform(form, 'qoder'))
        self.assertTrue(form['enabled']['qoder'])
        self.assertFalse(form['enabled']['trae'])
        self.assertFalse(settings.toggle_platform(form, 'qoder'))
        self.assertFalse(form['enabled']['qoder'])

    def test_form_reads_values(self):
        cfg = config.load(None)
        cfg['qoder']['base_url'] = 'https://example.test'
        cfg['trae']['token'] = 'tk-abc'
        form = settings.form_from_config(cfg)
        self.assertEqual(form['qoder']['base_url'], 'https://example.test')
        self.assertEqual(form['trae']['token'], 'tk-abc')

    def test_roundtrip_keeps_sections(self):
        cfg = config.load(None)
        cfg['trae']['token'] = 'tk'
        cfg['trae']['device_id'] = '123'
        back = settings.apply_form(cfg, settings.form_from_config(cfg))
        for p in platforms.keys():
            self.assertEqual(back[p]['enabled'], cfg[p]['enabled'])
            self.assertEqual(back[p].get('token'), cfg[p].get('token'))

    def test_apply_keeps_notify_and_runtime(self):
        cfg = config.load(None)
        cfg['notify'] = {'enabled': True, 'type': 'feishu', 'url': 'https://x/y'}
        form = settings.form_from_config(cfg)
        form['enabled']['qoder'] = True
        form['qoder']['token'] = 'pt-1'
        out = settings.apply_form(cfg, form)
        self.assertEqual(out['notify']['type'], 'feishu')
        self.assertEqual(out['notify']['url'], 'https://x/y')
        self.assertEqual(out['runtime']['retries'], cfg['runtime']['retries'])

    def test_apply_preserves_gui_click(self):
        cfg = config.load(None)
        cfg['trae']['gui_click'] = {'window': 'Trae CN', 'x_ratio': 0.5, 'y_ratio': 0.9}
        form = settings.form_from_config(cfg)
        out = settings.apply_form(cfg, form)
        self.assertEqual(out['trae']['gui_click']['window'], 'Trae CN')

    def test_apply_sets_enabled_and_strips_space(self):
        cfg = config.load(None)
        form = settings.form_from_config(cfg)
        form['enabled']['trae'] = True
        form['trae']['token'] = '  tk-1  '
        form['trae']['device_id'] = ' 42 '
        out = settings.apply_form(cfg, form)
        self.assertTrue(out['trae']['enabled'])
        self.assertEqual(out['trae']['token'], 'tk-1')
        self.assertEqual(out['trae']['device_id'], '42')

    def test_apply_uses_default_base_url_when_empty(self):
        cfg = config.load(None)
        form = settings.form_from_config(cfg)
        form['qoder']['base_url'] = ''
        out = settings.apply_form(cfg, form)
        self.assertEqual(out['qoder']['base_url'], 'https://gateway.qoder.com.cn')


class TimeTest(unittest.TestCase):
    def test_valid(self):
        for t in ('09:05', '00:00', '23:59', '10:10'):
            self.assertTrue(settings.validate_time(t), t)

    def test_invalid(self):
        for t in ('25:99', '9:05', '', 'abc', '24:00', '10:60'):
            self.assertFalse(settings.validate_time(t), t)


class ProblemsTest(unittest.TestCase):
    def setUp(self):
        self.qoder = mock.patch('signin.platforms.qoder.login_state',
                                return_value=LoginState(False, message='未登录'))
        self.workbuddy = mock.patch('signin.platforms.workbuddy.login_state',
                                    return_value=LoginState(False, message='未登录'))
        self.qoder.start()
        self.workbuddy.start()
        self.addCleanup(mock.patch.stopall)

    def test_enabled_but_not_logged_in(self):
        form = _form()
        form['enabled']['qoder'] = True
        problems = settings.problems(form)
        self.assertTrue(any('Qoder' in text for _, text in problems))

    def test_trae_gui_click_counts_as_configured(self):
        form = _form()
        form['enabled']['trae'] = True
        form['trae']['gui_click'] = {'window': 'Trae CN', 'x_ratio': 0.5, 'y_ratio': 0.9}
        problems = settings.problems(form)
        self.assertFalse(any('Trae' in text for _, text in problems))

    def test_complete_form_has_no_problem(self):
        form = _form()
        form['enabled'] = {k: False for k in platforms.keys()}
        form['enabled']['qoder'] = True
        form['enabled']['workbuddy'] = True
        form['enabled']['doubao'] = True
        for name in (self.qoder, self.workbuddy):
            mock.patch.stopall()
        with mock.patch('signin.platforms.qoder.login_state', return_value=LoginState(True)):
            with mock.patch('signin.platforms.workbuddy.login_state', return_value=LoginState(True)):
                with mock.patch('signin.platforms.doubao.login_state', return_value=LoginState(True)):
                    self.assertEqual(settings.problems(form), [])

    def test_nothing_enabled_is_reported(self):
        form = _form()
        form['enabled'] = {k: False for k in platforms.keys()}
        problems = settings.problems(form)
        self.assertEqual(len(problems), 1)

    def test_qoder_requires_client_login(self):
        form = _form()
        form['enabled']['qoder'] = True
        problems = settings.problems(form)
        self.assertTrue(any('登录' in text for _, text in problems))

    def test_ready_helper(self):
        form = _form()
        form['enabled']['qoder'] = True
        mock.patch.stopall()
        with mock.patch('signin.platforms.qoder.login_state', return_value=LoginState(True)):
            self.assertTrue(settings.ready(form, 'qoder'))
        self.assertFalse(settings.ready(form, 'trae'))


class CredentialTest(unittest.TestCase):
    def test_masked(self):
        self.assertIn('***', settings.credential_text('pt-abcdefgh'))
        self.assertEqual(settings.credential_text(''), '未填写')


class SaveTest(unittest.TestCase):
    def test_save_drops_internal_key(self):
        cfg = config.load(None)
        cfg['_path'] = 'C:/tmp/config.json'
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_cfg.json')
        try:
            settings.save_config(path, cfg)
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            self.assertNotIn('_path', data)
            self.assertIn('trae', data)
        finally:
            if os.path.exists(path):
                os.remove(path)


class TaskCommandTest(unittest.TestCase):
    def test_install_command(self):
        cmd = settings.task_command(r'C:\repo', '10:10')
        self.assertEqual(cmd[0], 'powershell.exe')
        self.assertTrue(any('install_task.ps1' in part for part in cmd))
        self.assertIn('-Time', cmd)
        self.assertIn('10:10', cmd)

    def test_remove_command(self):
        cmd = settings.remove_task_command(r'C:\repo')
        self.assertIn('-Remove', cmd)

    def test_task_state_tolerates_missing_stdout(self):
        # pythonw 下 subprocess 的 stdout 可能是 None，不能因此崩掉界面
        class _Out:
            returncode = 0
            stdout = None
            stderr = None

        with mock.patch('subprocess.run', return_value=_Out()):
            self.assertEqual(settings.task_state(), '已注册')


if __name__ == '__main__':
    unittest.main()
