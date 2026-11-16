"""AES-256-GCM 解密：固定向量（由独立实现生成并核对过）+ 篡改检测。"""
import unittest

from signin.core.aesgcm import gcm_decrypt

KEY = bytes(range(32))
NONCE = bytes(range(12))
CIPHERTEXT = bytes.fromhex(
    "a09b6dfe7870249b0ca910215463d0850d6162bb669cc6c7ddda70639de8e835"
    "abf52454474fa57dfb329874336295ad08d9e165dd7c4650977fa4aefd6c63"
)
TAG = bytes.fromhex("4d07329774e02ff73bda0eed78bbca7c")
PLAINTEXT = bytes.fromhex(
    "e799bbe5bd95e68081e887aae58aa8e88eb7e58f96"
    "e799bbe5bd95e68081e887aae58aa8e88eb7e58f96"
    "e799bbe5bd95e68081e887aae58aa8e88eb7e58f96"
)


class AesGcmTest(unittest.TestCase):
    def test_known_vector(self):
        self.assertEqual(gcm_decrypt(KEY, NONCE, CIPHERTEXT, TAG), PLAINTEXT)

    def test_empty_payload_tag(self):
        # NIST：全 0 密钥、全 0 nonce、空明文 → tag 530f8afb...
        self.assertEqual(
            gcm_decrypt(b"\x00" * 32, b"\x00" * 12, b"", bytes.fromhex("530f8afbc74536b9a963b4f1c4cb738b")),
            b"",
        )

    def test_tampered_tag_is_rejected(self):
        with self.assertRaises(ValueError):
            gcm_decrypt(KEY, NONCE, CIPHERTEXT, b"\x00" * 16)

    def test_wrong_key_is_rejected(self):
        with self.assertRaises(ValueError):
            gcm_decrypt(b"\x01" * 32, NONCE, CIPHERTEXT, TAG)

    def test_key_length_is_checked(self):
        with self.assertRaises(ValueError):
            gcm_decrypt(b"\x00" * 16, NONCE, CIPHERTEXT, TAG)


if __name__ == '__main__':
    unittest.main()
