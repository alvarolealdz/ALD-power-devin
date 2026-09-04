"""AGENTS.md: nothing in foundation/ or scaffold/ may reference a business domain."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN = ("kyc", "ticket", "refund", "invoice", "customer", "loan", "payment")


@pytest.mark.parametrize("layer", ["foundation", "scaffold"])
def test_layer_mentions_no_business_domain(layer):
    offenders = []
    for path in (ROOT / layer).rglob("*"):
        if path.is_dir() or path.suffix not in {".py", ".html", ".css", ".j2"}:
            continue
        text = path.read_text().lower()
        offenders += [f"{path.name}: {word}" for word in FORBIDDEN if word in text]
    assert not offenders


@pytest.mark.parametrize("layer", ["foundation", "scaffold"])
def test_layer_never_names_a_generated_app(layer):
    """Apps are discovered, never registered: no foundation edit per app."""
    offenders = [
        path.name for path in (ROOT / layer).rglob("*.py") if "widget" in path.read_text().lower()
    ]
    assert not offenders
