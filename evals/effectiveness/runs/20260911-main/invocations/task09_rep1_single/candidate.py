class _Invalid(Exception):
    pass


class _Parser:
    def __init__(self, text):
        self.text = text
        self.pos = 0
        self.length = len(text)

    def skip_trivia(self):
        while self.pos < self.length:
            char = self.text[self.pos]
            if char in " \t\r\n":
                self.pos += 1
            elif char == "#":
                self.pos += 1
                while self.pos < self.length and self.text[self.pos] != "\n":
                    self.pos += 1
            else:
                break

    @staticmethod
    def is_ascii_letter(char):
        return ("A" <= char <= "Z") or ("a" <= char <= "z")

    @staticmethod
    def is_ascii_digit(char):
        return "0" <= char <= "9"

    def parse_key(self):
        if self.pos >= self.length or not self.is_ascii_letter(self.text[self.pos]):
            raise _Invalid()

        start = self.pos
        self.pos += 1

        while self.pos < self.length:
            char = self.text[self.pos]
            if self.is_ascii_letter(char) or self.is_ascii_digit(char) or char == "_":
                self.pos += 1
            else:
                break

        if self.pos - start > 16:
            raise _Invalid()

        return self.text[start:self.pos]

    def parse_string(self):
        if self.pos >= self.length or self.text[self.pos] != '"':
            raise _Invalid()

        self.pos += 1
        chars = []
        escapes = {
            '"': '"',
            "\\": "\\",
            "n": "\n",
            "t": "\t",
            ";": ";",
            "#": "#",
        }

        while self.pos < self.length:
            char = self.text[self.pos]

            if char == '"':
                self.pos += 1
                value = "".join(chars)
                if len(value) > 64:
                    raise _Invalid()
                return value

            if char in "\r\n":
                raise _Invalid()

            if char == "\\":
                self.pos += 1
                if self.pos >= self.length:
                    raise _Invalid()

                escape = self.text[self.pos]
                if escape not in escapes:
                    raise _Invalid()

                chars.append(escapes[escape])
                self.pos += 1
            else:
                chars.append(char)
                self.pos += 1

        raise _Invalid()

    def parse_integer(self):
        start = self.pos

        if self.text[self.pos] == "-":
            self.pos += 1
            if self.pos >= self.length or not self.is_ascii_digit(self.text[self.pos]):
                raise _Invalid()

        digits_start = self.pos
        while self.pos < self.length and self.is_ascii_digit(self.text[self.pos]):
            self.pos += 1

        digits = self.text[digits_start:self.pos]
        if not digits:
            raise _Invalid()

        if len(digits) > 1 and digits[0] == "0":
            raise _Invalid()

        value = int(self.text[start:self.pos])
        if value < -1000000 or value > 1000000:
            raise _Invalid()

        return value

    def parse_scalar(self):
        if self.pos >= self.length:
            raise _Invalid()

        char = self.text[self.pos]

        if char == '"':
            return self.parse_string()

        if char == "-" or self.is_ascii_digit(char):
            return self.parse_integer()

        if self.text.startswith("true", self.pos):
            self.pos += 4
            return True

        if self.text.startswith("false", self.pos):
            self.pos += 5
            return False

        raise _Invalid()

    def parse_list(self):
        if self.pos >= self.length or self.text[self.pos] != "[":
            raise _Invalid()

        self.pos += 1
        self.skip_trivia()

        if self.pos < self.length and self.text[self.pos] == "]":
            self.pos += 1
            return []

        values = []

        while True:
            if len(values) >= 12:
                raise _Invalid()

            values.append(self.parse_scalar())
            self.skip_trivia()

            if self.pos >= self.length:
                raise _Invalid()

            if self.text[self.pos] == "]":
                self.pos += 1
                return values

            if self.text[self.pos] != ",":
                raise _Invalid()

            self.pos += 1
            self.skip_trivia()

            if self.pos >= self.length or self.text[self.pos] == "]":
                raise _Invalid()

    def parse_value(self):
        if self.pos < self.length and self.text[self.pos] == "[":
            return self.parse_list()
        return self.parse_scalar()

    def parse_document(self):
        values = {}
        self.skip_trivia()

        if self.pos >= self.length:
            return values

        while True:
            if len(values) >= 40:
                raise _Invalid()

            key = self.parse_key()
            if key in values:
                raise _Invalid()

            self.skip_trivia()
            if self.pos >= self.length or self.text[self.pos] != "=":
                raise _Invalid()

            self.pos += 1
            self.skip_trivia()
            values[key] = self.parse_value()

            self.skip_trivia()
            if self.pos >= self.length:
                return values

            if self.text[self.pos] != ";":
                raise _Invalid()

            self.pos += 1
            self.skip_trivia()

            if self.pos >= self.length:
                return values


def solve(payload):
    if not isinstance(payload, dict) or len(payload) != 1 or "text" not in payload:
        return {"error": "invalid"}

    text = payload["text"]
    if not isinstance(text, str) or len(text) > 512:
        return {"error": "invalid"}

    try:
        return {"values": _Parser(text).parse_document()}
    except _Invalid:
        return {"error": "invalid"}
