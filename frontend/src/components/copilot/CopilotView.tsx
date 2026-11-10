"use client";

import Link from "next/link";
import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { captureStream, getMic, getTabAudio, stopStream, type CaptureHandle } from "@/lib/audio";
import {
  CopilotSocket,
  type ChannelName,
  type SessionType,
  type SocketStatus,
  type Timings,
} from "@/lib/copilotSocket";
import { AppHeader } from "@/components/AppHeader";
import { RequireAuth } from "@/components/auth/AuthProvider";
import { SuggestionText, type Flag } from "@/components/SuggestionText";
import { accessToken } from "@/lib/supabase";
import { listDocuments, type DocumentSummary } from "@/lib/api";
import { initialState, reducer, type Line, type SessionContext, type Suggestion } from "./state";

type RunState = "idle" | "starting" | "live" | "paused";
type Mode = "meeting" | "practice";

export function CopilotView() {
  return (
    <RequireAuth>
      <Copilot />
    </RequireAuth>
  );
}

function Copilot() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const [run, setRun] = useState<RunState>("idle");
  const [socketStatus, setSocketStatus] = useState<SocketStatus>("closed");
  const [mode, setMode] = useState<Mode>("meeting");
  const [sessionType, setSessionType] = useState<SessionType>("mixed");
  const [hasMic, setHasMic] = useState(true);
  const [levels, setLevels] = useState<Record<ChannelName, number>>({ interviewer: 0, candidate: 0 });
  const [docs, setDocs] = useState<DocumentSummary[] | null>(null);
  const [selected, setSelected] = useState<{ cv: string; jd: string }>({ cv: "", jd: "" });

  const socketRef = useRef<CopilotSocket | null>(null);
  const capturesRef = useRef<CaptureHandle[]>([]);
  const streamsRef = useRef<MediaStream[]>([]);
  const pausedRef = useRef(false);
  const sessionTypeRef = useRef<SessionType>(sessionType);
  const selectedRef = useRef(selected);

  useEffect(() => {
    listDocuments()
      .then((all) => {
        setDocs(all);
        // Newest first: preselect the latest CV and job description.
        const pick = {
          cv: all.find((d) => d.kind === "cv")?.id ?? "",
          jd: all.find((d) => d.kind === "jd")?.id ?? "",
        };
        selectedRef.current = pick;
        setSelected(pick);
      })
      .catch(() => setDocs([]));
  }, []);

  const choose = (kind: "cv" | "jd", id: string) => {
    const next = { ...selectedRef.current, [kind]: id };
    selectedRef.current = next;
    setSelected(next);
  };

  const stop = useCallback(() => {
    capturesRef.current.forEach((c) => c.stop());
    capturesRef.current = [];
    streamsRef.current.forEach(stopStream);
    streamsRef.current = [];
    socketRef.current?.close();
    socketRef.current = null;
    pausedRef.current = false;
    setLevels({ interviewer: 0, candidate: 0 });
    setRun("idle");
  }, []);

  useEffect(() => stop, [stop]);


  const start = async () => {
    setRun("starting");
    dispatch({ type: "reset" });
    try {
      const tab = mode === "meeting" ? await getTabAudio() : null;
      if (tab) streamsRef.current.push(tab);
      let mic: MediaStream | null = null;
      try {
        mic = await getMic();
        streamsRef.current.push(mic);
      } catch (err) {
        // In meeting mode the mic is optional: the interviewer's tab audio is what matters.
        if (!tab) throw err;
        dispatch({
          type: "error",
          message: `${describeStartError(err)} Only the interviewer is being transcribed; your own answers won't appear.`,
        });
      }
      setHasMic(mic !== null);

      const socket = new CopilotSocket({
        onEvent: (event) => {
          dispatch({ type: "server", event });
          // The server ends the session when the month's minutes run out.
          if (event.type === "limit_reached") stop();
        },
        onStatus: setSocketStatus,
        getToken: accessToken,
        onOpen: () => [
          {
            type: "start",
            session_type: sessionTypeRef.current,
            cv_id: selectedRef.current.cv || null,
            jd_id: selectedRef.current.jd || null,
          },
        ],
      });
      socket.connect();
      socketRef.current = socket;

      const attach = async (stream: MediaStream, channel: ChannelName) => {
        const handle = await captureStream(stream, (pcm, rms) => {
          if (pausedRef.current) return;
          socket.sendAudio(channel, pcm);
          setLevels((l) => (Math.abs(l[channel] - rms) > 0.005 ? { ...l, [channel]: rms } : l));
        });
        capturesRef.current.push(handle);
        stream.getAudioTracks()[0]?.addEventListener("ended", stop);
      };
      if (tab) {
        await attach(tab, "interviewer");
        if (mic) await attach(mic, "candidate");
      } else if (mic) {
        await attach(mic, "interviewer"); // practice: you read the questions out loud
      }
      setRun("live");
    } catch (err) {
      stop();
      dispatch({ type: "error", message: describeStartError(err) });
    }
  };

  const togglePause = () => {
    const pausing = run === "live";
    pausedRef.current = pausing;
    if (pausing) socketRef.current?.send({ type: "pause" });
    setLevels({ interviewer: 0, candidate: 0 });
    setRun(pausing ? "paused" : "live");
  };

  const changeSessionType = (value: SessionType) => {
    setSessionType(value);
    sessionTypeRef.current = value;
    socketRef.current?.send({ type: "set_session_type", session_type: value });
  };

  const send = (type: "answer_now" | "regenerate" | "stop_answer") =>
    socketRef.current?.send({ type });

  const active = run === "live" || run === "paused";
  const current = state.suggestions[0];
  const streaming = current?.status === "streaming";

  return (
    <div className="flex min-h-screen flex-col">
      <AppHeader />
      <div className="flex flex-wrap items-center gap-3 border-b border-black/10 px-4 py-2 dark:border-white/10 sm:px-6">
        <StatusPill run={run} socket={socketStatus} />
        {state.usage && <MinutesLeft seconds={state.usage.remainingSeconds} />}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Select
            label="Source"
            value={mode}
            disabled={run !== "idle"}
            onChange={(v) => setMode(v as Mode)}
            options={[
              ["meeting", "Meeting tab + mic"],
              ["practice", "Practice (mic only)"],
            ]}
          />
          <Select
            label="Focus"
            value={sessionType}
            onChange={(v) => changeSessionType(v as SessionType)}
            options={[
              ["mixed", "Mixed"],
              ["behavioral", "Behavioral"],
              ["technical", "Technical"],
            ]}
          />
          {active && (
            <button onClick={togglePause} className={buttonSecondary}>
              {run === "paused" ? "Resume" : "Pause"}
            </button>
          )}
          {active ? (
            <button onClick={stop} className={buttonSecondary}>
              Stop
            </button>
          ) : (
            <button onClick={start} disabled={run === "starting"} className={buttonPrimary}>
              {run === "starting" ? "Starting…" : "Start"}
            </button>
          )}
        </div>
      </div>

      <ContextBar
        docs={docs}
        selected={selected}
        onChoose={choose}
        disabled={run !== "idle"}
        live={active ? state.context : null}
      />

      {state.limitReached && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 border-b border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-700 dark:text-red-300 sm:px-6"
        >
          <span>{state.limitReached}</span>
          <Link href="/pricing" className="rounded-md bg-primary px-3 py-1 font-medium text-primary-foreground">
            See plans
          </Link>
        </div>
      )}

      {state.error && (
        <div
          role="alert"
          className="flex items-start justify-between gap-4 border-b border-amber-500/30 bg-amber-500/10 px-4 py-2 text-sm text-amber-700 dark:text-amber-300 sm:px-6"
        >
          <span>{state.error}</span>
          <button onClick={() => dispatch({ type: "error", message: null })} aria-label="Dismiss">
            ✕
          </button>
        </div>
      )}

      <main className="grid flex-1 grid-cols-1 gap-4 p-4 sm:p-6 lg:grid-cols-5 lg:gap-6">
        <section className="flex min-h-64 flex-col rounded-xl border border-black/10 bg-surface lg:col-span-2 lg:max-h-[calc(100vh-7rem)] dark:border-white/10">
          <div className="flex items-center gap-4 border-b border-black/10 px-4 py-2 text-sm dark:border-white/10">
            <h2 className="font-semibold">Transcript</h2>
            <Meter label="Interviewer" level={levels.interviewer} speaking={state.speaking.interviewer} />
            {mode === "meeting" && hasMic && (
              <Meter label="You" level={levels.candidate} speaking={state.speaking.candidate} />
            )}
          </div>
          <Transcript lines={state.lines} mode={mode} />
        </section>

        <section className="order-first flex min-h-80 flex-col rounded-xl border border-black/10 bg-surface lg:order-none lg:col-span-3 lg:max-h-[calc(100vh-7rem)] dark:border-white/10">
          <div className="flex flex-wrap items-center gap-2 border-b border-black/10 px-4 py-2 dark:border-white/10">
            <h2 className="mr-auto text-sm font-semibold">Suggested answer</h2>
            <button onClick={() => send("answer_now")} disabled={!active} className={buttonSmall}>
              Answer now
            </button>
            {streaming ? (
              <button onClick={() => send("stop_answer")} className={buttonSmall}>
                Stop
              </button>
            ) : (
              <button onClick={() => send("regenerate")} disabled={!active || !current} className={buttonSmall}>
                Regenerate
              </button>
            )}
          </div>
          <div className="flex-1 overflow-y-auto px-5 py-4">
            {current ? <CurrentSuggestion s={current} /> : <EmptySuggestion mode={mode} />}
            {state.suggestions.length > 1 && <Earlier suggestions={state.suggestions.slice(1)} />}
          </div>
        </section>
      </main>
    </div>
  );
}

