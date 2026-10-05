"""Unit tests for JWT helpers and password hashing (P0#13)."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch
from uuid import UUID

from pydantic_settings import SettingsConfigDict

import jwt

from api.auth import passwords, tokens
from api.settings import Settings
from db.enums import UserRole


class SettingsNoDotEnv(Settings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")


def _minimal_env():
    return {
        "SESSION_SECRET_KEY": "s" * 32,
        "JWT_SECRET_KEY": "j" * 32,
        "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/db",
    }


class PasswordTests(unittest.TestCase):
    def test_hash_and_verify(self):
        h = passwords.hash_password("correct horse battery staple")
        self.assertTrue(passwords.verify_password("correct horse battery staple", h))
        self.assertFalse(passwords.verify_password("wrong", h))


class TokenTests(unittest.TestCase):
    def test_access_roundtrip(self):
        with patch.dict(os.environ, _minimal_env(), clear=True):
            s = SettingsNoDotEnv()
        uid = UUID("11111111-1111-4111-8111-111111111111")
        tid = UUID("22222222-2222-4222-8222-222222222222")
        token, expires_in = tokens.create_access_token(
            s, user_id=uid, tenant_id=tid, role=UserRole.CLINICIAN
        )
        self.assertGreater(expires_in, 0)
        payload = tokens.decode_access_principal(s, token)
        self.assertEqual(payload["sub"], str(uid))
        self.assertEqual(payload["tid"], str(tid))
        self.assertEqual(payload["role"], "CLINICIAN")

    def test_wrong_typ_rejected_for_access_principal(self):
        with patch.dict(os.environ, _minimal_env(), clear=True):
            s = SettingsNoDotEnv()
        bad = jwt.encode(
            {"sub": "x", "tid": "y", "role": "ADMIN", "typ": "refresh"},
            s.jwt_secret_key,
            algorithm=s.jwt_algorithm,
        )
        with self.assertRaises(jwt.InvalidTokenError):
            tokens.decode_access_principal(s, bad)


if __name__ == "__main__":
    unittest.main()
