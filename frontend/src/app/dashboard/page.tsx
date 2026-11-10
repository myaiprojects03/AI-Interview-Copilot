import type { Metadata } from "next";
import { brand } from "@/config/brand";
import { DashboardView } from "@/components/dashboard/DashboardView";

export const metadata: Metadata = { title: `Dashboard · ${brand.name}` };

export default function DashboardPage() {
  return <DashboardView />;
}
