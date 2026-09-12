class _Invalid(Exception):
    pass


class _Parser:
    def __init__(self, text):
        self.text = text
        self.length = len(text)
        self.index = 0

    @staticmethod
    def _is_letter(char):
        return "A" <= char <= "Z" or "a" <= char <= "z"

    @staticmethod
    def _is_digit(char):
        return "0" <= char <= "9"

    @staticmethod
    def _is_key_char(char):
        return (
            "A" <= char <= "Z"
            or "a" <= char <= "z"
            or "0" <= char <= "9"
            or char == "_"
        )

    def _fail(self):
        raise _Invalid()

    def _skip(self):
        while True:
            while self.index < self.length and self.text[self.index] in " \t\r\n":
                self.index += 1

            if self.index < self.length and self.text[self.index] == "#":
                newline = self.text.find("\n", self.index + 1)
                self.index = self.length if newline == -1 else newline + 1
                continue

            return

    def _parse_key(self):
        start = self.index

        if self.index >= self.length or not self._is_letter(self.text[self.index]):
            self._fail()

        self.index += 1
        while self.index < self.length and self._is_key_char(self.text[self.index]):
            self.index += 1

        if self.index - start > 16:
            self._fail()

        return self.text[start:self.index]

    def _parse_string(self):
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

            if char == '"':
                self.index += 1
                return "".join(chars)

            if char in "\r\n":
                self._fail()

            if char == "\\":
                self.index += 1
                if self.index >= self.length:
                    self._fail()

                escaped = self.text[self.index]
                if escaped not in escapes:
                    self._fail()

                chars.append(escapes[escaped])
                self.index += 1
            else:
                chars.append(char)
                self.index += 1

            if len(chars) > 64:
                self._fail()

        self._fail()

    def _parse_integer(self):
        start = self.index

        if self.text[self.index] == "-":
            self.index += 1

        digits_start = self.index
        while self.index < self.length and self._is_digit(self.text[self.index]):
            self.index += 1

        if self.index == digits_start:
            self._fail()

        digits = self.text[digits_start:self.index]
        if len(digits) > 1 and digits[0] == "0":
            self._fail()

        value = int(self.text[start:self.index])
        if value < -1000000 or value > 1000000:
            self._fail()

        return value

    def _parse_scalar(self):
        if self.index >= self.length:
            self._fail()

        char = self.text[self.index]

        if char == '"':
            return self._parse_string()

        if char == "-" or self._is_digit(char):
            return self._parse_integer()

        if self.text.startswith("true", self.index):
            self.index += 4
            return True

        if self.text.startswith("false", self.index):
            self.index += 5
            return False

        self._fail()

    def _parse_list(self):
        self.index += 1
        self._skip()

        if self.index < self.length and self.text[self.index] == "]":
            self.index += 1
            return []

        items = []

        while True:
            item = self._parse_scalar()
            items.append(item)

            if len(items) > 12:
                self._fail()

            self._skip()

            if self.index >= self.length:
                self._fail()

            if self.text[self.index] == "]":
                self.index += 1
                return items

            if self.text[self.index] != ",":
                self._fail()

            self.index += 1
            self._skip()

            if self.index >= self.length or self.text[self.index] == "]":
                self._fail()

    def _parse_value(self):
        if self.index < self.length and self.text[self.index] == "[":
            return self._parse_list()
        return self._parse_scalar()

    def parse(self):
        self._skip()

        if self.index == self.length:
            return {}

        values = {}
        assignment_count = 0

        while True:
            if assignment_count >= 40:
                self._fail()

            key = self._parse_key()
            self._skip()

            if self.index >= self.length or self.text[self.index] != "=":
                self._fail()

            self.index += 1
            self._skip()
            value = self._parse_value()
            self._skip()

            if key in values:
                self._fail()

            values[key] = value
            assignment_count += 1

            if self.index == self.length:
                return values

            if self.text[self.index] != ";":
                self._fail()

            self.index += 1
            self._skip()

            if self.index == self.length:
                return values


def solve(payload):
    if not isinstance(payload, dict) or len(payload) != 1 or "text" not in payload:
        return {"error": "invalid"}

    text = payload["text"]
    if not isinstance(text, str) or len(text) > 512:
        return {"error": "invalid"}

    try:
        return {"values": _Parser(text).parse()}
    except _Invalid:
        return {"error": "invalid"}
