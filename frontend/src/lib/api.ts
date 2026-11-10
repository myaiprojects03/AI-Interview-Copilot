import { accessToken } from "@/lib/supabase";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type ProviderStatus = {
  llm: { provider: string; model: string | null; configured: boolean };
  stt: { provider: string; model: string | null; configured: boolean };
  database: { configured: boolean; storage?: "postgres" | "memory" | null; error?: string | null };
};

export type DocKind = "cv" | "jd";

export type DocumentSummary = {
  id: string;
  kind: DocKind;
  title: string;
  filename: string | null;
  summary: string;
  chunk_count: number;
  word_count: number;
  created_at: string;
};

export type DocumentDetail = DocumentSummary & { content: string };

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  const token = await accessToken();
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init?.body && typeof init.body === "string") headers.set("Content-Type", "application/json");
  try {
    res = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init, headers });
  } catch {
    throw new Error(`Can't reach the backend at ${API_URL}. Is it running?`);
  }
  if (!res.ok) {
    let detail = `Request failed (HTTP ${res.status}).`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* keep the generic message */
    }
    if (res.status === 401 && typeof window !== "undefined" && token) {
      // The session expired or was revoked: sign in again.
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.replace(`/login?next=${next}`);
    }
    throw new ApiError(detail, res.status);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export function getProviderStatus(signal?: AbortSignal): Promise<ProviderStatus> {
  return request("/health/providers", { signal });
}

export function listDocuments(kind?: DocKind): Promise<DocumentSummary[]> {
  return request(kind ? `/documents?kind=${kind}` : "/documents");
}

export function getDocument(id: string): Promise<DocumentDetail> {
  return request(`/documents/${encodeURIComponent(id)}`);
}

export function deleteDocument(id: string): Promise<void> {
  return request(`/documents/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function uploadDocument(input: {
  kind: DocKind;
  file?: File | null;
  text?: string;
  title?: string;
}): Promise<DocumentSummary> {
  const form = new FormData();
  form.set("kind", input.kind);
  if (input.file) form.set("file", input.file);
  if (input.text) form.set("text", input.text);
  if (input.title) form.set("title", input.title);
  return request("/documents", { method: "POST", body: form });
}

// ---- Billing -------------------------------------------------------------------------------

export type PlanId = "free" | "starter" | "pro";

export type Plan = {
  id: PlanId;
  name: string;
  price_usd_month: number;
  minutes: number;
  blurb: string;
  price_id: string | null;
  available: boolean;
};

export type PlansResponse = {
  provider: "paddle" | "fake";
  paddle: { environment: "sandbox" | "production" } | null;
  plans: Plan[];
};

export type Account = {
  email?: string | null;
  plan: PlanId;
  plan_name: string;
  subscribed_plan: PlanId;
  status: string;
  provider: "paddle" | "fake" | null;
  cancel_at_period_end: boolean;
  current_period_end: string | null;
  can_manage: boolean;
  usage: { month: string; used_minutes: number; limit_minutes: number; remaining_minutes: number };
};

export type CheckoutResponse =
  | { provider: "fake"; done: true; account: Account }
  | {
      provider: "paddle";
      done: false;
      price_id: string;
      custom_data: Record<string, string>;
      email: string | null;
      success_url: string;
    };

export const getPlans = () => request<PlansResponse>("/billing/plans");
export const getAccount = () => request<Account>("/billing/me");
export const startCheckout = (plan: PlanId) =>
  request<CheckoutResponse>("/billing/checkout", { method: "POST", body: JSON.stringify({ plan }) });
export const syncCheckout = (transaction_id: string) =>
  request<Account>("/billing/sync", { method: "POST", body: JSON.stringify({ transaction_id }) });
export const changePlan = (plan: PlanId) =>
  request<Account>("/billing/change-plan", { method: "POST", body: JSON.stringify({ plan }) });
export const cancelPlan = () => request<Account>("/billing/cancel", { method: "POST" });
export const resumePlan = () => request<Account>("/billing/resume", { method: "POST" });
export const billingPortal = () => request<{ url: string }>("/billing/portal", { method: "POST" });

// ---- Interview history ---------------------------------------------------------------------

export type InterviewSummary = {
  id: string;
  started_at: string;
  ended_at: string | null;
  minutes: number;
  seconds: number;
  cv_title: string | null;
  jd_title: string | null;
  question_count: number;
};

export type InterviewDetail = InterviewSummary & {
  turns: { speaker: "interviewer" | "candidate"; text: string; at: string }[];
  answers: { question: string; question_type: string | null; answer: string; status: string; at: string }[];
};

export const listInterviews = () => request<InterviewSummary[]>("/sessions");
export const getInterview = (id: string) =>
  request<InterviewDetail>(`/sessions/${encodeURIComponent(id)}`);
export const deleteInterview = (id: string) =>
  request<void>(`/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
export const deleteAllMyData = () =>
  request<{ deleted_documents: number; deleted_interviews: number }>("/me/data", {
    method: "DELETE",
  });
