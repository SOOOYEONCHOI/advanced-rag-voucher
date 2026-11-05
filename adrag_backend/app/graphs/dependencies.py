"""Dependencies injected into compiled RAG graph nodes."""

from dataclasses import dataclass

from app.core.config import Settings
from app.core.runtime_settings import get_runtime_settings
from app.core.container import PipelineContainer


@dataclass(frozen=True)
class GraphDependencies:
    settings: Settings
    container: PipelineContainer


def default_graph_dependencies() -> GraphDependencies:
    settings = get_runtime_settings()
    return GraphDependencies(settings=settings, container=PipelineContainer(settings))
