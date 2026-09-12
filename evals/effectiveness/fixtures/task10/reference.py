import re


_CODE = re.compile(r"[A-Z][A-Z0-9_]{1,7}\Z")
_TAG = re.compile(r"[a-z][a-z0-9_-]{0,11}\Z")


class _ParseError(Exception):
    pass


def _csv_fields(line):
    fields = []
    chars = []
    quoted = False
    closed = False
    index = 0
    while index < len(line):
        char = line[index]
        if quoted:
            if char == '"':
                if index + 1 < len(line) and line[index + 1] == '"':
                    chars.append('"')
                    index += 2
                else:
                    quoted = False
                    closed = True
                    index += 1
            else:
                if char in "\r\n":
                    raise _ParseError
                chars.append(char)
                index += 1
            continue
        if closed:
            if char != ",":
                raise _ParseError
            fields.append("".join(chars))
            chars = []
            closed = False
            index += 1
            continue
        if char == '"':
            if chars:
                raise _ParseError
            quoted = True
            index += 1
        elif char == ",":
            fields.append("".join(chars))
            chars = []
            index += 1
        else:
            chars.append(char)
            index += 1
    if quoted:
        raise _ParseError
    fields.append("".join(chars))
    return fields


def _parse_record(line):
    fields = _csv_fields(line)
    if len(fields) != 5:
        raise _ParseError
    timestamp, level, code, message, tags_field = fields
    if (
        not timestamp
        or not all("0" <= char <= "9" for char in timestamp)
        or int(timestamp) > 1_000_000_000
        or level not in {"INFO", "WARN", "ERROR"}
        or _CODE.fullmatch(code) is None
        or len(message) > 80
    ):
        raise _ParseError
    if tags_field:
        tags = tags_field.split(";")
        if any(_TAG.fullmatch(tag) is None for tag in tags):
            raise _ParseError
        if len(set(tags)) != len(tags):
            raise _ParseError
    else:
        tags = []
    return {
        "at": int(timestamp),
        "level": level,
        "code": code,
        "message": message,
        "tags": sorted(tags),
    }


def solve(payload):
    if not isinstance(payload, dict) or set(payload) != {"text"}:
        return {"error": "invalid"}
    text = payload["text"]
    if not isinstance(text, str) or len(text) > 4096:
        return {"error": "invalid"}
    events = []
    try:
        for raw_line in text.split("\n"):
            line = raw_line
            if line.endswith("\r"):
                line = line[:-1]
            if "\r" in line:
                raise _ParseError
            if not line.strip(" \t") or line.lstrip(" \t").startswith("#"):
                continue
            if len(events) == 80:
                raise _ParseError
            event = _parse_record(line)
            event["_input_order"] = len(events)
            events.append(event)
    except (TypeError, ValueError, _ParseError):
        return {"error": "invalid"}
    counts = {"INFO": 0, "WARN": 0, "ERROR": 0}
    latest = {}
    for event in events:
        counts[event["level"]] += 1
        prior = latest.get(event["code"])
        if prior is None or (event["at"], event["_input_order"]) >= (
            prior["at"], prior["_input_order"]
        ):
            latest[event["code"]] = event
    events.sort(key=lambda event: (event["at"], event["_input_order"]))
    public_events = [
        {key: event[key] for key in ("at", "level", "code", "message", "tags")}
        for event in events
    ]
    latest_public = {
        code: {"at": event["at"], "level": event["level"]}
        for code, event in sorted(latest.items())
    }
    return {
        "events": public_events,
        "counts": counts,
        "latest_by_code": latest_public,
    }
