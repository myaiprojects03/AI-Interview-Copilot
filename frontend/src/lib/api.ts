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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init });
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
    throw new Error(detail);
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
