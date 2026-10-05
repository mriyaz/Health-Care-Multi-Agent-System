"""Unit tests for Clinical Documentation helpers (Section D) — no DB / no Whisper."""

from __future__ import annotations

import unittest

from api.services.note_quality import (
    combined_documentation_confidence,
    validate_soap_structure,
)
from api.services.phi_deidentify import deidentify_clinical_text, relink_placeholders


class PhiDeidentifyTests(unittest.TestCase):
    def test_phone_like_patterns_replaced(self):
        raw = "Call 555-123-4567 after visit."
        r = deidentify_clinical_text(raw)
        self.assertNotIn("555", r.text)
        self.assertIn("[[PHI_", r.text)

    def test_relink_roundtrip(self):
        raw = "Patient email patient@test.com here."
        r = deidentify_clinical_text(raw)
        restored = relink_placeholders(r.text, r.token_map)
        self.assertIn("patient@test.com", restored)


class SoapQualityTests(unittest.TestCase):
    def test_validate_soap_flags_short_sections(self):
        soap = {
            "subjective": "x" * 100,
            "objective": "y",
            "assessment": "z",
            "plan": "p" * 20,
        }
        conf, flagged = validate_soap_structure(soap, min_words_per_section=5)
        self.assertLess(conf, 1.0)
        self.assertIn("objective", flagged)
        self.assertIn("assessment", flagged)

    def test_combined_confidence(self):
        c = combined_documentation_confidence(0.9, 0.5)
        self.assertEqual(c, 0.5)


if __name__ == "__main__":
    unittest.main()