function describeStartError(err: unknown): string {
  if (err instanceof DOMException) {
    if (err.name === "NotAllowedError") return "Permission was denied or sharing was cancelled.";
    if (err.name === "NotFoundError") return "No microphone was found.";
    if (err.name === "NotReadableError")
      return "The microphone is in use by another app or isn't working.";
  }
  return err instanceof Error ? err.message : String(err);
}

function Transcript({ lines, mode }: { lines: Line[]; mode: Mode }) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [lines]);
  if (lines.length === 0) {
    return (
      <p className="p-4 text-sm text-muted">
        {mode === "meeting"
          ? "The interviewer's words (from the meeting tab) and yours (from the mic) appear here."
          : "Practice mode: read a question out loud and it appears here."}
      </p>
    );
  }
  return (
    <div className="flex-1 overflow-y-auto px-4 py-3">
      <ol className="flex flex-col gap-3">
        {lines.map((l) => (
          <li key={l.key} className="flex flex-col gap-0.5">
            <span
              className={`text-xs font-semibold uppercase tracking-wide ${
                l.channel === "interviewer" ? "text-primary" : "text-accent"
              }`}
            >
              {l.channel === "interviewer" ? "Interviewer" : "You"}
            </span>
            <span className={`text-base leading-relaxed ${l.final ? "" : "italic text-muted"}`}>
              {l.text}
            </span>
          </li>
        ))}
      </ol>
      <div ref={endRef} />
    </div>
  );
}

