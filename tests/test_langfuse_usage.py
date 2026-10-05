"""Unit tests for Langfuse usage mapping helpers (no live Langfuse server)."""

from api.observability.langfuse_client import usage_to_langfuse


def test_usage_to_langfuse_maps_openai_shape():
    u = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    assert usage_to_langfuse(u) == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }


def test_usage_to_langfuse_empty():
    assert usage_to_langfuse(None) == {}
    assert usage_to_langfuse({}) == {}
