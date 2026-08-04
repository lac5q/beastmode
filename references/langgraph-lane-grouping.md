# P0.3 — LangGraph lane-grouping spike

Date: 2026-08-03

## Measurement status

No live provider completion was available for a `usage_metadata` comparison:
the configured probe failed before completion, and the other provider
adapters were unavailable. No synthetic token result is being presented as a
provider measurement.

## Provisional number

Using the cache weights already documented by the Beastmode skill (a cold write
costs `1.25x`; a warm read costs `0.10x`) for 9 tasks across 3 lanes:

- lane-grouped: 3 cold writes + 6 warm reads = `3 × 1.25 + 6 × 0.10 = 4.35`
  normalized cache units;
- interleaved: 9 cold writes = `9 × 1.25 = 11.25` normalized cache units;
- analytical ratio: `11.25 / 4.35 = 2.59x` in favor of grouping.

This is an estimate from the existing cache model, **not** the required live
`usage_metadata` number. It is sufficient for a conservative design choice:
P4 must keep lane grouping as the default dispatcher behavior. Replace this
estimate with a provider-backed measurement before deliberately trading away
grouping for parallelism.
