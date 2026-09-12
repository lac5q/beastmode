import heapq


def solve(payload):
    if not isinstance(payload, dict):
        return {"error": "invalid"}

    if "workers" not in payload or "tasks" not in payload:
        return {"error": "invalid"}

    workers = payload["workers"]
    tasks = payload["tasks"]

    if type(workers) is not int or not 1 <= workers <= 80:
        return {"error": "invalid"}

    if not isinstance(tasks, list) or len(tasks) > 80:
        return {"error": "invalid"}

    records = {}

    for task in tasks:
        if not isinstance(task, dict):
            return {"error": "invalid"}

        if "id" not in task or "duration" not in task or "deps" not in task:
            return {"error": "invalid"}

        task_id = task["id"]
        duration = task["duration"]
        deps = task["deps"]

        if (
            not isinstance(task_id, str)
            or not task_id
            or len(task_id) > 40
            or task_id in records
        ):
            return {"error": "invalid"}

        if type(duration) is not int or not 1 <= duration <= 100000:
            return {"error": "invalid"}

        if not isinstance(deps, list):
            return {"error": "invalid"}

        seen = set()
        for dep in deps:
            if not isinstance(dep, str) or dep in seen:
                return {"error": "invalid"}
            seen.add(dep)

        records[task_id] = (duration, tuple(deps))

    dependents = {task_id: [] for task_id in records}
    remaining = {}

    for task_id, (_, deps) in records.items():
        remaining[task_id] = len(deps)
        for dep in deps:
            if dep not in records or dep == task_id:
                return {"error": "invalid"}
            dependents[dep].append(task_id)

    ready = [task_id for task_id, count in remaining.items() if count == 0]
    heapq.heapify(ready)

    running = []
    order = []
    start = {}
    finish = {}
    completed = 0

    def start_ready(now):
        slots = workers - len(running)
        while slots > 0 and ready:
            task_id = heapq.heappop(ready)
            task_finish = now + records[task_id][0]

            order.append(task_id)
            start[task_id] = now
            finish[task_id] = task_finish
            heapq.heappush(running, (task_finish, task_id))

            slots -= 1

    start_ready(0)

    while running:
        now = running[0][0]
        finished_now = []

        while running and running[0][0] == now:
            _, task_id = heapq.heappop(running)
            finished_now.append(task_id)
            completed += 1

        for task_id in finished_now:
            for dependent in dependents[task_id]:
                remaining[dependent] -= 1
                if remaining[dependent] == 0:
                    heapq.heappush(ready, dependent)

        start_ready(now)

    if completed != len(records):
        return {"error": "invalid"}

    return {
        "order": order,
        "start": start,
        "finish": finish,
        "makespan": max(finish.values(), default=0),
    }
