#!/usr/bin/env python3
"""Build demos/handy-manual-engineering.mp4 — engineering design film.

Same soft paper / copper editorial style as the UI design film, but the story
is the system: corpus → ingest → engine → API → client → work orders → eval.

  uv run --with pillow python demos/make_engineering_video.py
"""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
ILLUST = ROOT / "demos/engineering/illustrations"
DESIGN = ROOT / "specs/004-mobile-web-client/design"
OUT = ROOT / "demos/engineering"
FRAMES = OUT / "frames"
CLIPS = OUT / "clips"
VIDEO = ROOT / "demos/handy-manual-engineering.mp4"

W, H = 1920, 1080
FPS = 30
XFADE = 0.7

PAPER = (248, 243, 236)
INK = (42, 31, 23)
MUTED = (101, 86, 74)
COPPER = (161, 64, 11)
TEAL = (15, 118, 110)
GRAPHITE = (17, 19, 24)


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    for p in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


F_DISPLAY = font(56, bold=True)
F_TITLE = font(46, bold=True)
F_SUB = font(26)
F_LABEL = font(20, bold=True)
F_TINY = font(17)
F_CODE = font(18, bold=True)


def ease(u: float) -> float:
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


def wrap(draw: ImageDraw.ImageDraw, text: str, font_: ImageFont.ImageFont, max_w: int) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font_) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def load_cover(path: Path, size: tuple[int, int], *, zoom: float = 1.0, pan: tuple[float, float] = (0.5, 0.5)) -> Image.Image:
    img = Image.open(path).convert("RGB")
    tw, th = size
    scale = max(tw / img.width, th / img.height) * zoom
    nw, nh = max(1, int(img.width * scale)), max(1, int(img.height * scale))
    img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    cx, cy = int(pan[0] * nw), int(pan[1] * nh)
    left = max(0, min(nw - tw, cx - tw // 2))
    top = max(0, min(nh - th, cy - th // 2))
    return img.crop((left, top, left + tw, top + th))


def soft_vignette(img: Image.Image, strength: float = 0.35) -> Image.Image:
    base = img.convert("RGBA")
    vig = Image.new("L", base.size, 0)
    d = ImageDraw.Draw(vig)
    for i in range(40):
        a = int(255 * strength * (i / 40) ** 1.6)
        d.rectangle([i * 4, i * 3, W - i * 4, H - i * 3], outline=a)
    vig = vig.filter(ImageFilter.GaussianBlur(28))
    overlay = Image.new("RGBA", base.size, (30, 18, 8, 0))
    overlay.putalpha(vig)
    return Image.alpha_composite(base, overlay).convert("RGB")


def paper_wash(t: float = 0.0) -> Image.Image:
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img, "RGBA")
    for i, (col, r) in enumerate([((232, 180, 140, 38), 420), ((180, 160, 140, 26), 360), ((120, 140, 150, 20), 300)]):
        cx = int(W * (0.2 + 0.55 * ((math.sin(t * math.pi * 2 + i) + 1) / 2)))
        cy = int(H * (0.25 + 0.4 * ((math.cos(t * math.pi * 2 + i * 0.7) + 1) / 2)))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    return img.filter(ImageFilter.GaussianBlur(2))


def rounded_shadow(screen: Image.Image, radius: int = 28, shadow: int = 24) -> Image.Image:
    sw, sh = screen.size
    pad = shadow + 8
    canvas = Image.new("RGBA", (sw + pad * 2, sh + pad * 2), (0, 0, 0, 0))
    shad = Image.new("RGBA", (sw, sh), (60, 35, 15, 0))
    mask = Image.new("L", (sw, sh), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, sw - 1, sh - 1], radius=radius, fill=180)
    shad.putalpha(mask)
    shad = shad.filter(ImageFilter.GaussianBlur(shadow // 2 + 4))
    canvas.paste(shad, (pad + 6, pad + 10), shad)
    card = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    card.paste(screen.convert("RGBA"), (0, 0))
    rmask = Image.new("L", (sw, sh), 0)
    ImageDraw.Draw(rmask).rounded_rectangle([0, 0, sw - 1, sh - 1], radius=radius, fill=255)
    card.putalpha(rmask)
    canvas.paste(card, (pad, pad), card)
    return canvas


def fit_phone(path: Path, height: int = 780) -> Image.Image:
    img = Image.open(path).convert("RGB")
    target_w = int(height * 375 / 812)
    crop_h = int(img.width * 812 / 375)
    if img.height > crop_h:
        img = img.crop((0, 0, img.width, crop_h))
    return ImageOps.fit(img, (target_w, height), method=Image.Resampling.LANCZOS, centering=(0.5, 0.0))


def text_block(
    base: Image.Image,
    *,
    title: str,
    body: str = "",
    xy: tuple[int, int] = (100, 120),
    max_w: int = 720,
    reveal: float = 1.0,
) -> None:
    d = ImageDraw.Draw(base)
    r = ease(reveal)
    x, y = xy[0], xy[1] + int((1 - r) * 24)
    a = int(255 * r)
    for line in wrap(d, title, F_TITLE, max_w)[:3]:
        d.text((x, y), line, font=F_TITLE, fill=(*INK, a) if base.mode == "RGBA" else INK)
        y += 54
    y += 10
    for line in wrap(d, body, F_SUB, max_w)[:5]:
        d.text((x, y), line, font=F_SUB, fill=(*MUTED, a) if base.mode == "RGBA" else MUTED)
        y += 34


def chip(base: Image.Image, label: str, xy: tuple[int, int], reveal: float, color: tuple[int, int, int] = COPPER) -> None:
    d = ImageDraw.Draw(base)
    r = ease(reveal)
    x, y = xy
    tw = d.textlength(label, font=F_LABEL)
    d.rounded_rectangle([x, y, x + tw + 36, y + 38], radius=20, fill=(*color, int(220 * r)))
    d.text((x + 18, y + 9), label, font=F_LABEL, fill=(255, 255, 255, int(255 * r)))


def figure_card(
    base: Image.Image,
    *,
    code: str,
    title: str,
    body: str,
    box: tuple[int, int, int, int],
    reveal: float,
    accent: tuple[int, int, int] = COPPER,
) -> None:
    """Soft architecture figure card with feature code."""
    x0, y0, x1, y1 = box
    r = ease(reveal)
    rise = int((1 - r) * 28)
    card = Image.new("RGBA", (x1 - x0, y1 - y0), (255, 255, 255, int(230 * r)))
    mask = Image.new("L", card.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, card.width - 1, card.height - 1], radius=22, fill=255)
    card.putalpha(mask)
    # left accent bar
    cd = ImageDraw.Draw(card)
    cd.rounded_rectangle([0, 16, 6, card.height - 16], radius=3, fill=(*accent, int(255 * r)))
    cd.text((24, 22), code, font=F_CODE, fill=(*accent, int(255 * r)))
    cd.text((24, 52), title, font=F_LABEL, fill=(*INK, int(255 * r)))
    yy = 86
    for line in wrap(cd, body, F_TINY, card.width - 48)[:4]:
        cd.text((24, yy), line, font=F_TINY, fill=(*MUTED, int(240 * r)))
        yy += 24
    base.alpha_composite(card, (x0, y0 + rise))


# --- scenes -----------------------------------------------------------------

def scene_title(progress: float) -> Image.Image:
    bg = load_cover(ILLUST / "illust-title-hex.png", (W, H), zoom=1.05 + 0.05 * progress, pan=(0.5, 0.42))
    img = soft_vignette(bg, 0.45).convert("RGBA")
    card_w, card_h = 900, 300
    cx, cy = W // 2, H // 2 + 30
    r = ease(min(1.0, progress / 0.25))
    card = Image.new("RGBA", (card_w, card_h), (248, 243, 236, int(215 * r)))
    mask = Image.new("L", (card_w, card_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, card_w - 1, card_h - 1], radius=28, fill=255)
    card.putalpha(mask)
    img.paste(card, (cx - card_w // 2, cy - card_h // 2), card)
    d = ImageDraw.Draw(img)
    rise = int((1 - r) * 28)
    d.text((cx, cy - 50 + rise), "Engineering Handy Manual", font=F_DISPLAY, fill=(*INK, int(255 * r)), anchor="mm")
    d.text((cx, cy + 20 + rise), "A fixed pipeline from messy corpus to answers you can check", font=F_SUB, fill=(*MUTED, int(240 * r)), anchor="mm")
    d.rectangle([cx - 40, cy + 70, cx - 40 + int(80 * r), cy + 74], fill=COPPER)
    return img.convert("RGB")


def scene_illust(name: str, code: str, title: str, body: str, progress: float) -> Image.Image:
    zoom = 1.04 + 0.06 * progress
    bg = load_cover(ILLUST / name, (W, H), zoom=zoom, pan=(0.5, 0.48))
    img = soft_vignette(bg, 0.42).convert("RGBA")
    scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scrim)
    for i in range(920):
        a = int(155 * (1 - i / 920) ** 1.15)
        sd.line([(i, 0), (i, H)], fill=(248, 243, 236, a))
    img = Image.alpha_composite(img, scrim)
    reveal = min(1.0, progress / 0.2)
    chip(img, code, (96, 250), reveal)
    text_block(img, title=title, body=body, xy=(96, 310), max_w=720, reveal=reveal)
    d = ImageDraw.Draw(img)
    d.rectangle([96, 230, 96 + int(72 * ease(reveal)), 234], fill=COPPER)
    return img.convert("RGB")


def scene_stack_cards(progress: float) -> Image.Image:
    """Six feature cards as an engineering figure on paper."""
    img = paper_wash(progress).convert("RGBA")
    d = ImageDraw.Draw(img)
    rev = ease(min(1.0, progress / 0.18))
    d.text((W // 2, 64), "The system, in six pieces", font=F_TITLE, fill=(*INK, int(255 * rev)), anchor="mm")
    d.text((W // 2, 118), "Contracts first. One process. No silent shortcuts.", font=F_SUB, fill=(*MUTED, int(240 * rev)), anchor="mm")

    cards = [
        ("001", "Corpus ingest", "PDFs, wiki, cases → published dataset (ds_*)", COPPER),
        ("002", "Answer engine", "Fixed pipeline: resolve → retrieve → filter → answer", GRAPHITE),
        ("003", "Answer API", "Sessions, HTTP, static web, engine pool", TEAL),
        ("004", "Mobile client", "Phone UI: ask, cite, clarify, draft", COPPER),
        ("005", "Work orders", "Draft, approve, outbox to MaintPro / Servio", GRAPHITE),
        ("006", "Evaluation", "Golden questions scored over the real API", TEAL),
    ]
    # 2x3 grid
    cw, ch = 560, 200
    gap_x, gap_y = 36, 28
    total_w = cw * 2 + gap_x
    total_h = ch * 3 + gap_y * 2
    ox = (W - total_w) // 2
    oy = 160
    for i, (code, title, body, accent) in enumerate(cards):
        col, row = i % 2, i // 2
        x0 = ox + col * (cw + gap_x)
        y0 = oy + row * (ch + gap_y)
        local = ease(min(1.0, max(0.0, (progress - 0.08 - i * 0.05) / 0.2)))
        figure_card(img, code=code, title=title, body=body, box=(x0, y0, x0 + cw, y0 + ch), reveal=local, accent=accent)
    return img.convert("RGB")


def scene_pipeline_steps(progress: float) -> Image.Image:
    """Five engine steps as soft numbered figures."""
    img = paper_wash(progress * 0.4).convert("RGBA")
    d = ImageDraw.Draw(img)
    rev = ease(min(1.0, progress / 0.18))
    chip(img, "002 · engine", (96, 56), rev, GRAPHITE)
    d.text((96, 110), "A fixed pipeline — not an agent loop", font=F_TITLE, fill=(*INK, int(255 * rev)))
    d.text((96, 170), "Two to three fast-model calls. No tools. No open-ended planning.", font=F_SUB, fill=(*MUTED, int(240 * rev)))

    steps = [
        ("1", "Resolve", "Asset / model from the question"),
        ("2", "Retrieve", "Embedding search over serving"),
        ("3", "Filter", "ACL + restricted procedures"),
        ("4", "Generate", "Short answer with citations"),
        ("5", "Surface", "Conflicts, warn, abstain, clarify"),
    ]
    n = len(steps)
    card_w = 300
    gap = 24
    total = n * card_w + (n - 1) * gap
    x = (W - total) // 2
    y = 320
    for i, (num, title, body) in enumerate(steps):
        local = ease(min(1.0, max(0.0, (progress - 0.12 - i * 0.07) / 0.2)))
        rise = int((1 - local) * 36)
        card = Image.new("RGBA", (card_w, 280), (255, 255, 255, int(235 * local)))
        mask = Image.new("L", (card_w, 280), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, card_w - 1, 279], radius=22, fill=255)
        card.putalpha(mask)
        cd = ImageDraw.Draw(card)
        cd.ellipse([24, 28, 72, 76], fill=(*COPPER, int(255 * local)))
        cd.text((48, 52), num, font=F_LABEL, fill=(255, 255, 255, int(255 * local)), anchor="mm")
        cd.text((24, 100), title, font=F_LABEL, fill=(*INK, int(255 * local)))
        yy = 140
        for line in wrap(cd, body, F_TINY, card_w - 48)[:4]:
            cd.text((24, yy), line, font=F_TINY, fill=(*MUTED, int(240 * local)))
            yy += 26
        img.alpha_composite(card, (x, y + rise))
        if i < n - 1:
            # soft arrow
            ax = x + card_w + 4
            ay = y + 130
            ad = ImageDraw.Draw(img)
            ad.line([(ax, ay), (ax + gap - 8, ay)], fill=(*COPPER, int(180 * local)), width=3)
        x += card_w + gap
    return img.convert("RGB")


def scene_phone_callout(progress: float) -> Image.Image:
    img = paper_wash(progress).convert("RGBA")
    phone = fit_phone(DESIGN / "copper/02-answer-light.png", height=820)
    framed = rounded_shadow(phone, radius=36, shadow=28)
    ent = ease(min(1.0, progress / 0.22))
    a = framed.split()[-1].point(lambda p: int(p * ent))
    framed.putalpha(a)
    px = W - framed.width - 60 + int((1 - ent) * 100)
    py = (H - framed.height) // 2 + int(6 * math.sin(progress * math.pi * 2))
    img.alpha_composite(framed, (px, py))
    chip(img, "004 · client", (96, 220), ent)
    text_block(
        img,
        title="The phone is a thin client",
        body="Ask, read steps, open sources, clarify the machine, draft a work order. No local cache of answers — the API is the source of truth.",
        xy=(96, 280),
        max_w=700,
        reveal=ease(min(1.0, (progress - 0.08) / 0.2)),
    )
    return img.convert("RGB")


def scene_end(progress: float) -> Image.Image:
    bg = load_cover(ILLUST / "illust-soft-paper.png", (W, H), zoom=1.08, pan=(0.5, 0.5))
    img = soft_vignette(bg, 0.3).convert("RGBA")
    r = ease(min(1.0, progress / 0.3))
    d = ImageDraw.Draw(img)
    d.text((W // 2, H // 2 - 50), "Built to be checkable", font=F_DISPLAY, fill=(*INK, int(255 * r)), anchor="mm")
    d.text(
        (W // 2, H // 2 + 24),
        "Permissions at retrieve time. Conflicts on screen. Unverified values withheld.",
        font=F_SUB,
        fill=(*MUTED, int(240 * r)),
        anchor="mm",
    )
    d.rectangle([W // 2 - 40, H // 2 + 78, W // 2 - 40 + int(80 * r), H // 2 + 82], fill=COPPER)
    return img.convert("RGB")


STORY: list[tuple] = [
    ("title", (), 3.0, "fade"),
    ("illust", ("illust-technician.png", "Why", "Answers on site, from a messy export", "Manuals, wiki, cases, and mail — with real permission gaps."), 3.4, "smoothleft"),
    ("illust", ("eng-system-map.png", "001–006", "Six packages, one product", "Ingest, engine, API, client, work orders, evaluation."), 3.8, "dissolve"),
    ("stack", (), 5.0, "slideup"),
    ("illust", ("eng-corpus.png", "001 · ingest", "Publish a serving dataset", "Chunk, embed, ACL tables — then freeze a ds_* version."), 3.6, "wipeleft"),
    ("illust", ("eng-acl-gate.png", "Serving + ACL", "Filter before the model sees it", "Restricted procedures never reach an uncertified technician."), 3.8, "fadeblack"),
    ("illust", ("eng-pipeline.png", "002 · engine", "Resolve → retrieve → filter → answer", "Conflicts and abstentions are first-class outcomes."), 3.8, "circleopen"),
    ("pipeline", (), 5.2, "smoothright"),
    ("illust", ("eng-contracts.png", "Contracts", "Shared types, not shared shortcuts", "Identity, Ask, Answer, WorkOrder — engine and API agree."), 3.6, "diagtl"),
    ("illust", ("eng-api-phone.png", "003 · API", "One process on the edge", "Cookie session, engine pool, static client, no gateway."), 3.6, "fade"),
    ("phone", (), 4.0, "slideright"),
    ("illust", ("eng-workorder.png", "005 · work orders", "Draft → approve → CMMS", "Outbox to MaintPro or Servio after confirmation."), 3.6, "hlslice"),
    ("illust", ("eng-eval.png", "006 · eval", "Score the real stack", "Golden questions over HTTP — no model in the scorer."), 3.6, "dissolve"),
    ("end", (), 3.0, None),
]


def render(kind: str, args: tuple, progress: float) -> Image.Image:
    if kind == "title":
        return scene_title(progress)
    if kind == "illust":
        return scene_illust(*args, progress)
    if kind == "stack":
        return scene_stack_cards(progress)
    if kind == "pipeline":
        return scene_pipeline_steps(progress)
    if kind == "phone":
        return scene_phone_callout(progress)
    if kind == "end":
        return scene_end(progress)
    raise ValueError(kind)


def write_clip(path: Path, frames: list[Image.Image]) -> None:
    tmp = path.with_suffix(".frames")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    for i, fr in enumerate(frames):
        fr.save(tmp / f"{i:04d}.png")
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-framerate", str(FPS), "-i", str(tmp / "%04d.png"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "fast",
            str(path),
        ],
        check=True,
    )
    shutil.rmtree(tmp)


def stitch(clips: list[Path], holds: list[float], transitions: list[str | None]) -> None:
    inputs: list[str] = []
    for c in clips:
        inputs += ["-i", str(c)]
    parts, prev, cum = [], "[0:v]", holds[0]
    for i in range(1, len(clips)):
        td = XFADE
        offset = max(0.0, cum - td)
        trans = transitions[i - 1] or "fade"
        out = f"[v{i}]" if i < len(clips) - 1 else "[vout]"
        parts.append(f"{prev}[{i}:v]xfade=transition={trans}:duration={td:.3f}:offset={offset:.3f}{out}")
        prev = out
        cum += holds[i] - td
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            *inputs,
            "-filter_complex", ";".join(parts),
            "-map", "[vout]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium",
            "-movflags", "+faststart",
            str(VIDEO),
        ],
        check=True,
    )


def main() -> None:
    needed = [
        "eng-system-map.png", "eng-pipeline.png", "eng-corpus.png", "eng-acl-gate.png",
        "eng-contracts.png", "eng-api-phone.png", "eng-workorder.png", "eng-eval.png",
        "illust-title-hex.png", "illust-soft-paper.png", "illust-technician.png",
    ]
    for n in needed:
        if not (ILLUST / n).exists():
            raise SystemExit(f"Missing {ILLUST / n}")

    for d in (FRAMES, CLIPS):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)

    clips: list[Path] = []
    holds: list[float] = []
    transitions: list[str | None] = []

    for i, (kind, args, dur, trans) in enumerate(STORY):
        n = max(1, int(round(dur * FPS)))
        frames = [render(kind, args, f / max(1, n - 1)) for f in range(n)]
        frames[n // 2].save(FRAMES / f"{i:02d}-{kind}.png", optimize=True)
        clip = CLIPS / f"{i:02d}.mp4"
        write_clip(clip, frames)
        clips.append(clip)
        holds.append(dur)
        transitions.append(trans)
        print(f"  {i:02d} {kind:10} {dur:.1f}s → {trans or 'end'}")

    print("Stitching…")
    stitch(clips, holds, transitions)
    for d in (FRAMES, CLIPS):
        shutil.rmtree(d)
    total = sum(holds) - XFADE * (len(holds) - 1)
    print(f"\nWrote {VIDEO} (~{total:.0f}s)")


if __name__ == "__main__":
    main()
