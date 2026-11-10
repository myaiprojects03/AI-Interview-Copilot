"use client";

import { useEffect, useRef, useState } from "react";
import { AppHeader } from "@/components/AppHeader";
import { RequireAuth } from "@/components/auth/AuthProvider";
import {
  deleteDocument,
  getDocument,
  getProviderStatus,
  listDocuments,
  uploadDocument,
  type DocKind,
  type DocumentSummary,
} from "@/lib/api";

export function DocumentsView() {
  return (
    <RequireAuth>
      <Documents />
    </RequireAuth>
  );
}

function Documents() {
  const [docs, setDocs] = useState<DocumentSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [storage, setStorage] = useState<string | null>(null);
  const [storageError, setStorageError] = useState<string | null>(null);

  useEffect(() => {
    listDocuments()
      .then(setDocs)
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : String(err));
        setDocs([]);
      });
    getProviderStatus()
      .then((s) => {
        setStorage(s.database.storage ?? null);
        setStorageError(s.database.error ?? null);
      })
      .catch(() => {});
  }, []);

  const remove = async (doc: DocumentSummary) => {
    if (!window.confirm(`Delete “${doc.title}”? This permanently removes it and its search data.`)) return;
    try {
      await deleteDocument(doc.id);
      setDocs((d) => d?.filter((x) => x.id !== doc.id) ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="flex min-h-screen flex-col">
      <AppHeader />

      {storage === "memory" && (
        <p className="border-b border-amber-500/30 bg-amber-500/10 px-4 py-2 text-sm text-amber-700 dark:text-amber-300 sm:px-6">
          {storageError
            ? `The database couldn't be reached (${storageError}). `
            : "No database is set up yet. "}
          Uploads are kept in memory and disappear when the backend restarts.
        </p>
      )}
      {error && (
        <div
          role="alert"
          className="flex items-start justify-between gap-4 border-b border-amber-500/30 bg-amber-500/10 px-4 py-2 text-sm text-amber-700 dark:text-amber-300 sm:px-6"
        >
          <span>{error}</span>
          <button onClick={() => setError(null)} aria-label="Dismiss">
            ✕
          </button>
        </div>
      )}

      <main className="grid flex-1 grid-cols-1 gap-6 p-4 sm:p-6 lg:grid-cols-2">
        <Panel
          kind="cv"
          title="CV"
          help="Upload your CV as PDF, DOCX or text. Answers will use your real roles, projects and numbers."
          docs={docs?.filter((d) => d.kind === "cv") ?? null}
          onUploaded={(d) => setDocs((all) => [d, ...(all ?? [])])}
          onDelete={remove}
          onError={setError}
        />
        <Panel
          kind="jd"
          title="Job description"
          help="Paste the job ad or upload it. Answers will connect your experience to what the role needs."
          docs={docs?.filter((d) => d.kind === "jd") ?? null}
          onUploaded={(d) => setDocs((all) => [d, ...(all ?? [])])}
          onDelete={remove}
          onError={setError}
        />
      </main>
      <p className="px-4 pb-6 text-xs text-muted sm:px-6">
        Your documents are sent to the AI provider (Groq) to write summaries and answers. Delete them here at any time.
      </p>
    </div>
  );
}

function Panel({
  kind,
  title,
  help,
  docs,
  onUploaded,
  onDelete,
  onError,
}: {
  kind: DocKind;
  title: string;
  help: string;
  docs: DocumentSummary[] | null;
  onUploaded: (d: DocumentSummary) => void;
  onDelete: (d: DocumentSummary) => void;
  onError: (message: string) => void;
}) {
  return (
    <section className="flex flex-col gap-4 rounded-xl border border-black/10 bg-surface p-5 dark:border-white/10">
      <div>
        <h2 className="text-lg font-semibold">{title}</h2>
        <p className="text-sm text-muted">{help}</p>
      </div>
      <UploadForm kind={kind} onUploaded={onUploaded} onError={onError} />
      <div className="flex flex-col gap-2">
        {docs === null ? (
          <p className="text-sm text-muted">Loading…</p>
        ) : docs.length === 0 ? (
          <p className="text-sm text-muted">Nothing uploaded yet.</p>
        ) : (
          docs.map((d, i) => <DocRow key={d.id} doc={d} latest={i === 0} onDelete={onDelete} />)
        )}
      </div>
    </section>
  );
}

function UploadForm({
  kind,
  onUploaded,
  onError,
}: {
  kind: DocKind;
  onUploaded: (d: DocumentSummary) => void;
  onError: (message: string) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file && !text.trim()) {
      onError(kind === "cv" ? "Choose your CV file first." : "Paste the job description or choose a file.");
      return;
    }
    setBusy(true);
    try {
      const doc = await uploadDocument({ kind, file, text: file ? undefined : text, title });
      onUploaded(doc);
      setFile(null);
      setText("");
      setTitle("");
      if (inputRef.current) inputRef.current.value = "";
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <label
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const f = e.dataTransfer.files?.[0];
          if (f) setFile(f);
        }}
        className={`flex cursor-pointer flex-col items-center gap-1 rounded-lg border-2 border-dashed px-4 py-6 text-center text-sm ${
          dragging ? "border-primary bg-primary/5" : "border-black/15 dark:border-white/15"
        }`}
      >
        <span className="font-medium">{file ? file.name : "Drop a file here or click to choose"}</span>
        <span className="text-xs text-muted">PDF, DOCX, TXT or MD · up to 5 MB</span>
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.docx,.txt,.md"
          className="sr-only"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
      </label>
      {kind === "jd" && !file && (
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="…or paste the job description here"
          rows={5}
          className="rounded-lg border border-black/15 bg-background p-3 text-sm dark:border-white/15"
        />
      )}
      <div className="flex flex-wrap gap-2">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={kind === "cv" ? "Name (optional), e.g. Backend CV" : "Name (optional), e.g. Lumen Pay"}
          maxLength={120}
          className="min-w-0 flex-1 rounded-lg border border-black/15 bg-background px-3 py-1.5 text-sm dark:border-white/15"
        />
        <button
          type="submit"
          disabled={busy}
          className="rounded-lg bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-60"
        >
          {busy ? "Reading…" : "Upload"}
        </button>
      </div>
      {busy && <p className="text-xs text-muted">Extracting text, indexing and summarising. This takes a few seconds.</p>}
    </form>
  );
}

