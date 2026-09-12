def solve(payload):
    invalid = {"error": "invalid"}

    if not isinstance(payload, dict) or set(payload.keys()) != {"capacity", "requests"}:
        return invalid

    capacity = payload["capacity"]
    requests = payload["requests"]

    if (
        isinstance(capacity, bool)
        or not isinstance(capacity, int)
        or capacity < 0
        or capacity > 120
        or not isinstance(requests, list)
        or len(requests) > 40
    ):
        return invalid

    seen = set()
    items = []

    for request in requests:
        if not isinstance(request, dict) or set(request.keys()) != {
            "id",
            "units",
            "benefit",
        }:
            return invalid

        identifier = request["id"]
        units = request["units"]
        benefit = request["benefit"]

        if (
            not isinstance(identifier, str)
            or not identifier
            or len(identifier) > 16
            or identifier in seen
            or isinstance(units, bool)
            or not isinstance(units, int)
            or units < 1
            or units > 30
            or isinstance(benefit, bool)
            or not isinstance(benefit, int)
            or benefit < 1
            or benefit > 1000
        ):
            return invalid

        seen.add(identifier)
        items.append((identifier, units, benefit))

    items.sort(key=lambda item: item[0])

    states = [None] * (capacity + 1)
    states[0] = (0, ())

    for identifier, units, benefit in items:
        if units > capacity:
            continue

        for used in range(capacity - units, -1, -1):
            state = states[used]
            if state is None:
                continue

            new_used = used + units
            new_benefit = state[0] + benefit
            new_ids = state[1] + (identifier,)
            current = states[new_used]

            if (
                current is None
                or new_benefit > current[0]
                or (
                    new_benefit == current[0]
                    and new_ids < current[1]
                )
            ):
                states[new_used] = (new_benefit, new_ids)

    best_used = 0
    best_benefit = 0
    best_ids = ()

    for used, state in enumerate(states):
        if state is None:
            continue

        benefit, ids = state
        if (
            benefit > best_benefit
            or (
                benefit == best_benefit
                and (
                    used < best_used
                    or (used == best_used and ids < best_ids)
                )
            )
        ):
            best_used = used
            best_benefit = benefit
            best_ids = ids

    return {
        "selected": list(best_ids),
        "used": best_used,
        "benefit": best_benefit,
    }
