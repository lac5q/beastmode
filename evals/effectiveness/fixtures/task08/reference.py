def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _full_value_ok(value):
    if not isinstance(value, dict) or set(value) != {"name", "qty"}:
        return False
    return (
        isinstance(value["name"], str)
        and 1 <= len(value["name"]) <= 32
        and _integer(value["qty"])
        and 0 <= value["qty"] <= 10_000
    )


def _patch_value_ok(value):
    if not isinstance(value, dict) or not value or not set(value) <= {"name", "qty"}:
        return False
    if "name" in value and (not isinstance(value["name"], str) or not 1 <= len(value["name"]) <= 32):
        return False
    if "qty" in value and (not _integer(value["qty"]) or not 0 <= value["qty"] <= 10_000):
        return False
    return True


def _event_ok(event):
    if not isinstance(event, dict):
        return False
    common = {"id", "source", "seq", "at", "op"}
    if not common.issubset(event) or set(event) not in (
        common, common | {"value"}
    ):
        return False
    if not isinstance(event["id"], str) or not 1 <= len(event["id"]) <= 16:
        return False
    if event["source"] not in {"primary", "replica"}:
        return False
    if not _integer(event["seq"]) or not 1 <= event["seq"] <= 1_000_000:
        return False
    if not _integer(event["at"]) or not 0 <= event["at"] <= 1_000_000:
        return False
    if event["op"] == "set":
        return set(event) == common | {"value"} and _full_value_ok(event["value"])
    if event["op"] == "patch":
        return set(event) == common | {"value"} and _patch_value_ok(event["value"])
    if event["op"] == "delete":
        return set(event) == common
    return False


def solve(payload):
    if not isinstance(payload, dict) or set(payload) != {"as_of", "events"}:
        return {"error": "invalid"}
    as_of = payload["as_of"]
    events = payload["events"]
    if not _integer(as_of) or not 0 <= as_of <= 1_000_000:
        return {"error": "invalid"}
    if not isinstance(events, list) or len(events) > 80:
        return {"error": "invalid"}
    seen_sequences = set()
    grouped = {}
    for event in events:
        if not _event_ok(event):
            return {"error": "invalid"}
        sequence_key = (event["source"], event["id"], event["seq"])
        if sequence_key in seen_sequences:
            return {"error": "invalid"}
        seen_sequences.add(sequence_key)
        if event["at"] <= as_of:
            grouped.setdefault(event["id"], []).append(event)
    states = {}
    for ident, rows in grouped.items():
        rows.sort(key=lambda event: (
            event["at"],
            event["seq"],
            0 if event["source"] == "primary" else 1,
        ))
        state = None
        for event in rows:
            if event["op"] == "set":
                state = dict(event["value"])
            elif event["op"] == "patch":
                if state is not None:
                    state.update(event["value"])
            else:
                state = None
        if state is not None:
            states[ident] = state
    return {
        "records": [
            {"id": ident, "name": states[ident]["name"], "qty": states[ident]["qty"]}
            for ident in sorted(states)
        ]
    }
