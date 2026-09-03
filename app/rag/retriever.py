"""ChromaDB-backed store of historical PRs for similarity lookup.

One collection, `historical_prs`. Each document is a compact text summary of a
PR (title + body + truncated diff); metadata carries the label fields the
Phase 4 eval framework needs (had_bug, had_security_issue, clean_merge, ...).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import chromadb

from app.core.config import get_settings
from app.core.logging import get_logger
from app.rag.embeddings import get_embedding_function

log = get_logger(__name__)

COLLECTION = "historical_prs"
_MAX_DIFF_CHARS = 6000


@dataclass
class SimilarPR:
    pr_id: str
    repo: str
    number: int
    title: str
    summary: str
    distance: float
    metadata: dict


def pr_document_text(title: str, body: str, diff: str) -> str:
    body = (body or "").strip()
    diff = (diff or "")[:_MAX_DIFF_CHARS]
    return f"# {title}\n\n{body}\n\n--- DIFF ---\n{diff}".strip()


class SimilarPRStore:
    def __init__(self, persist_dir: str | None = None) -> None:
        path = persist_dir or get_settings().chroma_persist_dir
        Path(path).mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=path,
            settings=chromadb.Settings(anonymized_telemetry=False),
        )
        self._col = self._client.get_or_create_collection(
            name=COLLECTION,
            embedding_function=get_embedding_function(),
            metadata={"hnsw:space": "cosine"},
        )

    def count(self) -> int:
        return self._col.count()

    def add_pr(
        self,
        pr_id: str,
        repo: str,
        number: int,
        title: str,
        body: str,
        diff: str,
        labels: dict | None = None,
    ) -> None:
        meta = {"repo": repo, "number": int(number), "title": title}
        for k, v in (labels or {}).items():
            if isinstance(v, (str, int, float, bool)) or v is None:
                meta[k] = v
        self._col.upsert(
            ids=[pr_id],
            documents=[pr_document_text(title, body, diff)],
            metadatas=[meta],
        )

    def add_many(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        ids, docs, metas = [], [], []
        for r in rows:
            ids.append(r["pr_id"])
            docs.append(pr_document_text(r["title"], r.get("body", ""), r.get("diff", "")))
            meta = {"repo": r["repo"], "number": int(r["number"]), "title": r["title"]}
            for k, v in (r.get("labels") or {}).items():
                if isinstance(v, (str, int, float, bool)) or v is None:
                    meta[k] = v
            metas.append(meta)
        self._col.upsert(ids=ids, documents=docs, metadatas=metas)
        log.info("indexed %d PRs (total=%d)", len(rows), self.count())
        return len(rows)

    def query(self, diff_text: str, n_results: int = 5) -> list[SimilarPR]:
        if self.count() == 0:
            return []
        n = min(n_results, self.count())
        res = self._col.query(query_texts=[diff_text[:_MAX_DIFF_CHARS]], n_results=n)
        out: list[SimilarPR] = []
        for _id, doc, dist, meta in zip(
            res["ids"][0], res["documents"][0], res["distances"][0], res["metadatas"][0]
        ):
            out.append(
                SimilarPR(
                    pr_id=_id,
                    repo=meta.get("repo", ""),
                    number=int(meta.get("number", 0)),
                    title=meta.get("title", ""),
                    summary=doc[:800],
                    distance=float(dist),
                    metadata=meta,
                )
            )
        return out


@lru_cache
def get_similar_pr_store() -> SimilarPRStore:
    return SimilarPRStore()
