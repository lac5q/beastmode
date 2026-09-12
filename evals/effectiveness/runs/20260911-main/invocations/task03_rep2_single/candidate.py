def solve(payload):
    def is_integer(value):
        return type(value) is int

    def invalid():
        return {"error": "invalid"}

    if type(payload) is not dict:
        return invalid()
    if "intervals" not in payload or "queries" not in payload:
        return invalid()

    intervals = payload["intervals"]
    queries = payload["queries"]

    if type(intervals) is not list or type(queries) is not list:
        return invalid()
    if len(intervals) > 100 or len(queries) > 100:
        return invalid()

    parsed_intervals = []
    for interval in intervals:
        if type(interval) is not list or len(interval) != 2:
            return invalid()
        start, end = interval
        if (
            not is_integer(start)
            or not is_integer(end)
            or start < -1000000000
            or start > 1000000000
            or end < -1000000000
            or end > 1000000000
            or start >= end
        ):
            return invalid()
        parsed_intervals.append((start, end))

    parsed_queries = []
    for query in queries:
        if type(query) is not list or len(query) != 2:
            return invalid()
        start, end = query
        if (
            not is_integer(start)
            or not is_integer(end)
            or start < -1000000000
            or start > 1000000000
            or end < -1000000000
            or end > 1000000000
            or start > end
        ):
            return invalid()
        parsed_queries.append((start, end))

    parsed_intervals.sort()

    merged = []
    for start, end in parsed_intervals:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        elif end > merged[-1][1]:
            merged[-1][1] = end

    total = sum(end - start for start, end in merged)

    overlaps = []
    for query_start, query_end in parsed_queries:
        length = 0
        for interval_start, interval_end in merged:
            left = max(query_start, interval_start)
            right = min(query_end, interval_end)
            if left < right:
                length += right - left
        overlaps.append(length)

    return {
        "merged": merged,
        "total": total,
        "overlaps": overlaps,
    }
