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

## Rebranding

Edit `frontend/src/config/brand.ts` (name, tagline, logo, colours). Nothing else needs changing.

## Swapping providers

Set `LLM_PROVIDER` / `STT_PROVIDER` in `backend/.env`. Each provider implements an interface in
`backend/app/providers/base.py`; add a new one and register it in
`backend/app/providers/registry.py`.

## Docker

```bash
docker build -t copilot-backend ./backend
docker run --env-file backend/.env -p 8000:8000 copilot-backend
```
