# AI Interview Copilot

Listens to a live interview in the browser, transcribes the interviewer's questions, and
streams a suggested answer grounded in the candidate's own CV and the job description.

**Live:** https://ai-interview-copilot-frontend-pi.vercel.app
(API: https://ai-interview-copilot-tan.vercel.app, health check at `/health`)

Everything runs on free tiers with no payment card. See [docs/STACK.md](docs/STACK.md) for
each stack choice, its free limits and the paid upgrade path, and
[docs/AI_Interview_Copilot_Case_Study.pdf](docs/AI_Interview_Copilot_Case_Study.pdf) for the
case study with measured results.

```
backend/    FastAPI (Python): REST API, WebSocket, answer engine, provider interfaces
frontend/   Next.js + TypeScript + Tailwind: copilot, documents, dashboard, history, admin
docs/       Stack decisions, Vercel deployment guide, case study
```

## Production

| Part | Where | Notes |
|---|---|---|
| Website | Vercel project, Root Directory `frontend` | Next.js |
| API | Vercel project, Root Directory `backend` | FastAPI on Python 3.12, region `hnd1` (Tokyo) |
| Database + sign-in | Supabase (Tokyo) | Postgres + pgvector, Supabase Auth |
| Speech-to-text and LLM | Groq | `whisper-large-v3-turbo`, `openai/gpt-oss-120b` |
| Embeddings | Inside the API | `bge-small-en-v1.5` (ONNX), bundled at build time |
| Payments | Paddle Billing (sandbox) | Checkout opens once Paddle approves the website domain |

- Pushing to `main` redeploys both Vercel projects. A **Redeploy** of an older deployment
  rebuilds that deployment's commit, not the latest code.
- The API's build command (`python -m scripts.fetch_model`, in `backend/vercel.json`)
  downloads the embedding model into the bundle, so it loads offline at run time.
- Vercel closes WebSocket connections after 300 s. The server announces the limit and the
  browser switches to a fresh connection at a quiet moment, so sessions run on without a
  reload or lost words.
- Table setup runs once per schema change, under a database lock, so instances starting
  together don't collide.
- Hobby is for **non-commercial use**. A paid launch needs Vercel Pro ($20/month).

Full setup, every environment variable and the Supabase and Paddle settings:
[docs/DEPLOY_VERCEL.md](docs/DEPLOY_VERCEL.md).

### Environment variables in production

**API project** (`backend`):

| Variable | Value |
|---|---|
| `ENVIRONMENT` | `production` |
| `LLM_PROVIDER` / `STT_PROVIDER` | `groq` |
| `EMBEDDING_PROVIDER` | `local` |
| `GROQ_API_KEY` | Groq key (secret) |
| `DATABASE_URL` | Supabase **Transaction pooler** string, port `6543` (secret) |
| `SUPABASE_URL` | Supabase project URL |
| `CORS_ORIGINS` | The website address, e.g. `https://ai-interview-copilot-frontend-pi.vercel.app` |
| `APP_URL` | The website address (where billing sends people back) |
| `ADMIN_EMAILS` | Emails allowed to open `/admin` |
| `BILLING_PROVIDER`, `PADDLE_*` | `paddle`, sandbox keys, price IDs and webhook secret |
| `DB_POOL_MAX` | `3` |
| `WS_MAX_SECONDS` | `300` |

`CORS_ORIGINS` accepts one URL, comma-separated URLs or a JSON list; quotes and a trailing
`/` are ignored. Values marked **Sensitive** in Vercel can't be viewed again, and saving an
empty edit box blanks them, so only mark real secrets as sensitive.

**Website project** (`frontend`): `NEXT_PUBLIC_API_URL` (the API address),
`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`,
`NEXT_PUBLIC_PADDLE_CLIENT_TOKEN`.

## How it works

1. **CV and job description** (`/documents`): uploads (PDF, DOCX, TXT, MD, up to 4 MB) are
   split into sections that keep each role's title, company and dates, embedded locally and
   stored in pgvector. The LLM writes a short summary of each once.
2. **Live copilot** (`/copilot`, Chrome or Edge): the browser streams the meeting tab's
   audio and the microphone as two 16 kHz channels over `/ws/session`. The first message
   carries the sign-in token.
3. The backend cuts speech into utterances after 0.8 s of silence (`VAD_SILENCE_MS`) and
   transcribes each with Groq Whisper, with a partial transcript every 2 s
   (`STT_PARTIAL_INTERVAL_MS`).
4. When the interviewer asks a question, it is classified as **behavioral** (STAR story),
   **technical** (key points, code only if asked) or **general**. A follow-up within 6 s
   joins the same question.
5. The 4 most relevant CV sections and 2 job sections are retrieved, and the answer streams
   back word by word with its type and the CV roles it used.
6. Honesty checks: at session start one LLM call lists job skills the CV doesn't show.
   Answers must not claim them, the page shows them as **Not on your CV**, and any figure
   or listed skill an answer mentions without CV support is highlighted.
7. Every transcript line and answer is saved to the interview history (`/history`).

**Accounts and plans:** Supabase sign-in (email and password; the Google button is ready
once Google is enabled in Supabase). Plans are Free 30 min, Starter $9 / 120 min and
Pro $19 / 600 min of live interviewer audio a month (`backend/app/billing/plans.py`).
`/dashboard` shows plan, usage and history and can delete all of a user's data.

**Admin** (`/admin`, for `ADMIN_EMAILS` only): median, p90 and p95 timings per answer
stage and daily trends. Only timings and question types are stored, never content.

## Run locally

Prerequisites: Python 3.11+, Node.js 20+, a free Groq API key (https://console.groq.com/keys).

```bash
cd backend
py -3.11 -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
copy .env.example .env          # macOS/Linux: cp; then add GROQ_API_KEY
uvicorn app.main:app --reload   # http://localhost:8000/docs
```

```bash
cd frontend
npm install
copy .env.example .env.local    # macOS/Linux: cp
npm run dev                     # http://localhost:3000
```

Without `DATABASE_URL` documents are kept in memory, and without the Supabase settings
local development runs as a single dev user with simulated billing. For local sign-in,
add `http://localhost:3000/**` to Supabase's Redirect URLs, and add `http://localhost:3000`
to `CORS_ORIGINS` if a local website talks to the deployed API.

No call to test with? Open http://localhost:3000/demo/mock-interview.wav in another tab,
press Start on the copilot page and share that tab. Rebuild the recording with
`powershell -ExecutionPolicy Bypass -File backend/scripts/make_mock_interview.ps1`.

## Tests and evaluation

Run from `backend/`:

```bash
pytest                                  # unit tests, no keys needed (fake providers)
ruff check app tests scripts            # lint
python -m scripts.smoke_check           # Groq: LLM first-token time and speech-to-text
python -m scripts.replay_interview      # mock interview into the backend, per-turn timings
python -m scripts.eval_answers          # 15 labelled questions, writes evals/report.md
python -m scripts.eval_baseline         # plain chat prompt vs the copilot, same questions
python -m scripts.eval_jd_claims        # answers claiming job skills the CV lacks
```

Database tests run when `TEST_DATABASE_URL` is set; the bundled-model and tokenizer tests
run after `python -m scripts.fetch_model`. GitHub Actions runs the tests, lint, a Docker
build with a `/health` check, and the frontend lint and type check on every push.

## Customising

- **Branding:** `frontend/src/config/brand.ts` (name, tagline, logo, colours).
- **Providers:** set `LLM_PROVIDER` / `STT_PROVIDER`. Each provider implements an interface
  in `backend/app/providers/base.py` and is registered in `backend/app/providers/registry.py`.

## Other hosts

`backend/Dockerfile` (model baked in) and `render.yaml` run the API on an always-on server
such as Render, Railway, Fly.io or AWS, where the 300 s WebSocket limit doesn't apply:

```bash
docker build -t copilot-backend ./backend
docker run --env-file backend/.env -p 8000:8000 copilot-backend
```
