# AI Interview Copilot

Listens to a live interview, transcribes the interviewer's questions, and streams a suggested
answer grounded in the candidate's CV and the job description.

Everything runs on free tiers by default. See [docs/STACK.md](docs/STACK.md) for every
stack choice, its free limits, and the paid upgrade path.

```
backend/    FastAPI (Python 3.11): API, WebSocket, provider interfaces
frontend/   Next.js + TypeScript + Tailwind: copilot UI and dashboard
docs/       Stack decisions and phase plan
```

## Prerequisites

- Python 3.11
- Node.js 20+ (LTS)
- A free Groq API key: https://console.groq.com/keys

## Backend

```bash
cd backend
py -3.11 -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
copy .env.example .env          # macOS/Linux: cp .env.example .env, then add GROQ_API_KEY
uvicorn app.main:app --reload   # http://localhost:8000/docs
```

Checks:

```bash
pytest                          # unit tests (no keys needed, uses fake providers)
ruff check app tests scripts    # lint
python -m scripts.smoke_check   # calls Groq with your key: LLM first-token time + STT
```

## Frontend

```bash
cd frontend
npm install
copy .env.example .env.local    # macOS/Linux: cp .env.example .env.local
npm run dev                     # http://localhost:3000
```

The home page shows whether the backend is reachable and which providers are configured.

## Live copilot (Phase 1)

Open http://localhost:3000/copilot (Chrome or Edge; tab audio capture isn't supported elsewhere).

- **Meeting tab + mic:** press Start, pick the Zoom/Meet/Teams browser tab, turn on
  "Share tab audio", allow the mic. Use headphones so the mic doesn't hear the interviewer.
- **Practice (mic only):** read questions out loud yourself.
- **No call to test with?** Open http://localhost:3000/demo/mock-interview.wav in another
  tab, press Start and share that tab.

Replay the mock interview straight into the backend and print per-turn timings:

```bash
cd backend
python -m scripts.replay_interview
```

Rebuild the recording (Windows' built-in voice):

```bash
powershell -ExecutionPolicy Bypass -File backend/scripts/make_mock_interview.ps1
```

How it works: the browser sends 16 kHz PCM per channel over `/ws/session`. The backend cuts
speech into utterances when it hears 0.8 s of silence (`VAD_SILENCE_MS`), transcribes each
with Groq Whisper, and when an interviewer utterance looks like a question it streams an
answer from the LLM. Figures in an answer that the CV doesn't state are highlighted.

Free-tier limits to keep in mind: `gpt-oss-120b` allows 8,000 tokens a minute (about 6
answers a minute), and every partial transcript (`STT_PARTIAL_INTERVAL_MS`, 0 = off) is an
extra Whisper request.

## CV & job description (Phase 2)

Open http://localhost:3000/documents to upload a CV (PDF, DOCX, TXT, MD) and paste or upload
a job description. Each is split into sections (a role keeps its title, company and dates),
embedded locally (bge-small, ONNX on CPU), and summarised once by the LLM. On the copilot page, pick
which CV and job description to use before pressing Start.

For each question the copilot:

1. classifies it as **behavioral** (STAR story), **technical** (key points, code only if
   asked) or **general** (direct answer + points) — rules in `backend/app/answer/classify.py`;
2. retrieves the 4 most relevant CV sections and 2 job-description sections (in memory,
   ~5 ms);
3. streams an answer grounded in them, showing the type and the CV roles it used.

When a session has a job description, one extra LLM call at start lists the job's skills
and duties the CV doesn't show (checked against the CV text, cached per CV/JD pair). The
prompt tells the model never to claim them, the copilot shows them as "Not on your CV", and
any answer that mentions one highlights it. Measure with:

```bash
python -m scripts.eval_jd_claims            # Sara's test CV vs the Lumen Pay job
python -m scripts.eval_jd_claims --no-gaps  # same without the gap list
```

Storage: set `DATABASE_URL` to a Supabase **Session pooler** connection string and the
tables are created at startup. Without it, documents live in memory until restart.

Quality checks on the labelled question set (`backend/evals/questions.json`):

```bash
cd backend
python -m scripts.eval_answers          # 15 questions; writes evals/report.md
python -m scripts.eval_answers --all
```

## Accounts, plans and history (Phase 3)

- **Sign-in:** Supabase Auth (email + password, Google). Set `SUPABASE_URL` (backend) and
  `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` (frontend). Every API call
  sends the access token; the WebSocket sends it as its first message. Without these
  settings, local development runs as a single dev user.
- **Plans:** Free 30 min, Starter $9 / 120 min, Pro $19 / 600 min of live interview time a
  month (`backend/app/billing/plans.py`). Only live interviewer audio counts; pausing
  doesn't. The server checks the limit when a session starts and stops it when minutes
  run out.
- **Billing:** Paddle Billing (`BILLING_PROVIDER=paddle`) or simulated (`fake`, the
  default for development). Create the Paddle plans with
  `python -m scripts.paddle_setup`. After checkout the browser asks the backend to sync
  the subscription, so it works on localhost; in production Paddle webhooks
  (`POST /billing/webhook`, signature checked) keep plans in step.
- **Dashboard:** plan and usage, change / cancel / undo cancel, Paddle billing portal,
  interview history with transcripts and suggested answers, and "Delete all my data".

## Rebranding

Edit `frontend/src/config/brand.ts` (name, tagline, logo, colours). Nothing else needs changing.

## Swapping providers

Set `LLM_PROVIDER` / `STT_PROVIDER` in `backend/.env`. Each provider implements an interface in
`backend/app/providers/base.py`; add a new one and register it in
`backend/app/providers/registry.py`.

## Deployment

Both the website and the API deploy on **Vercel** (free Hobby plan, no card) as two projects
from this repository: see [docs/DEPLOY_VERCEL.md](docs/DEPLOY_VERCEL.md). The Docker image
and `render.yaml` remain for hosts with always-on servers (Render, AWS, Railway).

## Docker

```bash
docker build -t copilot-backend ./backend
docker run --env-file backend/.env -p 8000:8000 copilot-backend
```
