"""注册表：平台元数据自洽，新增平台无需改其他层。"""
import unittest

from signin import platforms
from signin.core import config
from signin.services import settings


class RegistryTest(unittest.TestCase):
    def test_keys_order_and_uniqueness(self):
        keys = platforms.keys()
        self.assertEqual(keys, ('trae', 'qoder', 'workbuddy', 'doubao'))
        self.assertEqual(len(keys), len(set(keys)))

    def test_every_spec_is_complete(self):
        for spec in platforms.all_specs():
            self.assertTrue(spec.label)
            self.assertTrue(spec.summary)
            self.assertTrue(spec.description)
            self.assertTrue(callable(spec.run))
            self.assertTrue(spec.fields, f'{spec.key} 没有可编辑字段')
            for fld in spec.fields:
                self.assertIn(fld.kind, ('text', 'secret', 'path', 'int', 'bool'))
                self.assertTrue(fld.label)

    def test_labels_sync_with_registry(self):
        from signin.core.models import LABELS
        for spec in platforms.all_specs():
            self.assertEqual(LABELS[spec.key], spec.label)

    def test_config_defaults_match_specs(self):
        for spec in platforms.all_specs():
            self.assertIn(spec.key, config.DEFAULTS)
            for fld in spec.fields:
                self.assertIn(fld.key, config.DEFAULTS[spec.key])
            for key in spec.defaults:
                self.assertIn(key, config.DEFAULTS[spec.key])

    def test_env_map_covers_every_declared_env(self):
        declared = {f.env for s in platforms.all_specs() for f in s.fields if f.env}
        self.assertTrue(declared)
        self.assertTrue(declared.issubset(set(config.ENV_MAP.keys())))

    def test_login_urls_derived(self):
        urls = settings.login_urls()
        self.assertIn('qoder', urls)
        self.assertNotIn('doubao', urls, '豆包没有网页登录页')

    def test_unknown_key_raises(self):
        with self.assertRaises(KeyError):
            platforms.get('nope')


if __name__ == '__main__':
    unittest.main()
