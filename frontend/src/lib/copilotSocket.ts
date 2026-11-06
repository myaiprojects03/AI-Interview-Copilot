import { API_URL } from "@/lib/api";

export const CHANNEL = { interviewer: 0, candidate: 1 } as const;
export type ChannelName = keyof typeof CHANNEL;
export type SessionType = "mixed" | "behavioral" | "technical";

export type Timings = {
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
  | { type: "suggestion_start"; id: number; question: string }
  | { type: "suggestion_delta"; id: number; text: string }
  | {
      type: "suggestion_end";
      id: number;
      status: "done" | "stopped" | "error";
      timings: Timings;
      /** Figures in the answer that the CV never states. */
      unverified: string[];
    }
  | { type: "error"; message: string; retryable?: boolean };

export type ControlMessage =
  | { type: "start"; session_type: SessionType }
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
  private retryTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private readonly handlers: {
      onEvent: (event: ServerEvent) => void;
      onStatus: (status: SocketStatus) => void;
      /** Sent again after every (re)connect, e.g. the session type. */
      onOpen: () => ControlMessage[];
    },
    private readonly url = API_URL.replace(/^http/, "ws") + "/ws/session",
  ) {}

  connect() {
    this.closedByUser = false;
    this.handlers.onStatus(this.attempt === 0 ? "connecting" : "reconnecting");
    const ws = new WebSocket(this.url);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onopen = () => {
      this.attempt = 0;
      this.handlers.onStatus("open");
      for (const msg of this.handlers.onOpen()) this.send(msg);
    };
    ws.onmessage = (e) => {
      if (typeof e.data === "string") this.handlers.onEvent(JSON.parse(e.data) as ServerEvent);
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      if (this.closedByUser) {
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

  get isOpen() {
    return this.ws?.readyState === WebSocket.OPEN;
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
