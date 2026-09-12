def solve(payload):
    def invalid():
        return {"error": "invalid"}

    def valid_int(value, lower, upper):
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            and lower <= value <= upper
        )

    if not isinstance(payload, dict):
        return invalid()
    if set(payload.keys()) != {"cpu", "memory", "jobs"}:
        return invalid()

    capacity_cpu = payload["cpu"]
    capacity_memory = payload["memory"]
    jobs = payload["jobs"]

    if not valid_int(capacity_cpu, 0, 64):
        return invalid()
    if not valid_int(capacity_memory, 0, 64):
        return invalid()
    if not isinstance(jobs, list) or len(jobs) > 16:
        return invalid()

    required_keys = {"id", "cpu", "memory", "priority", "deps"}
    records = []
    seen_ids = set()

    for job in jobs:
        if not isinstance(job, dict):
            return invalid()
        if set(job.keys()) != required_keys:
            return invalid()

        job_id = job["id"]
        job_cpu = job["cpu"]
        job_memory = job["memory"]
        priority = job["priority"]
        deps = job["deps"]

        if not isinstance(job_id, str) or not job_id or len(job_id) > 16:
            return invalid()
        if job_id in seen_ids:
            return invalid()
        seen_ids.add(job_id)

        if not valid_int(job_cpu, 1, 32):
            return invalid()
        if not valid_int(job_memory, 1, 32):
            return invalid()
        if not valid_int(priority, 1, 1000):
            return invalid()

        if not isinstance(deps, list) or len(deps) > 16:
            return invalid()

        seen_deps = set()
        for dep in deps:
            if not isinstance(dep, str) or dep in seen_deps:
                return invalid()
            seen_deps.add(dep)

        records.append((job_id, job_cpu, job_memory, priority, tuple(deps)))

    records.sort(key=lambda record: record[0])
    ids = [record[0] for record in records]
    id_to_index = {job_id: index for index, job_id in enumerate(ids)}

    dependency_masks = []
    for index, record in enumerate(records):
        mask = 0
        for dep in record[4]:
            dep_index = id_to_index.get(dep)
            if dep_index is None or dep_index == index:
                return invalid()
            mask |= 1 << dep_index
        dependency_masks.append(mask)

    states = [0] * len(records)

    def visit(index):
        if states[index] == 1:
            return False
        if states[index] == 2:
            return True

        states[index] = 1
        pending = dependency_masks[index]
        while pending:
            bit = pending & -pending
            dep_index = bit.bit_length() - 1
            if not visit(dep_index):
                return False
            pending ^= bit

        states[index] = 2
        return True

    for index in range(len(records)):
        if not visit(index):
            return invalid()

    n = len(records)
    cpus = [record[1] for record in records]
    memories = [record[2] for record in records]
    priorities = [record[3] for record in records]

    size = 1 << n
    used_cpu = [0] * size
    used_memory = [0] * size
    used_priority = [0] * size

    best_mask = 0
    best_priority = 0
    best_cost = 0
    best_ids = ()

    for mask in range(1, size):
        bit = mask & -mask
        index = bit.bit_length() - 1
        previous = mask ^ bit

        total_cpu = used_cpu[previous] + cpus[index]
        total_memory = used_memory[previous] + memories[index]
        total_priority = used_priority[previous] + priorities[index]

        used_cpu[mask] = total_cpu
        used_memory[mask] = total_memory
        used_priority[mask] = total_priority

        if total_cpu > capacity_cpu or total_memory > capacity_memory:
            continue

        pending = mask
        closed = True
        while pending:
            selected_bit = pending & -pending
            selected_index = selected_bit.bit_length() - 1
            dependencies = dependency_masks[selected_index]
            if dependencies & mask != dependencies:
                closed = False
                break
            pending ^= selected_bit

        if not closed:
            continue

        candidate_ids = tuple(
            ids[selected_index]
            for selected_index in range(n)
            if mask & (1 << selected_index)
        )
        cost = total_cpu + total_memory

        if (
            total_priority > best_priority
            or (
                total_priority == best_priority
                and (
                    cost < best_cost
                    or (cost == best_cost and candidate_ids < best_ids)
                )
            )
        ):
            best_mask = mask
            best_priority = total_priority
            best_cost = cost
            best_ids = candidate_ids

    return {
        "selected": [
            ids[index]
            for index in range(n)
            if best_mask & (1 << index)
        ],
        "used": {
            "cpu": used_cpu[best_mask],
            "memory": used_memory[best_mask],
        },
        "priority": used_priority[best_mask],
    }
