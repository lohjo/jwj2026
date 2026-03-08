"""Deduplicate fetched pages using sentence-transformer embeddings."""

import logging
from typing import Sequence

import numpy as np

logger = logging.getLogger(__name__)

# Lazy-loaded model to avoid import-time GPU init
_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def embed_texts(texts: list[str]) -> np.ndarray:
    """Return L2-normalised embeddings for a list of texts."""
    model = _get_model()
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(embeddings)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two L2-normalised vectors."""
    return float(np.dot(a, b))


def deduplicate(pages, threshold: float = 0.85):
    """
    Remove near-duplicate pages based on cosine similarity.

    Args:
        pages: List of FetchedPage objects.
        threshold: Cosine similarity threshold above which a page is considered duplicate.

    Returns:
        List of unique FetchedPage objects.
    """
    if not pages:
        return []

    texts = [p.text[:2000] for p in pages]  # first 2000 chars for embedding
    try:
        embeddings = embed_texts(texts)
    except Exception:
        logger.exception("Embedding failed; returning all pages without dedup")
        return list(pages)

    keep: list[int] = []
    for i, emb in enumerate(embeddings):
        is_dup = False
        for j in keep:
            if cosine_similarity(emb, embeddings[j]) > threshold:
                logger.debug("Page %s is duplicate of %s", pages[i].url, pages[j].url)
                is_dup = True
                break
        if not is_dup:
            keep.append(i)

    return [pages[i] for i in keep]
