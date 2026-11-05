export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type ProviderStatus = {
  llm: { provider: string; model: string | null; configured: boolean };
  stt: { provider: string; model: string | null; configured: boolean };
  database: { configured: boolean };
};

export async function getProviderStatus(signal?: AbortSignal): Promise<ProviderStatus> {
  const res = await fetch(`${API_URL}/health/providers`, { signal, cache: "no-store" });
  if (!res.ok) throw new Error(`Backend returned HTTP ${res.status}`);
  return res.json();
}
