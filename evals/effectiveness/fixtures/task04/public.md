# Task 04: minimum room assignment

Implement a pure Python `solve(payload)` function with JSON-compatible input and output.

The valid input is an object whose `intervals` field is an array of at most 100 elements. Each element is an object with a unique non-empty string `id` of at most 40 Unicode characters and integer `start` and `end` values in `[-1000000000,1000000000]` satisfying `start < end`. Booleans do not count as integers. Missing fields, wrong types, duplicate IDs, or any other violation returns exactly `{"error":"invalid"}`. The array may be empty. Unknown object keys are ignored.

Each interval occupies a room during the half-open interval `[start,end)`. Sort intervals by ascending `start`, then lexicographically ascending `id`. Process them in that order. Before assigning an interval, every room whose previous interval ended at or before its start is free, including at an equal boundary. Reuse the smallest-numbered free room. If none is free, create the next room number; room numbers start at `1`. An interval cannot share a room with an overlapping interval.

Return exactly `rooms` (the number of rooms created), `assignment` (each input ID to its room number), and `order` (the processing order). Object key order is irrelevant; `order` is the only place where ordering is represented.
