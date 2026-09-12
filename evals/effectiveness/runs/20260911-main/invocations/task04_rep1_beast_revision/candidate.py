import heapq


def solve(payload):
    if not isinstance(payload, dict) or "intervals" not in payload:
        return {"error": "invalid"}

    intervals = payload["intervals"]
    if not isinstance(intervals, list) or len(intervals) > 100:
        return {"error": "invalid"}

    records = []
    seen = set()

    for interval in intervals:
        if not isinstance(interval, dict):
            return {"error": "invalid"}
        if "id" not in interval or "start" not in interval or "end" not in interval:
            return {"error": "invalid"}

        ident = interval["id"]
        start = interval["start"]
        end = interval["end"]

        if not isinstance(ident, str) or not ident or len(ident) > 40:
            return {"error": "invalid"}
        if type(start) is not int or type(end) is not int:
            return {"error": "invalid"}
        if not (-1000000000 <= start <= 1000000000):
            return {"error": "invalid"}
        if not (-1000000000 <= end <= 1000000000):
            return {"error": "invalid"}
        if start >= end or ident in seen:
            return {"error": "invalid"}

        seen.add(ident)
        records.append((start, ident, end))

    records.sort(key=lambda record: (record[0], record[1]))

    occupied = []
    free = []
    assignment = {}
    order = []
    rooms = 0

    for start, ident, end in records:
        while occupied and occupied[0][0] <= start:
            _, room = heapq.heappop(occupied)
            heapq.heappush(free, room)

        if free:
            room = heapq.heappop(free)
        else:
            rooms += 1
            room = rooms

        assignment[ident] = room
        order.append(ident)
        heapq.heappush(occupied, (end, room))

    return {
        "rooms": rooms,
        "assignment": assignment,
        "order": order,
    }
