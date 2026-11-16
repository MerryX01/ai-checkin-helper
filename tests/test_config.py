"""配置加载、注册表驱动的默认值、环境变量覆盖、密钥打码。"""
import json
import os
import tempfile
import unittest

from signin import platforms
from signin.core import config as cfgmod


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='signin_')
        self.path = os.path.join(self.tmp, 'config.json')

    def write(self, data):
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        return self.path

    def test_defaults_cover_all_platforms(self):
        cfg = cfgmod.load(self.path)
        for key in platforms.keys():
            self.assertIn(key, cfg)
            self.assertIn('enabled', cfg[key])
        self.assertFalse(cfg['trae']['enabled'])
        self.assertTrue(cfg['doubao']['enabled'])

    def test_defaults_include_ui_and_runtime(self):
        cfg = cfgmod.load(self.path)
        self.assertIn('time', cfg['ui'])
        self.assertEqual(cfg['runtime']['retries'], 3)

    def test_file_value_then_env_overrides(self):
        p = self.write({'trae': {'token': 'file-token', 'enabled': True}})
        cfg = cfgmod.load(p)
        self.assertEqual(cfg['trae']['token'], 'file-token')

        os.environ['CHECKIN_TRAE_TOKEN'] = 'env-token'
        try:
            cfg2 = cfgmod.load(p)
            self.assertEqual(cfg2['trae']['token'], 'env-token')
        finally:
            del os.environ['CHECKIN_TRAE_TOKEN']

    def test_env_alone_enables_platform(self):
        os.environ['CHECKIN_TRAE_TOKEN'] = 'tk-env'
        try:
            cfg = cfgmod.load(self.path)
            self.assertEqual(cfg['trae']['token'], 'tk-env')
            self.assertTrue(cfg['trae']['enabled'])
        finally:
            del os.environ['CHECKIN_TRAE_TOKEN']

    def test_malformed_file_raises(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write('{not json')
        with self.assertRaises(cfgmod.ConfigError):
            cfgmod.load(self.path)

    def test_redact_hides_secret(self):
        self.assertEqual(cfgmod.redact('abcdefghijk'), 'abc***')
        self.assertEqual(cfgmod.redact('short'), '***')
        self.assertEqual(cfgmod.redact(''), '')

    def test_redact_dict_masks_nested_keys(self):
        d = {'token': 'abcdefghijk', 'nested': {'cookie': 'sessionid=abcdefghijk'}}
        out = cfgmod.redact_dict(d)
        self.assertEqual(out['token'], 'abc***')
        self.assertEqual(out['nested']['cookie'], 'ses***')

    def test_ensure_config_creates_default_file(self):
        target = cfgmod.ensure_config(self.tmp)
        self.assertTrue(os.path.exists(target))
        with open(target, encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('trae', data)

    def test_enabled_platforms_uses_registry(self):
        cfg = cfgmod.load(self.path)
        cfg['trae']['enabled'] = True
        cfg['doubao']['enabled'] = False
        self.assertEqual(cfgmod.enabled_platforms(cfg), ['trae'])


if __name__ == '__main__':
    unittest.main()
