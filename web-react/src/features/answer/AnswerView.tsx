// Renders an AnswerResponse (specs/contracts/answer.md) for every status, Graphite layout: compact
// context chips, then the answer text, then warnings, conflicts and the restricted block, then
// sources. Warnings and restricted always carry colour, an icon and a word.

import { ChevronDown, CircleHelp, ClipboardList, Cog, EyeOff, History, Info, Languages, Lock, Megaphone, Scale, ScanText, TriangleAlert, Check } from "lucide-react";
import { useMemo, type ReactNode } from "react";
import { Suggestion, Suggestions } from "@/components/ai-elements/suggestion";
import { Button } from "@/components/ui/button";
import {
  ABSTAIN_WORDS, BULLETIN_STATUS_WORDS, citationOrder, groupSentences, groupWords, isDidYouMean, noticeTitle,
  passageIdFromViewerUrl, sentenceParts, sourceFlags, sourceHref, titleWithRevision, type SentenceBlock,
} from "@/lib/text";
import type { AnswerResponse, Clarification, ClarifyOption, Conflict, Notice, ResolvedAsset, WorkOrderSuggestion } from "@/lib/types";
import { Cite, CitationContext, Flags, Parts, useCitations } from "./Citations";
import { useOpenSourceGroup } from "./sourceGroup";

interface Props {
  resp: AnswerResponse;
  question: string;
  /** `answer-heading` on the latest settled answer only; earlier turns get their own IDs. */
  headingId: string;
  /** Clarify options act only on the latest turn; earlier ones are shown, disabled. */
  latest: boolean;
  onClarify: (option: ClarifyOption) => void;
  onDraft: (suggestion: WorkOrderSuggestion, answerId: string) => void;
}

/** Screen-reader heading for the answer, by status. */
function headingFor(resp: AnswerResponse): string {
  if (isDidYouMean(resp)) return "Did you mean another name?";
  return { answer: "Answer", restricted: "Certification required", abstain: "No answer from your sources", clarify: "Which machine?" }[resp.status];
}

/** One answer turn. "Draft a work order" shows only when the response carries a suggestion. */
export function AnswerView({ resp, question, headingId, latest, onClarify, onDraft }: Props) {
  const ctx = useMemo(() => ({ resp, order: citationOrder(resp) }), [resp]);
  const blocks = groupSentences(resp.sentences);
  const suggestion = resp.work_order_suggestion;
  const draft = suggestion ? () => onDraft(suggestion, resp.answer_id) : null;
  return (
    <CitationContext.Provider value={ctx}>
      <article aria-labelledby={headingId} className={`answer status-${resp.status}`}>
        <h2 className="sr-only" id={headingId} tabIndex={-1}>{headingFor(resp)}</h2>
        {resp.question_used && resp.question_used !== question && (
          <p className="answering mt-0 mb-2 text-[15px] text-ink-soft">Answering: <em>{resp.question_used}</em></p>
        )}
        <ContextRow resp={resp} />
        {resp.status === "abstain" && <AbstainCard reason={resp.abstain_reason ?? null} />}
        {resp.status === "clarify" && resp.clarification && <ClarifyCard clarification={resp.clarification} latest={latest} onClarify={onClarify} />}
        {blocks.length > 0 && <div className="sentences">{blocks.map((b, i) => <Block block={b} key={i} />)}</div>}
        {(resp.conflicts ?? []).map((c, i) => <ConflictBlock conflict={c} key={i} />)}
        {resp.status === "restricted" && resp.restricted && <RestrictedCard onDraft={draft} resp={resp} />}
        {draft && resp.status !== "restricted" && (
          <div className="actions my-3.5 flex">
            <Button onClick={draft} type="button" variant="secondary"><ClipboardList aria-hidden />Draft a work order</Button>
          </div>
        )}
        {ctx.order.length > 0 && <SourceList />}
        <p className="meta mt-3 mb-0 text-[14px] text-ink-soft">Answer {resp.answer_id} · {resp.dataset_version}</p>
      </article>
    </CitationContext.Provider>
  );
}

