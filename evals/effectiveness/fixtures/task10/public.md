# Task 10: typed telemetry CSV parser

Implement a pure Python function solve(payload) that accepts and returns JSON-compatible values.

The payload must be an object with exactly one key, text. text is a string of
at most 4096 Unicode code points. Split it at line-feed characters. A
carriage return is allowed only immediately before a line feed and is removed.
The final line may be empty. A line containing only spaces or tabs is ignored.
A line whose first non-space/tab character is # is also ignored. Other lines
are records, with at most 80 records. A bare carriage return anywhere else is
invalid.

Each record is exactly five CSV fields in this order: timestamp, level, code,
message, tags. CSV quoting is strict: a quote may begin a field only at its
first character; inside a quoted field, a doubled quote represents one quote;
after a closing quote only a comma or end of line is allowed. Unquoted fields
cannot contain quotes. Newlines are not allowed inside quoted fields.

timestamp is an ASCII decimal integer from 0 through 1000000000. level is
exactly INFO, WARN, or ERROR. code matches
[A-Z][A-Z0-9_]{1,7}. message is any decoded string of at most 80 code points,
including the empty string. tags is empty or a semicolon-separated list of
distinct tags, each matching [a-z][a-z0-9_-]{0,11}. Tags are canonicalized
into Python/Unicode sorted order in the output. Any malformed record, wrong
field count, duplicate tag, extra payload key, or other violation returns
exactly {"error":"invalid"}.

Return exactly an object with these standalone fields:
* events: records in ascending (timestamp, input_record_order) order, each
  represented as {"at": timestamp, "level": level, "code": code,
  "message": message, "tags": sorted_tags}.
* counts: an object with exactly INFO, WARN, and ERROR integer counts,
  including zero counts.
* latest_by_code: for each code, the event with greatest
  (timestamp, input_record_order), represented as {"at": timestamp,
  "level": level}. A code absent from the input is absent from this object.

An empty or comment-only document returns empty events, zero counts, and an
empty latest_by_code. The stated text, record, field, and string limits are
the complete evaluation size envelope.
