"""Zero-argument LangGraph Studio factory."""

from .graphs.pipeline import build_pipeline


def studio_pipeline():
    """Return the default pipeline for ``langgraph dev`` discovery."""
    return build_pipeline()
