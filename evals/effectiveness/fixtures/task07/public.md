# Task 07: timestamped record reconciliation

Implement a pure Python function solve(payload) that accepts and returns JSON-compatible values.

The payload must be an object with exactly these keys: as_of, base, and
incoming. as_of is an integer from 0 through 1000000 inclusive; booleans are
not integers. base and incoming are arrays of at most 50 records. Record IDs
are unique within each array.

Every record has the four required common keys id, version, updated_at, and
deleted. id is a
non-empty string of at most 16 Unicode code points. version is an integer from
1 through 1000000. updated_at is an integer from 0 through 1000000. deleted is
a boolean. A live record (deleted false) also has a value key and no other
keys; a tombstone (deleted true) has no value key. A value has exactly name and
tags: name is a non-empty string of at most 32 code points, and tags is an
array of at most 8 distinct strings. Each tag matches
[a-z][a-z0-9_-]{0,11}. Arrays and objects must otherwise follow these types.
Any missing key, extra key, wrong type, out-of-range number, duplicate ID,
duplicate tag, or other violation returns exactly {"error":"invalid"}.

Only records with updated_at <= as_of are eligible. For each ID present in
either array, choose the eligible record with the greatest tuple
(version, updated_at, source_rank), where source_rank is 0 for base and 1 for
incoming. Thus an incoming record wins an exact version/time tie. A winning
tombstone removes the ID; an ID with no eligible record is absent.

Return exactly {"records": [...]}. The records array is sorted by ID using
Python/Unicode string ordering. Each surviving record is represented as
{"id": id, "version": version, "updated_at": updated_at, "value": value}.
The returned value has the same name and its tags sorted by Python/Unicode
string ordering. No tombstones are returned. An empty result has
"records": [].

The input object and every nested object reject unknown keys. The input is
limited to the stated array, string, and integer bounds so a solver may use
bounded in-memory processing.
