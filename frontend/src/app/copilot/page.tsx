import type { Metadata } from "next";
import { brand } from "@/config/brand";
import { CopilotView } from "@/components/copilot/CopilotView";

export const metadata: Metadata = { title: `Live copilot · ${brand.name}` };

export default function CopilotPage() {
  return <CopilotView />;
}
