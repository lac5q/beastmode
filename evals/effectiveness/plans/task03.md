# Director plan: Task 03

Acceptance: validate interval and query rules separately, return the union with touching intervals merged, and preserve original query order in overlap totals. Invalid input returns only the specified sentinel, not a partially computed union.

Validate top-level keys/array types and each exact two-element endpoint array before indexing. Integer endpoints exclude bool. Intervals require start < end, whereas queries allow equality. Follow public extra-key/bounds policies. Sort a copy of intervals by (start,end), merge if next_start <= current_end, and extend with max(current_end,next_end). Otherwise flush the current interval. Empty input yields no merged intervals and total zero. Total is sum(end-start), not count of endpoints.

For each query, sum max(0,min(query_end,segment_end)-max(query_start,segment_start)) over the disjoint merged union; skip segments wholly before and stop once wholly after if helpful. Do not double-count overlapping original intervals. Empty queries and boundary-only touches give zero. Avoid expanding integer ranges, since coordinate magnitude need not be small.

Review probes: touching chain, nested duplicates, negative coordinates, empty intervals with nonempty queries, empty queries with nonempty intervals, zero-length query versus invalid zero-length interval, bool endpoint. Outputs must match the public object's field names and exact structures.
