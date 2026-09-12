# Task 09: typed assignment-list parser

Implement a pure Python function solve(payload) that accepts and returns JSON-compatible values.

The payload must be an object with exactly one key, text. text is a string of
at most 512 Unicode code points. Parse a document containing zero or more
assignments (at most 40) separated by semicolons; a final semicolon is
optional. Whitespace
means space, tab, carriage return, or line feed and may occur around tokens.
Outside a quoted string, # starts a comment that runs through (but not
including) the next line feed or the end of the text. A comment is whitespace
for parsing, but it does not replace the required semicolon between
assignments.

An assignment is key = value. A key is an ASCII letter followed by zero or
more ASCII letters, digits, or underscores, with total length 1 through 16.
Keys must be unique. Values are an integer, the lowercase word true, the
lowercase word false, a quoted string, or a list in square brackets. Integers
are written with an optional minus sign and ASCII digits, have no leading zero
except for zero itself, and lie from -1000000 through 1000000. A quoted
string uses double quotes and allows only these escapes: backslash-double
quote, backslash-backslash, backslash-n, backslash-t, backslash-semicolon,
and backslash-hash. An unescaped line feed or carriage return is invalid
inside a quoted string; an unknown escape is invalid.
The decoded string length is at most 64.

A list contains one or more scalar values separated by commas; an empty list
is also valid. Scalar values use the integer, boolean, or quoted-string rules
above. Lists cannot nest, have at most 12 items, and cannot have a trailing
comma. Duplicate keys, a missing separator or equals sign, malformed escapes,
wrong types, extra payload keys, or any other violation returns exactly
{"error":"invalid"}. An empty text document is valid.

Return exactly {"values": {key: parsed_value, ...}}. Parsed values retain
their boolean, integer, string, and list types. Object key order is
irrelevant. The stated length, assignment, and list limits are the complete
evaluation size envelope.
