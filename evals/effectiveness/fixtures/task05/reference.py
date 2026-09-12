import re


_SKU = re.compile(r"^[A-Za-z0-9_.-]+$")


def _invalid():
    return {"error": "invalid"}


def solve(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("stock"), dict) or not isinstance(payload.get("events"), list):
        return _invalid()
    stock = {}
    if len(payload["stock"]) > 40:
        return _invalid()
    for sku, qty in payload["stock"].items():
        if (not isinstance(sku, str) or not sku or len(sku) > 32 or not _SKU.fullmatch(sku)
                or isinstance(qty, bool) or not isinstance(qty, int) or qty < 0 or qty > 1000000):
            return _invalid()
        stock[sku] = qty
    if len(payload["events"]) > 100:
        return _invalid()
    reserved = {sku: 0 for sku in stock}
    seen = set()
    applied, rejected, ignored = [], [], []
    for event in payload["events"]:
        if not isinstance(event, dict):
            return _invalid()
        ident, op, sku, qty = (event.get(key) for key in ("id", "op", "sku", "qty"))
        if (not isinstance(ident, str) or not ident or len(ident) > 40
                or not isinstance(op, str) or op not in {"receive", "reserve", "release", "ship"}
                or not isinstance(sku, str) or sku not in stock
                or isinstance(qty, bool) or not isinstance(qty, int) or qty < 1 or qty > 1000000):
            return _invalid()
        if ident in seen:
            ignored.append(ident)
            continue
        seen.add(ident)
        valid = True
        if op == "receive":
            stock[sku] += qty
        elif op == "reserve":
            if stock[sku] < qty:
                valid = False
            else:
                stock[sku] -= qty
                reserved[sku] += qty
        elif op == "release":
            if reserved[sku] < qty:
                valid = False
            else:
                reserved[sku] -= qty
                stock[sku] += qty
        else:
            if reserved[sku] < qty:
                valid = False
            else:
                reserved[sku] -= qty
        (applied if valid else rejected).append(ident)
    return {
        "stock": stock,
        "reserved": reserved,
        "applied": applied,
        "rejected": rejected,
        "ignored": ignored,
    }
