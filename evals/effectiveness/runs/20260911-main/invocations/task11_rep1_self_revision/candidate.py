def solve(payload):
    if not isinstance(payload, dict) or set(payload.keys()) != {"capacity", "requests"}:
        return {"error": "invalid"}

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
        return {"error": "invalid"}

    parsed = []
    seen_ids = set()

    for request in requests:
        if not isinstance(request, dict) or set(request.keys()) != {
            "id",
            "units",
            "benefit",
        }:
            return {"error": "invalid"}

        identifier = request["id"]
        units = request["units"]
        benefit = request["benefit"]

        if (
            not isinstance(identifier, str)
            or not identifier
            or len(identifier) > 16
            or isinstance(units, bool)
            or not isinstance(units, int)
            or units < 1
            or units > 30
            or isinstance(benefit, bool)
            or not isinstance(benefit, int)
            or benefit < 1
            or benefit > 1000
            or identifier in seen_ids
        ):
            return {"error": "invalid"}

        seen_ids.add(identifier)
        parsed.append((identifier, units, benefit))

    parsed.sort(key=lambda item: item[0])

    dp = [None] * (capacity + 1)
    dp[0] = (0, ())

    for identifier, units, benefit in parsed:
        for used in range(capacity, units - 1, -1):
            previous = dp[used - units]
            if previous is None:
                continue

            candidate = (
                previous[0] + benefit,
                previous[1] + (identifier,),
            )
            current = dp[used]

            if (
                current is None
                or candidate[0] > current[0]
                or (
                    candidate[0] == current[0]
                    and candidate[1] < current[1]
                )
            ):
                dp[used] = candidate

    best_used = 0
    best_benefit = 0
    best_ids = ()

    for used, state in enumerate(dp):
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
