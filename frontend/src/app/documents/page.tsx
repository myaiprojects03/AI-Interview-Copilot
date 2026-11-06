import type { Metadata } from "next";
import { brand } from "@/config/brand";
import { DocumentsView } from "@/components/documents/DocumentsView";

export const metadata: Metadata = { title: `CV & job descriptions · ${brand.name}` };

export default function DocumentsPage() {
  return <DocumentsView />;
}
