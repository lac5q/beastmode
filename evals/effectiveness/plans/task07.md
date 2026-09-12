# Director plan: Task 07

Acceptance: strictly validate both complete input arrays before time filtering, select the highest eligible (version, updated_at, source_rank) per ID, then apply the winning tombstone. Never let an ineligible future record hide an older eligible record.

Validate exact top-level keys; integer bounds excluding bool; per-array length; object field sets conditional on deleted; bounded nonempty Unicode IDs; true boolean deleted; uniqueness of IDs separately within each array. Live value requires its exact name/tags fields, bounded name, distinct bounded tags with full regex matching. A deleted record forbids value. Reject all extra keys recursively where the public spec declares exact object fields. Future/ineligible records still must be structurally valid.

For each source (base rank0, incoming rank1), consider only records at or before as_of. Track the maximum tuple for each ID, including tombstones. Compare version before timestamp, and source rank only after those. After selection, discard winners with deleted true. Sort surviving IDs with Python string ordering. Return the prescribed four output record fields without deleted; preserve name and sort a new tags list. Do not mutate payload. Empty arrays or only tombstones yield records [].

Review probes: incoming exact tie, higher version with older timestamp, future tombstone, future live record, no eligible records for an ID, per-source duplicate ID, malformed future record, boolean version/as_of, empty tag list, and extra nested key. The public contract determines all validation policies.
