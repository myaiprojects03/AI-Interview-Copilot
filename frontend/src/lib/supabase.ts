import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
// Supabase's newer "publishable" key or the legacy "anon" key; either works.
const key =
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

/** Sign-in is on when the Supabase URL and publishable key are set in .env.local.
 * Without them the app runs as a single local dev user (the backend does the same). */
export const authEnabled = Boolean(url && key);

let client: SupabaseClient | null = null;

export function supabase(): SupabaseClient {
  if (!authEnabled) throw new Error("Supabase isn't configured (NEXT_PUBLIC_SUPABASE_URL).");
  if (!client) {
    client = createClient(url!, key!, {
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
    });
  }
  return client;
}

/** The current access token (refreshed automatically by supabase-js), or null. */
export async function accessToken(): Promise<string | null> {
  if (!authEnabled) return null;
  const { data } = await supabase().auth.getSession();
  return data.session?.access_token ?? null;
}
