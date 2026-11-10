"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AppHeader } from "@/components/AppHeader";
import { RequireAuth } from "@/components/auth/AuthProvider";
import { SuggestionText } from "@/components/SuggestionText";
import { deleteInterview, getInterview, type InterviewDetail } from "@/lib/api";

export function HistoryView() {
  return (
    <RequireAuth>
      <div className="flex min-h-screen flex-col">
        <AppHeader />
        <History />
      </div>
    </RequireAuth>
  );
}

function History() {
  const router = useRouter();
  const [data, setData] = useState<InterviewDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("id");
    (id ? getInterview(id) : Promise.reject(new Error("No interview selected.")))
      .then(setData)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const remove = async () => {
    if (!data || !window.confirm("Delete this interview and its transcript? This can't be undone.")) return;
    try {
      await deleteInterview(data.id);
      router.push("/dashboard");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-4 py-8 sm:px-6">
      <Link href="/dashboard" className="text-sm text-primary hover:underline">
        ← Dashboard
      </Link>
      {error && <p role="alert" className="text-red-600 dark:text-red-400">{error}</p>}
      {data && (
        <>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h1 className="text-2xl font-semibold">Interview, {new Date(data.started_at).toLocaleString()}</h1>
              <p className="text-sm text-muted">
                {data.minutes} min · {data.question_count} question{data.question_count === 1 ? "" : "s"} ·{" "}
                {data.cv_title ?? "No CV"}
                {data.jd_title ? ` · ${data.jd_title}` : ""}
              </p>
            </div>
            <button
              onClick={remove}
              className="rounded-lg border border-red-500/40 px-4 py-2 text-sm text-red-600 hover:bg-red-500/10 dark:text-red-400"
            >
              Delete
            </button>
          </div>
          <div className="grid gap-6 lg:grid-cols-2">
            <section className="flex flex-col gap-3 rounded-xl border border-black/10 bg-surface p-5 dark:border-white/10">
              <h2 className="font-semibold">Transcript</h2>
              {data.turns.length === 0 && <p className="text-sm text-muted">Nothing was transcribed.</p>}
              <ol className="flex flex-col gap-3">
                {data.turns.map((t, i) => (
                  <li key={i} className="flex flex-col gap-0.5">
                    <span
                      className={`text-xs font-semibold uppercase tracking-wide ${
                        t.speaker === "interviewer" ? "text-primary" : "text-accent"
                      }`}
                    >
                      {t.speaker === "interviewer" ? "Interviewer" : "You"}
                    </span>
                    <span>{t.text}</span>
                  </li>
                ))}
              </ol>
            </section>
            <section className="flex flex-col gap-3 rounded-xl border border-black/10 bg-surface p-5 dark:border-white/10">
              <h2 className="font-semibold">Suggested answers</h2>
              {data.answers.length === 0 && <p className="text-sm text-muted">No suggestions in this session.</p>}
              {data.answers.map((a, i) => (
                <article key={i} className="flex flex-col gap-2 border-b border-black/10 pb-4 last:border-0 dark:border-white/10">
                  <p className="text-sm text-muted">
                    {a.question_type && (
                      <span className="mr-2 rounded-full bg-primary/15 px-2 py-0.5 text-xs font-medium text-primary">
                        {a.question_type}
                      </span>
                    )}
                    <span className="font-semibold">Q:</span> {a.question}
                    {a.status === "stopped" && <span className="ml-2 text-xs">(stopped)</span>}
                  </p>
                  <SuggestionText text={a.answer} />
                </article>
              ))}
            </section>
          </div>
        </>
      )}
    </main>
  );
}
