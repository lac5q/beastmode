from __future__ import annotations

from typing import get_type_hints

from beastmode.core.schema import required_meta_fields
from beastmode.langgraph.state import BeastmodeState, CHILD_META_FIELDS, ChildMeta


def test_child_meta_fields_are_derived_from_schema() -> None:
    assert CHILD_META_FIELDS == required_meta_fields()
    assert set(ChildMeta.__required_keys__) == set(required_meta_fields())


def test_state_exposes_a_reducer_for_fanout_metadata() -> None:
    child_meta = get_type_hints(BeastmodeState, include_extras=True)["child_meta"]
    assert child_meta.__metadata__[0].__name__ == "add"
