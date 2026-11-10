import type { Metadata } from "next";
import { brand } from "@/config/brand";
import { HistoryView } from "@/components/dashboard/HistoryView";

export const metadata: Metadata = { title: `Interview · ${brand.name}` };

export default function HistoryPage() {
  return <HistoryView />;
}
