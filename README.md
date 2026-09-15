# PRSense

AI-powered GitHub PR review bot. 100% free stack: Gemini/Groq LLMs, LangChain +
LangGraph, MCP tools, ChromaDB RAG, FastAPI, Streamlit. Built around a rigorous
evaluation framework that proves each iteration's improvement with metrics.

> Status: **Phase 4 (evaluation framework) built — dataset scrape pending a GitHub token.**

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
│   ├── agents/
│   │   ├── mcp_bridge.py       # loads MCP tools as LangChain tools for LangGraph
│   │   ├── schema.py           # Finding / ReviewResult (structured LLM output)
│   │   ├── prompts.py          # review prompts (v1 baseline + v2 precision-focused)
│   │   ├── llm.py              # Gemini primary, Groq fallback, provider override
│   │   └── graph.py            # the 5-node LangGraph review pipeline
│   ├── evals/
│   │   ├── labeling.py         # per-repo revert/regression/security detection (GitHub Search API)
│   │   ├── dataset_builder.py  # scrape + label historical PRs -> data/dataset.jsonl
│   │   ├── metrics.py          # precision/recall/F1/FPR + latency percentiles (pure fns)
│   │   ├── framework.py        # offline eval runner, caching, A/B comparison
│   │   └── regression_suite.py # curates the fixed must-catch/must-not-flag case set
│   └── db/client.py            # SQLite eval-run history (git commit + timestamp per run)
├── scripts/
│   ├── phase2_demo.py          # seed / query / mcp  — hands-on, no keys
│   └── phase3_demo.py          # run the full agent on a real PR — needs 1 LLM key
├── .github/workflows/ci.yml    # unit tests always; regression suite if a key secret exists
└── tests/                      # 29 tests (webhook, MCP, agent graph, eval metrics/framework/db — all mocked)
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

## Phase 3 — the review agent

```
fetch_context → retrieve_similar_prs → review → format_comment → post_comment
```

- **fetch_context / retrieve_similar_prs**: call the same functions the MCP
  server exposes (`app/mcp/tools.py`) directly — no subprocess spawned per
  review, which keeps the Phase 4 eval harness fast. The MCP server itself
  still stands as the interface for any *external* MCP client.
- **review**: Gemini primary, Groq automatic fallback on any error (quota,
  timeout, missing key), structured JSON output (`ReviewResult` — summary,
  typed findings with severity/file/line, overall risk).
- **format_comment**: findings → a readable Markdown GitHub comment.
- **post_comment**: gated by `AUTO_POST_COMMENTS` (default `false` — dry run,
  logged only). Flip it to `true` in `.env`, or pass `--post` to the demo
  script, once you trust the output.
- **Tracing**: every node is `@traceable`; set `LANGSMITH_TRACING=true` +
  `LANGSMITH_API_KEY` in `.env` to see each run's node-by-node trace at
  smith.langchain.com (free tier). Off by default — nothing phones home
  until you opt in.

Try it (needs one free key — `GEMINI_API_KEY` from
[aistudio.google.com/apikey](https://aistudio.google.com/apikey)):

```bash
.venv\Scripts\python scripts\phase3_demo.py                          # dry run, real PR
.venv\Scripts\python scripts\phase3_demo.py --pr pallets/flask#6145
.venv\Scripts\python scripts\phase3_demo.py --post                   # actually comments — careful
```

Without any key, `scripts/phase3_demo.py` prints the signup links and exits;
`tests/test_agent_graph.py` covers the graph's logic fully mocked, no key
needed.

## Phase 4 — evaluation framework

Needs `GITHUB_TOKEN` in `.env` (dataset scraping) and at least one LLM key
(eval runs). **This is the part of the project meant to be defensible, not
decorative** — every number below comes from a real run against real merged
PRs, not a hand-picked example.

### 1. Build the labeled dataset

```bash
.venv\Scripts\python -m app.evals.dataset_builder build --per-repo 50   # ~150 PRs total
.venv\Scripts\python -m app.evals.dataset_builder stats
```

Labels (`had_bug`, `had_security_issue`, `clean_merge`, `reverted`) are
derived from auditable public signals, not guessed — see
[`app/evals/labeling.py`](app/evals/labeling.py) docstring for the exact
rules. This is a **high-precision, low-recall** scheme: it will under-count
bugs that were fixed without referencing the original PR number. To measure
how good the auto-labeling actually is:

```bash
.venv\Scripts\python -m app.evals.dataset_builder audit --n 30   # -> data/label_audit.csv
# fill in the human_label column by hand, then:
.venv\Scripts\python -m app.evals.dataset_builder audit-report   # -> measured labeling precision
```

### 2. Index the dataset for RAG, then run an eval

```bash
.venv\Scripts\python -m app.evals.framework index                              # seed ChromaDB
.venv\Scripts\python -m app.evals.framework run --config v1_baseline --sample 50
.venv\Scripts\python -m app.evals.framework history
```

Reports precision / recall / F1 / false-positive-rate (PR-level: does the
agent flag ≥1 bug/security finding on a PR that's actually labeled buggy?)
and latency p50/p95/p99. Every LLM call is cached to disk keyed by
`(config, pr_id, diff)` — re-running the same config again is instant and
free; only a genuinely new (config, PR) pair spends quota.

### 3. A/B compare configs

```bash
.venv\Scripts\python -m app.evals.framework compare --configs v1_baseline v2_precision --sample 50
.venv\Scripts\python -m app.evals.framework compare --configs v1_baseline no_retrieval --sample 50
```

Built-in configs (`app/evals/framework.py::CONFIGS`): `v1_baseline`,
`v2_precision` (a stricter prompt that suppresses nitpicks), `no_retrieval`
(RAG turned off — isolates whether the ChromaDB similar-PR lookup actually
helps), `groq_only`. Every run is stored in SQLite (`data/prsense.db`) with
its git commit hash and timestamp, so `history` shows a clear before/after
trail as the project evolves — that table is what feeds the README's results
section and the Phase 5 dashboard.

### 4. Regression suite (must-always-pass cases)

```bash
.venv\Scripts\python -m app.evals.regression_suite select --n-bugs 6 --n-clean 6
.venv\Scripts\python -m pytest -v -m regression
```

Picks the highest-confidence bug cases (reverted PRs — the strongest signal)
and the highest-confidence clean cases (oldest, smallest merged PRs) into a
fixed `data/regression_cases.json`, then runs the *real* agent against every
one. Runs in CI (`.github/workflows/ci.yml`) against a `GEMINI_API_KEY`
repo secret if one is configured; self-skips otherwise rather than failing.
The everyday `pytest -q` / `pytest -v` run excludes this marker by default
(see `pytest.ini`) so normal development never burns LLM quota.

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
- [x] Phase 3 — LangGraph review state machine + LangSmith tracing
- [x] Phase 4 — Evaluation framework built (dataset builder, metrics, A/B harness, regression suite, CI). **Dataset not yet scraped** — needs `GITHUB_TOKEN`; results table goes here once it's run.
- [ ] Phase 5 — Streamlit dashboard + deployment

### Eval results (filled in after the first real run)

| Config | n | Precision | Recall | F1 | FPR | p50 latency |
|---|---|---|---|---|---|---|
| _pending dataset build_ | – | – | – | – | – | – |