/** A context chip that expands in place (a native details element) to show its detail. */
function Chip({ className = "", icon, label, open = false, children }: { className?: string; icon: ReactNode; label: ReactNode; open?: boolean; children: ReactNode }) {
  return (
    <details className={`ctx ${className}`} open={open}>
      <summary className="ctx-chip">
        <span className="ctx-face">{icon}<span className="ctx-label min-w-0">{label}</span><ChevronDown aria-hidden className="icon ctx-chev" /></span>
      </summary>
      <div className="ctx-detail">{children}</div>
    </details>
  );
}

const BULLETIN_SHORT: Record<string, string> = { affected: "applies", in_campaign: "in campaign", not_affected: "doesn't apply", check_on_site: "check on site" };
const WARN_NOTICES = new Set(["superseded", "possibly_stale", "check_on_site"]);
const NOTICE_ICONS: Record<string, ReactNode> = {
  translated: <Languages aria-hidden className="icon" />,
  history: <History aria-hidden className="icon" />,
  unverified_value: <ScanText aria-hidden className="icon" />,
  not_visible: <EyeOff aria-hidden className="icon" />,
  no_answer: <Info aria-hidden className="icon" />,
  bulletin: <Megaphone aria-hidden className="icon" />,
};

/** Title without its first word, the manufacturer ("Halden SB-2025-009" is "SB-2025-009"); one-word titles stay. */
function shortTitle(title: string): string {
  const words = title.split(" ");
  return words.length > 1 ? words.slice(1).join(" ") : title;
}

/**
 * Chips for the machine, its bulletins and the notices. A bulletin notice is dropped when the
 * machine lists bulletins, which already have their own chips.
 */
function ContextRow({ resp }: { resp: AnswerResponse }) {
  const asset = resp.asset;
  const bulletins = asset?.bulletins ?? [];
  const notices = (resp.notices ?? []).filter((n) => !(n.kind === "bulletin" && bulletins.length));
  if (!asset && !notices.length) return null;
  return (
    <div aria-label="About this answer" className="context" role="group">
      {asset && <MachineChip asset={asset} />}
      {bulletins.map((b) => {
        const warn = b.status === "check_on_site";
        return (
          <Chip
            className={`ctx-bulletin bulletin-${b.status}${warn ? " ctx-warn" : b.status === "affected" ? " ctx-ok" : ""}`}
            icon={warn ? <TriangleAlert aria-hidden className="icon" /> : <Megaphone aria-hidden className="icon" />}
            key={b.doc_id}
            label={<><span className="sr-only">Bulletin </span>{shortTitle(b.title)} {BULLETIN_SHORT[b.status] ?? b.status}</>}
          >
            <p className="m-0 font-semibold text-ink">{b.title}</p>
            <p className="m-0">{BULLETIN_STATUS_WORDS[b.status] ?? b.status}{b.campaign_code ? ` · campaign ${b.campaign_code}` : ""}</p>
            {b.reason && <p className="m-0">{b.reason}<Cite ids={b.citations} /></p>}
            {!b.reason && <Cite ids={b.citations} />}
          </Chip>
        );
      })}
      {notices.map((n, i) => <NoticeChip key={i} notice={n} resp={resp} />)}
    </div>
  );
}

