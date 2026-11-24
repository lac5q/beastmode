"""Independent exact-DOM acceptance validator for the frozen local fixture."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONTRACT = json.loads((ROOT / "contract.json").read_text(encoding="utf-8"))
EXPECTED = CONTRACT["acceptance"]["expected_dom"]

# This expression reads only the final DOM outcome. It deliberately does not
# inspect Agent.status or the model's DONE choice.
DOM_EXPRESSION = r"""
(() => ({
  title: document.title,
  pathname: location.pathname,
  hash: location.hash,
  detail_name: document.querySelector('.detail-copy h1')?.textContent?.trim() ?? null,
  detail_edition: document.querySelector('.detail-copy .edition')?.textContent?.trim() ?? null,
  description: document.querySelector('.detail-copy > p')?.textContent?.trim() ?? null,
  price: document.querySelector('.detail-copy .price')?.textContent?.replace(/\s+/g, ' ').trim() ?? null,
  success: document.querySelector('.detail-copy .success')?.textContent?.trim() ?? null,
  filter_note: document.querySelector('.fixture-note')?.textContent?.trim() ?? null,
  footer: document.querySelector('footer')?.textContent?.replace(/\s+/g, ' ').trim() ?? null
}))()
"""


def verify_snapshot(observed: object) -> dict:
    """Compare every frozen field exactly and return reviewable evidence."""

    if not isinstance(observed, dict):
        return {
            "passed": False,
            "mismatches": {"dom": {"expected": EXPECTED, "actual": observed}},
            "observed": observed,
        }
    mismatches = {
        key: {"expected": expected, "actual": observed.get(key)}
        for key, expected in EXPECTED.items()
        if observed.get(key) != expected
    }
    return {"passed": not mismatches, "mismatches": mismatches, "observed": observed}


def verify_browser(browser) -> dict:
    """Read the browser once and validate exact values independently of Jev."""

    try:
        observed = browser.evaluate(DOM_EXPRESSION)
    except (RuntimeError, ValueError, TypeError, KeyError) as error:  # pragma: no cover - live harness failures
        return {
            "passed": False,
            "mismatches": {"browser_evaluate": {"error": type(error).__name__, "message": str(error)}},
            "observed": None,
        }
    return verify_snapshot(observed)
