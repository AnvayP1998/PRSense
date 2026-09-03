# PRSense

AI-powered GitHub PR review bot. 100% free stack: Gemini/Groq LLMs, LangChain +
LangGraph, MCP tools, ChromaDB RAG, FastAPI, Streamlit. Built around a rigorous
evaluation framework that proves each iteration's improvement with metrics.

> Status: **Phase 2 (MCP layer + RAG) complete.**

## Stack (all genuinely free)

| Concern | Choice | Free tier |
|---|---|---|
| LLM (primary) | Google Gemini | ~1500 req/day |
| LLM (fallback) | Groq | generous free tier |
| Orchestration | LangChain + LangGraph | OSS |
| Tool protocol | MCP | OSS |
| Vector store | ChromaDB (local) | OSS |
| Relational DB | SQLite (dev) / Supabase (prod) | free |
| Tracing/evals | LangSmith | free tier |
| API | FastAPI | OSS |
| Dashboard | Streamlit | OSS |
| Hosting | Railway / Render free tier | free |

## What's here

```
prsense/
├── app/
│   ├── main.py                 # FastAPI app, /health
│   ├── core/
│   │   ├── config.py           # pydantic-settings, .env driven
│   │   ├── logging.py          # stderr (keeps MCP stdout stream clean)
│   │   └── github_client.py    # PyGithub wrapper: diff, files, metadata, comment
│   ├── webhooks/github.py      # POST /webhook/github, HMAC-SHA256 verified
│   ├── rag/
│   │   ├── embeddings.py       # local ONNX MiniLM (default) | Gemini (opt-in)
│   │   └── retriever.py        # ChromaDB store of historical PRs + labels
│   ├── mcp/
│   │   ├── tools.py            # get_pr_diff / get_repo_files / get_similar_prs /
│   │   │                       #   get_repo_coding_standards  (plain, testable fns)
│   │   └── server.py           # FastMCP server (stdio) wrapping those tools
│   └── agents/mcp_bridge.py    # loads MCP tools as LangChain tools for LangGraph
├── scripts/phase2_demo.py      # seed / query / mcp  — hands-on, no keys
└── tests/                      # 13 tests (webhook, MCP tools, MCP server round-trip)
```

### MCP tools exposed to the LLM

| Tool | Purpose |
|---|---|
| `get_pr_diff(pr_id)` | unified diff + per-file summary (`pr_id` = `owner/repo#123`) |
| `get_repo_files(repo, path, ref?)` | one file's content for extra context |
| `get_similar_prs(diff_text, n_results?)` | RAG over ChromaDB of historical PRs (with bug/revert labels) |
| `get_repo_coding_standards(repo, ref?)` | CONTRIBUTING.md, linters, `.editorconfig`, … |

## Phase 2 — try it (no API keys)

```bash
.venv\Scripts\python scripts\phase2_demo.py seed                       # index demo PRs
.venv\Scripts\python scripts\phase2_demo.py query "auth token is None" # RAG lookup
.venv\Scripts\python scripts\phase2_demo.py mcp                        # call tools via MCP
```

First run downloads the ONNX embedding model once (~79 MB, to `~/.cache/chroma`),
then everything is offline. ChromaDB telemetry is disabled.

## Setup

```bash
cd prsense
python -m venv .venv
.venv\Scripts\activate           # Windows;  source .venv/bin/activate on *nix
pip install -r requirements.txt
copy .env.example .env           # then fill in values
```

Python 3.11+ required (developed on 3.14).

## Run

```bash
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

- `GET  /health` → config sanity check
- `POST /webhook/github` → GitHub PR event receiver

## Test

```bash
.venv\Scripts\python -m pytest -q
```

## Local webhook testing

1. Start the server on :8000.
2. Expose it: `ngrok http 8000` (free) → copy the https URL.
3. On a test repo you own: Settings → Webhooks → Add webhook
   - Payload URL: `https://<ngrok>.ngrok-free.app/webhook/github`
   - Content type: `application/json`
   - Secret: same value as `GITHUB_WEBHOOK_SECRET` in `.env`
   - Events: "Pull requests" only
4. Open/reopen a PR, or use "Recent Deliveries → Redeliver" to replay.

Without ngrok you can still replay a captured payload with `curl` (see tests).

## Free-tier limits to watch

| Service | Limit | Notes |
|---|---|---|
| GitHub API | 5000 req/hr authenticated | `github_client.rate_limit_remaining()` |
| ngrok free | 1 online tunnel, random URL each restart | fine for dev |
| Gemini free | ~1500 req/day, 15 RPM (flash) | Phase 3 |
| Groq free | ~14.4k req/day, model-dependent RPM | Phase 3 fallback |

## Roadmap

- [x] Phase 1 — Foundation (FastAPI, webhook, GitHub client)
- [x] Phase 2 — MCP server + 4 tools, ChromaDB RAG, LangChain/LangGraph bridge
- [ ] Phase 3 — LangGraph review state machine + LangSmith tracing
- [ ] Phase 4 — Evaluation framework (dataset, precision/recall/F1, A/B, regression suite)
- [ ] Phase 5 — Streamlit dashboard + deployment
