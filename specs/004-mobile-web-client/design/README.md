# UI overhaul: three design directions (step 1, mockups only)

Three chat-style directions for the React client, rendered as real screens at 375 px in light
and dark against mock API data. Each folder has 10 screens and an `overview.png` (light row above
dark). The screens are:

1. `01-empty`: empty state.
2. `02-answer`: q04 (golden question: casing bolt torque on FRS-P-0031), with a bulletin, a
   warning and a conflict.
3. `03-restricted`: E-31 (compressor fault code) on TAC-C-0143 (Tacoma VRS-110 compressor) for
   u03 (technician without high-voltage certification).
4. `04-source`: the source panel for SB-2025-009 (Halden service bulletin).
5. `05-thread`: a two-turn thread. "Did you mean HCP-200?" (HCP-200: Halden pump model), then
   the follow-up "Oh, I meant HCP-200" with "Answering: …".

All three share the same structure, which applies the brief's rules:

- The answer text comes first.
- The machine, bulletins and notices are compact chips that expand in place.
- Warnings and restricted procedures always have colour, an icon and a word.
- Conflicts show both sides, with the preferred side marked "Applies to this machine" and the
  reason.
- Sources are compact and open the source panel as a bottom sheet.
- The mark is a hex nut with an H, in SVG.
- System fonts only.

| Direction | Feel | Citations |
|---|---|---|
| [Graphite](graphite/overview.png) | minimal monochrome, one cobalt accent | small superscript numbers, one per sentence |
| [Copper](copper/overview.png) | warm paper, copper brand colour, soft rounded surfaces | source-name pill per sentence ("SB-2025-009 +1") |
| [Console](console/overview.png) | dense pro tool, hairlines, monospace values | `[1]` `[2]`, one per source |

## Graphite

- **Palette:**
  - Light: white background, near-black text (`#111318`), grey secondary text (`#4a505c`),
    one cobalt accent (`#1d4ed8`).
  - Dark: `#0e0f12` background, `#ececf0` text, `#8db1ff` accent.
- **Type:** 17 px body at 1.55 line height, 27 px greeting, 22 px sheet title, 14–15 px labels.
  Codes are monospace.
- **Citations:** small superscript numbers in the accent colour, one group per sentence
  ("1,2"). Each group is a 44 × 44 px tap box that doesn't widen the line.
- **Warnings and restricted:** soft tinted blocks with no border. The title combines an icon
  and a word: "⚠ Warning" in rust, or "🔒 Restricted procedure" in red.
- **Conflicts:** plain rows between hairlines. The preferred side has a green "✓ Applies to this
  machine", the other side "Other source", and a "Why:" line follows.
- **Overall:** this is the quietest of the three, close to ChatGPT.

## Copper

- **Palette:**
  - Light: warm paper background (`#f8f3ec`), white answer card, brown-black text (`#2a1f17`),
    copper accent (`#a1400b`).
  - Dark: warm charcoal (`#191411`) with a light copper accent (`#f49a5a`).
- **Type:** 17 px body. Titles use the system's rounded face (`ui-rounded`, SF Pro Rounded on
  iPhone; other phones fall back to the system font). Greeting 27 px, sheet title 22 px.
- **Citations:** a soft pill naming the source at the end of each sentence ("SB-2025-009",
  "+1" when there are more). This is the Perplexity pattern.
- **Warnings and restricted:** rounded tinted cards with a larger icon and title.
- **Conflicts:** two rounded tiles, with the preferred tile tinted green and marked
  "✓ Applies to this machine".
- **Sources:** a two-column grid of tiles.
- **Overall:** this has the strongest brand of the three. The answer sits on one soft card with
  a shadow, not on stacked bordered boxes.

## Console

- **Palette:**
  - Light: cool grey (`#f4f6f8`) and white panels, slate text (`#0f172a`), teal accent
    (`#0f766e`).
  - Dark: near-black (`#0b0e12`) with a bright teal accent (`#2fd3c0`).
- **Type:** 16 px body at 1.45 line height. Section labels are 14 px monospace capitals
  ("SOURCES DISAGREE", "WARNING"), and codes and values are monospace. Greeting 22 px.
- **Citations:** one `[n]` per source in teal monospace. Each gets its own 44 px box with no
  overlap, which leaves a visible gap between neighbouring numbers.
- **Warnings and restricted:** a tinted row with a 3 px coloured left rule and a "⚠ WARNING" or
  "🔒 RESTRICTED PROCEDURE" label.
- **Conflicts:** compact rows between hairlines: "✓ APPLIES TO THIS MACHINE" in green above the
  preferred side, "OTHER SOURCE" above the other, then "Why:".
- **Overall:** this fits the most on one screen.

## Behaviour notes for the pick

- Graphite and Copper group a sentence's citations into one control. Its accessible name lists
  each source ("Sources 1: Halden SB-2025-009, p. 1, 1 Summary; 2: …"), and tapping it would open
  the panel on the first source with a switcher to the others. The client today has one control
  per source, so grouping is a behaviour change to confirm. Console keeps one control per source.
- `preferred: null` marks no side. It reads "Undecided" on each side and says "Check with a lead".
  It's built in the shared renderer, but q04 has a preferred side, so it isn't shown.
- Withheld values would read only "value unverified, see scanned page N". The renderer handles
  them, but none of these five screens has one.

## Checks

`node web/dev/mockups.mjs` renders every screen and checks each one. All 30 pass:

- no horizontal overflow at 375 px;
- every control is at least 44 × 44 px, measured on the control's own box (the visible pill
  or number sits inside it), and no two controls overlap;
- all text meets WCAG AA in both themes, placeholders included. The lowest ratios are 5.92:1
  for Graphite, 5.33:1 for Copper and 4.92:1 for Console;
- no text is under 14 px, and body text is 16 px or more;
- no console errors.

The data is mock API responses saved in `data/`, and `shared/data.js` is generated from them.
The mockups are static HTML and CSS (`shared/render.js`, `shared/base.css` and each direction's
`style.css`), so you can open `<direction>/index.html?screen=answer` in a browser.
