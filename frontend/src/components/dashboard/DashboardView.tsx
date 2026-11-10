"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AppHeader } from "@/components/AppHeader";
import { RequireAuth } from "@/components/auth/AuthProvider";
import {
  billingPortal,
  cancelPlan,
  deleteAllMyData,
  getAccount,
  listDocuments,
  listInterviews,
  resumePlan,
  type Account,
  type DocumentSummary,
  type InterviewSummary,
} from "@/lib/api";

export function DashboardView() {
  return (
    <RequireAuth>
      <div className="flex min-h-screen flex-col">
        <AppHeader />
        <Dashboard />
      </div>
    </RequireAuth>
  );
}

function errorText(err: unknown) {
  return err instanceof Error ? err.message : String(err);
}

function Dashboard() {
  const [account, setAccount] = useState<Account | null>(null);
  const [interviews, setInterviews] = useState<InterviewSummary[] | null>(null);
  const [docs, setDocs] = useState<DocumentSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    getAccount()
      .then((a) => {
        setAccount(a);
        if (q.get("checkout") === "done") setNotice("You're subscribed. Thanks!");
        else if (q.get("plan") === "changed") setNotice("Your plan has been changed.");
      })
      .catch((e: unknown) => setError(errorText(e)));
    listInterviews().then(setInterviews).catch(() => setInterviews([]));
    listDocuments().then(setDocs).catch(() => setDocs([]));
  }, []);

  const act = async (fn: () => Promise<Account>, confirmText?: string) => {
    if (confirmText && !window.confirm(confirmText)) return;
    setBusy(true);
    setError(null);
    try {
      setAccount(await fn());
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const openPortal = async () => {
    setBusy(true);
    try {
      window.location.href = (await billingPortal()).url;
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  };

  const wipe = async () => {
    if (!window.confirm("Delete all your CVs, job descriptions and interview transcripts? This can't be undone. Your plan isn't affected.")) return;
    try {
      const r = await deleteAllMyData();
      setDocs([]);
      setInterviews([]);
      setNotice(`Deleted ${r.deleted_documents} documents and ${r.deleted_interviews} interviews.`);
    } catch (e) {
      setError(errorText(e));
    }
  };

  const cvs = docs?.filter((d) => d.kind === "cv").length ?? 0;
  const jds = docs?.filter((d) => d.kind === "jd").length ?? 0;

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-4 py-8 sm:px-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      {notice && (
        <p className="rounded-lg border border-accent/40 bg-accent/10 px-4 py-2 text-sm">{notice}</p>
      )}
      {error && (
        <p role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-700 dark:text-red-300">
          {error}
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <section className="flex flex-col gap-4 rounded-xl border border-black/10 bg-surface p-5 lg:col-span-2 dark:border-white/10">
          {account ? (
            <PlanCard
              account={account}
              busy={busy}
              onCancel={() =>
                act(cancelPlan, "Cancel your plan? You keep it until the end of the billing period, then move to Free.")
              }
              onResume={() => act(resumePlan)}
              onPortal={openPortal}
            />
          ) : (
            <p className="text-sm text-muted">Loading your plan…</p>
          )}
        </section>

        <section className="flex flex-col gap-3 rounded-xl border border-black/10 bg-surface p-5 dark:border-white/10">
          <h2 className="font-semibold">Get ready</h2>
          <p className="text-sm text-muted">
            {docs === null ? "…" : `${cvs} CV${cvs === 1 ? "" : "s"} · ${jds} job description${jds === 1 ? "" : "s"}`}
          </p>
          <Link href="/documents" className="rounded-lg border border-black/15 px-4 py-2 text-center text-sm font-medium hover:bg-black/5 dark:border-white/15 dark:hover:bg-white/5">
            {cvs ? "Manage CVs & jobs" : "Upload your CV"}
          </Link>
          <Link href="/copilot" className="rounded-lg bg-primary px-4 py-2 text-center text-sm font-medium text-primary-foreground hover:opacity-90">
            Open live copilot
          </Link>
        </section>
      </div>

      <section className="flex flex-col gap-3 rounded-xl border border-black/10 bg-surface p-5 dark:border-white/10">
        <h2 className="font-semibold">Interview history</h2>
        {interviews === null ? (
          <p className="text-sm text-muted">Loading…</p>
        ) : interviews.length === 0 ? (
          <p className="text-sm text-muted">No interviews yet. Each copilot session is saved here with its transcript.</p>
        ) : (
          <ul className="divide-y divide-black/10 dark:divide-white/10">
            {interviews.map((s) => (
              <li key={s.id}>
                <Link href={`/history?id=${s.id}`} className="flex flex-wrap items-baseline justify-between gap-2 py-2 hover:text-primary">
                  <span className="font-medium">{new Date(s.started_at).toLocaleString()}</span>
                  <span className="text-xs text-muted">
                    {formatDuration(s.seconds)} · {s.question_count} question{s.question_count === 1 ? "" : "s"}
                    {s.jd_title ? ` · ${s.jd_title}` : ""}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-red-500/20 p-5">
        <div>
          <h2 className="font-semibold">Your data</h2>
          <p className="text-sm text-muted">Delete every CV, job description and interview transcript you&apos;ve saved.</p>
        </div>
        <button onClick={wipe} className="rounded-lg border border-red-500/40 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-500/10 dark:text-red-400">
          Delete all my data
        </button>
      </section>
    </main>
  );
}

function PlanCard({
  account,
  busy,
  onCancel,
  onResume,
  onPortal,
}: {
  account: Account;
  busy: boolean;
  onCancel: () => void;
  onResume: () => void;
  onPortal: () => void;
}) {
  const u = account.usage;
  const pct = u.limit_minutes ? Math.min(100, (u.used_minutes / u.limit_minutes) * 100) : 0;
  const paid = account.plan !== "free";
  const end = account.current_period_end ? new Date(account.current_period_end).toLocaleDateString() : null;
  return (
    <>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">
          {account.plan_name} plan
          {account.status === "past_due" && (
            <span className="ml-2 rounded-full bg-amber-500/15 px-2 py-0.5 text-xs text-amber-700 dark:text-amber-300">Payment due</span>
          )}
        </h2>
        {paid && end && (
          <span className="text-sm text-muted">
            {account.cancel_at_period_end ? `Ends on ${end}, then Free` : `Renews on ${end}`}
          </span>
        )}
        {account.status === "canceled" && <span className="text-sm text-muted">Your paid plan ended.</span>}
      </div>
      <div className="flex flex-col gap-1.5">
        <div className="flex justify-between text-sm">
          <span>
            {u.used_minutes} of {u.limit_minutes} minutes used this month
          </span>
          <span className="text-muted">{u.remaining_minutes} left</span>
        </div>
        <div className="h-2.5 overflow-hidden rounded-full bg-black/10 dark:bg-white/10">
          <div
            className={`h-full ${pct >= 100 ? "bg-red-500" : pct >= 80 ? "bg-amber-500" : "bg-accent"}`}
            style={{ width: `${pct}%` }}
          />
        </div>
        {pct >= 100 && (
          <p className="text-sm text-red-600 dark:text-red-400">
            You&apos;ve used all your minutes this month. Upgrade to keep using the live copilot.
          </p>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        <Link href="/pricing" className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90">
          {paid ? "Change plan" : "Upgrade"}
        </Link>
        {paid && !account.cancel_at_period_end && (
          <button onClick={onCancel} disabled={busy} className={secondary}>
            Cancel plan
          </button>
        )}
        {paid && account.cancel_at_period_end && (
          <button onClick={onResume} disabled={busy} className={secondary}>
            Keep my plan
          </button>
        )}
        {account.can_manage && (
          <button onClick={onPortal} disabled={busy} className={secondary}>
            Billing &amp; invoices
          </button>
        )}
      </div>
      {account.provider === "fake" && (
        <p className="text-xs text-muted">Test mode: billing is simulated, nothing is charged.</p>
      )}
    </>
  );
}

function formatDuration(seconds: number) {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

const secondary =
  "rounded-lg border border-black/15 px-4 py-2 text-sm font-medium hover:bg-black/5 disabled:opacity-60 dark:border-white/15 dark:hover:bg-white/5";
