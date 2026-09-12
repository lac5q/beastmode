import heapq


def solve(payload):
    def is_integer(value):
        return isinstance(value, int) and not isinstance(value, bool)

    if not isinstance(payload, dict):
        return {"error": "invalid"}

    lanes = payload.get("lanes")
    tasks = payload.get("tasks")

    if not is_integer(lanes) or not 1 <= lanes <= 80:
        return {"error": "invalid"}
    if not isinstance(tasks, list) or len(tasks) > 80:
        return {"error": "invalid"}

    ids = []
    durations = {}
    dependencies = {}
    task_ids = set()

    for task in tasks:
        if not isinstance(task, dict):
            return {"error": "invalid"}
        if any(field not in task for field in ("id", "duration", "deps")):
            return {"error": "invalid"}

        task_id = task["id"]
        duration = task["duration"]
        deps = task["deps"]

        if (
            not isinstance(task_id, str)
            or not task_id
            or len(task_id) > 40
            or not is_integer(duration)
            or not 1 <= duration <= 100000
            or not isinstance(deps, list)
        ):
            return {"error": "invalid"}

        if task_id in task_ids:
            return {"error": "invalid"}

        if any(not isinstance(dep, str) for dep in deps):
            return {"error": "invalid"}
        if len(set(deps)) != len(deps):
            return {"error": "invalid"}

        task_ids.add(task_id)
        ids.append(task_id)
        durations[task_id] = duration
        dependencies[task_id] = deps

    dependents = {task_id: [] for task_id in ids}
    indegree = {task_id: len(dependencies[task_id]) for task_id in ids}

    for task_id in ids:
        for dependency in dependencies[task_id]:
            if dependency not in task_ids or dependency == task_id:
                return {"error": "invalid"}
            dependents[dependency].append(task_id)

    topo_indegree = indegree.copy()
    topo_queue = [
        task_id for task_id in ids if topo_indegree[task_id] == 0
    ]
    topo_order = []

    for task_id in topo_queue:
        topo_order.append(task_id)
        for child in dependents[task_id]:
            topo_indegree[child] -= 1
            if topo_indegree[child] == 0:
                topo_queue.append(child)

    if len(topo_order) != len(ids):
        return {"error": "invalid"}

    critical = {}
    for task_id in reversed(topo_order):
        critical[task_id] = durations[task_id] + max(
            (critical[child] for child in dependents[task_id]),
            default=0,
        )

    remaining = indegree.copy()
    ready = []
    for task_id in ids:
        if remaining[task_id] == 0:
            heapq.heappush(ready, (-critical[task_id], task_id))

    running = []
    start = {}
    finish = {}
    order = []
    free_lanes = lanes
    current_time = 0

    while ready or running:
        while ready and free_lanes:
            _, task_id = heapq.heappop(ready)
            start[task_id] = current_time
            finish_time = current_time + durations[task_id]
            finish[task_id] = finish_time
            order.append(task_id)
            heapq.heappush(running, (finish_time, task_id))
            free_lanes -= 1

        if not running:
            return {"error": "invalid"}

        current_time = running[0][0]
        while running and running[0][0] == current_time:
            _, completed = heapq.heappop(running)
            free_lanes += 1

            for child in dependents[completed]:
                remaining[child] -= 1
                if remaining[child] == 0:
                    heapq.heappush(ready, (-critical[child], child))

    if len(order) != len(ids):
        return {"error": "invalid"}

    return {
        "order": order,
        "start": start,
        "finish": finish,
        "makespan": max(finish.values(), default=0),
        "critical": critical,
    }
