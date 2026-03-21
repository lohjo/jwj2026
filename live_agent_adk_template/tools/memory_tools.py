"""ADK tools for semantic memory operations.

Each tool is a plain function with typed args and docstring, passed to the ADK agent.
"""

from __future__ import annotations

from google.adk.tools import ToolContext


async def ingest_text(text: str, source: str, tool_context: ToolContext) -> dict:
    """Ingest a text event into semantic memory.

    Args:
        text: The text content to embed and store.
        source: Origin of the text (e.g. 'user', 'agent', 'document').

    Returns:
        dict with node id and 3D position.
    """
    from backend.embeddings.service import get_embedding_service
    from adk_app.runtime.pipeline import get_pipeline

    embedding = await get_embedding_service().embed_text(text)
    pipeline = get_pipeline()
    node = await pipeline.ingest(
        embedding=embedding,
        modality="text",
        label=text[:80],
        source=source,
        metadata={"full_text": text},
    )
    tool_context.state["last_ingested_node"] = node.id
    return {
        "status": "success",
        "node_id": node.id,
        "position_3d": node.position_3d,
        "cluster_id": node.cluster_id,
    }


async def ingest_image(image_description: str, source: str, tool_context: ToolContext) -> dict:
    """Ingest an image event by its description into semantic memory.

    Args:
        image_description: A textual description of the image content.
        source: Origin of the image (e.g. 'screenshot', 'upload').

    Returns:
        dict with node id and 3D position.
    """
    from backend.embeddings.service import get_embedding_service
    from adk_app.runtime.pipeline import get_pipeline

    embedding = await get_embedding_service().embed_text(image_description)
    pipeline = get_pipeline()
    node = await pipeline.ingest(
        embedding=embedding,
        modality="image",
        label=image_description[:80],
        source=source,
        metadata={"description": image_description},
    )
    tool_context.state["last_ingested_node"] = node.id
    return {
        "status": "success",
        "node_id": node.id,
        "position_3d": node.position_3d,
    }


_DEPRIORITIZE_KEYWORDS = {"review", "fixation", "deprioritize", "duplicate", "flagged"}


def _is_deprioritized(node) -> bool:
    """Check if any annotation contains a deprioritize keyword."""
    for ann in node.annotations:
        lower = ann.lower()
        if any(kw in lower for kw in _DEPRIORITIZE_KEYWORDS):
            return True
    return False


async def search_memory(query: str, top_k: int, tool_context: ToolContext) -> dict:
    """Search semantic memory for nodes similar to the query.

    Args:
        query: Natural language search query.
        top_k: Number of results to return.

    Returns:
        dict with list of matching nodes, including annotations.
        Nodes annotated with review/fixation/deprioritize keywords are
        pushed to the end of results (not excluded).
    """
    from backend.embeddings.service import get_embedding_service
    from adk_app.runtime.pipeline import get_pipeline

    embedding = await get_embedding_service().embed_text(query)
    pipeline = get_pipeline()
    nodes = await pipeline.search(embedding=embedding, top_k=top_k)

    # Stable sort: deprioritized nodes go to the end
    nodes.sort(key=lambda n: (1 if _is_deprioritized(n) else 0))

    return {
        "status": "success",
        "count": len(nodes),
        "results": [
            {
                "node_id": n.id,
                "label": n.label,
                "modality": n.modality,
                "position_3d": n.position_3d,
                "cluster_id": n.cluster_id,
                "annotations": n.annotations,
                "deprioritized": _is_deprioritized(n),
            }
            for n in nodes
        ],
    }


async def search_by_annotation(
    annotation_query: str, tool_context: ToolContext
) -> dict:
    """Find all memory nodes that have annotations matching the query text.

    Args:
        annotation_query: Text to match against node annotations (case-insensitive substring match).

    Returns:
        dict with list of matching annotated nodes.
    """
    from adk_app.runtime.pipeline import get_pipeline

    pipeline = get_pipeline()
    all_nodes = await pipeline.vector_store.get_all()
    query_lower = annotation_query.lower()

    matches = [
        n for n in all_nodes
        if any(query_lower in ann.lower() for ann in n.annotations)
        and not n.hidden
    ]

    return {
        "status": "success",
        "count": len(matches),
        "results": [
            {
                "node_id": n.id,
                "label": n.label,
                "modality": n.modality,
                "position_3d": n.position_3d,
                "cluster_id": n.cluster_id,
                "annotations": n.annotations,
            }
            for n in matches
        ],
    }


async def edit_node(
    node_id: str, action: str, value: str, tool_context: ToolContext
) -> dict:
    """Edit a semantic memory node.

    Args:
        node_id: The ID of the node to edit.
        action: One of 'relabel', 'pin', 'unpin', 'annotate', 'hide', 'delete'.
        value: The new label, annotation text, or empty string for toggle actions.

    Returns:
        dict with updated node state.
    """
    from adk_app.runtime.pipeline import get_pipeline

    pipeline = get_pipeline()
    result = await pipeline.edit_node(node_id=node_id, action=action, value=value)
    return result


async def get_trajectory_summary(tool_context: ToolContext) -> dict:
    """Get a summary of recent semantic trajectory patterns.

    Returns:
        dict with trajectory segments and current pattern.
    """
    from adk_app.runtime.pipeline import get_pipeline

    pipeline = get_pipeline()
    tracker = pipeline.trajectory_tracker
    active = tracker.get_active_segment()
    recent = tracker.get_recent_trajectory(n=20)
    segments = tracker.segments[-5:]  # last 5 completed segments

    return {
        "status": "success",
        "active_pattern": active.pattern,
        "active_drift": active.drift_magnitude,
        "recent_point_count": len(recent),
        "completed_segments": [
            {
                "pattern": s.pattern,
                "drift": s.drift_magnitude,
                "point_count": len(s.points),
            }
            for s in segments
        ],
    }


async def get_atlas_stats(tool_context: ToolContext) -> dict:
    """Get current atlas statistics.

    Returns:
        dict with atlas state information.
    """
    from adk_app.runtime.pipeline import get_pipeline

    pipeline = get_pipeline()
    atlas = pipeline.atlas
    store = pipeline.vector_store

    all_nodes = await store.get_all()
    return {
        "status": "success",
        "atlas_initialized": atlas.initialized,
        "landmark_count": atlas.landmark_count,
        "total_nodes": len(all_nodes),
        "modality_distribution": _count_modalities(all_nodes),
    }


def _count_modalities(nodes) -> dict[str, int]:
    counts: dict[str, int] = {}
    for n in nodes:
        counts[n.modality] = counts.get(n.modality, 0) + 1
    return counts
