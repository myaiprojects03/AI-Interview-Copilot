import { API_URL } from "@/lib/api";

export const CHANNEL = { interviewer: 0, candidate: 1 } as const;
export type ChannelName = keyof typeof CHANNEL;
export type SessionType = "mixed" | "behavioral" | "technical";
export type QuestionType = "behavioral" | "technical" | "general";
export type GapMention = { skill: string; matches: string[] };

export type Timings = {
  retrieval_ms?: number;
  stt_ms?: number;
  llm_first_token_ms?: number;
  speech_end_to_first_token_ms?: number;
  llm_total_ms?: number;
};

export type ServerEvent =
  /** max_seconds: the host closes this connection after this long (Vercel Hobby: 300). */
  | { type: "ready"; max_seconds?: number }
  | { type: "speech"; channel: ChannelName; active: boolean }
  | {
      type: "transcript";
      channel: ChannelName;
      utterance_id: number;
      text: string;
      final: boolean;
      stt_ms?: number;
    }
  | { type: "transcript_discard"; channel: ChannelName; utterance_id: number }
  | {
      type: "context";
      cv: { id: string; title: string } | null;
      jd: { id: string; title: string } | null;
      using_sample_cv: boolean;
      /** Skills the job asks for that the CV doesn't show. */
      gaps: string[];
    }
  | {
      type: "suggestion_start";
      id: number;
      question: string;
      question_type: QuestionType;
      /** CV roles/sections the answer drew on. */
      sources: string[];
    }
  | { type: "suggestion_delta"; id: number; text: string }
  | {
      type: "suggestion_end";
      id: number;
      status: "done" | "stopped" | "error";
      timings: Timings;
      /** Figures in the answer that the CV never states. */
      unverified: string[];
      /** Job skills the CV doesn't show that the answer mentions. */
      gap_mentions: GapMention[];
    }
  | { type: "usage"; plan: string; limit_seconds: number; remaining_seconds: number }
  | { type: "limit_reached"; plan: string; message: string }
  /** The interview this connection saves to; sent back after a reconnect to continue it. */
  | { type: "history"; id: string }
  | { type: "error"; message: string; retryable?: boolean; code?: "auth" };

/** Server close codes after which reconnecting is pointless. */
const CLOSE_AUTH = 4401;
const CLOSE_LIMIT = 4402;
/** The host's connection time limit was reached: reconnect straight away. */
const CLOSE_TIME_UP = 4408;

export type ControlMessage =
  | {
      type: "start";
      session_type: SessionType;
      /** A document id, or null for none (the sample CV is used when there's no CV). */
      cv_id: string | null;
      jd_id: string | null;
      /** Continue this interview after a reconnect (from the server's "history" event). */
      history_id?: string | null;
      /** Recent transcript lines, so answers keep their context on a fresh connection. */
      recent?: string[];
    }
  | { type: "set_session_type"; session_type: SessionType }
  | { type: "pause" }
  /** Finish (transcribe) any sentence in progress: sent to a connection being retired. */
  | { type: "flush" }
  | { type: "answer_now" }
  | { type: "regenerate" }
  | { type: "stop_answer" };

export type SocketStatus = "connecting" | "open" | "reconnecting" | "closed";

const RETRY_DELAYS_MS = [500, 1000, 2000, 4000, 8000];
/** Start looking for a quiet moment this long before the host cuts the connection (at most
 * 20% of its lifetime, so short limits don't cause constant switching). */
const SWITCH_LOOK_S = 40;
/** Switch even if it never goes quiet, this long before the cut. */
const SWITCH_FORCE_S = 12;
/** "Quiet": nobody speaking, and the last sentence ended at least this long ago, so its
 * transcript and any answer have already started on the old connection. */
const QUIET_AFTER_SPEECH_MS = 2500;
/** A retired connection closes once it has heard nothing for this long and has no answer
 * in progress, so its last transcript arrives first. */
const RETIRE_IDLE_MS = 3000;
const POLL_MS = 250;

/** Seconds before the cut to start looking for a quiet moment, and to force the switch. The
 * force point always comes after the look point, leaving a window to find a pause. */
function lookBefore(conn: { maxSeconds: number | null }) {
  return Math.min(SWITCH_LOOK_S, (conn.maxSeconds ?? 0) * 0.2);
}
function forceBefore(conn: { maxSeconds: number | null }) {
  return Math.min(SWITCH_FORCE_S, lookBefore(conn) / 2);
}

