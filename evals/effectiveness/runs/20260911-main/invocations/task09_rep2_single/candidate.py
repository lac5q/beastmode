class _Invalid(Exception):
    pass


class _Parser:
    def __init__(self, text):
        self.text = text
        self.index = 0
        self.length = len(text)

    def skip_ignored(self):
        while self.index < self.length:
            char = self.text[self.index]
            if char in " \t\r\n":
                self.index += 1
            elif char == "#":
                self.index += 1
                while self.index < self.length and self.text[self.index] != "\n":
                    self.index += 1
            else:
                break

    def parse(self):
        self.skip_ignored()
        values = {}

        if self.index == self.length:
            return values

        while True:
            if len(values) >= 40:
                raise _Invalid

            key = self.parse_key()
            self.skip_ignored()

            if self.index >= self.length or self.text[self.index] != "=":
                raise _Invalid
            self.index += 1

            self.skip_ignored()
            value = self.parse_value()

            if key in values:
                raise _Invalid
            values[key] = value

            self.skip_ignored()
            if self.index == self.length:
                return values

            if self.text[self.index] != ";":
                raise _Invalid
            self.index += 1

            self.skip_ignored()
            if self.index == self.length:
                return values

    def parse_key(self):
        if self.index >= self.length:
            raise _Invalid

        char = self.text[self.index]
        if not (("A" <= char <= "Z") or ("a" <= char <= "z")):
            raise _Invalid

        start = self.index
        self.index += 1

        while self.index < self.length:
            char = self.text[self.index]
            if (
                ("A" <= char <= "Z")
                or ("a" <= char <= "z")
                or ("0" <= char <= "9")
                or char == "_"
            ):
                self.index += 1
            else:
                break

        key = self.text[start:self.index]
        if len(key) > 16:
            raise _Invalid
        return key

    def parse_value(self):
        if self.index >= self.length:
            raise _Invalid

        char = self.text[self.index]
        if char == "[":
            return self.parse_list()
        if char == '"':
            return self.parse_string()
        if char == "-" or ("0" <= char <= "9"):
            return self.parse_integer()
        if self.text.startswith("true", self.index):
            self.index += 4
            return True
        if self.text.startswith("false", self.index):
            self.index += 5
            return False

        raise _Invalid

    def parse_scalar(self):
        if self.index >= self.length:
            raise _Invalid

        char = self.text[self.index]
        if char == '"':
            return self.parse_string()
        if char == "-" or ("0" <= char <= "9"):
            return self.parse_integer()
        if self.text.startswith("true", self.index):
            self.index += 4
            return True
        if self.text.startswith("false", self.index):
            self.index += 5
            return False

        raise _Invalid

    def parse_integer(self):
        start = self.index

        if self.index < self.length and self.text[self.index] == "-":
            self.index += 1

        digits_start = self.index
        while self.index < self.length:
            char = self.text[self.index]
            if "0" <= char <= "9":
                self.index += 1
            else:
                break

        if self.index == digits_start:
            raise _Invalid

        digits = self.text[digits_start:self.index]
        if len(digits) > 1 and digits[0] == "0":
            raise _Invalid

        value = int(self.text[start:self.index])
        if value < -1000000 or value > 1000000:
            raise _Invalid
        return value

    def parse_string(self):
        if self.text[self.index] != '"':
            raise _Invalid
        self.index += 1

        chars = []
        escapes = {
            '"': '"',
            "\\": "\\",
            "n": "\n",
            "t": "\t",
            ";": ";",
            "#": "#",
        }

        while self.index < self.length:
            char = self.text[self.index]
            self.index += 1

            if char == '"':
                return "".join(chars)

            if char == "\n" or char == "\r":
                raise _Invalid

            if char == "\\":
                if self.index >= self.length:
                    raise _Invalid
                escaped = self.text[self.index]
                self.index += 1
                if escaped not in escapes:
                    raise _Invalid
                char = escapes[escaped]

            chars.append(char)
            if len(chars) > 64:
                raise _Invalid

        raise _Invalid

    def parse_list(self):
        self.index += 1
        self.skip_ignored()

        if self.index < self.length and self.text[self.index] == "]":
            self.index += 1
            return []

        items = []
        while True:
            if len(items) >= 12:
                raise _Invalid

            items.append(self.parse_scalar())
            self.skip_ignored()

            if self.index >= self.length:
                raise _Invalid

            char = self.text[self.index]
            if char == "]":
                self.index += 1
                return items

            if char != ",":
                raise _Invalid

            self.index += 1
            self.skip_ignored()

            if self.index < self.length and self.text[self.index] == "]":
                raise _Invalid


def solve(payload):
    if not isinstance(payload, dict) or len(payload) != 1 or "text" not in payload:
        return {"error": "invalid"}

    text = payload["text"]
    if not isinstance(text, str) or len(text) > 512:
        return {"error": "invalid"}

    try:
        values = _Parser(text).parse()
    except _Invalid:
        return {"error": "invalid"}

    return {"values": values}
