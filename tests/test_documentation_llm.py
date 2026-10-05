"""Unit tests for documentation LLM JSON parsing."""

from __future__ import annotations

import unittest

from api.services.documentation_llm import _parse_json_object, soap_payload_to_note_soap


class ParseJsonObjectTests(unittest.TestCase):
    def test_extracts_json_from_prose_and_markdown_fence(self):
        raw = """Here is the JSON object in SOAP style:

```
{
  "subjective": "S text",
  "objective": "O text",
  "assessment": "A text",
  "plan": "P text",
  "icd10_suggestions": [],
  "confidence": 0.8
}
```

Note: extra commentary after the block."""
        out = _parse_json_object(raw)
        self.assertEqual(out["subjective"], "S text")
        self.assertEqual(out["objective"], "O text")
        self.assertEqual(out["assessment"], "A text")
        self.assertEqual(out["plan"], "P text")

    def test_parses_bare_json_object(self):
        out = _parse_json_object('{"subjective": "x", "objective": "y"}')
        self.assertEqual(out["subjective"], "x")


class SoapPayloadTests(unittest.TestCase):
    def test_icd10_appended_to_plan(self):
        note = soap_payload_to_note_soap(
            {
                "subjective": "s",
                "objective": "o",
                "assessment": "a",
                "plan": "Continue meds.",
                "icd10_suggestions": [
                    {"code": "E11.9", "rationale": "Type 2 diabetes"},
                ],
            }
        )
        self.assertIn("Continue meds.", note["plan"])
        self.assertIn("E11.9", note["plan"])
        self.assertEqual(note["subjective"], "s")


if __name__ == "__main__":
    unittest.main()