type Conn = {
  id: number;
  ws: WebSocket;
  authed: boolean;
  openedAt: number;
  maxSeconds: number | null;
  speaking: Set<string>;
  lastSpeechEnd: number;
  /** Answers this connection started but hasn't finished. */
  pending: Set<number>;
  timers: ReturnType<typeof setTimeout>[];
};

/**
 * WebSocket to the copilot backend.
 *
 * - Reconnects automatically after drops (backoff), never after sign-in or plan-limit closes.
 * - On hosts that cut long connections (Vercel Hobby: 5 minutes) it switches to a fresh
 *   connection before the cut, at a quiet moment: the new one takes the audio, the old one
 *   finishes any answer it is writing and then closes. The page and audio capture are
 *   untouched. Every event is tagged with the id of the connection it came from.
 */
export class CopilotSocket {
  private current: Conn | null = null;
  private switching: Conn | null = null;
  private retiring = new Set<Conn>();
  private nextId = 1;
  private attempt = 0;
  private closedByUser = false;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private readonly handlers: {
      onEvent: (event: ServerEvent, connId: number) => void;
      onStatus: (status: SocketStatus) => void;
      /** Sent after every (re)connect and switch, e.g. start with the session type. */
      onOpen: () => ControlMessage[];
      /** The sign-in token, sent as the first message (browsers can't set WS headers). */
      getToken: () => Promise<string | null>;
    },
    private readonly url = API_URL.replace(/^http/, "ws") + "/ws/session",
  ) {}

  connect() {
    this.closedByUser = false;
    this.handlers.onStatus(this.attempt === 0 ? "connecting" : "reconnecting");
    this.current = this.open(false);
  }

  private open(isSwitch: boolean): Conn {
    const conn: Conn = {
      id: this.nextId++,
      ws: new WebSocket(this.url),
      authed: false,
      openedAt: Date.now(),
      maxSeconds: null,
      speaking: new Set(),
      lastSpeechEnd: 0,
      pending: new Set(),
      timers: [],
    };
    const { ws } = conn;
    ws.binaryType = "arraybuffer";

    ws.onopen = async () => {
      const token = await this.handlers.getToken();
      if (ws.readyState !== WebSocket.OPEN) return;
      ws.send(JSON.stringify({ type: "auth", token }));
      conn.authed = true;
      if (isSwitch) {
        if (this.switching !== conn || this.closedByUser) {
          ws.close();
          return;
        }
        // Set up the new connection now, but only move the audio over between sentences.
        for (const msg of this.handlers.onOpen()) this.sendOn(conn, msg);
        this.promoteWhenQuiet(conn);
        return;
      }
      this.attempt = 0;
      this.handlers.onStatus("open");
      for (const msg of this.handlers.onOpen()) this.sendOn(conn, msg);
    };

    ws.onmessage = (e) => {
      if (typeof e.data !== "string") return;
      const event = JSON.parse(e.data) as ServerEvent;
      this.track(conn, event);
      this.handlers.onEvent(event, conn.id);
    };

    ws.onclose = (e) => {
      conn.timers.forEach(clearTimeout);
      if (this.retiring.delete(conn)) return; // a retired connection finishing normally
      if (conn === this.switching) {
        this.switching = null; // the fresh connection failed; the current one carries on
        return;
      }
      if (conn !== this.current) return;
      this.current = null;
      if (this.closedByUser || e.code === CLOSE_AUTH || e.code === CLOSE_LIMIT) {
        this.handlers.onStatus("closed");
        return;
      }
      if (e.code === CLOSE_TIME_UP) {
        // The host's time limit hit before a switch could happen: reconnect at once.
        this.handlers.onStatus("reconnecting");
        this.current = this.open(false);
        return;
      }
      if (this.attempt >= RETRY_DELAYS_MS.length) {
        this.handlers.onStatus("closed");
        this.handlers.onEvent(
          { type: "error", message: "Lost connection to the copilot server. Press Start to try again." },
          conn.id,
        );
        return;
      }
      this.handlers.onStatus("reconnecting");
      this.retryTimer = setTimeout(() => {
        this.current = this.open(false);
      }, RETRY_DELAYS_MS[this.attempt++]);
    };
    return conn;
  }

  /** Follow what each connection is doing, to pick a quiet moment and know when it's done. */
  private track(conn: Conn, event: ServerEvent) {
    if (event.type === "ready" && event.max_seconds) {
      conn.maxSeconds = event.max_seconds;
      const lookAt = Math.max(1, event.max_seconds - lookBefore(conn)) * 1000;
      conn.timers.push(setTimeout(() => this.waitForQuiet(conn), lookAt));
    } else if (event.type === "speech") {
      if (event.active) conn.speaking.add(event.channel);
      else {
        conn.speaking.delete(event.channel);
        conn.lastSpeechEnd = Date.now();
      }
    } else if (event.type === "suggestion_start") {
      conn.pending.add(event.id);
    } else if (event.type === "suggestion_end") {
      conn.pending.delete(event.id);
    }
  }

  private deadline(conn: Conn, secondsBefore: number) {
    return conn.openedAt + ((conn.maxSeconds ?? 0) - secondsBefore) * 1000;
  }

  private waitForQuiet(conn: Conn) {
    if (conn !== this.current || this.switching || this.closedByUser) return;
    const quiet =
      conn.speaking.size === 0 && Date.now() - conn.lastSpeechEnd > QUIET_AFTER_SPEECH_MS;
    if (quiet || Date.now() >= this.deadline(conn, forceBefore(conn))) {
      this.switching = this.open(true);
      return;
    }
    conn.timers.push(setTimeout(() => this.waitForQuiet(conn), POLL_MS));
  }

  /** Move the audio to the fresh connection once nobody is mid-sentence (checked again here:
   * someone may have started talking while it was connecting), or at the force deadline. */
  private promoteWhenQuiet(next: Conn) {
    const old = this.current;
    if (this.switching !== next || this.closedByUser || next.ws.readyState !== WebSocket.OPEN) {
      return;
    }
    const forced = !old || Date.now() >= this.deadline(old, forceBefore(old));
    if (old && old.speaking.size > 0 && !forced) {
      next.timers.push(setTimeout(() => this.promoteWhenQuiet(next), POLL_MS));
      return;
    }
    this.switching = null;
    this.current = next;
    this.attempt = 0;
    this.handlers.onStatus("open");
    if (old) {
      // Forced mid-sentence: have the old connection finish what it heard.
      if (old.speaking.size > 0) this.sendOn(old, { type: "flush" });
      this.retire(old);
    }
  }

  /** Stop sending audio to `conn`; close it once its answers are done (or near its cut). */
  private retire(conn: Conn) {
    this.retiring.add(conn);
    const retiredAt = Date.now();
    const check = () => {
      if (conn.ws.readyState !== WebSocket.OPEN) return;
      const lastHeard = Math.max(conn.lastSpeechEnd, retiredAt);
      const idle =
        conn.pending.size === 0 &&
        conn.speaking.size === 0 &&
        Date.now() - lastHeard > RETIRE_IDLE_MS;
      if (idle || Date.now() >= this.deadline(conn, 2)) {
        conn.ws.close();
        return;
      }
      conn.timers.push(setTimeout(check, POLL_MS));
    };
    check();
  }

  /** Open and signed in: audio and controls can be sent. */
  get isOpen() {
    const c = this.current;
    return Boolean(c && c.authed && c.ws.readyState === WebSocket.OPEN);
  }

  sendAudio(channel: ChannelName, pcm: ArrayBuffer) {
    if (!this.isOpen) return;
    const frame = new Uint8Array(1 + pcm.byteLength);
    frame[0] = CHANNEL[channel];
    frame.set(new Uint8Array(pcm), 1);
    this.current!.ws.send(frame);
  }

  private sendOn(conn: Conn, msg: ControlMessage) {
    if (conn.authed && conn.ws.readyState === WebSocket.OPEN) conn.ws.send(JSON.stringify(msg));
  }

  send(msg: ControlMessage) {
    if (this.current) this.sendOn(this.current, msg);
    // An answer may still be streaming on a retiring connection: let Stop reach it too.
    if (msg.type === "stop_answer") this.retiring.forEach((c) => this.sendOn(c, msg));
  }

  close() {
    this.closedByUser = true;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    for (const c of [this.current, this.switching, ...this.retiring]) {
      if (!c) continue;
      c.timers.forEach(clearTimeout);
      c.ws.close();
    }
    this.current = null;
    this.switching = null;
    this.retiring.clear();
    this.attempt = 0;
  }
}
