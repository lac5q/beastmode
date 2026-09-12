# Director plan: Task 10

Acceptance: strict single-line CSV decoding followed by typed field validation, stable event ordering, complete zero-inclusive counts, and latest-per-code selection by timestamp then input record order. Avoid permissive CSV defaults that admit malformed quote placement.

Validate exact payload key and text size. Reject any CR that is not immediately followed by LF before ignoring comments/blank lines; then normalize CRLF to LF and split lines. Ignore only lines blank under space/tab or whose first non-space/tab character is '#'. Do not trim record fields: whitespace in typed fields must satisfy their exact grammar. Enforce the record count.

Implement a finite-state CSV scan for each record: field start may open quotes; quoted fields decode doubled quotes; closing quote must be followed by comma or line end; unquoted fields reject any quote. Preserve empty fields, including final tags. Require exactly5 decoded fields. Validate ASCII decimal timestamp and bound (leading zeros are not prohibited), exact level, full code regex (minimum2 characters), decoded message length, and distinct full-matching semicolon tags. Sort tags; empty tags field means [].

Create events with their original record index. Stable sort by (timestamp,index), removing index from output. Counts include every input record and all three level keys at zero when absent. latest_by_code selects max(timestamp,index), not last textual row regardless of time; return only at/level there. Review probes: quoted commas and doubled quotes; empty message/tags; duplicate timestamp tie; input unsorted by time; quote after an unquoted prefix; junk after closing quote; bare CR even in comment; one-character code invalid. No multiline CSV is permitted.
