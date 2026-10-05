"""Unit tests for FHIR helpers (no live HAPI required)."""

from __future__ import annotations

import unittest

from api.fhir.hl7v2 import (
    parse_pid_segment,
    pid_to_fhir_patient_draft,
    split_hl7_segments,
)
from api.fhir.mappers import (
    encounter_period_to_datetimes,
    encounter_to_internal_metadata,
    patient_dedup_fingerprint,
    validate_document_reference,
    validate_encounter,
    validate_patient,
)
from api.fhir.observation_norm import normalize_observation
from api.fhir.smart import build_authorize_url


class ObservationNormTests(unittest.TestCase):
    def test_lb_to_kg(self):
        obs = {
            "resourceType": "Observation",
            "valueQuantity": {
                "value": 220,
                "unit": "lb",
                "system": "http://unitsofmeasure.org",
                "code": "[lb_av]",
            },
        }
        out = normalize_observation(obs)
        self.assertAlmostEqual(out["valueQuantity"]["value"], 99.79, places=1)
        self.assertEqual(out["valueQuantity"]["code"], "kg")


class PatientDedupTests(unittest.TestCase):
    def test_fingerprint_stable(self):
        p = {
            "resourceType": "Patient",
            "name": [{"family": "Smith", "given": ["Jane"]}],
            "birthDate": "1990-05-05",
            "address": [
                {
                    "line": ["1 Main"],
                    "city": "Boston",
                    "state": "MA",
                    "postalCode": "02101",
                }
            ],
        }
        a = patient_dedup_fingerprint(p)
        b = patient_dedup_fingerprint(dict(p))
        self.assertEqual(a, b)


class SmartUrlTests(unittest.TestCase):
    def test_authorize_url_contains_params(self):
        u = build_authorize_url(
            authorize_endpoint="https://ehr.example.com/auth/authorize",
            client_id="cid",
            redirect_uri="https://app/cb",
            scope="launch/patient",
            state="xyz",
            aud="https://ehr.example.com/fhir",
        )
        self.assertIn("client_id=cid", u)
        self.assertIn("aud=https%3A%2F%2Fehr.example.com%2Ffhir", u)


class HL7PidTests(unittest.TestCase):
    def test_parse_pid(self):
        msg = "MSH|^~\\&\rPID|1||12345^^^MRN||Doe^John||19800115|M|||123 St^^Austin^TX^78701^USA"
        segs = split_hl7_segments(msg)
        pid = next(s for s in segs if s.startswith("PID|"))
        p = parse_pid_segment(pid)
        self.assertEqual(p.family_name, "Doe")
        self.assertEqual(p.given_name, "John")
        self.assertEqual(p.birth_date, "19800115")
        draft = pid_to_fhir_patient_draft(p)
        self.assertEqual(draft["resourceType"], "Patient")
        self.assertEqual(draft["birthDate"], "1980-01-15")


class FhirResourcesValidationTests(unittest.TestCase):
    def test_validate_minimal_patient(self):
        out = validate_patient(
            {
                "resourceType": "Patient",
                "active": True,
                "gender": "unknown",
            }
        )
        self.assertEqual(out["resourceType"], "Patient")

    def test_validate_r4_encounter_from_hapi_seed(self):
        """HAPI R4 seed uses ``class`` Coding, ``period``, and ``reasonCode``."""
        out = validate_encounter(
            {
                "resourceType": "Encounter",
                "id": "healthos-sample-encounter-001",
                "status": "finished",
                "class": {
                    "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                    "code": "AMB",
                    "display": "ambulatory",
                },
                "type": [
                    {
                        "coding": [
                            {
                                "system": "http://snomed.info/sct",
                                "code": "185349003",
                                "display": "Encounter for check up",
                            }
                        ],
                        "text": "Annual physical",
                    }
                ],
                "subject": {"reference": "Patient/healthos-sample-patient-001"},
                "period": {
                    "start": "2024-01-15T09:00:00+00:00",
                    "end": "2024-01-15T09:45:00+00:00",
                },
                "reasonCode": [{"text": "Annual physical"}],
            }
        )
        self.assertEqual(out["resourceType"], "Encounter")
        self.assertEqual(out["status"], "finished")
        self.assertIn("actualPeriod", out)
        meta = encounter_to_internal_metadata(out)
        self.assertEqual(meta["fhir_reason_text"], "Annual physical")
        started, ended = encounter_period_to_datetimes(out)
        self.assertIsNotNone(started)
        self.assertIsNotNone(ended)

    def test_validate_r4_document_reference_for_note_writeback(self):
        out = validate_document_reference(
            {
                "resourceType": "DocumentReference",
                "status": "current",
                "type": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": "11506-3",
                            "display": "Progress note",
                        }
                    ]
                },
                "subject": {"reference": "Patient/healthos-sample-patient-001"},
                "date": "2024-01-15T09:00:00Z",
                "content": [
                    {
                        "attachment": {
                            "contentType": "text/plain; charset=utf-8",
                            "data": "dGVzdA==",
                            "title": "SOAP Note",
                        }
                    }
                ],
                "context": {
                    "encounter": [
                        {"reference": "Encounter/healthos-sample-encounter-001"}
                    ]
                },
            }
        )
        self.assertEqual(out["resourceType"], "DocumentReference")
        self.assertIsInstance(out["context"], list)
        self.assertEqual(
            out["context"][0]["reference"], "Encounter/healthos-sample-encounter-001"
        )


if __name__ == "__main__":
    unittest.main()
