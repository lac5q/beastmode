import re

_CODE_RE = re.compile(r"[A-Z][A-Z0-9_]{1,7}\Z")
_TAG_RE = re.compile(r"[a-z][a-z0-9_-]{0,11}\Z")


def _invalid():
    return {"error": "invalid"}


def _parse_csv_line(line):
    fields = []
    length = len(line)
    position = 0

    while True:
        if position < length and line[position] == '"':
            position += 1
            decoded = []
            closed = False

            while position < length:
                character = line[position]
                if character == '"':
                    if position + 1 < length and line[position + 1] == '"':
                        decoded.append('"')
                        position += 2
                    else:
                        position += 1
                        closed = True
                        break
                else:
                    decoded.append(character)
                    position += 1

            if not closed:
                return None
            if position < length and line[position] != ",":
                return None

            field = "".join(decoded)
        else:
            start = position
            while position < length and line[position] != ",":
                if line[position] == '"':
                    return None
                position += 1
            field = line[start:position]

        fields.append(field)

        if position == length:
            return fields

        position += 1


def _parse_timestamp(value):
    if not value:
        return None

    result = 0
    for character in value:
        code_point = ord(character)
        if code_point < 48 or code_point > 57:
            return None
        result = result * 10 + code_point - 48
        if result > 1000000000:
            return None

    return result


def solve(payload):
    if not isinstance(payload, dict) or len(payload) != 1 or "text" not in payload:
        return _invalid()

    text = payload["text"]
    if not isinstance(text, str) or len(text) > 4096:
        return _invalid()

    events = []
    counts = {"INFO": 0, "WARN": 0, "ERROR": 0}
    latest = {}
    record_order = 0

    for raw_line in text.split("\n"):
        if raw_line.endswith("\r"):
            line = raw_line[:-1]
        else:
            line = raw_line

        if "\r" in line:
            return _invalid()

        first = 0
        while first < len(line) and line[first] in (" ", "\t"):
            first += 1

        if first == len(line) or line[first] == "#":
            continue

        if record_order >= 80:
            return _invalid()

        fields = _parse_csv_line(line)
        if fields is None or len(fields) != 5:
            return _invalid()

        timestamp = _parse_timestamp(fields[0])
        level = fields[1]
        code = fields[2]
        message = fields[3]
        tags_field = fields[4]

        if timestamp is None:
            return _invalid()
        if level not in counts:
            return _invalid()
        if _CODE_RE.fullmatch(code) is None:
            return _invalid()
        if len(message) > 80:
            return _invalid()

        if tags_field == "":
            tags = []
        else:
            raw_tags = tags_field.split(";")
            tags = []
            seen = set()

            for tag in raw_tags:
                if _TAG_RE.fullmatch(tag) is None or tag in seen:
                    return _invalid()
                seen.add(tag)
                tags.append(tag)

            tags.sort()

        event = {
            "at": timestamp,
            "level": level,
            "code": code,
            "message": message,
            "tags": tags,
        }

        events.append((timestamp, record_order, event))
        counts[level] += 1

        previous = latest.get(code)
        if previous is None or timestamp >= previous[0]:
            latest[code] = (timestamp, record_order, level)

        record_order += 1

    events.sort(key=lambda item: (item[0], item[1]))

    latest_by_code = {
        code: {"at": value[0], "level": value[2]}
        for code, value in latest.items()
    }

    return {
        "events": [event for _, _, event in events],
        "counts": counts,
        "latest_by_code": latest_by_code,
    }
