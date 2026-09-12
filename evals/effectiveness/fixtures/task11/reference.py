def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _better(candidate, current):
    if current is None:
        return True
    if candidate[0] != current[0]:
        return candidate[0] > current[0]
    if candidate[1] != current[1]:
        return candidate[1] < current[1]
    return candidate[2] < current[2]


def solve(payload):
    if not isinstance(payload, dict) or set(payload) != {"capacity", "requests"}:
        return {"error": "invalid"}
    capacity = payload["capacity"]
    requests = payload["requests"]
    if not _integer(capacity) or not 0 <= capacity <= 120:
        return {"error": "invalid"}
    if not isinstance(requests, list) or len(requests) > 40:
        return {"error": "invalid"}
    seen = set()
    for request in requests:
        if not isinstance(request, dict) or set(request) != {"id", "units", "benefit"}:
            return {"error": "invalid"}
        ident = request["id"]
        if (
            not isinstance(ident, str)
            or not 1 <= len(ident) <= 16
            or ident in seen
            or not _integer(request["units"])
            or not 1 <= request["units"] <= 30
            or not _integer(request["benefit"])
            or not 1 <= request["benefit"] <= 1000
        ):
            return {"error": "invalid"}
        seen.add(ident)
    dp = [None] * (capacity + 1)
    dp[0] = (0, 0, ())
    for request in requests:
        units = request["units"]
        benefit = request["benefit"]
        ident = request["id"]
        for used in range(capacity - units, -1, -1):
            current = dp[used]
            if current is None:
                continue
            candidate_ids = tuple(sorted(current[2] + (ident,)))
            candidate = (
                current[0] + benefit,
                current[1] + units,
                candidate_ids,
            )
            target = used + units
            if _better(candidate, dp[target]):
                dp[target] = candidate
    best = None
    for candidate in dp:
        if candidate is not None and _better(candidate, best):
            best = candidate
    return {"selected": list(best[2]), "used": best[1], "benefit": best[0]}
