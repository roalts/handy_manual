// Mockup renderer shared by the three design directions. Static, no build step, no network:
// data comes from ../shared/data.js (mock API responses captured by web/dev/mockups.mjs).
// Text goes in only as text nodes, as in the client. Each direction sets window.DIRECTION and
// its own style.css; ?screen=empty|answer|restricted|source|thread picks the screen.

(() => {
  const D = window.MOCK_DATA;
  const opt = window.DIRECTION;
  const screen = new URLSearchParams(location.search).get("screen") || "answer";

  const ICONS = {
    warning: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    lock: '<rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    chevron: '<path d="m6 9 6 6 6-6"/>',
    send: '<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>',
    pen: '<path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.4 2.6a1 1 0 0 1 3 3l-9 9a2 2 0 0 1-.85.5l-2.87.84a.5.5 0 0 1-.62-.62l.84-2.87a2 2 0 0 1 .5-.85z"/>',
    x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    doc: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M16 13H8"/><path d="M16 17H8"/>',
    scale: '<path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="M7 21h10"/><path d="M12 3v18"/><path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"/>',
    bulletin: '<path d="m3 11 18-5v12L3 14v-3z"/><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"/>',
    machine: '<rect x="3" y="7" width="18" height="11" rx="2"/><circle cx="9" cy="12.5" r="2.5"/><path d="M15 11h3M15 14h3M7 18v2M17 18v2"/>',
    translate: '<path d="m5 8 6 6"/><path d="m4 14 6-6 2-3"/><path d="M2 5h12"/><path d="M7 2h1"/><path d="m22 22-5-10-5 10"/><path d="M14 18h6"/>',
    help: '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
    clipboard: '<rect width="8" height="4" x="8" y="2" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="M9 12h6M9 16h4"/>',
    arrow: '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    zoom: '<path d="M15 3h6v6"/><path d="M9 21H3v-6"/><path d="m21 3-7 7"/><path d="m3 21 7-7"/>',
  };
  const MARK = '<path class="mark-nut" d="M16 2.2 28 9.1v13.8L16 29.8 4 22.9V9.1Z"/><path class="mark-h" d="M11.5 10.5v11M20.5 10.5v11M11.5 16h9"/>';

  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) el.append(kid);
    return el;
  }
  function icon(name, cls = "icon") {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("class", cls);
    svg.setAttribute("aria-hidden", "true");
    svg.innerHTML = ICONS[name];
    return svg;
  }
  function mark() {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 32 32");
    svg.setAttribute("class", "mark");
    svg.setAttribute("aria-hidden", "true");
    svg.innerHTML = MARK;
    return svg;
  }

  const DOC_TYPE = { bulletin: "Bulletin", service_manual: "Manual", case_export: "Case", wiki: "Wiki", work_order_export: "Work order" };
  function shortName(c) {
    const w = c.title.split(" ");
    if (c.doc_type === "case_export") return c.locator;
    if (c.doc_type === "bulletin") return w.slice(1).join(" ");
    if (c.doc_type === "service_manual") return `${w[1]} manual`;
    return w[w.length - 1];
  }
  const GROUP_WORDS = D.groups;

  function citationOrder(r) {
    const order = [];
    const add = (ids) => { for (const id of ids || []) if (!order.includes(id)) order.push(id); };
    for (const s of r.sentences || []) add(s.citations);
    for (const c of r.conflicts || []) for (const side of c.sides) add(side.citations);
    for (const n of r.notices || []) add(n.citations);
    for (const b of r.asset?.bulletins || []) add(b.citations);
    add(r.restricted?.citations);
    return order;
  }

  /** Citations for one sentence or side: grouped into one control, or one control each. */
  function cites(r, ids) {
    if (!ids?.length) return null;
    const order = citationOrder(r);
    const items = ids.map((id) => ({ n: order.indexOf(id) + 1, c: r.citations[id] }));
    const describe = ({ n, c }) => `${n}: ${c.title}, ${c.locator}`;
    if (opt.cite === "each") {
      return h("span", { class: "cites" }, items.map((it) =>
        h("a", { class: "cite", href: "#", "aria-label": `Source ${describe(it)}` }, h("span", { class: "cite-face" }, `[${it.n}]`))));
    }
    const label = items.length === 1 ? `Source ${describe(items[0])}` : `Sources ${items.map(describe).join("; ")}`;
    const face = opt.cite === "pill"
      ? [h("span", { class: "cite-name" }, shortName(items[0].c)), items.length > 1 ? h("span", { class: "cite-more" }, `+${items.length - 1}`) : null]
      : [items.map((it) => it.n).join(",")];
    return h("span", { class: "cites" }, h("a", { class: "cite", href: "#", "aria-label": label }, h("span", { class: "cite-face" }, face)));
  }

  function textOf(segments) {
    return segments.map((s) => s.kind === "unverified" ? `value unverified, see scanned page ${s.page}` : s.text).join("");
  }

  function context(r, { open = false } = {}) {
    const a = r.asset;
    const chips = [];
    if (a) {
      chips.push(h("details", { class: "ctx ctx-machine", open },
        h("summary", { class: "ctx-chip" }, h("span", { class: "ctx-face" }, icon("machine"),
          h("span", { class: "ctx-label" }, h("span", { class: "code" }, a.asset_id), ` · ${a.model}`), icon("chevron", "icon chev"))),
        h("dl", { class: "ctx-detail" },
          [["Model", a.model], ["Serial", a.serial], ["Firmware", a.firmware], ["Site", `${a.site_name} (${a.site})`]]
            .map(([k, v]) => h("div", {}, h("dt", {}, k), h("dd", {}, v))))));
      for (const b of a.bulletins || []) {
        chips.push(h("details", { class: "ctx ctx-bulletin" },
          h("summary", { class: "ctx-chip" }, h("span", { class: "ctx-face" }, icon("bulletin"),
            h("span", { class: "ctx-label" }, `${b.title.split(" ").slice(1).join(" ")} applies`), icon("chevron", "icon chev"))),
          h("p", { class: "ctx-detail" }, b.reason, cites(r, b.citations))));
      }
    }
    for (const n of r.notices || []) {
      if (n.kind === "bulletin" && a?.bulletins?.length) continue;
      const iconName = n.kind === "translated" ? "translate" : "doc";
      const title = { translated: "Machine translation", possibly_stale: "Possibly out of date", superseded: "Superseded source" }[n.kind] || "Note";
      chips.push(h("details", { class: `ctx ctx-notice ctx-${n.kind}` },
        h("summary", { class: "ctx-chip" }, h("span", { class: "ctx-face" }, icon(iconName), h("span", { class: "ctx-label" }, title), icon("chevron", "icon chev"))),
        h("p", { class: "ctx-detail" }, n.text, cites(r, n.citations))));
    }
    return chips.length ? h("div", { class: "context", role: "group", "aria-label": "About this answer" }, chips) : null;
  }

  function sentence(r, s) {
    if (s.kind === "warning") {
      return h("div", { class: "callout callout-warning", role: "note" },
        h("p", { class: "callout-title" }, icon("warning"), "Warning"),
        h("p", { class: "callout-text" }, textOf(s.segments), cites(r, s.citations)));
    }
    return h("p", { class: "stmt" }, textOf(s.segments), cites(r, s.citations));
  }

  function conflict(r, c) {
    return h("section", { class: "conflict", "aria-label": `Sources disagree: ${c.topic}` },
      h("p", { class: "conflict-title" }, icon("scale"), h("span", {}, "Sources disagree: ", h("strong", {}, c.topic))),
      h("ul", { class: "sides" }, c.sides.map((side, i) => {
        const preferred = c.preferred === i;
        return h("li", { class: `side${preferred ? " preferred" : ""}` },
          h("p", { class: "side-tag" }, preferred ? [icon("check"), "Applies to this machine"] : c.preferred === null ? "Undecided" : "Other source"),
          h("p", { class: "side-text" }, side.statement, cites(r, side.citations)));
      })),
      h("p", { class: "conflict-why" }, c.preferred === null ? "Neither side is confirmed for this machine. Check with a lead." : [h("strong", {}, "Why: "), c.reason]));
  }

  function restricted(r) {
    const x = r.restricted;
    return h("section", { class: "callout callout-restricted", role: "note" },
      h("p", { class: "callout-title" }, icon("lock"), "Restricted procedure"),
      h("p", { class: "callout-text" }, "The fix follows ", h("span", { class: "code" }, x.procedure), ". You need:"),
      h("ul", { class: "missing" }, x.missing_groups.map((g) => h("li", {}, GROUP_WORDS[g] || g, " ", h("span", { class: "code muted" }, `(${g})`)))),
      h("div", { class: "callout-actions" },
        h("button", { class: "btn btn-primary", type: "button" }, icon("clipboard"), "Draft a work order"),
        h("p", { class: "fine" }, "A lead approves it, then a certified technician picks it up.")));
  }

  function sources(r) {
    const order = citationOrder(r);
    const list = order.map((id, i) => {
      const c = r.citations[id];
      return h("li", {}, h("a", { class: "src", href: "#", "aria-label": `Source ${i + 1}: ${c.title}, ${c.locator}` },
        h("span", { class: "src-n" }, String(i + 1)),
        h("span", { class: "src-body" },
          h("span", { class: "src-title" }, c.title),
          h("span", { class: "src-meta" }, `${DOC_TYPE[c.doc_type] || "Source"} · ${c.locator}`))));
    });
    return h("details", { class: "sources", open: true },
      h("summary", { class: "sources-head" }, h("span", {}, `Sources (${order.length})`), icon("chevron", "icon chev")),
      h("ol", { class: "src-list" }, list));
  }

  function clarify(r) {
    return h("section", { class: "clarify" },
      h("p", { class: "clarify-q" }, icon("help"), r.clarification.question),
      h("div", { class: "options" }, r.clarification.options.map((o) => h("button", { class: "btn btn-option", type: "button" }, o.label))));
  }

  function turn(question, r, { contextOpen = false } = {}) {
    return h("section", { class: "turn" },
      h("div", { class: "q" }, h("p", { class: "q-text" }, h("span", { class: "visually-hidden" }, "You asked: "), question)),
      h("article", { class: "a", "aria-label": "Answer" },
        h("div", { class: "a-head" }, mark(), h("span", { class: "a-who" }, "Handy Manual")),
        r.question_used ? h("p", { class: "answering" }, "Answering: ", h("em", {}, r.question_used)) : null,
        r.clarification ? clarify(r) : null,
        context(r, { open: contextOpen }),
        h("div", { class: "a-body" }, (r.sentences || []).map((s) => sentence(r, s))),
        (r.conflicts || []).map((c) => conflict(r, c)),
        r.restricted ? restricted(r) : null,
        citationOrder(r).length ? sources(r) : null));
  }

  function header() {
    return h("header", { class: "top" },
      h("a", { class: "brand", href: "#", "aria-label": "Handy Manual, home" }, mark(), h("span", { class: "brand-name" }, "Handy Manual")),
      h("div", { class: "top-actions" },
        screen === "empty" ? null : h("button", { class: "icon-btn", type: "button", "aria-label": "New question" }, icon("pen")),
        h("button", { class: "avatar", type: "button", "aria-label": `${D.user.name}, account and sign out` }, h("span", { class: "avatar-face" }, D.user.initials))));
  }

  function composer({ followUp = false } = {}) {
    return h("footer", { class: "dock" },
      followUp ? h("div", { class: "followbar" }, h("span", { class: "followbar-text" }, "Follow-up to the answer above"),
        h("button", { class: "btn btn-quiet", type: "button" }, "New question")) : null,
      h("form", { class: "composer", onsubmit: "return false" },
        h("label", { class: "visually-hidden", for: "question" }, "Question"),
        h("textarea", { id: "question", rows: "1", placeholder: followUp ? "Ask a follow-up" : "Ask the Handy Manual" }),
        h("button", { class: "send", type: "submit", "aria-label": "Ask" }, icon("send"))),
      h("p", { class: "dock-hint" }, "Answers come only from the documents you can see."));
  }

  function empty() {
    return h("section", { class: "empty" },
      h("div", { class: "hero" }, mark(), h("h1", { class: "hero-title" }, `Hi ${D.user.first}, what are you working on?`),
        h("p", { class: "hero-sub" }, "Ask about a machine, a fault code or a part. Every answer shows its sources.")),
      h("ul", { class: "examples", "aria-label": "Example questions" }, D.examples.map((q) =>
        h("li", {}, h("button", { class: "example", type: "button" }, h("span", {}, q), icon("arrow"))))));
  }

  function sourceSheet() {
    const s = D.source;
    return h("div", { class: "sheet-layer" },
      h("div", { class: "scrim" }),
      h("section", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "sheet-title" },
        h("div", { class: "grabber", "aria-hidden": "true" }),
        h("div", { class: "sheet-head" },
          h("div", {}, h("p", { class: "sheet-kicker" }, `Source 1 · ${DOC_TYPE[s.doc_type]}`), h("h2", { id: "sheet-title", class: "sheet-title" }, s.title)),
          h("button", { class: "icon-btn", type: "button", "aria-label": "Close source" }, icon("x"))),
        h("dl", { class: "facts" }, [["Section", s.locator], ["Revision", s.revision], ["Issued", s.issue_date], ["Status", "Current"]].map(([k, v]) =>
          h("div", {}, h("dt", {}, k), h("dd", {}, v)))),
        h("div", { class: "passage" }, s.text_original.split("\n").map((line, i) => h("p", { class: i === 0 ? "passage-head" : "" }, line))),
        h("figure", { class: "page" },
          h("img", { src: "../data/page-1.png", alt: `Page ${s.page} of ${s.title}`, width: "600", height: "800" }),
          h("figcaption", {}, h("span", {}, `Page ${s.page} · pinch to zoom`),
            h("a", { class: "link", href: "#" }, icon("zoom"), "Full size")))));
  }

  const app = h("div", { class: `app screen-${screen}` });
  const main = h("main", { class: "thread", id: "main" });
  const q04 = "Casing bolt torque for FRS-P-0031 after a seal change";
  if (screen === "empty") main.append(empty());
  if (screen === "answer" || screen === "source") main.append(turn(q04, D.q04));
  if (screen === "restricted") main.append(turn("E-31 on TAC-C-0143, how do I reset it?", D.restricted, { contextOpen: true }));
  if (screen === "thread") {
    main.append(turn("What is the impeller clearance on an HCP-20?", D.clarify), turn("Oh, I meant HCP-200", D.followup, { contextOpen: true }));
  }
  const page = h("div", { class: "page-wrap" }, header(), main, composer({ followUp: screen !== "empty" }));
  app.append(page);
  if (screen === "source") {
    page.setAttribute("inert", "");
    app.append(sourceSheet());
  }
  document.body.append(app);
  document.title = `Handy Manual · ${opt.title} · ${screen}`;
})();
