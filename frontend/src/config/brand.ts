/**
 * Branding lives in this one file. To rebrand the app, edit the values below:
 * name, tagline, logo and colours are read from here everywhere in the UI.
 */
export const brand = {
  name: "AI Interview Copilot",
  shortName: "Copilot",
  tagline: "Real-time answer suggestions grounded in your CV and the job description.",
  /** Path under /public, or a full URL. */
  logo: "/logo.svg",
  supportEmail: "support@example.com",
  colors: {
    primary: "#4f46e5",
    primaryForeground: "#ffffff",
    accent: "#14b8a6",
    light: { background: "#ffffff", foreground: "#0f172a", muted: "#64748b", surface: "#f8fafc" },
    dark: { background: "#0b1020", foreground: "#e2e8f0", muted: "#94a3b8", surface: "#131a2e" },
  },
} as const;

/** CSS custom properties generated from the brand colours (used by globals.css). */
export function brandCssVariables(): string {
  const c = brand.colors;
  return `
:root {
  --brand-primary: ${c.primary};
  --brand-primary-foreground: ${c.primaryForeground};
  --brand-accent: ${c.accent};
  --background: ${c.light.background};
  --foreground: ${c.light.foreground};
  --muted: ${c.light.muted};
  --surface: ${c.light.surface};
}
@media (prefers-color-scheme: dark) {
  :root {
    --background: ${c.dark.background};
    --foreground: ${c.dark.foreground};
    --muted: ${c.dark.muted};
    --surface: ${c.dark.surface};
  }
}`;
}
