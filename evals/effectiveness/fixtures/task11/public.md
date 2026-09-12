# Task 11: bounded single-budget allocation

Implement a pure Python function solve(payload) that accepts and returns JSON-compatible values.

The payload must be an object with exactly the keys capacity and requests.
capacity is an integer from 0 through 120 inclusive; booleans are not
integers. requests is an array of at most 40 request objects. Each request has
exactly id, units, and benefit. id is a non-empty string of at most 16 Unicode
code points and is unique across requests. units is an integer from 1 through
30. benefit is an integer from 1 through 1000. Any missing or extra key, wrong
type, duplicate ID, or out-of-range value returns exactly
{"error":"invalid"}. The stated limits are the complete evaluation size
envelope.

Choose a subset of requests, using each request at most once, whose total
units is at most capacity. Maximize the sum of benefit. If several subsets
have the same benefit, choose the one with the smaller total units. If they
still tie, sort each subset's IDs by Python/Unicode string ordering and choose
the lexicographically smaller ID list. The empty subset is always allowed.

Return exactly {"selected": [...], "used": integer, "benefit": integer}.
selected is the chosen ID list in sorted order. used and benefit are the sums
for that subset. No other output fields are allowed. A zero capacity or empty
request array therefore returns selected [], used 0, benefit 0.