const TYPE_LABEL = {
  behavioral: "Behavioral · STAR",
  technical: "Technical",
  general: "General",
} as const;

function CurrentSuggestion({ s }: { s: Suggestion }) {
  return (
    <article className="flex flex-col gap-4" aria-live="polite">
      <div className="flex flex-col gap-1.5">
        <p className="text-sm text-muted">
          {s.questionType && (
            <span className="mr-2 rounded-full bg-primary/15 px-2 py-0.5 text-xs font-medium text-primary">
              {TYPE_LABEL[s.questionType]}
            </span>
          )}
          <span className="font-semibold">Q:</span> {s.question}
        </p>
        {s.sources.length > 0 && (
          <p className="text-xs text-muted">Based on: {s.sources.join(" · ")}</p>
        )}
      </div>
      <div className="text-xl leading-relaxed lg:text-2xl">
        {s.text ? (
          <SuggestionText text={s.text} flagged={flagsFor(s)} />
        ) : s.status === "streaming" ? (
          <span className="text-muted">Thinking…</span>
        ) : null}
        {s.status === "streaming" && s.text && (
          <span className="ml-1 inline-block h-5 w-2 animate-pulse bg-primary align-middle" />
        )}
      </div>
      <TimingLine s={s} />
    </article>
  );
}

