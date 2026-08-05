"""LangGraph-facing state primitives.

The actual graph builders are added in later roadmap phases.  These types are
safe to import alongside a user's own graph and derive their child metadata
shape from the repository schema at import time.
"""

from .context import BeastmodeContext
from .state import BEASTMODE_STATE_KEY_PREFIX, BeastmodeState, ChildMeta, CHILD_META_FIELDS

__all__ = ["BeastmodeContext", "BeastmodeState", "ChildMeta", "CHILD_META_FIELDS", "BEASTMODE_STATE_KEY_PREFIX"]

# State is useful for schema/parity checks even on a machine that has not
# opted into LangGraph.  Keep the runtime binding lazy so the base wheel and
# the install-free bash lane do not acquire an accidental import dependency.
try:
    from .graphs.fanout import FanoutState, build_fanout
    from .gates import autonomy_gate, phase_gate, provenance_gate
    from .nodes import PipelineDependencies, challenge
    from .models import SeatChatModel, as_chat_model
    from .nodes import acceptance_contract, judgment_review, mechanical_validation
    from beastmode.core.routing import route_by_verification_cost
    from .runtime import (
        arun_pipeline,
        async_sqlite_checkpointer,
        async_postgres_checkpointer,
        checkpoint_history,
        durability_for,
        replay_from_checkpoint,
        postgres_checkpointer,
        run_pipeline,
        sqlite_checkpointer,
    )
except ModuleNotFoundError as exc:
    if exc.name and exc.name.startswith("langgraph"):
        pass
    else:
        raise
else:
    __all__ += [
        "FanoutState",
        "PipelineDependencies",
        "challenge",
        "SeatChatModel",
        "as_chat_model",
        "build_fanout",
        "acceptance_contract",
        "autonomy_gate",
        "phase_gate",
        "arun_pipeline",
        "async_sqlite_checkpointer",
        "async_postgres_checkpointer",
        "checkpoint_history",
        "durability_for",
        "judgment_review",
        "mechanical_validation",
        "provenance_gate",
        "route_by_verification_cost",
        "run_pipeline",
        "replay_from_checkpoint",
        "postgres_checkpointer",
        "sqlite_checkpointer",
    ]
