def solve(payload):
    if not isinstance(payload, dict):
        return {"error": "invalid"}

    if "intervals" not in payload or "queries" not in payload:
        return {"error": "invalid"}

    intervals = payload["intervals"]
    queries = payload["queries"]

    if not isinstance(intervals, list) or not isinstance(queries, list):
        return {"error": "invalid"}

    if len(intervals) > 100 or len(queries) > 100:
        return {"error": "invalid"}

    def valid_endpoint(value):
        return type(value) is int and -1000000000 <= value <= 1000000000

    normalized = []

    for interval in intervals:
        if (
            not isinstance(interval, list)
            or len(interval) != 2
            or not valid_endpoint(interval[0])
            or not valid_endpoint(interval[1])
            or interval[0] >= interval[1]
        ):
            return {"error": "invalid"}

        normalized.append((interval[0], interval[1]))

    for query in queries:
        if (
            not isinstance(query, list)
            or len(query) != 2
            or not valid_endpoint(query[0])
            or not valid_endpoint(query[1])
            or query[0] > query[1]
        ):
            return {"error": "invalid"}

    normalized.sort()

    merged = []
    for start, end in normalized:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        elif end > merged[-1][1]:
            merged[-1][1] = end

    total = sum(end - start for start, end in merged)

    overlaps = []
    for query_start, query_end in queries:
        covered = 0
        for interval_start, interval_end in merged:
            left = max(query_start, interval_start)
            right = min(query_end, interval_end)
            if left < right:
                covered += right - left
        overlaps.append(covered)

    return {
        "merged": merged,
        "total": total,
        "overlaps": overlaps,
    }
