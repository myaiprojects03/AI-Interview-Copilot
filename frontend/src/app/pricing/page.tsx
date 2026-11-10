import type { Metadata } from "next";
import { brand } from "@/config/brand";
import { PricingView } from "@/components/billing/PricingView";

export const metadata: Metadata = { title: `Plans · ${brand.name}` };

export default function PricingPage() {
  return <PricingView />;
}
