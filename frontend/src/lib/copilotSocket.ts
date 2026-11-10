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
  | { type: "ready" }
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

export type ControlMessage =
  | {
      type: "start";
      session_type: SessionType;
      /** A document id, or null for none (the sample CV is used when there's no CV). */
      cv_id: string | null;
      jd_id: string | null;
      /** Continue this interview after a reconnect (from the server's "history" event). */
      history_id?: string | null;
    }
  | { type: "set_session_type"; session_type: SessionType }
  | { type: "pause" }
  | { type: "answer_now" }
  | { type: "regenerate" }
  | { type: "stop_answer" };

export type SocketStatus = "connecting" | "open" | "reconnecting" | "closed";

const RETRY_DELAYS_MS = [500, 1000, 2000, 4000, 8000];

/** WebSocket to the copilot backend, with automatic reconnect. */
export class CopilotSocket {
  private ws: WebSocket | null = null;
  private attempt = 0;
  private closedByUser = false;
  private authed = false;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private readonly handlers: {
      onEvent: (event: ServerEvent) => void;
      onStatus: (status: SocketStatus) => void;
      /** Sent again after every (re)connect, e.g. the session type. */
      onOpen: () => ControlMessage[];
      /** The sign-in token, sent as the first message (browsers can't set WS headers). */
      getToken: () => Promise<string | null>;
    },
    private readonly url = API_URL.replace(/^http/, "ws") + "/ws/session",
  ) {}

  connect() {
    this.closedByUser = false;
    this.authed = false;
    this.handlers.onStatus(this.attempt === 0 ? "connecting" : "reconnecting");
    const ws = new WebSocket(this.url);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onopen = async () => {
      const token = await this.handlers.getToken();
      if (this.ws !== ws || ws.readyState !== WebSocket.OPEN) return;
      ws.send(JSON.stringify({ type: "auth", token }));
      this.authed = true;
      this.attempt = 0;
      this.handlers.onStatus("open");
      for (const msg of this.handlers.onOpen()) this.send(msg);
    };
    ws.onmessage = (e) => {
      if (typeof e.data === "string") this.handlers.onEvent(JSON.parse(e.data) as ServerEvent);
    };
    ws.onclose = (e) => {
      if (this.ws !== ws) return;
      this.ws = null;
      this.authed = false;
      if (this.closedByUser || e.code === CLOSE_AUTH || e.code === CLOSE_LIMIT) {
        this.handlers.onStatus("closed");
        return;
      }
      if (this.attempt >= RETRY_DELAYS_MS.length) {
        this.handlers.onStatus("closed");
        this.handlers.onEvent({
          type: "error",
          message: "Lost connection to the copilot server. Press Start to try again.",
        });
        return;
      }
      this.handlers.onStatus("reconnecting");
      this.retryTimer = setTimeout(() => this.connect(), RETRY_DELAYS_MS[this.attempt++]);
    };
  }

  /** Open and signed in: audio and controls can be sent. */
  get isOpen() {
    return this.authed && this.ws?.readyState === WebSocket.OPEN;
  }

  sendAudio(channel: ChannelName, pcm: ArrayBuffer) {
    if (!this.isOpen) return;
    const frame = new Uint8Array(1 + pcm.byteLength);
    frame[0] = CHANNEL[channel];
    frame.set(new Uint8Array(pcm), 1);
    this.ws!.send(frame);
  }

  send(msg: ControlMessage) {
    if (this.isOpen) this.ws!.send(JSON.stringify(msg));
  }

  close() {
    this.closedByUser = true;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.ws?.close();
    this.ws = null;
    this.attempt = 0;
  }
}
