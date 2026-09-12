def solve(payload):
    if type(payload) is not dict or set(payload.keys()) != {"cpu", "memory", "jobs"}:
        return {"error": "invalid"}

    capacity_cpu = payload["cpu"]
    capacity_memory = payload["memory"]
    jobs = payload["jobs"]

    if (
        type(capacity_cpu) is not int
        or type(capacity_memory) is not int
        or not 0 <= capacity_cpu <= 64
        or not 0 <= capacity_memory <= 64
        or type(jobs) is not list
        or len(jobs) > 16
    ):
        return {"error": "invalid"}

    job_keys = {"id", "cpu", "memory", "priority", "deps"}
    ids = []
    job_cpus = []
    job_memories = []
    job_priorities = []
    raw_dependencies = []
    seen_ids = set()

    for job in jobs:
        if type(job) is not dict or set(job.keys()) != job_keys:
            return {"error": "invalid"}

        job_id = job["id"]
        job_cpu = job["cpu"]
        job_memory = job["memory"]
        job_priority = job["priority"]
        dependencies = job["deps"]

        if (
            type(job_id) is not str
            or not 0 < len(job_id) <= 16
            or job_id in seen_ids
            or type(job_cpu) is not int
            or not 1 <= job_cpu <= 32
            or type(job_memory) is not int
            or not 1 <= job_memory <= 32
            or type(job_priority) is not int
            or not 1 <= job_priority <= 1000
            or type(dependencies) is not list
            or len(dependencies) > 16
        ):
            return {"error": "invalid"}

        dependency_set = set()
        for dependency in dependencies:
            if type(dependency) is not str or dependency in dependency_set:
                return {"error": "invalid"}
            dependency_set.add(dependency)

        seen_ids.add(job_id)
        ids.append(job_id)
        job_cpus.append(job_cpu)
        job_memories.append(job_memory)
        job_priorities.append(job_priority)
        raw_dependencies.append(dependencies)

    index_by_id = {job_id: index for index, job_id in enumerate(ids)}
    dependencies_by_index = []

    for index, dependencies in enumerate(raw_dependencies):
        resolved = []
        for dependency in dependencies:
            dependency_index = index_by_id.get(dependency)
            if dependency_index is None or dependency_index == index:
                return {"error": "invalid"}
            resolved.append(dependency_index)
        dependencies_by_index.append(resolved)

    count = len(ids)
    required = [0] * count
    state = [0] * count

    def visit(index):
        if state[index] == 2:
            return required[index]
        if state[index] == 1:
            return None

        state[index] = 1
        mask = 0

        for dependency in dependencies_by_index[index]:
            dependency_mask = visit(dependency)
            if dependency_mask is None:
                return None
            mask |= (1 << dependency) | dependency_mask

        state[index] = 2
        required[index] = mask
        return mask

    for index in range(count):
        if visit(index) is None:
            return {"error": "invalid"}

    size = 1 << count
    cpu_sums = [0] * size
    memory_sums = [0] * size
    priority_sums = [0] * size
    dependency_unions = [0] * size

    best_priority = 0
    best_cost = 0
    best_cpu = 0
    best_memory = 0
    best_ids = ()

    for mask in range(1, size):
        bit = mask & -mask
        index = bit.bit_length() - 1
        previous = mask ^ bit

        cpu_sums[mask] = cpu_sums[previous] + job_cpus[index]
        memory_sums[mask] = memory_sums[previous] + job_memories[index]
        priority_sums[mask] = priority_sums[previous] + job_priorities[index]
        dependency_unions[mask] = dependency_unions[previous] | required[index]

        used_cpu = cpu_sums[mask]
        used_memory = memory_sums[mask]

        if used_cpu > capacity_cpu or used_memory > capacity_memory:
            continue
        if dependency_unions[mask] & ~mask:
            continue

        candidate_priority = priority_sums[mask]
        candidate_cost = used_cpu + used_memory
        candidate_ids = tuple(
            sorted(ids[i] for i in range(count) if mask & (1 << i))
        )

        if candidate_priority > best_priority:
            should_update = True
        elif candidate_priority < best_priority:
            should_update = False
        elif candidate_cost < best_cost:
            should_update = True
        elif candidate_cost > best_cost:
            should_update = False
        else:
            should_update = candidate_ids < best_ids

        if should_update:
            best_priority = candidate_priority
            best_cost = candidate_cost
            best_cpu = used_cpu
            best_memory = used_memory
            best_ids = candidate_ids

    return {
        "selected": list(best_ids),
        "used": {"cpu": best_cpu, "memory": best_memory},
        "priority": best_priority,
    }
