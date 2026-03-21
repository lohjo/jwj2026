"""Semantic event pipeline.

Central coordinator that connects embeddings → atlas → vector store → trajectories → websocket.
"""

from __future__ import annotations

import logging
import time
import uuid

from backend.atlas.engine import SemanticAtlas
from backend.models import MemoryNode, TrajectoryPoint
from backend.trajectories.tracker import TrajectoryTracker
from backend.vectorstore.base import VectorStore
from backend.vectorstore.factory import create_vector_store
from backend.websocket.hub import hub

logger = logging.getLogger(__name__)


class SemanticPipeline:
    """Orchestrates the full ingest → embed → project → store → broadcast flow."""

    def __init__(self):
        self.vector_store: VectorStore = create_vector_store()
        self.atlas: SemanticAtlas = SemanticAtlas()
        self.trajectory_tracker: TrajectoryTracker = TrajectoryTracker()
        self._initialized = False

    @property
    def is_ready(self) -> bool:
        return self._initialized

    async def initialize(self) -> None:
        """Initialize vector store and load existing embeddings into atlas."""
        await self.vector_store.initialize()

        # Try to bootstrap atlas from existing data
        existing = await self.vector_store.get_all()
        if existing:
            embeddings = [n.embedding for n in existing if n.embedding]
            if len(embeddings) >= 4:
                self.atlas.initialize_from_embeddings(embeddings)
                # Re-project existing nodes
                for node in existing:
                    if node.embedding:
                        node.position_3d = self.atlas.project(node.embedding)
                await self.vector_store.upsert_batch(existing)

        self._initialized = True
        logger.info(
            "Pipeline initialized (atlas=%s, nodes=%d)",
            self.atlas.initialized,
            len(existing) if existing else 0,
        )

    async def ingest(
        self,
        embedding: list[float],
        modality: str = "text",
        label: str = "",
        source: str = "user",
        metadata: dict | None = None,
    ) -> MemoryNode:
        """Ingest an embedding into the full pipeline."""
        node_id = uuid.uuid4().hex
        now = time.time()
        had_atlas = self.atlas.initialized

        # Atlas projection
        if not self.atlas.initialized:
            auto_init = self.atlas.buffer_embedding(embedding)
            if auto_init:
                # Re-project all previously buffered nodes with real positions
                all_nodes = await self.vector_store.get_all()
                if all_nodes:
                    for n in all_nodes:
                        if n.embedding:
                            n.position_3d = self.atlas.project(n.embedding)
                            n.cluster_id = self.atlas.assign_cluster(n.embedding)
                    await self.vector_store.upsert_batch(all_nodes)
                position_3d = self.atlas.project(embedding)
                # Broadcast full snapshot so frontend gets updated positions
                # (deferred to after this node is stored below)
            else:
                # Pre-init: spread nodes using first embedding dims
                # so they don't all pile up at the origin
                position_3d = self.atlas.pre_init_position(embedding)
        else:
            position_3d = self.atlas.project(embedding)
            self.atlas.maybe_expand(embedding)

        # Create node
        cluster_id = self.atlas.assign_cluster(embedding) if self.atlas.initialized else -1
        node = MemoryNode(
            id=node_id,
            embedding=embedding,
            position_3d=position_3d,
            label=label,
            modality=modality,
            cluster_id=cluster_id,
            timestamp=now,
            metadata=metadata or {},
        )

        # Store
        await self.vector_store.upsert(node)

        # Trajectory
        tp = TrajectoryPoint(
            node_id=node_id,
            position_3d=position_3d,
            timestamp=now,
            modality=modality,
        )
        completed_segment = self.trajectory_tracker.add_point(tp)

        # Broadcast to frontend
        await hub.broadcast_node_update(node.model_dump(exclude={"embedding"}))

        if completed_segment:
            await hub.broadcast_trajectory_update(completed_segment.model_dump())
            # Alert frontend about trajectory pattern change for voice narration
            active = self.trajectory_tracker.get_active_segment()
            await hub.broadcast({
                "type": "trajectory_alert",
                "payload": {
                    "old_pattern": completed_segment.pattern,
                    "new_pattern": active.pattern,
                    "drift": completed_segment.drift_magnitude,
                    "message": (
                        f"Trajectory pattern shifted from {completed_segment.pattern} "
                        f"to {active.pattern} with drift {completed_segment.drift_magnitude:.3f}"
                    ),
                },
            })

        # Always broadcast the active trajectory so the HUD updates live
        active = self.trajectory_tracker.get_active_segment()
        await hub.broadcast({"type": "active_trajectory", "payload": active.model_dump()})

        # If atlas just initialized, broadcast full snapshot to update all clients
        if not had_atlas and self.atlas.initialized:
            snapshot = await self.get_snapshot()
            await hub.broadcast_atlas_snapshot(snapshot)

        return node

    async def search(
        self, embedding: list[float], top_k: int = 20
    ) -> list[MemoryNode]:
        """Search the vector store."""
        return await self.vector_store.search(embedding, top_k=top_k)

    async def edit_node(
        self, node_id: str, action: str, value: str = ""
    ) -> dict:
        """Apply an edit to a memory node."""
        node = await self.vector_store.get(node_id)
        if not node:
            return {"status": "error", "message": f"Node {node_id} not found"}

        if action == "relabel":
            node.label = value
            # Re-embed so the node moves to its new semantic position
            from backend.embeddings.service import get_embedding_service
            try:
                embedding = await get_embedding_service().embed_text(value)
                node.embedding = embedding
                if self.atlas.initialized:
                    node.position_3d = self.atlas.project(embedding)
                    node.cluster_id = self.atlas.assign_cluster(embedding)
            except Exception:
                logger.warning("Failed to re-embed relabeled node %s", node_id)
        elif action == "pin":
            node.pinned = True
        elif action == "unpin":
            node.pinned = False
        elif action == "annotate":
            node.annotations.append(value)
        elif action == "hide":
            node.hidden = True
        elif action == "delete":
            await self.vector_store.delete(node_id)
            await hub.broadcast_node_edit({"action": "delete", "node_id": node_id})
            return {"status": "success", "action": "delete", "node_id": node_id}
        else:
            return {"status": "error", "message": f"Unknown action: {action}"}

        await self.vector_store.upsert(node)
        await hub.broadcast_node_edit(
            {"action": action, "node_id": node_id, "value": value}
        )
        # For relabel, also broadcast full node update so frontend gets new position
        # and add a trajectory point so the pattern classification updates.
        if action == "relabel":
            await hub.broadcast_node_update(node.model_dump(exclude={"embedding"}))
            # Trajectory point at the new position so pattern re-classifies
            tp = TrajectoryPoint(
                node_id=node_id,
                position_3d=node.position_3d,
                timestamp=time.time(),
                modality=node.modality,
            )
            completed_segment = self.trajectory_tracker.add_point(tp)
            if completed_segment:
                await hub.broadcast_trajectory_update(completed_segment.model_dump())
            active = self.trajectory_tracker.get_active_segment()
            await hub.broadcast({"type": "active_trajectory", "payload": active.model_dump()})
        return {"status": "success", "action": action, "node_id": node_id}

    async def get_snapshot(self) -> dict:
        """Build a full atlas snapshot for the frontend."""
        all_nodes = await self.vector_store.get_all()
        visible_nodes = [n for n in all_nodes if not n.hidden]

        # Get landmarks as nodes
        landmark_nodes = []
        if self.atlas.initialized:
            positions = self.atlas.get_landmark_positions()
            for i, pos in enumerate(positions):
                landmark_nodes.append(
                    MemoryNode(
                        id=f"landmark_{i}",
                        embedding=[],
                        position_3d=pos,
                        label=f"Landmark {i}",
                        modality="landmark",
                    )
                )

        # Compute similarity edges between all visible nodes
        edges = []
        if self.atlas.initialized and len(visible_nodes) > 1:
            embeddings = [n.embedding for n in visible_nodes if n.embedding]
            node_ids = [n.id for n in visible_nodes if n.embedding]
            if len(embeddings) >= 2:
                edges = self.atlas.compute_similarity_edges(embeddings, node_ids)

        # Compute cluster summaries — group labels by cluster_id
        cluster_summaries: dict[int, list[str]] = {}
        for n in visible_nodes:
            cid = n.cluster_id
            if cid >= 0:
                cluster_summaries.setdefault(cid, []).append(n.label[:30])

        return {
            "nodes": [n.model_dump(exclude={"embedding"}) for n in visible_nodes],
            "trajectories": [s.model_dump() for s in self.trajectory_tracker.segments[-10:]],
            "active_trajectory": self.trajectory_tracker.get_active_segment().model_dump(),
            "landmarks": [n.model_dump(exclude={"embedding"}) for n in landmark_nodes],
            "edges": edges,
            "cluster_summaries": cluster_summaries,
            "timestamp": time.time(),
        }


# ── Singleton ────────────────────────────────────────────────────

_pipeline: SemanticPipeline | None = None


def get_pipeline() -> SemanticPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = SemanticPipeline()
    return _pipeline
