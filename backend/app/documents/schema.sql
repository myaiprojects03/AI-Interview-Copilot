-- Applied automatically at backend startup when DATABASE_URL is set. Safe to re-run.
create extension if not exists vector;

create table if not exists documents (
    id          uuid primary key default gen_random_uuid(),
    user_id     text not null,
    kind        text not null check (kind in ('cv', 'jd')),
    title       text not null,
    filename    text,
    content     text not null,
    summary     text not null default '',
    created_at  timestamptz not null default now()
);
create index if not exists documents_user_kind_idx on documents (user_id, kind, created_at desc);

create table if not exists document_chunks (
    id           bigserial primary key,
    document_id  uuid not null references documents (id) on delete cascade,
    user_id      text not null,
    position     int not null,
    content      text not null,
    metadata     jsonb not null default '{}'::jsonb,
    embedding    vector(384) not null
);
create index if not exists document_chunks_doc_idx on document_chunks (document_id, position);
create index if not exists document_chunks_user_idx on document_chunks (user_id);

-- Supabase exposes the public schema through its REST API. Row level security with no
-- policies blocks that path entirely; the backend connects as the database owner and is
-- unaffected, and scopes every query by user_id itself.
alter table documents enable row level security;
alter table document_chunks enable row level security;

-- Accounts (Phase 3) -------------------------------------------------------------------
create table if not exists subscriptions (
    user_id               text primary key,
    plan                  text not null default 'free',
    status                text not null default 'none',
    provider              text,
    customer_id           text,
    subscription_id       text,
    current_period_end    timestamptz,
    cancel_at_period_end  boolean not null default false,
    updated_at            timestamptz not null default now()
);
create index if not exists subscriptions_customer_idx on subscriptions (customer_id);

create table if not exists usage_monthly (
    user_id  text not null,
    month    text not null,              -- 'YYYY-MM' (UTC)
    seconds  double precision not null default 0,
    primary key (user_id, month)
);

create table if not exists interview_sessions (
    id             uuid primary key default gen_random_uuid(),
    user_id        text not null,
    started_at     timestamptz not null default now(),
    ended_at       timestamptz,
    audio_seconds  double precision not null default 0,
    cv_title       text,
    jd_title       text
);
create index if not exists interview_sessions_user_idx on interview_sessions (user_id, started_at desc);

create table if not exists session_turns (
    id          bigserial primary key,
    session_id  uuid not null references interview_sessions (id) on delete cascade,
    user_id     text not null,
    speaker     text not null,
    text        text not null,
    created_at  timestamptz not null default now()
);
create index if not exists session_turns_session_idx on session_turns (session_id, id);

create table if not exists session_answers (
    id             bigserial primary key,
    session_id     uuid not null references interview_sessions (id) on delete cascade,
    user_id        text not null,
    question       text not null,
    question_type  text,
    answer         text not null,
    status         text not null,
    created_at     timestamptz not null default now()
);
create index if not exists session_answers_session_idx on session_answers (session_id, id);

alter table subscriptions enable row level security;
alter table usage_monthly enable row level security;
alter table interview_sessions enable row level security;
alter table session_turns enable row level security;
alter table session_answers enable row level security;