function flagsFor(s: Suggestion): Flag[] {
  return [
    ...(s.unverified ?? []).map((text) => ({
      text,
      note: "Not in your CV. Check this before you say it.",
    })),
    ...(s.gapMentions ?? []).flatMap((g) =>
      g.matches.map((text) => ({ text, note: `${g.skill} isn't on your CV.` })),
    ),
  ];
}

function TimingLine({ s }: { s: Suggestion }) {
  if (s.status === "streaming") return null;
  const t: Timings = s.timings ?? {};
  const parts: string[] = [];
  if (t.speech_end_to_first_token_ms != null)
    parts.push(`question end → first words ${(t.speech_end_to_first_token_ms / 1000).toFixed(1)} s`);
  if (t.stt_ms != null) parts.push(`transcribe ${t.stt_ms} ms`);
  if (t.llm_first_token_ms != null) parts.push(`AI first token ${t.llm_first_token_ms} ms`);
  const label = s.status === "stopped" ? "Stopped" : s.status === "error" ? "Failed" : null;
  const flagged = s.unverified?.length ?? 0;
  const skills = s.gapMentions?.map((g) => g.skill) ?? [];
  return (
    <div className="flex flex-col gap-1 text-xs text-muted">
      {flagged > 0 && (
        <p className="text-amber-700 dark:text-amber-300">
          {flagged === 1 ? "1 highlighted figure isn't" : `${flagged} highlighted figures aren't`} in
          your CV. Check before saying it.
        </p>
      )}
      {skills.length > 0 && (
        <p className="text-amber-700 dark:text-amber-300">
          Mentions {skills.join(", ")}, which {skills.length === 1 ? "isn't" : "aren't"} on your CV.
          Don&apos;t claim {skills.length === 1 ? "it" : "them"} as experience.
        </p>
      )}
      <p>{[label, ...parts].filter(Boolean).join(" · ")}</p>
    </div>
  );
}

function EmptySuggestion({ mode }: { mode: Mode }) {
  return (
    <div className="flex flex-col gap-3 text-muted">
      <p className="text-lg">Suggestions appear here a moment after the interviewer asks a question.</p>
      <ol className="list-decimal space-y-1 pl-5 text-sm">
        {mode === "meeting" ? (
          <>
            <li>Open your Zoom, Google Meet or Teams call in a Chrome or Edge tab.</li>
            <li>Press Start, choose that tab, and turn on “Share tab audio”.</li>
            <li>Allow the microphone. Use headphones so your mic doesn’t pick up the interviewer.</li>
          </>
        ) : (
          <>
            <li>Press Start and allow the microphone.</li>
            <li>Read an interview question out loud, then pause.</li>
          </>
        )}
      </ol>
      <p className="text-sm">
        No call to test with? Open{" "}
        <a className="text-primary underline" href="/demo/mock-interview.wav" target="_blank">
          the mock interview recording
        </a>{" "}
        in a new tab, press Start here and share that tab.
      </p>
    </div>
  );
}

function Earlier({ suggestions }: { suggestions: Suggestion[] }) {
  return (
    <div className="mt-8 flex flex-col gap-2 border-t border-black/10 pt-4 dark:border-white/10">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Earlier</h3>
      {suggestions.map((s) => (
        <details key={s.key} className="rounded-lg px-2 py-1 text-sm hover:bg-black/5 dark:hover:bg-white/5">
          <summary className="cursor-pointer text-muted">{s.question}</summary>
          <div className="py-2 text-base">
            <SuggestionText text={s.text} flagged={flagsFor(s)} />
          </div>
        </details>
      ))}
    </div>
  );
}

function Meter({ label, level, speaking }: { label: string; level: number; speaking: boolean }) {
  const pct = Math.min(100, Math.round(Math.sqrt(level) * 220));
  return (
    <span className="flex items-center gap-2 text-xs text-muted">
      <span className={`h-2 w-2 rounded-full ${speaking ? "bg-accent" : "bg-black/20 dark:bg-white/20"}`} />
      {label}
      <span className="h-1.5 w-12 overflow-hidden rounded-full bg-black/10 dark:bg-white/10">
        <span className="block h-full bg-accent transition-[width]" style={{ width: `${pct}%` }} />
      </span>
    </span>
  );
}

