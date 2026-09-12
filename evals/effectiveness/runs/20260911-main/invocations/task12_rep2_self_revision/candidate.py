def solve(payload):
    def valid_int(value, low, high):
        return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high

    if not isinstance(payload, dict) or set(payload.keys()) != {"cpu", "memory", "jobs"}:
        return {"error": "invalid"}

    capacity_cpu = payload["cpu"]
    capacity_memory = payload["memory"]
    jobs = payload["jobs"]

    if not valid_int(capacity_cpu, 0, 64) or not valid_int(capacity_memory, 0, 64):
        return {"error": "invalid"}
    if not isinstance(jobs, list) or len(jobs) > 16:
        return {"error": "invalid"}

    expected_keys = {"id", "cpu", "memory", "priority", "deps"}
    ids = []
    job_data = []

    for job in jobs:
        if not isinstance(job, dict) or set(job.keys()) != expected_keys:
            return {"error": "invalid"}

        job_id = job["id"]
        if not isinstance(job_id, str) or not job_id or len(job_id) > 16:
            return {"error": "invalid"}
        if not valid_int(job["cpu"], 1, 32):
            return {"error": "invalid"}
        if not valid_int(job["memory"], 1, 32):
            return {"error": "invalid"}
        if not valid_int(job["priority"], 1, 1000):
            return {"error": "invalid"}

        deps = job["deps"]
        if not isinstance(deps, list) or len(deps) > 16:
            return {"error": "invalid"}
        if any(not isinstance(dep, str) for dep in deps):
            return {"error": "invalid"}
        if len(set(deps)) != len(deps):
            return {"error": "invalid"}

        ids.append(job_id)
        job_data.append(job)

    if len(set(ids)) != len(ids):
        return {"error": "invalid"}

    id_to_index = {job_id: index for index, job_id in enumerate(ids)}
    dependency_indices = []

    for index, job in enumerate(job_data):
        dependencies = []
        for dep in job["deps"]:
            if dep not in id_to_index or dep == ids[index]:
                return {"error": "invalid"}
            dependencies.append(id_to_index[dep])
        dependency_indices.append(dependencies)

    state = [0] * len(jobs)
    required = [0] * len(jobs)

    def visit(index):
        if state[index] == 1:
            raise ValueError
        if state[index] == 2:
            return required[index]

        state[index] = 1
        mask = 1 << index
        for dependency in dependency_indices[index]:
            mask |= visit(dependency)

        required[index] = mask
        state[index] = 2
        return mask

    try:
        for index in range(len(jobs)):
            visit(index)
    except ValueError:
        return {"error": "invalid"}

    best_ids = []
    best_cpu = 0
    best_memory = 0
    best_priority = 0
    best_resource_total = 0

    for mask in range(1 << len(jobs)):
        for index in range(len(jobs)):
            if mask & (1 << index) and (mask & required[index]) != required[index]:
                break
        else:
            used_cpu = 0
            used_memory = 0
            priority = 0
            selected_ids = []

            for index, job in enumerate(job_data):
                if mask & (1 << index):
                    used_cpu += job["cpu"]
                    used_memory += job["memory"]
                    priority += job["priority"]
                    selected_ids.append(ids[index])

            if used_cpu > capacity_cpu or used_memory > capacity_memory:
                continue

            selected_ids.sort()
            resource_total = used_cpu + used_memory

            if (
                priority > best_priority
                or (
                    priority == best_priority
                    and (
                        resource_total < best_resource_total
                        or (
                            resource_total == best_resource_total
                            and selected_ids < best_ids
                        )
                    )
                )
            ):
                best_ids = selected_ids
                best_cpu = used_cpu
                best_memory = used_memory
                best_priority = priority
                best_resource_total = resource_total

    return {
        "selected": best_ids,
        "used": {
            "cpu": best_cpu,
            "memory": best_memory,
        },
        "priority": best_priority,
    }
