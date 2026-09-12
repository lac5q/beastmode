def solve(payload):
    def invalid():
        return {"error": "invalid"}

    def valid_sku(value):
        if not isinstance(value, str) or not value or len(value) > 32:
            return False
        return all(
            "A" <= char <= "Z"
            or "a" <= char <= "z"
            or "0" <= char <= "9"
            or char in "_.-"
            for char in value
        )

    def valid_int(value):
        return type(value) is int

    if not isinstance(payload, dict):
        return invalid()
    if "stock" not in payload or "events" not in payload:
        return invalid()

    initial_stock = payload["stock"]
    events = payload["events"]

    if not isinstance(initial_stock, dict) or len(initial_stock) > 40:
        return invalid()
    if not isinstance(events, list) or len(events) > 100:
        return invalid()

    stock = {}
    for sku, quantity in initial_stock.items():
        if (
            not valid_sku(sku)
            or not valid_int(quantity)
            or quantity < 0
            or quantity > 1000000
        ):
            return invalid()
        stock[sku] = quantity

    reserved = {sku: 0 for sku in stock}
    applied = []
    rejected = []
    ignored = []
    seen = set()

    for event in events:
        if not isinstance(event, dict):
            return invalid()

        required = ("id", "op", "sku", "qty")
        if any(key not in event for key in required):
            return invalid()

        event_id = event["id"]
        operation = event["op"]
        sku = event["sku"]
        quantity = event["qty"]

        if (
            not isinstance(event_id, str)
            or not event_id
            or len(event_id) > 40
            or not isinstance(operation, str)
            or operation not in {"receive", "reserve", "release", "ship"}
            or not isinstance(sku, str)
            or sku not in stock
            or not valid_int(quantity)
            or quantity <= 0
            or quantity > 1000000
        ):
            return invalid()

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
