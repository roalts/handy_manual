import { TriangleAlert } from "lucide-react";
import { lazy, Suspense, useEffect, useState } from "react";
import { Flags, UnverifiedValue } from "@/features/answer/Citations";
import { LANGUAGE_NAMES, parseSourceText, sourceFlags } from "@/lib/text";
import type { SourceView as Source } from "@/lib/types";

const ZoomableImage = lazy(() => import("./ZoomableImage"));

export const DOC_TYPE_WORDS: Record<string, string> = {
  service_manual: "Service manual",
  bulletin: "Manufacturer bulletin",
  wiki: "Team wiki",
  case_export: "Support case",
  sop: "Controlled procedure",
  work_instruction: "Work instruction",
  email: "Email",
  chat: "Chat",
};

/**
 * A cited passage: its facts and warnings, the text (original and English side by side on wide
 * screens when machine-translated) and the page image when there is one.
 */
export function SourceView({ src, focus }: { src: Source; focus: "page" | null }) {
  const translated = Boolean(src.text_en) && Boolean(src.lang) && src.lang !== "en";
  const langName = LANGUAGE_NAMES[src.lang] ?? src.lang;
  const facts: [string, string][] = [
    ["Type", DOC_TYPE_WORDS[src.doc_type] ?? src.doc_type],
    ...(src.revision ? [["Revision", src.revision] as [string, string]] : []),
    ...(src.issue_date ? [["Issued", src.issue_date] as [string, string]] : []),
    ...(src.status && src.status !== "active" ? [["Status", src.status] as [string, string]] : []),
  ];

  return (
    <article aria-labelledby="source-title" className="source">
      <Flags flags={sourceFlags(src)} />
      <dl className="source-facts mt-2 mb-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5">
        {[["Section", src.locator] as [string, string], ...facts].map(([k, v]) => (
          <div className="contents" key={k}>
            <dt className="text-[14px] text-ink-soft">{k}</dt>
            <dd className={`m-0 text-[15px]${k === "Section" ? " source-locator" : ""}`}>{v}</dd>
          </div>
        ))}
      </dl>
      {(src.status === "superseded" || src.superseded_by) && (
        <div className="notice notice-superseded" role="note">
          <strong className="notice-title"><TriangleAlert aria-hidden className="icon" />Superseded revision</strong>
          <span className="notice-text">A newer revision replaces this document. Check the current revision before you rely on it.</span>
        </div>
      )}
      {src.possibly_stale && (
        <div className="notice notice-possibly_stale" role="note">
          <strong className="notice-title"><TriangleAlert aria-hidden className="icon" />Possibly out of date</strong>
          <span className="notice-text">This source may no longer be current.</span>
        </div>
      )}
      <div className="md:grid md:grid-cols-2 md:gap-3">
        {translated ? (
          <>
            <PassageText kind="original" label={`Original (${langName})`} src={src} text={src.text_original} />
            <PassageText kind="translation" label="English (machine-translated)" src={src} text={src.text_en ?? ""} />
          </>
        ) : (
          <PassageText kind="original" label={null} src={src} text={src.text_original} />
        )}
      </div>
      {src.page_image_url && <PageImage focus={focus} src={src} url={src.page_image_url} />}
    </article>
  );
}

/** Passage text with withheld values as placeholders, which link to the page image only when there is one. */
function PassageText({ label, text, src, kind }: { label: string | null; text: string; src: Source; kind: "original" | "translation" }) {
  return (
    <section aria-label={label ?? "Passage"} className={`passage passage-${kind} my-3.5`}>
      {label && <h3 className="text-[14px] font-semibold text-ink-soft">{label}</h3>}
      <div className="passage-text max-h-[70vh] overflow-auto rounded-[var(--radius)] bg-paper-soft px-3.5 py-3 text-[16px] whitespace-pre-wrap" lang={kind === "original" ? src.lang : "en"}>
        {parseSourceText(text).map((p, i) =>
          p.kind === "unverified"
            ? <UnverifiedValue key={i} page={p.page ?? src.page} passageId={src.page_image_url ? src.passage_id : null} />
            : <span key={i}>{p.text}</span>)}
      </div>
    </section>
  );
}

/** The page image, zoomable, with a full-size link; scrolled to when the route asks for the page. */
function PageImage({ src, url, focus }: { src: Source; url: string; focus: "page" | null }) {
  const [state, setState] = useState<"loading" | "loaded" | "failed">("loading");
  const label = src.page ? `${src.ocr ? "Scanned page" : "Page"} ${src.page}` : "Page image";

  useEffect(() => {
    if (focus === "page") document.getElementById("page-image")?.scrollIntoView({ block: "start" });
  }, [focus]);

  return (
    <section aria-label={label} className="page-image my-3.5" id="page-image">
      <h3 className="text-[15px]">{label}</h3>
      {state === "loading" && <p className="hint">Loading page image…</p>}
      {state === "failed" ? (
        <p className="hint">The page image couldn't be loaded. The text above is the cited passage.</p>
      ) : (
        <>
          <Suspense fallback={<p className="hint">Loading page image…</p>}>
            <ZoomableImage alt={`${label} of ${src.title}`} onError={() => setState("failed")} onLoad={() => setState("loaded")} src={url} />
          </Suspense>
          <p className="hint flex flex-wrap items-center justify-between gap-x-3">
            <span>Pinch or double-tap to zoom.</span>
            <a className="page-link inline-flex min-h-tap items-center font-semibold no-underline" href={url} rel="noopener" target="_blank">Open full size</a>
          </p>
        </>
      )}
    </section>
  );
}
