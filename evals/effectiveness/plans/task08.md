# Director plan: Task 08

Acceptance: validate every event and the full per-(source,id) sequence uniqueness constraint before dropping future events; apply eligible events in the stated chronological tuple order, not payload order or sequence order alone.

Check exact top-level keys, bounded as_of excluding bool, events array and size. Validate each event's common fields and op-specific exact key set. set value requires both name and qty; patch value requires a nonempty subset with valid field types/bounds; delete forbids value. Reject extra nested keys and malformed future events. Track (source,id,seq) triples for duplicates across the entire input; the same seq may occur for a different ID or source.

After validation, filter at <= as_of and group by ID. Sort each group by (at,seq,source_rank), with primary0 and replica1. Keep absent versus live state explicitly. set replaces the complete current record; patch updates only provided fields if currently live and otherwise does nothing; delete makes it absent. A later set recreates it. Do not manufacture a record from a patch or retain old fields across a replacing set.

Return surviving records as the specified flat id/name/qty objects sorted by Unicode ID. Input maps should not be mutated. Review probes: same timestamp with seq and source ties; shuffled events; future duplicate sequence; delete->patch->set; empty patch invalid; qty zero valid and bool invalid; repeated seq permitted across sources. Public specification outranks this plan.
