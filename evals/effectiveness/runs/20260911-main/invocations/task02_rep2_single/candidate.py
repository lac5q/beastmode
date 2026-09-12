def solve(payload):
    def invalid():
        return {"error": "invalid"}

    if type(payload) is not dict:
        return invalid()

    lanes = payload.get("lanes")
    tasks = payload.get("tasks")

    if type(lanes) is not int or not 1 <= lanes <= 80:
        return invalid()
    if type(tasks) is not list or len(tasks) > 80:
        return invalid()

    ids = []
    durations = {}
    task_deps = {}

    for task in tasks:
        if type(task) is not dict:
            return invalid()
        if "id" not in task or "duration" not in task or "deps" not in task:
            return invalid()

        task_id = task["id"]
        duration = task["duration"]
        deps = task["deps"]

        if type(task_id) is not str or not task_id or len(task_id) > 40:
            return invalid()
        if task_id in durations:
            return invalid()
        if type(duration) is not int or not 1 <= duration <= 100000:
            return invalid()
        if type(deps) is not list:
            return invalid()

        seen = set()
        for dep in deps:
            if type(dep) is not str or dep in seen:
                return invalid()
            seen.add(dep)

        ids.append(task_id)
        durations[task_id] = duration
        task_deps[task_id] = deps

    dependants = {task_id: [] for task_id in ids}

    for task_id in ids:
        for dep in task_deps[task_id]:
            if dep not in durations or dep == task_id:
                return invalid()
            dependants[dep].append(task_id)

    indegree = {task_id: len(task_deps[task_id]) for task_id in ids}
    queue = [task_id for task_id in ids if indegree[task_id] == 0]
    topo = []

    while queue:
        task_id = queue.pop()
        topo.append(task_id)
        for child in dependants[task_id]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)

    if len(topo) != len(ids):
        return invalid()

    critical = {task_id: durations[task_id] for task_id in ids}
    for task_id in reversed(topo):
        if dependants[task_id]:
            critical[task_id] = durations[task_id] + max(
                critical[child] for child in dependants[task_id]
            )

    remaining = {task_id: len(task_deps[task_id]) for task_id in ids}
    ready = [task_id for task_id in ids if remaining[task_id] == 0]
    running = {}
    active = 0
    completed = 0
    now = 0

    order = []
    start_times = {}
    finish_times = {}

    while completed < len(ids):
        if running:
            now = min(running)
            finished = running.pop(now)
            active -= len(finished)
            completed += len(finished)

            for task_id in finished:
                for child in dependants[task_id]:
                    remaining[child] -= 1
                    if remaining[child] == 0:
                        ready.append(child)
        elif not ready:
            return invalid()

        slots = lanes - active
        if slots > 0 and ready:
            ready.sort(key=lambda task_id: (-critical[task_id], task_id))
            count = min(slots, len(ready))
            selected = ready[:count]
            del ready[:count]

            for task_id in selected:
                start_times[task_id] = now
                finish_time = now + durations[task_id]
                finish_times[task_id] = finish_time
                running.setdefault(finish_time, []).append(task_id)
                order.append(task_id)

            active += count

    return {
        "order": order,
        "start": {task_id: start_times[task_id] for task_id in ids},
        "finish": {task_id: finish_times[task_id] for task_id in ids},
        "makespan": max(finish_times.values(), default=0),
        "critical": {task_id: critical[task_id] for task_id in ids},
    }
