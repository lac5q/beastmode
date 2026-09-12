import heapq


def solve(payload):
    def invalid():
        return {"error": "invalid"}

    if not isinstance(payload, dict):
        return invalid()

    lanes = payload.get("lanes")
    tasks = payload.get("tasks")

    if (
        isinstance(lanes, bool)
        or not isinstance(lanes, int)
        or lanes < 1
        or lanes > 80
        or not isinstance(tasks, list)
        or len(tasks) > 80
    ):
        return invalid()

    ids = []
    durations = []
    deps_by_index = []
    id_to_index = {}

    for task in tasks:
        if not isinstance(task, dict):
            return invalid()
        if "id" not in task or "duration" not in task or "deps" not in task:
            return invalid()

        task_id = task["id"]
        duration = task["duration"]
        deps = task["deps"]

        if (
            not isinstance(task_id, str)
            or not task_id
            or len(task_id) > 40
            or task_id in id_to_index
            or isinstance(duration, bool)
            or not isinstance(duration, int)
            or duration < 1
            or duration > 100000
            or not isinstance(deps, list)
        ):
            return invalid()

        index = len(ids)
        id_to_index[task_id] = index
        ids.append(task_id)
        durations.append(duration)
        deps_by_index.append(deps)

    count = len(ids)
    children = [[] for _ in range(count)]
    indegrees = [0] * count

    for index, deps in enumerate(deps_by_index):
        seen = set()

        for dep_id in deps:
            if not isinstance(dep_id, str) or dep_id in seen:
                return invalid()
            seen.add(dep_id)

            if dep_id not in id_to_index or dep_id == ids[index]:
                return invalid()

            dep_index = id_to_index[dep_id]
            children[dep_index].append(index)
            indegrees[index] += 1

    topo_indegrees = indegrees[:]
    stack = [i for i in range(count) if topo_indegrees[i] == 0]
    topo_order = []

    while stack:
        index = stack.pop()
        topo_order.append(index)

        for child in children[index]:
            topo_indegrees[child] -= 1
            if topo_indegrees[child] == 0:
                stack.append(child)

    if len(topo_order) != count:
        return invalid()

    critical_values = [0] * count

    for index in reversed(topo_order):
        longest_child = 0
        for child in children[index]:
            if critical_values[child] > longest_child:
                longest_child = critical_values[child]
        critical_values[index] = durations[index] + longest_child

    ready = []
    for index in range(count):
        if indegrees[index] == 0:
            heapq.heappush(
                ready,
                (-critical_values[index], ids[index], index),
            )

    running = []
    remaining = indegrees[:]
    order = []
    starts = {}
    finishes = {}
    current_time = 0

    while len(order) < count:
        while ready and len(running) < lanes:
            _, task_id, index = heapq.heappop(ready)
            start_time = current_time
            finish_time = start_time + durations[index]

            starts[task_id] = start_time
            finishes[task_id] = finish_time
            order.append(task_id)

            heapq.heappush(running, (finish_time, task_id, index))

        if not running:
            return invalid()

        current_time = running[0][0]
        completed = []

        while running and running[0][0] == current_time:
            _, _, index = heapq.heappop(running)
            completed.append(index)

        for index in completed:
            for child in children[index]:
                remaining[child] -= 1
                if remaining[child] == 0:
                    heapq.heappush(
                        ready,
                        (-critical_values[child], ids[child], child),
                    )

    critical = {
        ids[index]: critical_values[index]
        for index in range(count)
    }

    makespan = max(finishes.values(), default=0)

    return {
        "order": order,
        "start": starts,
        "finish": finishes,
        "makespan": makespan,
        "critical": critical,
    }
