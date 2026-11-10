import type { Metadata } from "next";
import { brand } from "@/config/brand";
import { AdminView } from "@/components/admin/AdminView";

export const metadata: Metadata = { title: `Admin · ${brand.name}` };

export default function AdminPage() {
  return <AdminView />;
}
