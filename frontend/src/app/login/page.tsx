import type { Metadata } from "next";
import { brand } from "@/config/brand";
import { LoginView } from "@/components/auth/LoginView";

export const metadata: Metadata = { title: `Sign in · ${brand.name}` };

export default function LoginPage() {
  return <LoginView />;
}
