"""Smoke tests for the LangGraph echo pipeline (P0#9)."""

import unittest

from api.graphs.echo_graph import compile_echo_graph


class EchoGraphTests(unittest.TestCase):
    def test_echo_returns_same_text(self):
        app = compile_echo_graph()
        result = app.invoke({"input_text": "healthos-smoke"})
        self.assertEqual(result.get("output_text"), "healthos-smoke")

    def test_echo_empty_input(self):
        app = compile_echo_graph()
        result = app.invoke({"input_text": ""})
        self.assertEqual(result.get("output_text"), "")


if __name__ == "__main__":
    unittest.main()
