# Task 12: dependency-closed two-resource allocation

Implement a pure Python function solve(payload) that accepts and returns JSON-compatible values.

The payload must be an object with exactly the keys cpu, memory, and jobs. cpu
and memory are integers from 0 through 64 inclusive; booleans are not
integers. jobs is an array of at most 16 job objects. Every job has exactly
id, cpu, memory, priority, and deps. id is a unique non-empty string of at
most 16 Unicode code points. A job's cpu and memory are integers from 1
through 32. priority is an integer from 1 through 1000. deps is an array of
at most 16 distinct string IDs, and every dependency names another job in the
same input. A self-dependency or any directed dependency cycle is invalid.
Missing or extra keys, wrong types, duplicate IDs or dependencies, unknown
dependencies, out-of-range values, or any other violation returns exactly
{"error":"invalid"}. The stated limits are the complete evaluation size
envelope.

Choose a subset of jobs whose total cpu is at most cpu and whose total memory
is at most memory. If a job is selected, every direct and transitive
dependency must also be selected. Maximize total priority. If several
dependency-closed subsets have the same priority, choose the one with the
smaller sum of cpu plus memory. If they still tie, sort each subset's IDs by
Python/Unicode string ordering and choose the lexicographically smaller ID
list. The empty subset is always allowed.

Return exactly {"selected": [...], "used": {"cpu": integer, "memory":
integer}, "priority": integer}. selected is sorted by ID, used contains the
resource sums, and priority is the sum for the selected jobs. No other output
fields are allowed. Zero capacities or no jobs therefore return an empty
selection with zero usage and priority.
