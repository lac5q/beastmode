"""Reference implementation for the deterministic dependency scheduler."""


def _invalid():
    return {"error": "invalid"}


def solve(payload):
    if not isinstance(payload, dict) or isinstance(payload.get("workers"), bool):
        return _invalid()
    workers = payload.get("workers")
    tasks = payload.get("tasks")
    if not isinstance(workers, int) or workers < 1 or workers > 80 or not isinstance(tasks, list) or len(tasks) > 80:
        return _invalid()
    by_id = {}
    for task in tasks:
        if not isinstance(task, dict):
            return _invalid()
        ident = task.get("id")
        duration = task.get("duration")
        deps = task.get("deps")
        if (not isinstance(ident, str) or not ident or len(ident) > 40 or ident in by_id
                or isinstance(duration, bool) or not isinstance(duration, int)
                or duration <= 0 or duration > 100000 or not isinstance(deps, list)):
            return _invalid()
        if any(not isinstance(dep, str) for dep in deps) or len(set(deps)) != len(deps):
            return _invalid()
        by_id[ident] = (duration, deps)
    if any(dep not in by_id for _, deps in by_id.values() for dep in deps):
        return _invalid()
    indegree = {ident: 0 for ident in by_id}
    children = {ident: [] for ident in by_id}
    for ident, (_, deps) in by_id.items():
        indegree[ident] = len(deps)
        for dep in deps:
            children[dep].append(ident)
    queue = sorted(ident for ident, degree in indegree.items() if degree == 0)
    visited = []
    while queue:
        ident = queue.pop(0)
        visited.append(ident)
        for child in children[ident]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
                queue.sort()
    if len(visited) != len(by_id):
        return _invalid()

    unstarted = set(by_id)
    running = {}
    completed = set()
    started = {}
    finished = {}
    order = []
    now = 0
    while unstarted or running:
        done = [ident for ident, finish in running.items() if finish == now]
        for ident in done:
            del running[ident]
            completed.add(ident)
        ready = sorted(
            ident for ident in unstarted
            if all(dep in completed for dep in by_id[ident][1])
        )
        for ident in ready[: workers - len(running)]:
            duration = by_id[ident][0]
            unstarted.remove(ident)
            started[ident] = now
            finished[ident] = now + duration
            running[ident] = now + duration
            order.append(ident)
        if running:
            now = min(running.values())
        elif unstarted:
            return _invalid()
    return {
        "order": order,
        "start": started,
        "finish": finished,
        "makespan": max(finished.values(), default=0),
    }
