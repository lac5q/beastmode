import heapq


def _invalid():
    return {"error": "invalid"}


def solve(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("intervals"), list):
        return _invalid()
    if len(payload["intervals"]) > 100:
        return _invalid()
    intervals = []
    seen = set()
    for item in payload["intervals"]:
        if not isinstance(item, dict):
            return _invalid()
        ident, start, end = item.get("id"), item.get("start"), item.get("end")
        if (not isinstance(ident, str) or not ident or len(ident) > 40 or ident in seen
                or isinstance(start, bool) or not isinstance(start, int)
                or isinstance(end, bool) or not isinstance(end, int) or abs(start) > 1000000000
                or abs(end) > 1000000000 or start >= end):
            return _invalid()
        seen.add(ident)
        intervals.append((start, ident, end))
    intervals.sort(key=lambda value: (value[0], value[1]))
    busy = []
    free = []
    next_room = 1
    assignment = {}
    order = []
    for start, ident, end in intervals:
        while busy and busy[0][0] <= start:
            _, room = heapq.heappop(busy)
            heapq.heappush(free, room)
        if free:
            room = heapq.heappop(free)
        else:
            room = next_room
            next_room += 1
        heapq.heappush(busy, (end, room))
        assignment[ident] = room
        order.append(ident)
    return {"rooms": next_room - 1, "assignment": assignment, "order": order}
