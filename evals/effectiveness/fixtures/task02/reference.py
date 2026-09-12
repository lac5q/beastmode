"""Reference implementation for critical-path-priority scheduling."""


def _invalid():
    return {"error": "invalid"}


def solve(payload):
    if not isinstance(payload, dict):
        return _invalid()
    lanes = payload.get("lanes")
    tasks = payload.get("tasks")
    if (isinstance(lanes, bool) or not isinstance(lanes, int) or lanes < 1 or lanes > 80
            or not isinstance(tasks, list) or len(tasks) > 80):
        return _invalid()
    by_id = {}
    for task in tasks:
        if not isinstance(task, dict):
            return _invalid()
        ident, duration, deps = task.get("id"), task.get("duration"), task.get("deps")
        if (not isinstance(ident, str) or not ident or len(ident) > 40 or ident in by_id
                or isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0 or duration > 100000
                or not isinstance(deps, list) or any(not isinstance(dep, str) for dep in deps)):
            return _invalid()
        if len(set(deps)) != len(deps):
            return _invalid()
        by_id[ident] = (duration, deps)
    if any(dep not in by_id for _, deps in by_id.values() for dep in deps):
        return _invalid()
    indegree = {ident: len(deps) for ident, (_, deps) in by_id.items()}
    children = {ident: [] for ident in by_id}
    for ident, (_, deps) in by_id.items():
        for dep in deps:
            children[dep].append(ident)
    queue = sorted(k for k, v in indegree.items() if v == 0)
    topo = []
    while queue:
        ident = queue.pop(0)
        topo.append(ident)
        for child in children[ident]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
                queue.sort()
    if len(topo) != len(by_id):
        return _invalid()
    critical = {}
    for ident in reversed(topo):
        duration, _ = by_id[ident]
        critical[ident] = duration + max((critical[c] for c in children[ident]), default=0)

    unstarted = set(by_id)
    running = {}
    completed = set()
    started, finished, order = {}, {}, []
    now = 0
    while unstarted or running:
        for ident in [k for k, finish in running.items() if finish == now]:
            del running[ident]
            completed.add(ident)
        ready = sorted(
            (ident for ident in unstarted if all(dep in completed for dep in by_id[ident][1])),
            key=lambda ident: (-critical[ident], ident),
        )
        for ident in ready[: lanes - len(running)]:
            unstarted.remove(ident)
            started[ident] = now
            finished[ident] = now + by_id[ident][0]
            running[ident] = finished[ident]
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
        "critical": critical,
    }
