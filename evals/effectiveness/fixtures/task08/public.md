# Task 08: ordered record event reconciliation

Implement a pure Python function solve(payload) that accepts and returns JSON-compatible values.

The payload must be an object with exactly the keys as_of and events. as_of is
an integer from 0 through 1000000 inclusive; booleans are not integers.
events is an array of at most 80 event objects. Every event has the five
common keys id, source, seq, at, and op. id is a non-empty string of at most
16 Unicode code points. source is exactly primary or replica. seq is an
integer from 1 through 1000000. at is an integer from 0 through 1000000.
op is exactly set, patch, or delete. For each (source, id) pair, seq values
must be unique. Future events still must be well-formed and still participate
in this uniqueness rule.

A set event has exactly one additional key, value. A value has exactly name
and qty: name is a non-empty string of at most 32 code points and qty is an
integer from 0 through 10000; booleans are not integers. A patch event also
has exactly one additional key, value, but its value is a non-empty object
whose keys are a subset of name and qty, with the same field rules. A delete
event has no value key. Any missing or extra key, wrong type, duplicate
sequence, out-of-range value, or other violation returns exactly
{"error":"invalid"}. The input object and all nested objects reject unknown
keys. There are no implicit defaults.

Ignore events with at > as_of after validating them. For each remaining ID,
sort its events by (at, seq, source_rank), where source_rank is 0 for primary
and 1 for replica. Apply them in that order. set replaces the complete current
record. patch changes only the named fields if the ID is currently live; a
patch for an absent or deleted ID is ignored. delete removes the current
record. A later set can create a record again.

Return exactly {"records": [...]}. Each surviving record is
{"id": id, "name": name, "qty": qty}, and records are sorted by ID using
Python/Unicode string ordering. An empty result has "records": [].

The stated event, string, and integer limits are the complete evaluation size
envelope and permit bounded in-memory processing.
