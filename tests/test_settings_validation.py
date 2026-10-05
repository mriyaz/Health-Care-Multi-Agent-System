"""Settings load and validation (P0#11)."""

import os
import unittest
from unittest.mock import patch

from pydantic import ValidationError
from pydantic_settings import SettingsConfigDict

from api.settings import Settings


class SettingsNoDotEnv(Settings):
    """Same as production Settings but does not read `.env` — keeps tests deterministic."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")


class SettingsValidationTests(unittest.TestCase):
    def test_requires_session_secret_and_db_via_url(self):
        env = {
            "SESSION_SECRET_KEY": "x" * 32,
            "JWT_SECRET_KEY": "j" * 32,
            "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/db",
        }
        with patch.dict(os.environ, env, clear=True):
            s = SettingsNoDotEnv()
            self.assertEqual(s.session_secret_key, "x" * 32)
            self.assertEqual(s.get_async_database_url(), env["DATABASE_URL"])

    def test_requires_postgres_password_when_no_database_url(self):
        env = {
            "SESSION_SECRET_KEY": "y" * 32,
            "JWT_SECRET_KEY": "k" * 32,
            "POSTGRES_PASSWORD": "secret-db-pass",
        }
        with patch.dict(os.environ, env, clear=True):
            s = SettingsNoDotEnv()
            self.assertIn("secret-db-pass", s.get_async_database_url())

    def test_rejects_missing_session_secret(self):
        env = {
            "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/db",
            "JWT_SECRET_KEY": "j" * 32,
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ValidationError):
                SettingsNoDotEnv()

    def test_rejects_short_session_secret(self):
        env = {
            "SESSION_SECRET_KEY": "short",
            "JWT_SECRET_KEY": "j" * 32,
            "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/db",
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ValidationError):
                SettingsNoDotEnv()

    def test_strips_whitespace_from_openrouter_model_ids(self):
        env = {
            "SESSION_SECRET_KEY": "x" * 32,
            "JWT_SECRET_KEY": "j" * 32,
            "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/db",
            "OPENROUTER_MODEL_DEV": " meta-llama/llama-3.1-8b-instruct ",
            "OPENROUTER_MODEL_PRODUCTION": " meta-llama/llama-3.1-8b-instruct ",
            "OPENROUTER_MODEL_DEMO": " meta-llama/llama-3.1-8b-instruct ",
        }
        with patch.dict(os.environ, env, clear=True):
            s = SettingsNoDotEnv()
            self.assertEqual(s.openrouter_model_dev, "meta-llama/llama-3.1-8b-instruct")
            self.assertEqual(
                s.openrouter_model_production, "meta-llama/llama-3.1-8b-instruct"
            )
            self.assertEqual(
                s.openrouter_model_demo, "meta-llama/llama-3.1-8b-instruct"
            )

    def test_rejects_missing_db_when_no_postgres_password(self):
        env = {"SESSION_SECRET_KEY": "z" * 32, "JWT_SECRET_KEY": "j" * 32}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ValidationError) as ctx:
                SettingsNoDotEnv()
            self.assertIn("Database configuration incomplete", str(ctx.exception))

    def test_rejects_missing_jwt_secret(self):
        env = {
            "SESSION_SECRET_KEY": "z" * 32,
            "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/db",
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ValidationError):
                SettingsNoDotEnv()


if __name__ == "__main__":
    unittest.main()
