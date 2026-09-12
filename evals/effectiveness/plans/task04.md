# Director plan: Task 04

Acceptance: deterministic minimal room allocation in the public processing order; reuse the smallest available room number after releasing ALL rooms ending at or before the next start. Half-open intervals permit equal-boundary reuse.

Validate the top-level object/list, interval objects, unique nonempty string IDs, and strict start/end integer rules excluding bool; validate before hashing IDs or comparing values. Apply public extra-field and size policy. Sort by (start,id), independent of input order and end time.

Maintain a min-heap of occupied (end,room_id) and a separate min-heap of free room IDs. For each interval in sorted order, pop every occupied record with end <= start and push its room ID into free. Allocate heappop(free) when available; otherwise increment total_created and use that new ID. Push the current (end,room_id). Record assignment and processing order. Do not pick the earliest finishing room among free rooms; smallest room ID is the rule. rooms is total IDs created, which equals the peak occupancy under this greedy allocation, not the final occupied heap length.

Review probes: simultaneous starts tied by ID, multiple rooms becoming free together, a lower ID freeing later but before the next start, touching intervals, negative times, shuffled input, and empty array. No unit-time simulation or input mutation is required.
