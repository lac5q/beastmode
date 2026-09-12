def _invalid():
    return {"error": "invalid"}


def solve(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("initial"), dict) or not isinstance(payload.get("events"), list):
        return _invalid()
    initial = payload["initial"]
    status = initial.get("status")
    assignee = initial.get("assignee")
    labels = initial.get("labels")
    if ("status" not in initial or "assignee" not in initial or "labels" not in initial
            or not isinstance(status, str) or status not in {"todo", "doing", "done", "cancelled"}
            or (assignee is not None and (not isinstance(assignee, str) or not assignee or len(assignee) > 40))
            or not isinstance(labels, list) or len(labels) > 10
            or any(not isinstance(label, str) or not label or len(label) > 20 for label in labels)
            or len(payload["events"]) > 100):
        return _invalid()
    if len(set(labels)) != len(labels):
        return _invalid()
    labels = list(labels)
    seen = set()
    applied, rejected, ignored = [], [], []
    for event in payload["events"]:
        if not isinstance(event, dict):
            return _invalid()
        ident, op = event.get("id"), event.get("op")
        if (not isinstance(ident, str) or not ident or len(ident) > 40
                or not isinstance(op, str)
                or op not in {"start", "complete", "reopen", "cancel", "assign", "label", "unlabel"}):
            return _invalid()
        if op in {"assign", "label", "unlabel"} and "value" not in event:
            return _invalid()
        value = event.get("value")
        if op == "assign" and value is not None and (not isinstance(value, str) or not value or len(value) > 40):
            return _invalid()
        if op in {"label", "unlabel"} and (not isinstance(value, str) or not value or len(value) > 20):
            return _invalid()
        if ident in seen:
            ignored.append(ident)
            continue
        seen.add(ident)
        valid = True
        if op == "start":
            valid = status == "todo"
            if valid:
                status = "doing"
        elif op == "complete":
            valid = status == "doing"
            if valid:
                status = "done"
        elif op == "reopen":
            valid = status in {"done", "cancelled"}
            if valid:
                status = "todo"
        elif op == "cancel":
            valid = status in {"todo", "doing"}
            if valid:
                status = "cancelled"
        elif op == "assign":
            assignee = value
        elif op == "label":
            valid = value not in labels and len(labels) < 10
            if valid:
                labels.append(value)
        elif op == "unlabel":
            valid = value in labels
            if valid:
                labels.remove(value)
        (applied if valid else rejected).append(ident)
    return {
        "state": {"status": status, "assignee": assignee, "labels": labels},
        "applied": applied,
        "rejected": rejected,
        "ignored": ignored,
    }
