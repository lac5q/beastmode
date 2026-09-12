def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _better(candidate, current):
    if current is None:
        return True
    if candidate[0] != current[0]:
        return candidate[0] > current[0]
    if candidate[1] != current[1]:
        return candidate[1] < current[1]
    return candidate[2] < current[2]


def solve(payload):
    if not isinstance(payload, dict) or set(payload) != {"cpu", "memory", "jobs"}:
        return {"error": "invalid"}
    limit_cpu = payload["cpu"]
    limit_memory = payload["memory"]
    jobs = payload["jobs"]
    if (
        not _integer(limit_cpu)
        or not 0 <= limit_cpu <= 64
        or not _integer(limit_memory)
        or not 0 <= limit_memory <= 64
        or not isinstance(jobs, list)
        or len(jobs) > 16
    ):
        return {"error": "invalid"}
    seen = set()
    for job in jobs:
        if not isinstance(job, dict) or set(job) != {"id", "cpu", "memory", "priority", "deps"}:
            return {"error": "invalid"}
        ident = job["id"]
        if (
            not isinstance(ident, str)
            or not 1 <= len(ident) <= 16
            or ident in seen
            or not _integer(job["cpu"])
            or not 1 <= job["cpu"] <= 32
            or not _integer(job["memory"])
            or not 1 <= job["memory"] <= 32
            or not _integer(job["priority"])
            or not 1 <= job["priority"] <= 1000
            or not isinstance(job["deps"], list)
            or len(job["deps"]) > 16
        ):
            return {"error": "invalid"}
        if any(not isinstance(dep, str) for dep in job["deps"]):
            return {"error": "invalid"}
        if len(set(job["deps"])) != len(job["deps"]):
            return {"error": "invalid"}
        seen.add(ident)
    ids = [job["id"] for job in jobs]
    index = {ident: number for number, ident in enumerate(ids)}
    direct = []
    for job in jobs:
        mask = 0
        for dep in job["deps"]:
            if dep not in index or dep == job["id"]:
                return {"error": "invalid"}
            mask |= 1 << index[dep]
        direct.append(mask)
    state = [0] * len(jobs)
    closure = [0] * len(jobs)

    def visit(number):
        if state[number] == 1:
            raise ValueError
        if state[number] == 2:
            return closure[number]
        state[number] = 1
        result = direct[number]
        for dependency in range(len(jobs)):
            if direct[number] & (1 << dependency):
                result |= visit(dependency)
        state[number] = 2
        closure[number] = result
        return result

    try:
        for number in range(len(jobs)):
            visit(number)
    except ValueError:
        return {"error": "invalid"}

    best = (0, 0, ())
    best_usage = (0, 0)
    for mask in range(1 << len(jobs)):
        valid = True
        used_cpu = 0
        used_memory = 0
        priority = 0
        selected_ids = []
        for number, job in enumerate(jobs):
            if mask & (1 << number):
                if closure[number] & mask != closure[number]:
                    valid = False
                    break
                used_cpu += job["cpu"]
                used_memory += job["memory"]
                priority += job["priority"]
                selected_ids.append(job["id"])
        if not valid or used_cpu > limit_cpu or used_memory > limit_memory:
            continue
        selected_ids = tuple(sorted(selected_ids))
        candidate = (priority, used_cpu + used_memory, selected_ids)
        if _better(candidate, best):
            best = candidate
            best_usage = (used_cpu, used_memory)
    return {
        "selected": list(best[2]),
        "used": {"cpu": best_usage[0], "memory": best_usage[1]},
        "priority": best[0],
    }
