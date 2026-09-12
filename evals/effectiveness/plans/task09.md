# Director plan: Task 09

Acceptance: implement the stated grammar, preserve scalar JSON types, and reject trailing junk, missing separators, duplicate keys, and malformed strings/lists. Do not use Python eval or split the document naively on semicolons, commas, or hash characters inside strings.

Use an index-based scanner with a skip_whitespace_and_comments routine applied only outside quoted strings. Comments end at LF or EOF and count as whitespace, never as an assignment separator. Parse a key with the exact ASCII pattern/length, then '=', then one scalar or nonnested list. After a value require EOF or ';'; consume an optional final semicolon but reject an empty assignment from repeated separators. Enforce the public policy if it explicitly says otherwise. Validate the payload's exact keys and text length first.

String parsing must distinguish raw characters from escapes: accept only the six listed escapes, reject unknown/truncated escapes and raw line breaks, and enforce decoded length. Scalar parser handles lowercase booleans and the integer grammar/range with token termination checked by the surrounding grammar; avoid isdigit broadening the specified digit alphabet. Optional '-' may precede zero, since the public grammar does not ban negative zero. Lists allow empty or up to12 scalars, forbid nesting and trailing commas. Preserve bool versus int; do not coerce quoted scalars.

Review probes: '#' and ';' inside strings, escaped quote/backslash, comments between tokens, comment without required semicolon, signed/leading-zero numbers, repeated key, malformed list separator, empty/comment-only document. Track input position to reject every unconsumed non-whitespace/comment character. Public grammar outranks any implementation assumption.
