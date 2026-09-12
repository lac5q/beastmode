def _invalid():
    return {"error": "invalid"}


def _interval(value, allow_empty):
    if not isinstance(value, list) or len(value) != 2:
        return None
    start, end = value
    if any(isinstance(x, bool) or not isinstance(x, int) for x in (start, end)):
        return None
    if abs(start) > 1000000000 or abs(end) > 1000000000 or start > end or (start == end and not allow_empty):
        return None
    return start, end


def solve(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("intervals"), list) or not isinstance(payload.get("queries"), list):
        return _invalid()
    if len(payload["intervals"]) > 100 or len(payload["queries"]) > 100:
        return _invalid()
    intervals = []
    for value in payload["intervals"]:
        item = _interval(value, False)
        if item is None:
            return _invalid()
        intervals.append(item)
    queries = []
    for value in payload["queries"]:
        item = _interval(value, True)
        if item is None:
            return _invalid()
        queries.append(item)
    intervals.sort()
    merged = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    overlaps = []
    for qstart, qend in queries:
        overlaps.append(sum(max(0, min(qend, end) - max(qstart, start)) for start, end in merged))
    return {
        "merged": merged,
        "total": sum(end - start for start, end in merged),
        "overlaps": overlaps,
    }