/** The resolved machine: asset ID and model, expanding to serial, site and firmware. */
function MachineChip({ asset }: { asset: ResolvedAsset }) {
  const rows: [string, string][] = [
    ["Model", asset.model],
    ["Serial", asset.serial],
    ["Site", `${asset.site_name} (${asset.site})`],
    ...(asset.firmware ? [["Firmware", asset.firmware] as [string, string]] : []),
  ];
  return (
    <Chip className="ctx-machine asset" icon={<Cog aria-hidden className="icon" />} label={<><span className="sr-only">Machine </span><span className="asset-id code">{asset.asset_id}</span> · {asset.model}</>}>
      <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-3.5 gap-y-0.5">
        {rows.map(([k, v]) => <div className="contents" key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
      </dl>
    </Chip>
  );
}

/** One notice; open from the start on an abstain, where it explains the missing answer. */
function NoticeChip({ notice, resp }: { notice: Notice; resp: AnswerResponse }) {
  const warn = WARN_NOTICES.has(notice.kind);
  const title = noticeTitle(notice.kind, resp);
  const kind = notice.kind === "not_visible" && title === noticeTitle("no_answer", resp) ? "no_answer" : notice.kind;
  return (
    <Chip
      className={`notice-chip notice-${notice.kind}${warn ? " ctx-warn" : ""}`}
      icon={warn ? <TriangleAlert aria-hidden className="icon" /> : NOTICE_ICONS[kind] ?? <Info aria-hidden className="icon" />}
      label={title}
      open={resp.status === "abstain"}
    >
      <p className="notice-text m-0">{notice.text}<Cite ids={notice.citations} /></p>
    </Chip>
  );
}

/** Names the restricted procedure and the groups the user lacks, never its steps; offers a draft when there is a suggestion. */
function RestrictedCard({ resp, onDraft }: { resp: AnswerResponse; onDraft: (() => void) | null }) {
  const r = resp.restricted!;
  return (
    <section aria-labelledby="restricted-title" className="card restricted">
      <h3 className="block-title" id="restricted-title"><Lock aria-hidden className="icon" />Restricted procedure</h3>
      <p className="mt-1">
        This work is done under <span className="code font-semibold">{r.procedure}</span>. Its steps aren't shown because you don't have:
      </p>
      <ul aria-label="What you're missing" className="missing-groups my-1.5 list-disc pl-5 font-semibold">
        {r.missing_groups.map((g) => (
          <li key={g}>
            {groupWords(g)}
            {groupWords(g) !== g && <span className="group-id code font-normal text-ink-soft"> ({g})</span>}
          </li>
        ))}
      </ul>
      <p className="restricted-cite m-0 text-[15px] text-ink-soft">Why this is restricted<Cite ids={r.citations} /></p>
      {onDraft ? (
        <div className="actions mt-3.5">
          <Button onClick={onDraft} type="button"><ClipboardList aria-hidden />Draft a work order</Button>
          <p className="hint mt-1.5 mb-0">A lead approves it, then a certified technician picks it up.</p>
        </div>
      ) : (
        <p className="hint">Call your team lead to arrange a certified technician.</p>
      )}
    </section>
  );
}

/** Why there is no answer, in plain words for the abstain reason. */
function AbstainCard({ reason }: { reason: string | null }) {
  return (
    <section aria-labelledby="abstain-title" className="card abstain">
      <h3 className="block-title" id="abstain-title"><Info aria-hidden className="icon" />No answer from your sources</h3>
      <p className="mt-1">{(reason && ABSTAIN_WORDS[reason]) ?? "No permitted source covers this."}</p>
      <p className="hint mb-0">This is not an error. Nothing was guessed. Check with your team lead or support.</p>
    </section>
  );
}

/** The clarify question and its options, which are disabled on earlier turns. */
function ClarifyCard({ clarification, latest, onClarify }: { clarification: Clarification; latest: boolean; onClarify: Props["onClarify"] }) {
  const retyped = clarification.options.every((o) => o.question);
  return (
    <section aria-labelledby={latest ? "clarify-title" : undefined} className="clarify my-1">
      <h3 className="block-title text-[17px]" id={latest ? "clarify-title" : undefined}><CircleHelp aria-hidden className="icon text-brand" />{clarification.question}</h3>
      <p className="hint">
        {retyped ? "That name isn't in the documents. Tap the right one to ask again:" : "The answer depends on the machine. Pick one:"}
      </p>
      <Suggestions className="options flex flex-wrap gap-2">
        {clarification.options.map((o) => (
          <Suggestion className="btn option w-auto bg-brand-soft" disabled={!latest} key={o.asset_id ?? o.question ?? o.label} onClick={onClarify} suggestion={o} variant="secondary">
            {o.label}
          </Suggestion>
        ))}
      </Suggestions>
    </section>
  );
}

/** A sentence's text followed by its citation control. */
function Body({ s }: { s: SentenceBlock["items"][number] }) {
  return <><span className="sentence-text"><Parts parts={sentenceParts(s.segments)} /></span><Cite ids={s.citations} /></>;
}

/** Steps as a numbered list (the answer's step numbers when given), a warning box, or a paragraph. */
function Block({ block }: { block: SentenceBlock }) {
  if (block.kind === "steps") {
    const first = block.items[0]?.step_number;
    const start = Number.isInteger(first) ? (first as number) : 1;
    return (
      <ol className="steps my-3 list-none p-0" start={start}>
        {block.items.map((s, i) => {
          const n = Number.isInteger(s.step_number) ? (s.step_number as number) : start + i;
          return (
            <li className="relative my-2 pl-8" key={i} value={n}>
              <span aria-hidden className="absolute top-0 left-0 font-bold text-brand tabular-nums">{n}.</span>
              <Body s={s} />
            </li>
          );
        })}
      </ol>
    );
  }
  const s = block.items[0];
  if (block.kind === "warning") {
    return (
      <div className="warning" role="note">
        <p className="block-title"><TriangleAlert aria-hidden className="icon" />Warning</p>
        <p className="m-0"><Body s={s} /></p>
      </div>
    );
  }
  return <p className="statement my-2.5"><Body s={s} /></p>;
}

/** Sources that disagree. Without a valid `preferred` side it is shown as not decided, as a warning. */
function ConflictBlock({ conflict: c }: { conflict: Conflict }) {
  const decided = Number.isInteger(c.preferred) && (c.preferred as number) >= 0 && (c.preferred as number) < c.sides.length;
  return (
    <section aria-label={`Sources disagree: ${c.topic}`} className="conflict mt-5">
      <h3 className="flex items-center gap-2 text-[15px] font-normal text-ink-soft">
        <Scale aria-hidden className="icon" /><span>Sources disagree: <strong className="text-ink">{c.topic}</strong></span>
      </h3>
      <ul className="sides m-0 mt-1.5 list-none p-0">
        {c.sides.map((side, i) => {
          const preferred = decided && i === c.preferred;
          return (
            <li className={`side border-t border-line py-2.5 last:border-b${preferred ? " preferred" : ""}`} key={i}>
              <p className={`tag m-0 ${preferred ? "text-ok-line" : "text-ink-soft"}`}>
                {preferred ? <><Check aria-hidden className="icon" />Applies to this machine</> : decided ? "Does not apply here" : "Undecided"}
              </p>
              <p className="mt-0.5 mb-0">{side.statement}<Cite ids={side.citations} /></p>
            </li>
          );
        })}
      </ul>
      {decided ? (
        <p className="conflict-reason text-[15px] text-ink-soft"><strong className="text-ink">Why: </strong>{c.reason}</p>
      ) : (
        <div className="conflict-undecided warning">
          <p className="block-title"><TriangleAlert aria-hidden className="icon" />Not decided</p>
          <p className="m-0">The sources could not settle which one applies. Check with your team lead before you go ahead.</p>
          {c.reason && <p className="conflict-reason mb-0">{c.reason}</p>}
        </div>
      )}
    </section>
  );
}

/** Every cited source in citation order; each opens the source sheet on its own, without a switcher. */
function SourceList() {
  const { resp, order } = useCitations();
  const openGroup = useOpenSourceGroup();
  return (
    <details className="sources mt-5" open>
      <summary className="flex min-h-tap items-center justify-between text-[15px] font-semibold text-ink-soft">
        <span>Sources ({order.length})</span>
        <ChevronDown aria-hidden className="icon ctx-chev" />
      </summary>
      <ol className="m-0 list-none p-0">
        {order.map((id, i) => {
          const c = resp.citations?.[id];
          if (!c) return <li className="border-t border-line py-2" key={id}>Source missing from the response</li>;
          const passageId = passageIdFromViewerUrl(c.viewer_url) ?? id;
          return (
            <li className="border-t border-line first:border-t-0" key={id}>
              <a
                className="source-link flex min-h-tap gap-2.5 py-2 text-ink no-underline"
                href={sourceHref(passageId)}
                onClick={() => openGroup([{ passageId, n: i + 1, title: c.title, locator: c.locator }])}
              >
                <span className="min-w-[1.2em] pt-0.5 text-[14px] font-bold text-brand tabular-nums">{i + 1}</span>
                <span className="flex min-w-0 flex-col">
                  <span className="source-title text-[16px]">{titleWithRevision(c.title, c.revision)}</span>
                  <span className="source-locator text-[14px] text-ink-soft">{c.locator}</span>
                  <Flags flags={sourceFlags(c)} />
                </span>
              </a>
            </li>
          );
        })}
      </ol>
    </details>
  );
}
