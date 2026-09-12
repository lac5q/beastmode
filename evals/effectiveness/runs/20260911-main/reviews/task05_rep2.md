# Director review: task05 repetition 2

Reviewed only the public specification, frozen director plan and this Beastmode initial candidate. No baseline candidates or held-out cases/results consulted.

Required correction: validate operation is a string BEFORE checking membership in the operation set. Currently operation not in {receive,reserve,release,ship} hashes the supplied JSON value. An array or object operation is unhashable and raises TypeError, violating the required invalid sentinel for malformed events. For example, public-contract-derived payload {"stock":{"A":0},"events":[{"id":"x","op":[],"sku":"A","qty":1}]} must return {"error":"invalid"}, not raise. The same applies to an object-valued op, including malformed duplicate events. Add the type guard before membership (or use another safe validation approach).

The rest of the reducer appears consistent with the public contract: ASCII SKU grammar and numeric bounds exclude booleans; every event is validated before reduction; seen IDs are marked before rejection, preserving idempotency after a rejected first event; receive/reserve/release/ship update the correct maps and insufficient quantities cause no state changes. Unknown keys are ignored, all initial SKUs retained, and accumulated state has no unstated cap. Preserve those behaviors and return complete corrected final code.
