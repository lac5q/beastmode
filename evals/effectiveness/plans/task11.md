# Director plan: Task 11

Acceptance: solve exact 0/1 subset optimization, then apply all tie-breakers in order: highest benefit, lowest used units, lexicographically smallest sorted ID list. A greedy benefit/units ratio does not satisfy this contract.

Validate exact object keys, capacity and request bounds with bool excluded, request object field sets, and unique bounded string IDs before optimizing. Sort requests by ID. Dynamic programming by exact used capacity needs only121 states: each state stores best benefit and sorted selected-ID tuple at that exact usage. Start with only usage0=(benefit0,empty tuple). For each request, iterate used capacity DOWNWARD so that request cannot be reused, or derive a new table from the previous table. Update a state for larger benefit or equal benefit with lexicographically smaller ID tuple. Sorting requests makes appending its ID maintain tuple order.

After all requests, compare reachable states globally by (-benefit, used, id_tuple); choose the minimum. Do not choose exact capacity by default or accidentally prefer a fuller subset. Return the three specified fields with selected converted to list. Positive request costs and benefits make the empty-capacity case straightforward.

Review probes: a greedy ratio counterexample, optimum below capacity, equal benefit with lower usage, equal benefit/usage with ID tie, request larger than capacity, shuffled input, duplicate ID, bool numeric, maximum40 requests. Complexity O(requests*capacity) up to tuple comparison costs; never enumerate2^40 subsets.
