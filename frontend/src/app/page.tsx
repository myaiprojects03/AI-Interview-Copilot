import Image from "next/image";
import { brand } from "@/config/brand";
import { BackendStatus } from "@/components/BackendStatus";
import { HomeActions } from "@/components/HomeActions";

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
      <HomeActions />
      <BackendStatus />
    </main>
  );
}
