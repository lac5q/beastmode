import re


_TAG = re.compile(r"[a-z][a-z0-9_-]{0,11}\Z")
_MISSING = object()


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _value_ok(value):
    if not isinstance(value, dict) or set(value) != {"name", "tags"}:
        return False
    name = value["name"]
    tags = value["tags"]
    if not isinstance(name, str) or not 1 <= len(name) <= 32:
        return False
    if not isinstance(tags, list) or len(tags) > 8:
        return False
    if any(not isinstance(tag, str) or _TAG.fullmatch(tag) is None for tag in tags):
        return False
    return len(set(tags)) == len(tags)


def _record_ok(record):
    if not isinstance(record, dict):
        return False
    common = {"id", "version", "updated_at", "deleted"}
    if not common.issubset(record):
        return False
    if set(record) not in (common, common | {"value"}):
        return False
    ident = record["id"]
    version = record["version"]
    updated = record["updated_at"]
    deleted = record["deleted"]
    if not isinstance(ident, str) or not 1 <= len(ident) <= 16:
        return False
    if not _integer(version) or not 1 <= version <= 1_000_000:
        return False
    if not _integer(updated) or not 0 <= updated <= 1_000_000:
        return False
    if not isinstance(deleted, bool):
        return False
    if deleted:
        return set(record) == common
    return set(record) == common | {"value"} and _value_ok(record["value"])


def solve(payload):
    if not isinstance(payload, dict) or set(payload) != {"as_of", "base", "incoming"}:
        return {"error": "invalid"}
    as_of = payload["as_of"]
    if not _integer(as_of) or not 0 <= as_of <= 1_000_000:
        return {"error": "invalid"}
    chosen = {}
    for source_rank, rows in enumerate((payload["base"], payload["incoming"])):
        if not isinstance(rows, list) or len(rows) > 50:
            return {"error": "invalid"}
        seen = set()
        for row in rows:
            if not _record_ok(row) or row["id"] in seen:
                return {"error": "invalid"}
            seen.add(row["id"])
            if row["updated_at"] <= as_of:
                rank = (row["version"], row["updated_at"], source_rank)
                current = chosen.get(row["id"], _MISSING)
                if current is _MISSING or rank > current[0]:
                    chosen[row["id"]] = (rank, row)
    output = []
    for ident in sorted(chosen):
        row = chosen[ident][1]
        if row["deleted"]:
            continue
        value = {
            "name": row["value"]["name"],
            "tags": sorted(row["value"]["tags"]),
        }
        output.append({
            "id": ident,
            "version": row["version"],
            "updated_at": row["updated_at"],
            "value": value,
        })
    return {"records": output}
