"""Task T8 verify: known-model test + explicit missing-model-returns-null test."""

from app.services.cost_service import compute_cost_usd


def test_known_model_returns_positive_cost():
    cost = compute_cost_usd("gpt-4o", prompt_tokens=100, completion_tokens=50)
    assert cost is not None
    assert cost > 0


def test_unknown_model_returns_none_not_zero():
    """eng-review D6: a missing price must never silently read as free."""
    cost = compute_cost_usd("totally-fake-model-xyz", prompt_tokens=100, completion_tokens=50)
    assert cost is None


def test_missing_token_counts_returns_none():
    assert compute_cost_usd("gpt-4o", prompt_tokens=None, completion_tokens=50) is None
    assert compute_cost_usd("gpt-4o", prompt_tokens=100, completion_tokens=None) is None
