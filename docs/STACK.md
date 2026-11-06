# Stack decisions (free tier first)

Rule for this project: every service has a $0 option for development and the early stages of
running the app. Paid providers from the spec (Deepgram, OpenAI, Pinecone, AWS) stay *possible*
because each one sits behind an interface (see `backend/app/providers/`), but none of them is the default.

| Layer | Spec recommended | **Chosen (free)** | Free limits / notes | Paid upgrade path |
|---|---|---|---|---|
| Frontend | Next.js + TS + Tailwind | **Next.js + TS + Tailwind** | Open source | — |
| Frontend hosting | Vercel | **Vercel Hobby** | Free for personal/non-commercial use. A paid client app needs Vercel Pro, or use Cloudflare Pages (free, commercial use allowed) | Vercel Pro |
| Audio capture | getDisplayMedia + getUserMedia | **Same (browser APIs)** | Free. Tab audio capture works in Chrome/Edge | Electron for system audio |
| Realtime transport | WebSocket | **WebSocket (FastAPI)** | Free | — |
| Backend | FastAPI | **FastAPI + asyncio** | Open source | — |
| Speech-to-text | Deepgram streaming | **Groq Whisper (`whisper-large-v3-turbo`)** on VAD-cut chunks | Free tier with rate limits (per-minute / per-day audio seconds) | Deepgram streaming (starts with $200 free credit), AssemblyAI |
| STT offline fallback | Whisper | **faster-whisper (local, CPU)** | Free, runs on our own server, slower | — |
| LLM | OpenAI | **Groq (`openai/gpt-oss-120b`, reasoning effort `low`)** | Free tier with rate limits; first token ~0.5 s in our test. Alternatives on the same key: `openai/gpt-oss-20b`, `qwen/qwen3.8-27b` | OpenAI, Claude |
| LLM fallback | — | **Google Gemini Flash (free tier)** | Free tier with rate limits | — |
| CV / JD parsing | PyMuPDF, python-docx | **pypdf + python-docx** | Open source. pypdf has a permissive licence (PyMuPDF is AGPL, a problem for a closed-source SaaS) | PyMuPDF commercial licence |
| Embeddings | OpenAI embeddings | **fastembed (`BAAI/bge-small-en-v1.5`, local ONNX)** | Free, runs on CPU, no API key; ~5 ms per question; ~67 MB model downloaded on first start | OpenAI embeddings |
| Vector store | Pinecone | **pgvector inside Supabase Postgres** | Free; one database, so the API stays stateless with no per-instance FAISS files | Pinecone |
| Database | PostgreSQL | **Supabase Postgres (free project)** | 500 MB DB; free projects pause after a week of no activity | Supabase Pro, Neon |
| Auth | Auth.js / Clerk | **Supabase Auth (email + Google)** | 50k monthly active users free | — |
| File storage (CVs) | — | **Not needed**: only the extracted text is kept (in Postgres); the original file is discarded after parsing | — | Supabase Storage (1 GB free) if originals must be kept |
| Payments | Stripe | **Stripe (test mode)** | No monthly fee; per-transaction fee only on live payments. Check that Stripe supports the client's country, otherwise use Lemon Squeezy / Paddle | Paddle |
| Backend hosting | Docker on AWS | **Docker image on Render / Koyeb free tier** (decided in Phase 4) | Free instances sleep when idle, so the first request is slow | AWS, Railway |
| Shared session state (multi-instance) | — | **Upstash Redis free tier** (Phase 4) | Free tier with request limits | — |
| CI | — | **GitHub Actions** | Free for public repos and a monthly free allowance for private ones | — |

## Accounts you need for Phase 1 (all free, no card)

1. **Groq**: https://console.groq.com → API key → `GROQ_API_KEY` (LLM + Whisper STT)
2. **Supabase**: https://supabase.com → new project → `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_ANON_KEY` (needed from Phase 2)
3. Optional: **Google AI Studio**: https://aistudio.google.com → `GEMINI_API_KEY` (LLM fallback)

Stripe test-mode keys are needed from Phase 3.

## Phases

- **Phase 0, foundations (this one):** stack decisions, monorepo layout, config, provider
  interfaces, health checks, brand config file, Dockerfile, provider smoke check.
- **Phase 1, real-time core:** tab + mic capture, WebSocket audio streaming, VAD question
  detection, live transcript, streamed answers from a sample CV.
- **Phase 2, answer engine:** CV/JD upload, parsing, embeddings, retrieval, behavioral vs
  technical formatting, prompt tuning on a test question set.
- **Phase 3, SaaS layer:** auth, dashboard + history, Stripe plans and webhooks, usage limits.
- **Phase 4, hardening and launch:** latency logging + admin view, reconnects, tests, deployment.
