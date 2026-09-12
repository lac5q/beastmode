def solve(payload):
    def is_integer(value):
        return isinstance(value, int) and not isinstance(value, bool)

    def valid_stock_key(value):
        if not isinstance(value, str) or not value or len(value) > 32:
            return False
        return all(
            ("A" <= char <= "Z")
            or ("a" <= char <= "z")
            or ("0" <= char <= "9")
            or char in "_.-"
            for char in value
        )

    if not isinstance(payload, dict):
        return {"error": "invalid"}

    if "stock" not in payload or "events" not in payload:
        return {"error": "invalid"}

    raw_stock = payload["stock"]
    raw_events = payload["events"]

    if not isinstance(raw_stock, dict) or len(raw_stock) > 40:
        return {"error": "invalid"}

    stock = {}
    for sku, quantity in raw_stock.items():
        if (
            not valid_stock_key(sku)
            or not is_integer(quantity)
            or quantity < 0
            or quantity > 1000000
        ):
            return {"error": "invalid"}
        stock[sku] = quantity

    if not isinstance(raw_events, list) or len(raw_events) > 100:
        return {"error": "invalid"}

    reserved = {sku: 0 for sku in stock}
    applied = []
    rejected = []
    ignored = []
    seen = set()

    for event in raw_events:
        if not isinstance(event, dict):
            return {"error": "invalid"}

        required = ("id", "op", "sku", "qty")
        if any(key not in event for key in required):
            return {"error": "invalid"}

        event_id = event["id"]
        operation = event["op"]
        sku = event["sku"]
        quantity = event["qty"]

        if (
            not isinstance(event_id, str)
            or not event_id
            or len(event_id) > 40
            or operation not in {"receive", "reserve", "release", "ship"}
            or not isinstance(sku, str)
            or sku not in stock
            or not is_integer(quantity)
            or quantity <= 0
            or quantity > 1000000
        ):
            return {"error": "invalid"}

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
