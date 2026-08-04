"""Verification-cost routing rule shared by future framework bindings."""

from __future__ import annotations

from typing import Literal


Route = Literal["economy", "frontier", "blocked"]


def route_by_verification_cost(
    *,
    objectively_verifiable: bool,
    can_create_verifier: bool = False,
    judgment_required: bool = False,
) -> Route:
    """Route cheap when an objective verifier exists; otherwise require judgment."""
    if objectively_verifiable or can_create_verifier:
        return "economy"
    if judgment_required:
        return "frontier"
    return "blocked"
