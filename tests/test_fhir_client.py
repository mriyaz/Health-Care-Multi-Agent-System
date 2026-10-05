"""FhirRestClient with mocked HTTP transport."""

from __future__ import annotations

import unittest

import httpx

from api.fhir.client import FhirRestClient, FhirRestError


class FhirRestClientTests(unittest.TestCase):
    def test_read_patient(self):
        payload = {"resourceType": "Patient", "id": "p1", "active": True}

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertIn("/Patient/p1", str(request.url))
            return httpx.Response(200, json=payload)

        transport = httpx.MockTransport(handler)

        async def run():
            async with httpx.AsyncClient(transport=transport) as http:
                c = FhirRestClient(base_url="http://h/fhir", http=http)
                got = await c.read("Patient", "p1")
                self.assertEqual(got["id"], "p1")

        import asyncio

        asyncio.run(run())

    def test_error_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="not found")

        transport = httpx.MockTransport(handler)

        async def run():
            async with httpx.AsyncClient(transport=transport) as http:
                c = FhirRestClient(base_url="http://h/fhir", http=http)
                with self.assertRaises(FhirRestError):
                    await c.read("Patient", "missing")

        import asyncio

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
