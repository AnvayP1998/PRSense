"""Embedding function selection for the RAG store.

Default: ChromaDB's built-in ONNX MiniLM (all-MiniLM-L6-v2) — fully local,
no API key, ~79 MB model downloaded once to ~/.cache/chroma.

Optional: Gemini embeddings (free tier) if GEMINI_API_KEY is set and
PRSENSE_EMBEDDINGS=gemini. Kept behind a flag so nothing breaks offline.
"""
from __future__ import annotations

import os

from chromadb.utils import embedding_functions

from app.core.config import get_settings


def get_embedding_function():
    mode = os.getenv("PRSENSE_EMBEDDINGS", "local").lower()
    settings = get_settings()

    if mode == "gemini" and settings.gemini_api_key:
        return embedding_functions.GoogleGenerativeAiEmbeddingFunction(
            api_key=settings.gemini_api_key,
            model_name="models/text-embedding-004",
        )

    # Local default. Deterministic, offline, free.
    return embedding_functions.ONNXMiniLM_L6_V2()
