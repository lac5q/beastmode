"""Framework-neutral Beastmode primitives.

This package deliberately imports no agent framework. LangGraph, LangChain,
CrewAI, and provider SDKs belong behind optional bindings and extras.
"""

from .contract import AcceptanceContract
from .provenance import ProvenanceResult, check_provenance
from .routing import route_by_verification_cost
from .schema import (
    acn_contract,
    concurrency_default,
    load_schema,
    required_batch_fields,
    required_meta_fields,
    required_task_fields,
    schema_root,
)
from .seats import (
    SeatModel,
    SeatUnavailable,
    UnknownAliasError,
    preflight_seat,
    resolve_alias,
    resolve_many,
    write_child_meta,
)
from .worktree import isolated_worktree

__all__ = [
    "AcceptanceContract",
    "ProvenanceResult",
    "SeatModel",
    "SeatUnavailable",
    "UnknownAliasError",
    "check_provenance",
    "acn_contract",
    "concurrency_default",
    "load_schema",
    "required_meta_fields",
    "required_batch_fields",
    "required_task_fields",
    "resolve_alias",
    "resolve_many",
    "preflight_seat",
    "route_by_verification_cost",
    "schema_root",
    "write_child_meta",
    "isolated_worktree",
]
