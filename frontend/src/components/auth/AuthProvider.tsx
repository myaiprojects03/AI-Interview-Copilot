"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { Session } from "@supabase/supabase-js";
import { useRouter } from "next/navigation";
import { authEnabled, supabase } from "@/lib/supabase";

type AuthState = {
  /** false until the stored session has been read. */
  ready: boolean;
  session: Session | null;
  email: string | null;
  enabled: boolean;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthState>({
  ready: false,
  session: null,
  email: null,
  enabled: authEnabled,
  signOut: async () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [ready, setReady] = useState(!authEnabled);
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    if (!authEnabled) return;
    const client = supabase();
    client.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setReady(true);
    });
    const { data } = client.auth.onAuthStateChange((_event, next) => setSession(next));
    return () => data.subscription.unsubscribe();
  }, []);

  const value: AuthState = {
    ready,
    session,
    email: authEnabled ? (session?.user.email ?? null) : "dev@localhost",
    enabled: authEnabled,
    signOut: async () => {
      if (authEnabled) await supabase().auth.signOut();
      router.replace("/login");
    },
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  return useContext(AuthContext);
}

/** Renders children only for signed-in users; sends everyone else to /login. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { ready, session, enabled } = useAuth();
  const allowed = !enabled || Boolean(session);

  useEffect(() => {
    if (ready && !allowed) {
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.replace(`/login?next=${next}`);
    }
  }, [ready, allowed]);

  if (!ready || !allowed) {
    return <div className="flex flex-1 items-center justify-center p-10 text-sm text-muted">Loading…</div>;
  }
  return <>{children}</>;
}
