# Task 01: dependency scheduler

Implement a pure Python function `solve(payload)` that accepts and returns JSON-compatible values.

The valid input is an object with an integer `workers` in `1..80` and a `tasks` array of at most 80 tasks. Each task is an object with a unique non-empty string `id` of at most 40 Unicode characters, a positive integer `duration` in `1..100000`, and a `deps` array of distinct string task IDs. Every dependency must name a task in the same array. An empty task array is valid. A self-dependency, a dependency cycle, missing required field, wrong type, duplicate ID, duplicate dependency, or any other violation of these rules returns exactly `{"error":"invalid"}`. Booleans are not integers for this contract. Unknown object keys are ignored.

Schedule the tasks on `workers` identical workers. Time starts at zero and is integral. A task becomes ready only after every dependency has finished. At each time when one or more tasks finish, finish all of them before starting new work. Also perform the initial starts at time zero. If several ready tasks compete for slots, choose the lexicographically smallest `id` first using Python/Unicode string ordering. Start as many chosen tasks as there are free workers. A task occupies a worker for exactly its duration; tasks that finish at the same time free their slots together. Repeat until all tasks finish.

Return an object with `order` (task IDs in start order), `start` (ID to start time), `finish` (ID to finish time), and `makespan` (the greatest finish time, or `0` for no tasks). No extra keys are needed. JSON object key order is irrelevant.
