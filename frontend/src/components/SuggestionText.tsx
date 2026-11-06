import { Fragment, type ReactNode } from "react";

const preClass = "overflow-x-auto rounded-lg bg-black/5 p-3 font-mono text-base dark:bg-white/10";

/** Text to highlight, and the tooltip explaining why. */
export type Flag = { text: string; note: string };
type Flags = { re: RegExp; notes: Map<string, string> };

function buildFlags(flagged: Flag[]): Flags | null {
  const texts = [...new Set(flagged.map((f) => f.text).filter(Boolean))];
  if (texts.length === 0) return null;
  const alternatives = texts
    .sort((a, b) => b.length - a.length)
    .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join("|");
  // Whole words only, so a flagged "Go" doesn't light up "Google".
  return {
    re: new RegExp(`(?<![\\w-])(${alternatives})(?!\\w)`, "g"),
    notes: new Map(flagged.map((f) => [f.text, f.note])),
  };
}

/** Renders the small markdown subset the answer prompt asks for: bullets, **bold**, `code`
 * and fenced code blocks. Text is rendered as React nodes, never as raw HTML.
 * `flagged` text (figures or skills not on the CV) is highlighted so the candidate checks it. */
export function SuggestionText({ text, flagged = [] }: { text: string; flagged?: Flag[] }) {
  const flags = buildFlags(flagged);
  const inline = (s: string) => renderInline(s, flags);

  const blocks: ReactNode[] = [];
  let bullets: string[] = [];
  let code: string[] | null = null;

  const flushBullets = () => {
    if (bullets.length === 0) return;
    blocks.push(
      <ul key={`ul-${blocks.length}`} className="flex list-disc flex-col gap-2 pl-6 marker:text-primary">
        {bullets.map((b, i) => (
          <li key={i}>{inline(b)}</li>
        ))}
      </ul>,
    );
    bullets = [];
  };

  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    if (line.trim().startsWith("```")) {
      if (code) {
        blocks.push(
          <pre key={`pre-${blocks.length}`} className={preClass}>
            {code.join("\n")}
          </pre>,
        );
        code = null;
      } else {
        flushBullets();
        code = [];
      }
      continue;
    }
    if (code) {
      code.push(raw);
      continue;
    }
    const bullet = line.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)$/);
    if (bullet) {
      bullets.push(bullet[1]);
      continue;
    }
    flushBullets();
    if (line.trim()) blocks.push(<p key={`p-${blocks.length}`}>{inline(line.trim())}</p>);
  }
  if (code) {
    blocks.push(
      <pre key="pre-open" className={preClass}>
        {(code as string[]).join("\n")}
      </pre>,
    );
  }
  flushBullets();
  return <div className="flex flex-col gap-4">{blocks}</div>;
}

function renderInline(text: string, flags: Flags | null): ReactNode {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return <strong key={i}>{flag(part.slice(2, -2), flags)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      return (
        <code key={i} className="rounded bg-black/5 px-1 font-mono text-[0.9em] dark:bg-white/10">
          {part.slice(1, -1)}
        </code>
      );
    }
    return <Fragment key={i}>{flag(part, flags)}</Fragment>;
  });
}

function flag(text: string, flags: Flags | null): ReactNode {
  if (!flags) return text;
  return text.split(flags.re).map((piece, i) =>
    i % 2 === 1 ? (
      <mark
        key={i}
        title={flags.notes.get(piece) ?? "Not in your CV. Check this before you say it."}
        className="rounded bg-amber-400/30 px-0.5 text-inherit underline decoration-amber-500 decoration-dotted"
      >
        {piece}
      </mark>
    ) : (
      <Fragment key={i}>{piece}</Fragment>
    ),
  );
}
