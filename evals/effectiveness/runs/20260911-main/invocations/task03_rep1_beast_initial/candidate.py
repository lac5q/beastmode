def solve(payload):
    def valid_endpoint(value):
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            and -1000000000 <= value <= 1000000000
        )

    def invalid():
        return {"error": "invalid"}

    if not isinstance(payload, dict):
        return invalid()

    if "intervals" not in payload or "queries" not in payload:
        return invalid()

    raw_intervals = payload["intervals"]
    raw_queries = payload["queries"]

    if (
        not isinstance(raw_intervals, list)
        or not isinstance(raw_queries, list)
        or len(raw_intervals) > 100
        or len(raw_queries) > 100
    ):
        return invalid()

    intervals = []
    for item in raw_intervals:
        if not isinstance(item, list) or len(item) != 2:
            return invalid()

        start, end = item
        if (
            not valid_endpoint(start)
            or not valid_endpoint(end)
            or start >= end
        ):
            return invalid()

        intervals.append((start, end))

    queries = []
    for item in raw_queries:
        if not isinstance(item, list) or len(item) != 2:
            return invalid()

        start, end = item
        if (
            not valid_endpoint(start)
            or not valid_endpoint(end)
            or start > end
        ):
            return invalid()

        queries.append((start, end))

    intervals.sort(key=lambda interval: (interval[0], interval[1]))

    merged = []
    if intervals:
        current_start, current_end = intervals[0]

        for start, end in intervals[1:]:
            if start <= current_end:
                if end > current_end:
                    current_end = end
            else:
                merged.append([current_start, current_end])
                current_start, current_end = start, end

        merged.append([current_start, current_end])

    total = sum(end - start for start, end in merged)

    overlaps = []
    for query_start, query_end in queries:
        covered = 0
        for segment_start, segment_end in merged:
            if segment_end <= query_start:
                continue
            if segment_start >= query_end:
                break

            overlap_start = max(query_start, segment_start)
            overlap_end = min(query_end, segment_end)
            if overlap_start < overlap_end:
                covered += overlap_end - overlap_start

        overlaps.append(covered)

    return {
        "merged": merged,
        "total": total,
        "overlaps": overlaps,
    }
