import Image from "next/image";
import Link from "next/link";
import { brand } from "@/config/brand";
import { BackendStatus } from "@/components/BackendStatus";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col items-start justify-center gap-8 px-4 py-16 sm:px-8">
      <div className="flex items-center gap-3">
        <Image src={brand.logo} alt="" width={40} height={40} priority />
        <span className="text-xl font-semibold">{brand.name}</span>
      </div>
      <div className="flex flex-col gap-3">
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          Your live interview copilot
        </h1>
        <p className="text-lg text-muted">{brand.tagline}</p>
      </div>
      <div className="flex flex-wrap gap-3">
        <Link
          href="/documents"
          className="rounded-lg border border-black/15 px-5 py-2.5 font-medium hover:bg-black/5 dark:border-white/15 dark:hover:bg-white/5"
        >
          1. Add your CV &amp; job description
        </Link>
        <Link
          href="/copilot"
          className="rounded-lg bg-primary px-5 py-2.5 font-medium text-primary-foreground hover:opacity-90"
        >
          2. Open the live copilot
        </Link>
      </div>
      <BackendStatus />
    </main>
  );
}
