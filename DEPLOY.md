# Deploying PRSense (free tier)

Two services from one repo: the FastAPI webhook app, and the Streamlit
dashboard. Both are stateless enough to run on a free web-service tier —
with one real caveat, covered first.

## The one thing that isn't actually free-and-persistent: disk

Render's and Railway's free/hobby web services use **ephemeral disk** — a
redeploy, restart, or (on Render free) the instance sleeping after 15
minutes idle and waking back up can wipe `data/prsense.db` (eval history +
review feed) and `data/chroma/` (the RAG index). Durable disk on either
platform is a paid add-on, which breaks the "100% free" constraint this
project holds itself to.

What this means in practice, and the workaround actually used here:

- **`data/dataset.jsonl` is committed to the repo** (see the README), so
  every deploy can re-seed ChromaDB from a real 150-PR dataset in seconds —
  no re-scraping, no `GITHUB_TOKEN` needed at deploy time.
- **The eval-run history and review feed reset on redeploy.** That's an
  honest limitation, not hidden: a free, zero-maintenance deployment of a
  SQLite-backed app simply doesn't get free persistent storage. The
  historical numbers in the README's results table come from local runs
  (exactly how a reader should read them) — the live deployment is a
  **working demo of the agent**, not a persistent production dashboard.
- If you want real persistence later without paying: swap `app/db/client.py`
  for Supabase's free tier (a persistent Postgres database is free there;
  only compute/disk on Render/Railway is the ephemeral part) — the whole
  point of having one `EvalDB` class is that this is a one-file change.

Verify current free-tier terms before deploying — both platforms' pricing
has changed before and will again; nothing here should be taken as a
permanent guarantee.

## 1. Push to GitHub

Already done if you're reading this from the repo — both platforms deploy
from a GitHub repo you connect, so this is already satisfied.

## 2. Render (recommended: true forever-free web service, sleeps when idle)

1. https://dashboard.render.com → New → **Web Service** → connect this repo.
2. Build command:
   ```
   pip install -r requirements.txt
   ```
3. Start command (webhook service):
   ```
   python -m app.evals.framework index; python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```
   The `index` step re-seeds ChromaDB from the committed `data/dataset.jsonl`
   on every boot — cheap (no LLM calls, just local embeddings) and makes
   the ephemeral-disk issue above harmless for RAG.
4. Add a **second** Web Service, same repo, for the dashboard:
   ```
   python -m streamlit run dashboard/streamlit_app.py --server.port $PORT --server.address 0.0.0.0
   ```
5. Environment variables (Settings → Environment, both services): copy
   every key from `.env.example` that you actually use —
   `GITHUB_TOKEN`, `GITHUB_WEBHOOK_SECRET`, `GEMINI_API_KEY`, `GEMINI_MODEL`,
   `GROQ_API_KEY`, `GROQ_MODEL`, `AUTO_POST_COMMENTS=false` (keep this
   `false` until you trust the deployed output), `CHROMA_PERSIST_DIR`,
   `SQLITE_PATH`. **Never commit `.env`** — this is exactly why it's
   gitignored.
6. Deploy. Render gives the webhook service a URL like
   `https://prsense-xxxx.onrender.com` — that's what goes into GitHub's
   webhook config (Settings → Webhooks → Payload URL
   `.../webhook/github`), same as the local `ngrok` setup in the README,
   just permanent.
7. Free tier sleeps after ~15 min idle and takes ~30-60s to wake on the
   next request — a GitHub webhook delivery during that window will look
   slow but still succeeds (GitHub retries on timeout).

## 3. Railway (alternative)

Railway's free offering has shifted between a perpetual free tier and a
trial-credit model over time — check <https://railway.app/pricing> for
what's currently true before relying on it.

1. https://railway.app/new → Deploy from GitHub repo.
2. Railway auto-detects Python; add a `railway.toml` or just set the start
   command in the service settings, same two commands as the Render section
   above (one service for the webhook app, one for the dashboard).
3. Variables tab: same environment variables as step 5 above.
4. Railway assigns a public domain per service (Settings → Networking →
   Generate Domain) — use the webhook service's domain the same way as
   Render's.

## 4. After deploying

- Test with `curl https://<your-domain>/health` — should return
  `{"status":"ok",...}`.
- Point a real repo's webhook at `<domain>/webhook/github`, open a test PR,
  confirm a dry-run review appears in the service logs (and in the
  dashboard's "Recent reviews" once Supabase-backed persistence replaces
  the ephemeral SQLite, or just read the logs directly until then).
- Leave `AUTO_POST_COMMENTS=false` until you've watched several dry runs
  and trust the output — flipping it to `true` means the agent posts real
  comments on real PRs.
