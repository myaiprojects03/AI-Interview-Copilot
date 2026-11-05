"use client";

import { useEffect, useState } from "react";
import { API_URL, getProviderStatus, type ProviderStatus } from "@/lib/api";

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ok"; status: ProviderStatus };

function Row({ label, ok, detail }: { label: string; ok: boolean; detail: string }) {
  return (
    <li className="flex items-center justify-between gap-4 py-2">
      <span className="font-medium">{label}</span>
      <span className="flex items-center gap-2 text-sm text-muted">
        {detail}
        <span
          className={`inline-block h-2.5 w-2.5 rounded-full ${ok ? "bg-accent" : "bg-amber-500"}`}
          aria-label={ok ? "configured" : "not configured"}
        />
      </span>
    </li>
  );
}

export function BackendStatus() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    getProviderStatus(controller.signal)
      .then((status) => setState({ kind: "ok", status }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setState({ kind: "error", message: err instanceof Error ? err.message : String(err) });
      });
    return () => controller.abort();
  }, []);

  return (
    <section className="w-full rounded-xl border border-black/10 bg-surface p-5 dark:border-white/10">
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">
        Backend status
      </h2>
      {state.kind === "loading" && <p className="text-sm text-muted">Checking {API_URL}…</p>}
      {state.kind === "error" && (
        <p className="text-sm text-amber-600">
          Can&apos;t reach the backend at {API_URL} ({state.message}). Start it with{" "}
          <code className="font-mono">uvicorn app.main:app --reload</code>.
        </p>
      )}
      {state.kind === "ok" && (
        <ul className="divide-y divide-black/10 dark:divide-white/10">
          <Row
            label="Language model"
            ok={state.status.llm.configured}
            detail={`${state.status.llm.provider}${state.status.llm.model ? ` · ${state.status.llm.model}` : ""}`}
          />
          <Row
            label="Speech-to-text"
            ok={state.status.stt.configured}
            detail={`${state.status.stt.provider}${state.status.stt.model ? ` · ${state.status.stt.model}` : ""}`}
          />
          <Row
            label="Database"
            ok={state.status.database.configured}
            detail={state.status.database.configured ? "connected" : "not set (Phase 2)"}
          />
        </ul>
      )}
    </section>
  );
}
