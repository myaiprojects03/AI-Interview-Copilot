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
