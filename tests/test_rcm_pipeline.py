"""Unit tests for Revenue Cycle (Section E) — pure logic, no Docker."""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

from pydantic_settings import SettingsConfigDict

from api.services.rcm_charge_capture import charge_capture_hints
from api.services.rcm_codes import suggest_icd10_cpt
from api.services.rcm_denial_risk import compute_denial_risk_score
from api.services.rcm_prebill import run_prebill_audit
from api.services.rcm_shap import phrase_attributions_for_code
from api.services.rcm_validation import validate_codes_against_rules
from api.settings import Settings


class SettingsNoDotEnv(Settings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")


def _minimal_settings() -> SettingsNoDotEnv:
    env = {
        "SESSION_SECRET_KEY": "s" * 32,
        "JWT_SECRET_KEY": "j" * 32,
        "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/db",
        "HEALTHOS_ORCHESTRATOR_CHECKPOINTER": "memory",
    }
    with patch.dict(os.environ, env, clear=True):
        return SettingsNoDotEnv()


class RCMValidationTests(unittest.TestCase):
    def test_validation_supports_lcd_match(self):
        rules = [
            {
                "icd10_codes": ["E119"],
                "cpt_codes": ["99213"],
                "policy_identifier": "L001",
                "rule_narrative": "Stable chronic disease management.",
            }
        ]
        v = validate_codes_against_rules(
            primary_icd="E11.9",
            primary_cpt="99213",
            all_icd=["E11.9"],
            all_cpt=["99213"],
            retrieved_rules=rules,
        )
        self.assertTrue(v["validation_ok"])

    def test_validation_detects_icd_mismatch(self):
        rules = [
            {
                "icd10_codes": ["I10"],
                "cpt_codes": ["99213"],
                "policy_identifier": "L002",
                "rule_narrative": "Hypertension management only.",
            }
        ]
        v = validate_codes_against_rules(
            primary_icd="E11.9",
            primary_cpt="99213",
            all_icd=["E11.9", "I10"],
            all_cpt=["99213"],
            retrieved_rules=rules,
        )
        self.assertIn("ICD_LCD_MISMATCH", v["flags"])


class RCMAttributionTests(unittest.TestCase):
    def test_shap_like_weights_sum_to_one(self):
        text = "Type 2 diabetes follow-up. Blood pressure elevated today."
        r = phrase_attributions_for_code(
            text,
            code="E11.9",
            description="Type 2 diabetes mellitus",
        )
        vals = [p["shap_value"] for p in r["phrases"]]
        self.assertTrue(vals)
        self.assertAlmostEqual(sum(vals), 1.0, places=5)


class RCMDenialRiskTests(unittest.TestCase):
    def test_risk_increases_with_low_confidence(self):
        low = compute_denial_risk_score(
            icd_confidence=0.5,
            cpt_confidence=0.5,
            validation={"validation_ok": True, "reasons": [], "flags": []},
            prebill_score_ratio=1.0,
            cpt_risk_flags=[],
        )
        high = compute_denial_risk_score(
            icd_confidence=0.95,
            cpt_confidence=0.95,
            validation={"validation_ok": True, "reasons": [], "flags": []},
            prebill_score_ratio=1.0,
            cpt_risk_flags=[],
        )
        self.assertGreater(low["risk_score"], high["risk_score"])


class RCMStubSuggestTests(unittest.TestCase):
    def test_stub_diabetes_icd(self):
        settings = _minimal_settings()

        async def _run():
            return await suggest_icd10_cpt(
                clinical_note="Established patient with type 2 diabetes follow-up.",
                specialty="GENERAL",
                procedure_description=None,
                openrouter=None,
                settings=settings,
                state={},
            )

        out = asyncio.run(_run())
        codes = [x["code"] for x in out["icd10"]]
        self.assertIn("E11.9", codes)


class RCMChargeCaptureTests(unittest.TestCase):
    def test_detects_missing_injection_code(self):
        h = charge_capture_hints(
            "Patient received steroid injection today for knee pain.",
            suggested_cpt_codes=["99213"],
        )
        self.assertTrue(h["review_recommended"])
        codes = [x["likely_cpt"] for x in h["possible_missed_services"]]
        self.assertIn("96372", codes)


class RCMPrebillTests(unittest.TestCase):
    def test_prebill_returns_twelve_checkpoints(self):
        pb = run_prebill_audit(
            clinical_note="Assessment and plan for hypertension with medication adjustment.",
            primary_icd="I10",
            primary_cpt="99214",
            validation={"validation_ok": True},
            cpt_entry={"risk_flags": []},
            payer_org="DEMO",
        )
        self.assertEqual(pb["total"], 12)


if __name__ == "__main__":
    unittest.main()
