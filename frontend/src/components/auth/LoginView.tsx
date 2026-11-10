"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useState } from "react";
import { brand } from "@/config/brand";
import { useAuth } from "@/components/auth/AuthProvider";
import { authEnabled, supabase } from "@/lib/supabase";

type Mode = "signin" | "signup" | "reset";

function nextUrl(): string {
  const next = new URLSearchParams(window.location.search).get("next");
  // Only same-site paths, never an external URL.
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/dashboard";
}

export function LoginView() {
  const { ready, session } = useAuth();
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!authEnabled || (ready && session)) window.location.replace(nextUrl());
  }, [ready, session]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    const auth = supabase().auth;
    try {
      if (mode === "signin") {
        const { error } = await auth.signInWithPassword({ email, password });
        if (error) throw error;
        window.location.replace(nextUrl());
      } else if (mode === "signup") {
        const { data, error } = await auth.signUp({
          email,
          password,
          options: { emailRedirectTo: `${window.location.origin}/login` },
        });
        if (error) throw error;
        if (data.session) window.location.replace(nextUrl());
        else setNotice("Check your inbox: we sent a link to confirm your email, then sign in.");
      } else {
        const { error } = await auth.resetPasswordForEmail(email, {
          redirectTo: `${window.location.origin}/login`,
        });
        if (error) throw error;
        setNotice("If that email has an account, a reset link is on its way.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const google = async () => {
    setError(null);
    const { error } = await supabase().auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${window.location.origin}/login?next=${encodeURIComponent(nextUrl())}` },
    });
    if (error) {
      setError(
        error.message.includes("not enabled")
          ? "Google sign-in isn't switched on yet. Use email for now."
          : error.message,
      );
    }
  };

  const title = { signin: "Sign in", signup: "Create your account", reset: "Reset your password" }[mode];

  return (
    <main className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center gap-6 px-4 py-12">
      <Link href="/" className="flex items-center gap-2 font-semibold">
        <Image src={brand.logo} alt="" width={32} height={32} />
        {brand.name}
      </Link>
      <h1 className="text-2xl font-semibold">{title}</h1>

      {mode !== "reset" && (
        <>
          <button
            onClick={google}
            className="flex items-center justify-center gap-2 rounded-lg border border-black/15 px-4 py-2 font-medium hover:bg-black/5 dark:border-white/15 dark:hover:bg-white/5"
          >
            <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden>
              <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.6 5.4 2.7 13.3l7.9 6.1C12.5 13.6 17.8 9.5 24 9.5z" />
              <path fill="#4285F4" d="M46.1 24.6c0-1.6-.1-3.1-.4-4.6H24v9h12.4c-.5 2.9-2.2 5.3-4.6 6.9l7.4 5.7c4.3-4 6.9-9.9 6.9-17z" />
              <path fill="#FBBC05" d="M10.6 28.7c-.5-1.4-.8-3-.8-4.7s.3-3.2.8-4.7l-7.9-6.1C1 16.5 0 20.1 0 24s1 7.5 2.7 10.8l7.9-6.1z" />
              <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.4-5.7c-2.1 1.4-4.8 2.3-8.5 2.3-6.2 0-11.5-4.2-13.4-9.9l-7.9 6.1C6.6 42.6 14.6 48 24 48z" />
            </svg>
            Continue with Google
          </button>
          <div className="flex items-center gap-3 text-xs text-muted">
            <span className="h-px flex-1 bg-black/10 dark:bg-white/10" />
            or with email
            <span className="h-px flex-1 bg-black/10 dark:bg-white/10" />
          </div>
        </>
      )}

      <form onSubmit={submit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-sm">
          Email
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="rounded-lg border border-black/15 bg-background px-3 py-2 dark:border-white/15"
          />
        </label>
        {mode !== "reset" && (
          <label className="flex flex-col gap-1 text-sm">
            Password
            <input
              type="password"
              required
              minLength={8}
              autoComplete={mode === "signup" ? "new-password" : "current-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="rounded-lg border border-black/15 bg-background px-3 py-2 dark:border-white/15"
            />
          </label>
        )}
        {error && (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        )}
        {notice && <p className="text-sm text-accent">{notice}</p>}
        <button
          type="submit"
          disabled={busy}
          className="rounded-lg bg-primary px-4 py-2 font-medium text-primary-foreground hover:opacity-90 disabled:opacity-60"
        >
          {busy ? "Please wait…" : { signin: "Sign in", signup: "Create account", reset: "Send reset link" }[mode]}
        </button>
      </form>

      <div className="flex flex-col gap-1 text-sm text-muted">
        {mode === "signin" && (
          <>
            <button className="text-left hover:underline" onClick={() => setMode("signup")}>
              New here? <span className="text-primary">Create an account</span>
            </button>
            <button className="text-left hover:underline" onClick={() => setMode("reset")}>
              Forgot your password?
            </button>
          </>
        )}
        {mode !== "signin" && (
          <button className="text-left hover:underline" onClick={() => setMode("signin")}>
            Already have an account? <span className="text-primary">Sign in</span>
          </button>
        )}
      </div>
    </main>
  );
}
