# Deploy on Vercel (frontend + backend, free Hobby plan, no card)

Both halves deploy from the same GitHub repository as **two Vercel projects**:

| Project | Root Directory | Framework (auto-detected) |
|---|---|---|
| Backend API | `backend` | FastAPI (Python 3.12) |
| Website | `frontend` | Next.js |

How the backend runs on Vercel:

- `backend/vercel.json` sets the build command (`python -m scripts.fetch_model`, which bundles
  the ~67 MB embedding model so it loads offline), the region (`hnd1`, Tokyo, next to the
  Supabase database) and a 300 s function limit.
- Vercel Hobby closes WebSocket connections after **300 s**. The server tells the browser,
  which opens a fresh connection at a quiet moment before the cut and moves the audio to it;
  the old connection finishes any answer and closes. The page and audio capture are untouched.
- Uploads are capped at 4 MB (Vercel rejects request bodies over 4.5 MB).
- Hobby is for **non-commercial use**. A paid launch needs Vercel Pro ($20/month), which also
  allows connections of up to 800 s (set `WS_MAX_SECONDS` to match).

## 1. Backend project

1. https://vercel.com/new → import `myaiprojects03/AI-Interview-Copilot`.
2. **Project Name**: `ai-interview-copilot-api`. **Root Directory**: `backend` (click Edit).
   Framework should show **FastAPI**.
3. **Environment Variables** (paste the block, then fill the blanks):

   ```
   ENVIRONMENT=production
   LLM_PROVIDER=groq
   STT_PROVIDER=groq
   EMBEDDING_PROVIDER=local
   BILLING_PROVIDER=paddle
   PADDLE_ENVIRONMENT=sandbox
   PADDLE_PRICE_STARTER=pri_01m724h7em0bg4e5978pyftxqn
   PADDLE_PRICE_PRO=pri_01m724h80a79syp1rheds3e6nd
   PADDLE_WEBHOOK_SECRET=not-set-yet
   DB_POOL_MAX=3
   WS_MAX_SECONDS=300
   CORS_ORIGINS=["http://localhost:3000"]
   APP_URL=http://localhost:3000
   ADMIN_EMAILS=
   GROQ_API_KEY=
   SUPABASE_URL=
   PADDLE_API_KEY=
   DATABASE_URL=
   ```

   - `DATABASE_URL`: the Supabase **Transaction pooler** string (port **6543**). It suits many
     short-lived serverless instances. It's your Session pooler string with `:5432` changed
     to `:6543`.
   - `ADMIN_EMAILS`: the email you sign in with.
   - The rest: copy from `backend/.env`.
4. **Deploy**. When done, open `https://<backend-domain>/health`: it should return
   `{"status":"ok", ...}`. Note the domain (e.g. `https://ai-interview-copilot-api.vercel.app`).

## 2. Website project

1. https://vercel.com/new → import the same repository again.
2. **Project Name**: `ai-interview-copilot`. **Root Directory**: `frontend`. Framework:
   **Next.js**.
3. **Environment Variables**:

   ```
   NEXT_PUBLIC_API_URL=https://<backend-domain>
   NEXT_PUBLIC_SUPABASE_URL=
   NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=
   NEXT_PUBLIC_PADDLE_CLIENT_TOKEN=
   ```

   Copy the last three from `frontend/.env.local`.
4. **Deploy** and note the domain (e.g. `https://ai-interview-copilot.vercel.app`).

## 3. Connect them

1. **Backend project → Settings → Environment Variables**: set
   `CORS_ORIGINS=["https://<website-domain>"]` and `APP_URL=https://<website-domain>`,
   then **Deployments → ⋯ → Redeploy**.
2. **Supabase → Authentication → URL Configuration**: Site URL `https://<website-domain>`;
   add `https://<website-domain>/**` to Redirect URLs (keep the localhost ones for development).
3. **Paddle (sandbox)**:
   - **Checkout → Website approval**: add `<website-domain>`.
   - **Checkout → Checkout settings → Default payment link**: `https://<website-domain>/pricing`.
   - **Developer tools → Notifications → New destination**: URL
     `https://<backend-domain>/billing/webhook`, events `subscription.created`,
     `subscription.updated`, `subscription.canceled`, `transaction.completed`. Copy the
     destination's secret key into the backend's `PADDLE_WEBHOOK_SECRET`, then redeploy.

## Notes

- Pushing to `main` redeploys both projects automatically.
- The first request after a while idle takes a few seconds (cold start). The copilot page
  wakes the backend as soon as it opens.
- Hobby includes about 360 GB-hours of function memory a month (~180 hours of open
  interview connections at 2 GB) and 4 CPU-hours. Usage is under **Usage** in the dashboard.
