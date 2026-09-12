import re


_INTEGER = re.compile(r"-?(0|[1-9][0-9]*)\Z")


class _ParseError(Exception):
    pass


class _Parser:
    def __init__(self, text):
        self.text = text
        self.index = 0

    def _skip_gap(self):
        while self.index < len(self.text):
            char = self.text[self.index]
            if char in " \t\r\n":
                self.index += 1
            elif char == "#":
                end = self.text.find("\n", self.index)
                self.index = len(self.text) if end < 0 else end + 1
            else:
                return

    def _parse_key(self):
        self._skip_gap()
        start = self.index
        if start >= len(self.text) or not (
            "A" <= self.text[start] <= "Z" or "a" <= self.text[start] <= "z"
        ):
            raise _ParseError
        self.index += 1
        while self.index < len(self.text):
            char = self.text[self.index]
            if (
                "A" <= char <= "Z"
                or "a" <= char <= "z"
                or "0" <= char <= "9"
                or char == "_"
            ):
                self.index += 1
            else:
                break
        key = self.text[start:self.index]
        if len(key) > 16:
            raise _ParseError
        return key

    def _parse_string(self):
        if self.index >= len(self.text) or self.text[self.index] != '"':
            raise _ParseError
        self.index += 1
        output = []
        escapes = {
            '"': '"',
            "\\": "\\",
            "n": "\n",
            "t": "\t",
            ";": ";",
            "#": "#",
        }
        while self.index < len(self.text):
            char = self.text[self.index]
            self.index += 1
            if char == '"':
                if len(output) > 64:
                    raise _ParseError
                return "".join(output)
            if char in "\r\n":
                raise _ParseError
            if char == "\\":
                if self.index >= len(self.text):
                    raise _ParseError
                escaped = self.text[self.index]
                self.index += 1
                if escaped not in escapes:
                    raise _ParseError
                char = escapes[escaped]
            output.append(char)
            if len(output) > 64:
                raise _ParseError
        raise _ParseError

    def _parse_scalar(self):
        self._skip_gap()
        if self.index >= len(self.text):
            raise _ParseError
        if self.text[self.index] == '"':
            return self._parse_string()
        if self.text[self.index] == "[":
            raise _ParseError
        start = self.index
        while self.index < len(self.text):
            if self.text[self.index] in " \t\r\n;,]#[": 
                break
            self.index += 1
        token = self.text[start:self.index]
        if token in {"true", "false"}:
            return token == "true"
        if _INTEGER.fullmatch(token) is not None:
            number = int(token)
            if -1_000_000 <= number <= 1_000_000:
                return number
        raise _ParseError

    def _parse_value(self):
        self._skip_gap()
        if self.index < len(self.text) and self.text[self.index] == "[":
            self.index += 1
            self._skip_gap()
            values = []
            if self.index < len(self.text) and self.text[self.index] == "]":
                self.index += 1
                return values
            while True:
                if len(values) == 12:
                    raise _ParseError
                values.append(self._parse_scalar())
                self._skip_gap()
                if self.index >= len(self.text):
                    raise _ParseError
                char = self.text[self.index]
                if char == "]":
                    self.index += 1
                    return values
                if char != ",":
                    raise _ParseError
                self.index += 1
                self._skip_gap()
                if self.index >= len(self.text) or self.text[self.index] == "]":
                    raise _ParseError
        return self._parse_scalar()

    def parse(self):
        values = {}
        self._skip_gap()
        if self.index == len(self.text):
            return values
        while True:
            key = self._parse_key()
            self._skip_gap()
            if self.index >= len(self.text) or self.text[self.index] != "=":
                raise _ParseError
            self.index += 1
            value = self._parse_value()
            if key in values or len(values) == 40:
                raise _ParseError
            values[key] = value
            self._skip_gap()
            if self.index == len(self.text):
                return values
            if self.text[self.index] != ";":
                raise _ParseError
            self.index += 1
            self._skip_gap()
            if self.index == len(self.text):
                return values


def solve(payload):
    if not isinstance(payload, dict) or set(payload) != {"text"}:
        return {"error": "invalid"}
    text = payload["text"]
    if not isinstance(text, str) or len(text) > 512:
        return {"error": "invalid"}
    try:
        return {"values": _Parser(text).parse()}
    except (TypeError, ValueError, _ParseError):
        return {"error": "invalid"}
