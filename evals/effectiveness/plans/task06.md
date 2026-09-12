# Director plan: Task 06

Acceptance: validate every initial field and event before reducing, apply the exact status transition table, preserve label order, and distinguish malformed input from a semantically rejected operation. Ignore unknown object keys as specified.

Validate the top-level object, initial status membership, nullable bounded assignee string, distinct bounded nonempty initial labels and count, event count/objects/IDs/operations, and op-specific values. Do not access membership in a set before checking potentially unhashable JSON values. Extra value on an operation that does not require it is an ignored key. Repeated IDs are valid but their event shapes still must validate.

Copy initial state and labels. Track seen IDs; mark a first ID seen before applying or rejecting. A repeated ID appends to ignored without a state change. Encode transitions explicitly: start todo->doing; complete doing->done; reopen done/cancelled->todo; cancel todo/doing->cancelled. Reject disallowed transitions. assign always applies including null. label appends only if absent and current label count <10; unlabel removes only a present label, preserving other labels' order. Semantic rejection never changes state.

Review probes: rejected operation followed by repeated ID; reopen after cancellation; assign in terminal state; duplicate label; full labels then removal and append; removal preserves order; invalid missing value for assign/label/unlabel; empty event list. Record applied/rejected/ignored IDs in occurrence order and return only specified state/list fields.
