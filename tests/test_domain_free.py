"""AGENTS.md: nothing in foundation/ may reference a business domain."""

from pathlib import Path

FOUNDATION = Path(__file__).resolve().parent.parent / "foundation"
FORBIDDEN = ("kyc", "ticket", "refund", "invoice", "customer", "loan", "payment")


def test_foundation_mentions_no_business_domain():
    offenders = []
    for path in FOUNDATION.rglob("*"):
        if path.is_dir() or path.suffix not in {".py", ".html", ".css"}:
            continue
        text = path.read_text().lower()
        offenders += [f"{path.name}: {word}" for word in FORBIDDEN if word in text]
    assert not offenders
