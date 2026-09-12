def solve(payload):
    def is_int(value):
        return isinstance(value, int) and not isinstance(value, bool)

    def valid_string(value, maximum):
        return isinstance(value, str) and 0 < len(value) <= maximum

    def valid_field_value(value, field):
        if field == "name":
            return valid_string(value, 32)
        return is_int(value) and 0 <= value <= 10000

    def invalid():
        return {"error": "invalid"}

    if not isinstance(payload, dict):
        return invalid()
    if set(payload.keys()) != {"as_of", "events"}:
        return invalid()

    as_of = payload["as_of"]
    events = payload["events"]

    if not is_int(as_of) or not 0 <= as_of <= 1000000:
        return invalid()
    if not isinstance(events, list) or len(events) > 80:
        return invalid()

    common_keys = {"id", "source", "seq", "at", "op"}
    seen = set()
    validated = []

    for event in events:
        if not isinstance(event, dict):
            return invalid()
        if not common_keys.issubset(event.keys()):
            return invalid()

        event_id = event["id"]
        source = event["source"]
        seq = event["seq"]
        at = event["at"]
        op = event["op"]

        if not valid_string(event_id, 16):
            return invalid()
        if source not in ("primary", "replica"):
            return invalid()
        if not is_int(seq) or not 1 <= seq <= 1000000:
            return invalid()
        if not is_int(at) or not 0 <= at <= 1000000:
            return invalid()
        if op not in ("set", "patch", "delete"):
            return invalid()

        expected_keys = common_keys
        value = None

        if op in ("set", "patch"):
            if set(event.keys()) != common_keys | {"value"}:
                return invalid()

            value = event["value"]
            if not isinstance(value, dict):
                return invalid()

            if op == "set":
                if set(value.keys()) != {"name", "qty"}:
                    return invalid()
            else:
                if not value or not set(value.keys()).issubset({"name", "qty"}):
                    return invalid()

            for field, field_value in value.items():
                if not valid_field_value(field_value, field):
                    return invalid()

            value = dict(value)
        else:
            if set(event.keys()) != common_keys:
                return invalid()

        sequence_key = (source, event_id, seq)
        if sequence_key in seen:
            return invalid()
        seen.add(sequence_key)

        validated.append((event_id, source, seq, at, op, value))

    grouped = {}
    for event in validated:
        event_id, source, seq, at, op, value = event
        if at <= as_of:
            grouped.setdefault(event_id, []).append(event)

    records = {}

    for event_id, event_group in grouped.items():
        event_group.sort(key=lambda event: (
            event[3],
            event[2],
            0 if event[1] == "primary" else 1,
        ))

        for _, _, _, _, op, value in event_group:
            if op == "set":
                records[event_id] = {
                    "name": value["name"],
                    "qty": value["qty"],
                }
            elif op == "patch":
                if event_id in records:
                    records[event_id].update(value)
            else:
                records.pop(event_id, None)

    return {
        "records": [
            {
                "id": event_id,
                "name": records[event_id]["name"],
                "qty": records[event_id]["qty"],
            }
            for event_id in sorted(records)
        ]
    }
