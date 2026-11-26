import hashlib
import math
import re

import httpx
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import SemanticEmbedding

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two equal-length vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=True))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return round(max(-1.0, min(1.0, dot / (norm_a * norm_b))), 4)


def _deterministic_embed(text: str, dimensions: int) -> list[float]:
    """Generate a deterministic L2-normalized feature-hashing embedding vector."""
    dims = max(16, dimensions)
    vec = [0.0] * dims
    words = _TOKEN_RE.findall(text.lower())
    features: list[str] = list(words)
    for w in words:
        if len(w) >= 3:
            for i in range(len(w) - 2):
                features.append(w[i : i + 3])

    if not features:
        return vec

    for feat in features:
        digest = hashlib.blake2b(feat.encode("utf-8"), digest_size=8).digest()
        raw_int = int.from_bytes(digest, "big")
        bucket = raw_int % dims
        sign = 1.0 if ((raw_int >> 63) & 1) == 0 else -1.0
        vec[bucket] += sign

    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0.0:
        vec = [round(v / norm, 6) for v in vec]
    return vec


class EmbeddingService:
    """Generates semantic embeddings via deterministic hashing or local Ollama."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.dimensions = settings.embedding_dimensions

    async def embed(self, text: str) -> tuple[list[float], str]:
        """Return (vector, provider_used) for input text."""
        if self.settings.embedding_provider == "ollama":
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(
                        f"{self.settings.ollama_base_url.rstrip('/')}/api/embeddings",
                        json={
                            "model": self.settings.ollama_default_model,
                            "prompt": text,
                        },
                    )
                    resp.raise_for_status()
                    raw_vec = resp.json().get("embedding")
                    if isinstance(raw_vec, list) and raw_vec:
                        return [float(x) for x in raw_vec], "ollama"
            except Exception:
                pass
        return _deterministic_embed(text, self.dimensions), "deterministic"


async def upsert_embedding(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: str,
    source_text: str,
    embedding_service: EmbeddingService,
) -> SemanticEmbedding:
    """Persist or update a semantic embedding vector for a domain entity."""
    vector, provider = await embedding_service.embed(source_text)
    existing = (
        await db.execute(
            select(SemanticEmbedding).where(
                SemanticEmbedding.entity_type == entity_type,
                SemanticEmbedding.entity_id == entity_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        row = SemanticEmbedding(
            entity_type=entity_type,
            entity_id=entity_id,
            source_text=source_text,
            provider=provider,
            dimensions=len(vector),
            vector_json=vector,
        )
        db.add(row)
        await db.flush()
        return row

    existing.source_text = source_text
    existing.provider = provider
    existing.dimensions = len(vector)
    existing.vector_json = vector
    await db.flush()
    return existing


async def find_similar_entities(
    db: AsyncSession,
    *,
    entity_type: str,
    query_text: str,
    embedding_service: EmbeddingService,
    top_k: int = 5,
    min_score: float = 0.20,
) -> list[tuple[SemanticEmbedding, float]]:
    """Rank stored embeddings by cosine similarity against query_text."""
    query_vec, _ = await embedding_service.embed(query_text)
    rows = (
        await db.execute(
            select(SemanticEmbedding).where(SemanticEmbedding.entity_type == entity_type)
        )
    ).scalars().all()

    scored: list[tuple[SemanticEmbedding, float]] = []
    for row in rows:
        score = cosine_similarity(query_vec, row.vector_json)
        if score >= min_score:
            scored.append((row, score))

    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:top_k]


def get_embedding_service(request: Request) -> EmbeddingService:
    """FastAPI dependency returning the app-scoped EmbeddingService."""
    svc: EmbeddingService = request.app.state.embedding_service
    return svc
