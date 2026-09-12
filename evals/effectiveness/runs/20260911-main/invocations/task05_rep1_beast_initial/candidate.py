def solve(payload):
    def valid_int(value, minimum, maximum):
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            and minimum <= value <= maximum
        )

    def valid_sku(value):
        if not isinstance(value, str) or not (1 <= len(value) <= 32):
            return False
        if not value.isascii():
            return False
        return all(
            ("A" <= ch <= "Z")
            or ("a" <= ch <= "z")
            or ("0" <= ch <= "9")
            or ch in "_.-"
            for ch in value
        )

    invalid = {"error": "invalid"}

    if not isinstance(payload, dict):
        return invalid
    if "stock" not in payload or "events" not in payload:
        return invalid

    initial_stock = payload["stock"]
    events = payload["events"]

    if not isinstance(initial_stock, dict) or len(initial_stock) > 40:
        return invalid
    if not isinstance(events, list) or len(events) > 100:
        return invalid

    for sku, quantity in initial_stock.items():
        if not valid_sku(sku):
            return invalid
        if not valid_int(quantity, 0, 1_000_000):
            return invalid

    normalized_events = []
    operations = {"receive", "reserve", "release", "ship"}

    for event in events:
        if not isinstance(event, dict):
            return invalid
        if not all(field in event for field in ("id", "op", "sku", "qty")):
            return invalid

        event_id = event["id"]
        operation = event["op"]
        sku = event["sku"]
        quantity = event["qty"]

        if not isinstance(event_id, str) or not (1 <= len(event_id) <= 40):
            return invalid
        if not isinstance(operation, str) or operation not in operations:
            return invalid
        if not isinstance(sku, str) or sku not in initial_stock:
            return invalid
        if not valid_int(quantity, 1, 1_000_000):
            return invalid

        normalized_events.append((event_id, operation, sku, quantity))

    stock = dict(initial_stock)
    reserved = {sku: 0 for sku in initial_stock}
    applied = []
    rejected = []
    ignored = []
    seen = set()

    for event_id, operation, sku, quantity in normalized_events:
        if event_id in seen:
            ignored.append(event_id)
            continue

        seen.add(event_id)

        if operation == "receive":
            stock[sku] += quantity
            applied.append(event_id)
        elif operation == "reserve":
            if stock[sku] < quantity:
                rejected.append(event_id)
            else:
                stock[sku] -= quantity
                reserved[sku] += quantity
                applied.append(event_id)
        elif operation == "release":
            if reserved[sku] < quantity:
                rejected.append(event_id)
            else:
                reserved[sku] -= quantity
                stock[sku] += quantity
                applied.append(event_id)
        else:
            if reserved[sku] < quantity:
                rejected.append(event_id)
            else:
                reserved[sku] -= quantity
                applied.append(event_id)

    return {
        "stock": stock,
        "reserved": reserved,
        "applied": applied,
        "rejected": rejected,
        "ignored": ignored,
    }
