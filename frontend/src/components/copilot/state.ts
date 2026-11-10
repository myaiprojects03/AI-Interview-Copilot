import type {
  ChannelName,
  GapMention,
  QuestionType,
  ServerEvent,
  Timings,
} from "@/lib/copilotSocket";

export type SessionContext = Extract<ServerEvent, { type: "context" }>;

export type Line = {
  key: string;
  channel: ChannelName;
  text: string;
  final: boolean;
};

export type Suggestion = {
  id: number;
  key: string;
  question: string;
  questionType?: QuestionType;
  sources: string[];
  text: string;
  status: "streaming" | "done" | "stopped" | "error";
  timings?: Timings;
  unverified?: string[];
  gapMentions?: GapMention[];
};

export type CopilotState = {
  /** Increments on every (re)connect so ids from a new server session never collide. */
  epoch: number;
  lines: Line[];
  suggestions: Suggestion[]; // newest first
  speaking: Record<ChannelName, boolean>;
  context: SessionContext | null;
  usage: { remainingSeconds: number; limitSeconds: number; plan: string } | null;
  /** Set when the month's minutes ran out; the session has ended. */
  limitReached: string | null;
  error: string | null;
};

export const initialState: CopilotState = {
  epoch: 0,
  lines: [],
  suggestions: [],
  speaking: { interviewer: false, candidate: false },
  context: null,
  usage: null,
  limitReached: null,
  error: null,
};

export type Action =
  | { type: "server"; event: ServerEvent }
  | { type: "error"; message: string | null }
  | { type: "reset" };

const MAX_LINES = 200;
const MAX_SUGGESTIONS = 10;

export function reducer(state: CopilotState, action: Action): CopilotState {
  if (action.type === "reset") return { ...initialState, epoch: state.epoch };
  if (action.type === "error") return { ...state, error: action.message };

  const e = action.event;
  switch (e.type) {
    case "usage":
      return {
        ...state,
        usage: { remainingSeconds: e.remaining_seconds, limitSeconds: e.limit_seconds, plan: e.plan },
      };
    case "limit_reached":
      return { ...state, limitReached: e.message };
    case "ready":
      return { ...state, epoch: state.epoch + 1, error: null };
    case "context":
      return { ...state, context: e };
    case "speech":
      return { ...state, speaking: { ...state.speaking, [e.channel]: e.active } };
    case "transcript": {
      const key = `${state.epoch}-${e.channel}-${e.utterance_id}`;
      const idx = state.lines.findIndex((l) => l.key === key);
      if (idx >= 0) {
        if (state.lines[idx].final && !e.final) return state; // stale partial
        const lines = state.lines.slice();
        lines[idx] = { ...lines[idx], text: e.text, final: e.final };
        return { ...state, lines };
      }
      const line: Line = { key, channel: e.channel, text: e.text, final: e.final };
      return { ...state, lines: [...state.lines, line].slice(-MAX_LINES) };
    }
    case "transcript_discard": {
      const key = `${state.epoch}-${e.channel}-${e.utterance_id}`;
      return { ...state, lines: state.lines.filter((l) => l.key !== key) };
    }
    case "suggestion_start": {
      const s: Suggestion = {
        id: e.id,
        key: `${state.epoch}-${e.id}`,
        question: e.question,
        questionType: e.question_type,
        sources: e.sources ?? [],
        text: "",
        status: "streaming",
      };
      return { ...state, suggestions: [s, ...state.suggestions].slice(0, MAX_SUGGESTIONS) };
    }
    case "suggestion_delta":
    case "suggestion_end": {
      const key = `${state.epoch}-${e.id}`;
      return {
        ...state,
        suggestions: state.suggestions.map((s) => {
          if (s.key !== key) return s;
          return e.type === "suggestion_delta"
            ? { ...s, text: s.text + e.text }
            : {
                ...s,
                status: e.status,
                timings: e.timings,
                unverified: e.unverified,
                gapMentions: e.gap_mentions,
              };
        }),
      };
    }
    case "error":
      return { ...state, error: e.message };
  }
}