function ContextBar({
  docs,
  selected,
  onChoose,
  disabled,
  live,
}: {
  docs: DocumentSummary[] | null;
  selected: { cv: string; jd: string };
  onChoose: (kind: "cv" | "jd", id: string) => void;
  disabled: boolean;
  live: SessionContext | null;
}) {
  const cvs = docs?.filter((d) => d.kind === "cv") ?? [];
  const jds = docs?.filter((d) => d.kind === "jd") ?? [];
  const usingSample = live ? live.using_sample_cv : cvs.length === 0 || !selected.cv;
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-black/10 px-4 py-2 text-sm dark:border-white/10 sm:px-6">
      <Select
        label="CV"
        value={selected.cv}
        disabled={disabled || docs === null}
        onChange={(v) => onChoose("cv", v)}
        options={[["", "Sample CV (demo)"], ...cvs.map((d): [string, string] => [d.id, `CV: ${d.title}`])]}
      />
      <Select
        label="Job description"
        value={selected.jd}
        disabled={disabled || docs === null}
        onChange={(v) => onChoose("jd", v)}
        options={[["", "No job description"], ...jds.map((d): [string, string] => [d.id, `Job: ${d.title}`])]}
      />
      {usingSample && (
        <span className="text-xs text-amber-700 dark:text-amber-300">
          Answers use a fictional sample CV until you upload yours.
        </span>
      )}
      {live && live.gaps.length > 0 && (
        <span
          className="text-xs text-muted"
          title="The job asks for these but your CV doesn't show them. Answers won't claim them; be ready to say how you'd learn them."
        >
          <span className="font-semibold text-amber-700 dark:text-amber-300">Not on your CV:</span>{" "}
          {live.gaps.join(" · ")}
        </span>
      )}
      <Link href="/documents" className="ml-auto text-xs text-primary underline">
        Manage CVs &amp; job descriptions
      </Link>
    </div>
  );
}

function MinutesLeft({ seconds }: { seconds: number }) {
  const minutes = Math.floor(seconds / 60);
  const low = seconds < 5 * 60;
  return (
    <span
      className={`rounded-full border px-3 py-1 text-xs ${
        low ? "border-amber-500/40 text-amber-700 dark:text-amber-300" : "border-black/10 text-muted dark:border-white/10"
      }`}
      title="Live interview minutes left this month"
    >
      {minutes < 1 ? "Under 1 min left" : `${minutes} min left`}
    </span>
  );
}

function StatusPill({ run, socket }: { run: RunState; socket: SocketStatus }) {
  let text = "Not started";
  let color = "bg-black/20 dark:bg-white/20";
  if (run === "starting") text = "Starting…";
  else if (run === "paused") {
    text = "Paused";
    color = "bg-amber-500";
  } else if (run === "live") {
    if (socket === "open") {
      text = "Listening";
      color = "bg-accent";
    } else {
      text = socket === "reconnecting" ? "Reconnecting…" : "Connecting…";
      color = "bg-amber-500";
    }
  }
  return (
    <span className="flex items-center gap-2 rounded-full border border-black/10 px-3 py-1 text-xs dark:border-white/10">
      <span className={`h-2 w-2 rounded-full ${color}`} />
      {text}
    </span>
  );
}

function Select({
  label,
  value,
  options,
  onChange,
  disabled,
}: {
  label: string;
  value: string;
  options: [string, string][];
  onChange: (v: string) => void;
  disabled?: boolean;
}) {
  return (
    <label className="flex items-center gap-1 text-sm">
      <span className="sr-only">{label}</span>
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-lg border border-black/15 bg-background px-2 py-1.5 disabled:opacity-60 dark:border-white/15"
      >
        {options.map(([v, text]) => (
          <option key={v} value={v}>
            {text}
          </option>
        ))}
      </select>
    </label>
  );
}

const buttonPrimary =
  "rounded-lg bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-60";
const buttonSecondary =
  "rounded-lg border border-black/15 px-4 py-1.5 text-sm font-medium hover:bg-black/5 dark:border-white/15 dark:hover:bg-white/5";
const buttonSmall =
  "rounded-md border border-black/15 px-3 py-1 text-sm hover:bg-black/5 disabled:opacity-40 dark:border-white/15 dark:hover:bg-white/5";
