"use client";

import Image from "next/image";
import Link from "next/link";
import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { brand } from "@/config/brand";
import { captureStream, getMic, getTabAudio, stopStream, type CaptureHandle } from "@/lib/audio";
import {
  CopilotSocket,
  type ChannelName,
  type SessionType,
  type SocketStatus,
  type Timings,
} from "@/lib/copilotSocket";
import { SuggestionText } from "@/components/SuggestionText";
import { initialState, reducer, type Line, type Suggestion } from "./state";

type RunState = "idle" | "starting" | "live" | "paused";
type Mode = "meeting" | "practice";

export function CopilotView() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const [run, setRun] = useState<RunState>("idle");
  const [socketStatus, setSocketStatus] = useState<SocketStatus>("closed");
  const [mode, setMode] = useState<Mode>("meeting");
  const [sessionType, setSessionType] = useState<SessionType>("mixed");
  const [levels, setLevels] = useState<Record<ChannelName, number>>({ interviewer: 0, candidate: 0 });

  const socketRef = useRef<CopilotSocket | null>(null);
  const capturesRef = useRef<CaptureHandle[]>([]);
  const streamsRef = useRef<MediaStream[]>([]);
  const pausedRef = useRef(false);
  const sessionTypeRef = useRef<SessionType>(sessionType);

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
    dispatch({ type: "error", message: null });
    try {
      const tab = mode === "meeting" ? await getTabAudio() : null;
      if (tab) streamsRef.current.push(tab);
      const mic = await getMic();
      streamsRef.current.push(mic);

      const socket = new CopilotSocket({
        onEvent: (event) => dispatch({ type: "server", event }),
        onStatus: setSocketStatus,
        onOpen: () => [{ type: "start", session_type: sessionTypeRef.current }],
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
        await attach(mic, "candidate");
      } else {
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
      <header className="flex flex-wrap items-center gap-3 border-b border-black/10 px-4 py-3 dark:border-white/10 sm:px-6">
        <Link href="/" className="flex items-center gap-2 font-semibold">
          <Image src={brand.logo} alt="" width={28} height={28} />
          <span className="hidden sm:inline">{brand.name}</span>
        </Link>
        <StatusPill run={run} socket={socketStatus} />
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
      </header>

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
            {mode === "meeting" && (
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

function CurrentSuggestion({ s }: { s: Suggestion }) {
  return (
    <article className="flex flex-col gap-4" aria-live="polite">
      <p className="text-sm text-muted">
        <span className="font-semibold">Q:</span> {s.question}
      </p>
      <div className="text-xl leading-relaxed lg:text-2xl">
        {s.text ? (
          <SuggestionText text={s.text} flagged={s.unverified} />
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
  return (
    <div className="flex flex-col gap-1 text-xs text-muted">
      {flagged > 0 && (
        <p className="text-amber-700 dark:text-amber-300">
          {flagged === 1 ? "1 highlighted figure isn't" : `${flagged} highlighted figures aren't`} in
          your CV. Check before saying it.
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
            <SuggestionText text={s.text} flagged={s.unverified} />
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
