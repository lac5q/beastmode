_COMMON_KEYS = frozenset(("id", "source", "seq", "at", "op"))
_RECORD_KEYS = frozenset(("name", "qty"))
_TOP_LEVEL_KEYS = frozenset(("as_of", "events"))


def _invalid():
    return {"error": "invalid"}


def _exact_keys(obj, expected):
    if not isinstance(obj, dict) or len(obj) != len(expected):
        return False
    if not all(isinstance(key, str) for key in obj):
        return False
    return set(obj) == expected


def _valid_int(value, minimum, maximum):
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and minimum <= value <= maximum
    )


def _valid_string(value, maximum):
    return isinstance(value, str) and 0 < len(value) <= maximum


def solve(payload):
    if not _exact_keys(payload, _TOP_LEVEL_KEYS):
        return _invalid()

    as_of = payload["as_of"]
    events = payload["events"]

    if not _valid_int(as_of, 0, 1_000_000):
        return _invalid()
    if not isinstance(events, list) or len(events) > 80:
        return _invalid()

    grouped = {}
    seen_sequences = {}

    for event in events:
        if not isinstance(event, dict):
            return _invalid()
        if not all(key in event for key in _COMMON_KEYS):
            return _invalid()

        operation = event["op"]
        if operation not in ("set", "patch", "delete"):
            return _invalid()

        expected_keys = (
            _COMMON_KEYS
            if operation == "delete"
            else _COMMON_KEYS | frozenset(("value",))
        )
        if not _exact_keys(event, expected_keys):
            return _invalid()

        identifier = event["id"]
        source = event["source"]
        sequence = event["seq"]
        at = event["at"]

        if not _valid_string(identifier, 16):
            return _invalid()
        if source not in ("primary", "replica"):
            return _invalid()
        if not _valid_int(sequence, 1, 1_000_000):
            return _invalid()
        if not _valid_int(at, 0, 1_000_000):
            return _invalid()

        sequence_key = (source, identifier)
        sequences = seen_sequences.setdefault(sequence_key, set())
        if sequence in sequences:
            return _invalid()
        sequences.add(sequence)

        event_value = None

        if operation == "set":
            value = event["value"]
            if not _exact_keys(value, _RECORD_KEYS):
                return _invalid()

            name = value["name"]
            quantity = value["qty"]
            if not _valid_string(name, 32):
                return _invalid()
            if not _valid_int(quantity, 0, 10_000):
                return _invalid()

            event_value = (name, quantity)

        elif operation == "patch":
            value = event["value"]
            if not isinstance(value, dict) or not value:
                return _invalid()
            if not all(
                isinstance(key, str) and key in _RECORD_KEYS
                for key in value
            ):
                return _invalid()

            name = value.get("name")
            quantity = value.get("qty")

            if "name" in value and not _valid_string(name, 32):
                return _invalid()
            if "qty" in value and not _valid_int(quantity, 0, 10_000):
                return _invalid()

            event_value = (name, quantity)

        if at <= as_of:
            source_rank = 0 if source == "primary" else 1
            grouped.setdefault(identifier, []).append(
                (at, sequence, source_rank, operation, event_value)
            )

    live = {}

    for identifier, identifier_events in grouped.items():
        identifier_events.sort(key=lambda item: item[:3])

        for _, _, _, operation, value in identifier_events:
            if operation == "set":
                live[identifier] = [value[0], value[1]]
            elif operation == "patch":
                if identifier in live:
                    if value[0] is not None:
                        live[identifier][0] = value[0]
                    if value[1] is not None:
                        live[identifier][1] = value[1]
            else:
                live.pop(identifier, None)

    return {
        "records": [
            {
                "id": identifier,
                "name": live[identifier][0],
                "qty": live[identifier][1],
            }
            for identifier in sorted(live)
        ]
    }
