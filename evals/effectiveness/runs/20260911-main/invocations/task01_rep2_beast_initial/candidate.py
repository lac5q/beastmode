import heapq


def solve(payload):
    invalid = {"error": "invalid"}

    def is_integer(value):
        return isinstance(value, int) and not isinstance(value, bool)

    if not isinstance(payload, dict):
        return invalid
    if "workers" not in payload or "tasks" not in payload:
        return invalid

    workers = payload["workers"]
    tasks = payload["tasks"]

    if not is_integer(workers) or not 1 <= workers <= 80:
        return invalid
    if not isinstance(tasks, list) or len(tasks) > 80:
        return invalid

    records = []
    task_ids = []
    id_set = set()

    for task in tasks:
        if not isinstance(task, dict):
            return invalid
        if "id" not in task or "duration" not in task or "deps" not in task:
            return invalid

        task_id = task["id"]
        duration = task["duration"]
        deps_value = task["deps"]

        if not isinstance(task_id, str) or not task_id or len(task_id) > 40:
            return invalid
        if not is_integer(duration) or not 1 <= duration <= 100000:
            return invalid
        if not isinstance(deps_value, list):
            return invalid
        if task_id in id_set:
            return invalid

        deps = []
        dep_set = set()
        for dep in deps_value:
            if not isinstance(dep, str) or not dep or len(dep) > 40:
                return invalid
            if dep in dep_set:
                return invalid
            dep_set.add(dep)
            deps.append(dep)

        id_set.add(task_id)
        task_ids.append(task_id)
        records.append((task_id, duration, deps))

    durations = {}
    remaining = {}
    dependents = {task_id: [] for task_id in task_ids}

    for task_id, duration, deps in records:
        durations[task_id] = duration
        remaining[task_id] = len(deps)

        for dep in deps:
            if dep not in id_set or dep == task_id:
                return invalid
            dependents[dep].append(task_id)

    topo_remaining = remaining.copy()
    topo_ready = []

    for task_id in task_ids:
        if topo_remaining[task_id] == 0:
            heapq.heappush(topo_ready, task_id)

    processed = 0
    while topo_ready:
        task_id = heapq.heappop(topo_ready)
        processed += 1

        for child in dependents[task_id]:
            topo_remaining[child] -= 1
            if topo_remaining[child] == 0:
                heapq.heappush(topo_ready, child)

    if processed != len(task_ids):
        return invalid

    ready = []
    for task_id in task_ids:
        if remaining[task_id] == 0:
            heapq.heappush(ready, task_id)

    running = []
    order = []
    start = {}
    finish = {}
    now = 0

    while len(finish) < len(task_ids):
        while ready and len(running) < workers:
            task_id = heapq.heappop(ready)
            end_time = now + durations[task_id]
            start[task_id] = now
            order.append(task_id)
            heapq.heappush(running, (end_time, task_id))

        if not running:
            return invalid

        now = running[0][0]
        completed = []

        while running and running[0][0] == now:
            _, task_id = heapq.heappop(running)
            finish[task_id] = now
            completed.append(task_id)

        for task_id in completed:
            for child in dependents[task_id]:
                remaining[child] -= 1
                if remaining[child] == 0:
                    heapq.heappush(ready, child)

    return {
        "order": order,
        "start": start,
        "finish": finish,
        "makespan": max(finish.values(), default=0),
    }
