from beastmode.core.routing import route_by_verification_cost


def test_objective_verifier_routes_to_economy() -> None:
    assert route_by_verification_cost(objectively_verifiable=True) == "economy"


def test_current_lane_can_create_verifier_before_frontier_escalation() -> None:
    assert route_by_verification_cost(objectively_verifiable=False, can_create_verifier=True) == "economy"


def test_unverifiable_judgment_routes_to_frontier() -> None:
    assert route_by_verification_cost(objectively_verifiable=False, judgment_required=True) == "frontier"


def test_unverifiable_non_judgment_work_is_blocked() -> None:
    assert route_by_verification_cost(objectively_verifiable=False) == "blocked"
