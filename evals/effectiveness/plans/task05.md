# Director plan: Task 05

Acceptance: separate malformed input (whole-call invalid sentinel) from a valid but unaffordable operation (rejected event). Preserve event occurrence order, idempotency by ID, and both state maps for every initial SKU.

First validate all input before reducing: top-level object, stock object/size/SKU ASCII pattern and length, bounded non-bool integer quantities, event array size, required event fields/ID length/operation/SKU membership. Unknown keys are ignored. Even repeated-ID events must satisfy the public shape validation: duplicate handling is a state rule, not an exemption from the preceding malformed-event rule. Output maps should be copies, not aliases of payload.

Initialize reserved to zero per SKU and seen IDs to empty. For each event: if seen, append its ID to ignored and stop processing it; otherwise mark seen BEFORE deciding whether the operation can apply. Thus a first rejected occurrence still suppresses later occurrences of that ID. receive adds to stock; reserve requires stock >= qty then transfers to reserved; release requires reserved >= qty then transfers to stock; ship requires reserved >= qty then subtracts only from reserved. Reject without partial state changes on insufficient quantity. Input bounds do not impose an unstated cap on accumulated state.

Review probes: rejected first event followed by same ID; duplicate with different valid fields; reserve then ship versus release; zero-stock SKU; empty maps/events; invalid bool qty; malformed duplicate; initial stock retains keys at zero. The exact public specification is authoritative.
