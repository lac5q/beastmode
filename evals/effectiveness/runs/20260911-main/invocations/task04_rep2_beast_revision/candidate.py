import heapq


def solve(payload):
    if not isinstance(payload, dict) or "intervals" not in payload:
        return {"error": "invalid"}

    intervals = payload["intervals"]
    if not isinstance(intervals, list) or len(intervals) > 100:
        return {"error": "invalid"}

    validated = []

    for item in intervals:
        if not isinstance(item, dict):
            return {"error": "invalid"}

        if "id" not in item or "start" not in item or "end" not in item:
            return {"error": "invalid"}

        identifier = item["id"]
        start = item["start"]
        end = item["end"]

        if (
            not isinstance(identifier, str)
            or not identifier
            or len(identifier) > 40
            or not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start < -1000000000
            or start > 1000000000
            or end < -1000000000
            or end > 1000000000
            or start >= end
        ):
            return {"error": "invalid"}

        validated.append((identifier, start, end))

    seen = set()
    for identifier, _, _ in validated:
        if identifier in seen:
            return {"error": "invalid"}
        seen.add(identifier)

    ordered = sorted(validated, key=lambda item: (item[1], item[0]))

    occupied = []
    free_rooms = []
    assignment = {}
    order = []
    rooms = 0

    for identifier, start, end in ordered:
        while occupied and occupied[0][0] <= start:
            _, room = heapq.heappop(occupied)
            heapq.heappush(free_rooms, room)

        if free_rooms:
            room = heapq.heappop(free_rooms)
        else:
            rooms += 1
            room = rooms

        heapq.heappush(occupied, (end, room))
        assignment[identifier] = room
        order.append(identifier)

    return {
        "rooms": rooms,
        "assignment": assignment,
        "order": order,
    }
