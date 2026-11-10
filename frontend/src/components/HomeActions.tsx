"use client";

import Link from "next/link";
import { useAuth } from "@/components/auth/AuthProvider";

const primary = "rounded-lg bg-primary px-5 py-2.5 font-medium text-primary-foreground hover:opacity-90";
const secondary =
  "rounded-lg border border-black/15 px-5 py-2.5 font-medium hover:bg-black/5 dark:border-white/15 dark:hover:bg-white/5";

export function HomeActions() {
  const { ready, session, enabled } = useAuth();
  if (!ready) return <div className="h-11" />;
  if (enabled && !session) {
    return (
      <div className="flex flex-wrap gap-3">
        <Link href="/login" className={primary}>
          Sign in
        </Link>
        <Link href="/pricing" className={secondary}>
          See plans
        </Link>
      </div>
    );
  }
  return (
    <div className="flex flex-wrap gap-3">
      <Link href="/dashboard" className={primary}>
        Go to dashboard
      </Link>
      <Link href="/copilot" className={secondary}>
        Open live copilot
      </Link>
    </div>
  );
}
