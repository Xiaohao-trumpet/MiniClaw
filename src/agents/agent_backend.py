"""Backward-compatible alias for the new model adapter contract."""

from src.models.model_adapter import GenerationOptions, ModelAdapter, ModelRequest, ModelResponse, ModelUsage

AgentBackend = ModelAdapter

__all__ = [
    "AgentBackend",
    "GenerationOptions",
    "ModelAdapter",
    "ModelRequest",
    "ModelResponse",
    "ModelUsage",
]