function DocRow({
  doc,
  latest,
  onDelete,
}: {
  doc: DocumentSummary;
  latest: boolean;
  onDelete: (d: DocumentSummary) => void;
}) {
  const [open, setOpen] = useState(false);
  const [content, setContent] = useState<string | null>(null);

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && content === null) {
      try {
        setContent((await getDocument(doc.id)).content);
      } catch {
        setContent("");
      }
    }
  };

  return (
    <article className="rounded-lg border border-black/10 p-3 dark:border-white/10">
      <div className="flex items-start gap-3">
        <button onClick={toggle} className="flex min-w-0 flex-1 flex-col items-start text-left" aria-expanded={open}>
          <span className="flex items-center gap-2 font-medium">
            <span className="truncate">{doc.title}</span>
            {latest && (
              <span className="rounded-full bg-primary/15 px-2 py-0.5 text-xs font-normal text-primary">Latest</span>
            )}
          </span>
          <span className="text-xs text-muted">
            {new Date(doc.created_at).toLocaleString()} · {doc.word_count} words · {doc.chunk_count} sections indexed
          </span>
        </button>
        <button
          onClick={() => onDelete(doc)}
          className="rounded-md px-2 py-1 text-xs text-muted hover:bg-black/5 hover:text-red-600 dark:hover:bg-white/5"
        >
          Delete
        </button>
      </div>
      {open && (
        <div className="mt-3 flex flex-col gap-3 text-sm">
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Summary used in every answer</h3>
            <p className="whitespace-pre-line">{doc.summary}</p>
          </div>
          <details>
            <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-muted">
              Extracted text
            </summary>
            <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded bg-black/5 p-2 font-sans text-xs dark:bg-white/5">
              {content ?? "Loading…"}
            </pre>
          </details>
        </div>
      )}
    </article>
  );
}
