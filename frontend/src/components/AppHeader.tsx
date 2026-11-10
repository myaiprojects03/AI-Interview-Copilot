"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { brand } from "@/config/brand";
import { useAuth } from "@/components/auth/AuthProvider";

const NAV = [
  ["/dashboard", "Dashboard"],
  ["/copilot", "Live copilot"],
  ["/documents", "CV & jobs"],
  ["/pricing", "Plans"],
] as const;

/** Top bar shared by the signed-in pages. `children` go on the right (page actions). */
export function AppHeader({ children }: { children?: ReactNode }) {
  const pathname = usePathname();
  const { email, enabled, session, signOut } = useAuth();
  return (
    <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-black/10 px-4 py-3 dark:border-white/10 sm:px-6">
      <Link href="/dashboard" className="flex items-center gap-2 font-semibold">
        <Image src={brand.logo} alt="" width={28} height={28} />
        <span className="hidden lg:inline">{brand.name}</span>
      </Link>
      <nav className="flex flex-wrap items-center gap-1 text-sm">
        {NAV.map(([href, label]) => (
          <Link
            key={href}
            href={href}
            className={`rounded-md px-2.5 py-1 ${
              pathname === href ? "bg-primary/15 font-medium text-primary" : "text-muted hover:bg-black/5 dark:hover:bg-white/5"
            }`}
          >
            {label}
          </Link>
        ))}
      </nav>
      <div className="ml-auto flex flex-wrap items-center gap-2">
        {children}
        {(!enabled || session) && (
          <span className="flex items-center gap-2 text-xs text-muted">
            <span className="hidden max-w-48 truncate sm:inline" title={email ?? ""}>
              {email}
            </span>
            {enabled && (
              <button onClick={signOut} className="rounded-md px-2 py-1 hover:bg-black/5 dark:hover:bg-white/5">
                Sign out
              </button>
            )}
          </span>
        )}
      </div>
    </header>
  );
}
