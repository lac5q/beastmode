# Task 03: interval union and query lengths

Implement a pure Python `solve(payload)` function that maps JSON-compatible input to JSON-compatible output.

The valid input is an object with `intervals` and `queries`, both arrays of at most 100 elements. Every interval is a two-element integer array `[start,end]` with `start < end` and endpoints in `[-1000000000,1000000000]`. Every query is a two-element integer array with `start <= end` and endpoints in that range; an equal pair is an empty query. Booleans are not integers. Any missing field, wrong type, non-integer endpoint, reversed interval, or other violation returns exactly `{"error":"invalid"}`. Either array may be empty. Unknown object keys are ignored.

Intervals use half-open boundaries: `[start,end)` includes `start` and excludes `end`. Sort intervals by start then end and form their union. Overlapping or touching intervals are one merged interval, so `[1,3)` and `[3,5)` merge. The returned `merged` array is sorted and has no overlap or gap that could be joined. For each query, calculate the total number of covered integer-time units in its intersection with the union; count a boundary-only contact as zero. The query answers remain in input order.

Return exactly an object with `merged`, `total` (the sum of each merged interval's length), and `overlaps` (one integer per query). Negative endpoints are allowed. Object key order is irrelevant.
