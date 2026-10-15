#!/usr/bin/env python3
"""Build demos/handy-manual-design.mp4 — soft illustration design film.

Uses generated illustrations in demos/design/illustrations/ plus the three
UI directions in specs/004-mobile-web-client/design/{graphite,copper,console}/.

  uv run --with pillow python demos/make_design_video.py
"""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
ILLUST = ROOT / "demos/design/illustrations"
DESIGN = ROOT / "specs/004-mobile-web-client/design"
OUT = ROOT / "demos/design"
FRAMES = OUT / "frames"
CLIPS = OUT / "clips"
VIDEO = ROOT / "demos/handy-manual-design.mp4"

W, H = 1920, 1080
FPS = 30
XFADE = 0.7

PAPER = (248, 243, 236)
INK = (42, 31, 23)
MUTED = (101, 86, 74)
COPPER = (161, 64, 11)
GRAPHITE = (17, 19, 24)
CONSOLE_TEAL = (15, 118, 110)
SOFT = (241, 232, 221)


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    paths = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Georgia Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Georgia.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


F_HERO = font(72, bold=True)
F_TITLE = font(48, bold=True)
F_SUB = font(28)
F_LABEL = font(22, bold=True)
F_TINY = font(18)
F_DISPLAY = font(56, bold=True)


def ease(u: float) -> float:
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


def load_cover(path: Path, size: tuple[int, int], *, zoom: float = 1.0, pan: tuple[float, float] = (0.5, 0.5)) -> Image.Image:
    """Cover-fit image with Ken Burns zoom/pan. pan is (x,y) in 0..1 for crop center."""
    img = Image.open(path).convert("RGB")
    tw, th = size
    scale = max(tw / img.width, th / img.height) * zoom
    nw, nh = max(1, int(img.width * scale)), max(1, int(img.height * scale))
    img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    cx = int(pan[0] * nw)
    cy = int(pan[1] * nh)
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
    # soft drifting blobs
    for i, (col, r) in enumerate([((232, 180, 140, 40), 420), ((180, 160, 140, 28), 360), ((120, 140, 150, 22), 300)]):
        cx = int(W * (0.2 + 0.55 * ((math.sin(t * math.pi * 2 + i) + 1) / 2)))
        cy = int(H * (0.25 + 0.4 * ((math.cos(t * math.pi * 2 + i * 0.7) + 1) / 2)))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    return img.filter(ImageFilter.GaussianBlur(2))


def rounded_shadow(screen: Image.Image, radius: int = 36, shadow: int = 28) -> Image.Image:
    """Phone/card with soft drop shadow."""
    sw, sh = screen.size
    pad = shadow + 8
    canvas = Image.new("RGBA", (sw + pad * 2, sh + pad * 2), (0, 0, 0, 0))
    # shadow
    shad = Image.new("RGBA", (sw, sh), (60, 35, 15, 0))
    mask = Image.new("L", (sw, sh), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, sw - 1, sh - 1], radius=radius, fill=180)
    shad.putalpha(mask)
    shad = shad.filter(ImageFilter.GaussianBlur(shadow // 2 + 4))
    canvas.paste(shad, (pad + 6, pad + 10), shad)
    # screen with rounded corners
    card = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    card.paste(screen.convert("RGBA"), (0, 0))
    rmask = Image.new("L", (sw, sh), 0)
    ImageDraw.Draw(rmask).rounded_rectangle([0, 0, sw - 1, sh - 1], radius=radius, fill=255)
    card.putalpha(rmask)
    canvas.paste(card, (pad, pad), card)
    return canvas


def fit_phone(path: Path, height: int = 820) -> Image.Image:
    img = Image.open(path).convert("RGB")
    # top-align crop to phone aspect ~9:19.5 then scale
    target_w = int(height * 375 / 812)
    # take top portion of tall mockup
    crop_h = int(img.width * 812 / 375)
    if img.height > crop_h:
        img = img.crop((0, 0, img.width, crop_h))
    img = ImageOps.fit(img, (target_w, height), method=Image.Resampling.LANCZOS, centering=(0.5, 0.0))
    return img


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


def text_block(
    base: Image.Image,
    *,
    eyebrow: str = "",
    title: str,
    body: str = "",
    xy: tuple[int, int] = (100, 120),
    max_w: int = 720,
    reveal: float = 1.0,
    ink: tuple[int, int, int] = INK,
) -> None:
    d = ImageDraw.Draw(base)
    r = ease(reveal)
    x, y = xy
    y += int((1 - r) * 24)
    a = int(255 * r)
    if eyebrow:
        d.text((x, y), eyebrow.upper(), font=F_TINY, fill=(*COPPER, a) if base.mode == "RGBA" else COPPER)
        y += 36
    for line in wrap(d, title, F_TITLE, max_w)[:3]:
        d.text((x, y), line, font=F_TITLE, fill=(*ink, a) if base.mode == "RGBA" else ink)
        y += 56
    y += 8
    if body:
        for line in wrap(d, body, F_SUB, max_w)[:4]:
            d.text((x, y), line, font=F_SUB, fill=(*MUTED, a) if base.mode == "RGBA" else MUTED)
            y += 36


def chapter_chip(base: Image.Image, label: str, color: tuple[int, int, int], xy: tuple[int, int], reveal: float) -> None:
    d = ImageDraw.Draw(base)
    r = ease(reveal)
    x, y = xy
    pad_x, pad_y = 18, 10
    tw = d.textlength(label, font=F_LABEL)
    box = [x, y, x + tw + pad_x * 2, y + 28 + pad_y]
    fill = (*color, int(220 * r))
    d.rounded_rectangle(box, radius=20, fill=fill)
    d.text((x + pad_x, y + pad_y), label, font=F_LABEL, fill=(255, 255, 255, int(255 * r)))


# --- Scene builders ---------------------------------------------------------

def scene_full_illust(
    illust: Path,
    *,
    eyebrow: str,
    title: str,
    body: str,
    progress: float,
    dark_text: bool = True,
) -> Image.Image:
    zoom = 1.04 + 0.06 * progress
    pan = (0.48 + 0.04 * progress, 0.48)
    bg = load_cover(illust, (W, H), zoom=zoom, pan=pan)
    bg = soft_vignette(bg, 0.4)
    img = bg.convert("RGBA")
    # soft left scrim for text
    scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scrim)
    for i in range(900):
        a = int(150 * (1 - i / 900) ** 1.2)
        col = (248, 243, 236, a) if dark_text else (20, 16, 12, a)
        sd.line([(i, 0), (i, H)], fill=col)
    img = Image.alpha_composite(img, scrim)
    reveal = min(1.0, progress / 0.2)
    text_block(
        img,
        eyebrow=eyebrow,
        title=title,
        body=body,
        xy=(96, 280),
        max_w=700,
        reveal=reveal,
        ink=INK if dark_text else (245, 242, 236),
    )
    # copper rule
    d = ImageDraw.Draw(img)
    d.rectangle([96, 240, 96 + int(80 * ease(reveal)), 244], fill=COPPER)
    return img.convert("RGB")


def scene_title(progress: float) -> Image.Image:
    bg = load_cover(ILLUST / "illust-title-hex.png", (W, H), zoom=1.05 + 0.05 * progress, pan=(0.5, 0.45))
    bg = soft_vignette(bg, 0.45)
    img = bg.convert("RGBA")
    # center soft card
    card_w, card_h = 820, 280
    cx, cy = W // 2, H // 2 + 40
    card = Image.new("RGBA", (card_w, card_h), (248, 243, 236, int(210 * ease(min(1, progress / 0.25)))))
    mask = Image.new("L", (card_w, card_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, card_w - 1, card_h - 1], radius=28, fill=255)
    card.putalpha(mask)
    # blur card edge soft
    img.paste(card, (cx - card_w // 2, cy - card_h // 2), card)
    d = ImageDraw.Draw(img)
    r = ease(min(1.0, (progress - 0.1) / 0.25))
    rise = int((1 - r) * 30)
    d.text((cx, cy - 40 + rise), "Designing Handy Manual", font=F_DISPLAY, fill=(*INK, int(255 * r)), anchor="mm")
    d.text((cx, cy + 30 + rise), "Three directions for a field answer you can trust", font=F_SUB, fill=(*MUTED, int(240 * r)), anchor="mm")
    d.rectangle([cx - 40, cy + 70, cx - 40 + int(80 * r), cy + 74], fill=COPPER)
    return img.convert("RGB")


def scene_phone_on_paper(
    phone_path: Path,
    *,
    eyebrow: str,
    title: str,
    body: str,
    progress: float,
    accent: tuple[int, int, int] = COPPER,
    phone_right: bool = True,
) -> Image.Image:
    img = paper_wash(progress).convert("RGBA")
    # faint brand watermark
    d = ImageDraw.Draw(img)
    d.text((W - 40, H - 36), "HANDY MANUAL", font=F_TINY, fill=(*COPPER, 120), anchor="rm")

    phone = fit_phone(phone_path, height=860)
    framed = rounded_shadow(phone, radius=40, shadow=32)
    # entrance
    ent = ease(min(1.0, progress / 0.22))
    slide = int((1 - ent) * (120 if phone_right else -120))
    px = (W - framed.width - 80 + slide) if phone_right else (40 + slide)
    py = (H - framed.height) // 2 + int((1 - ent) * 40)
    # slight float
    py += int(8 * math.sin(progress * math.pi * 2))
    phone_layer = framed.copy()
    # apply overall alpha via multiply on alpha channel
    a = phone_layer.split()[-1].point(lambda p: int(p * ent))
    phone_layer.putalpha(a)
    img.alpha_composite(phone_layer, (px, py))

    tx = 90 if phone_right else W - 760
    chip = eyebrow.split("·")[0].strip() if "·" in eyebrow else eyebrow[:22]
    chapter_chip(img, chip, accent, (tx, 210), ease(min(1, progress / 0.2)))
    text_block(
        img,
        title=title,
        body=body,
        xy=(tx, 270),
        max_w=680,
        reveal=ease(min(1.0, (progress - 0.08) / 0.2)),
    )
    return img.convert("RGB")


def scene_trio(progress: float) -> Image.Image:
    """Three phones: Graphite / Copper / Console."""
    img = paper_wash(progress * 0.5).convert("RGBA")
    d = ImageDraw.Draw(img)
    reveal = ease(min(1.0, progress / 0.2))
    d.text((W // 2, 72), "One product, three voices", font=F_TITLE, fill=(*INK, int(255 * reveal)), anchor="mm")
    d.text((W // 2, 130), "Same structure. Different feel.", font=F_SUB, fill=(*MUTED, int(240 * reveal)), anchor="mm")

    dirs = [
        ("graphite", "Graphite", GRAPHITE, "Quiet. Cobalt accent."),
        ("copper", "Copper", COPPER, "Warm paper. Soft cards."),
        ("console", "Console", CONSOLE_TEAL, "Dense. Teal hairlines."),
    ]
    phones = []
    for name, _, _, _ in dirs:
        phones.append(fit_phone(DESIGN / name / "02-answer-light.png", height=620))

    gap = 40
    total_w = sum(rounded_shadow(p, 28, 18).width for p in phones) + gap * 2
    x = (W - total_w) // 2
    base_y = 180
    for i, ((name, label, color, blurb), phone) in enumerate(zip(dirs, phones)):
        # staggered entrance
        local = ease(min(1.0, max(0.0, (progress - 0.1 - i * 0.08) / 0.22)))
        framed = rounded_shadow(phone, radius=28, shadow=18)
        a = framed.split()[-1].point(lambda p, loc=local: int(p * loc))
        framed.putalpha(a)
        rise = int((1 - local) * 50)
        img.alpha_composite(framed, (x, base_y + rise))
        cx = x + framed.width // 2
        d.text((cx, base_y + framed.height + 16), label, font=F_LABEL, fill=(*color, int(255 * local)), anchor="ma")
        d.text((cx, base_y + framed.height + 48), blurb, font=F_TINY, fill=(*MUTED, int(230 * local)), anchor="ma")
        x += framed.width + gap
    return img.convert("RGB")


def scene_overview_pan(direction: str, progress: float, title: str, body: str) -> Image.Image:
    """Soft pan across a direction overview strip."""
    path = DESIGN / direction / "overview.png"
    # overview is tall grid; pan vertically
    src = Image.open(path).convert("RGB")
    # scale to width W with margins
    margin = 120
    scale = (W - margin * 2) / src.width
    nw, nh = int(src.width * scale), int(src.height * scale)
    src = src.resize((nw, nh), Image.Resampling.LANCZOS)
    img = paper_wash(0.2).convert("RGBA")
    max_scroll = max(0, nh - (H - 200))
    y_off = int(max_scroll * ease(progress))
    view = src.crop((0, y_off, nw, y_off + min(nh, H - 160)))
    shadow = rounded_shadow(view, radius=20, shadow=20)
    img.alpha_composite(shadow, ((W - shadow.width) // 2, 100))
    # caption band bottom
    band = Image.new("RGBA", (W, 140), (248, 243, 236, 230))
    bd = ImageDraw.Draw(band)
    bd.rectangle([0, 0, W, 3], fill=COPPER)
    bd.text((80, 28), title, font=F_TITLE, fill=INK)
    for i, line in enumerate(wrap(bd, body, F_SUB, W - 160)[:2]):
        bd.text((80, 84 + i * 28), line, font=F_SUB, fill=MUTED)
    img.alpha_composite(band, (0, H - 140))
    return img.convert("RGB")


def scene_end(progress: float) -> Image.Image:
    bg = load_cover(ILLUST / "illust-soft-paper.png", (W, H), zoom=1.08, pan=(0.5, 0.5))
    img = soft_vignette(bg, 0.3).convert("RGBA")
    r = ease(min(1.0, progress / 0.3))
    d = ImageDraw.Draw(img)
    d.text((W // 2, H // 2 - 40), "Handy Manual", font=F_DISPLAY, fill=(*INK, int(255 * r)), anchor="mm")
    d.text((W // 2, H // 2 + 30), "Soft enough for a phone. Strict enough for the site.", font=F_SUB, fill=(*MUTED, int(240 * r)), anchor="mm")
    d.rectangle([W // 2 - 40, H // 2 + 80, W // 2 - 40 + int(80 * r), H // 2 + 84], fill=COPPER)
    return img.convert("RGB")


STORY: list[tuple] = [
    # kind, args..., duration, transition
    ("title", (), 3.0, "fade"),
    ("illust", ("illust-technician.png", "Context", "Designed for the bay floor", "One-handed, short answers, sources you can open.", True), 3.6, "smoothleft"),
    ("illust", ("illust-principles.png", "Principles", "Answer. Cite. Warn. Conflict.", "The structure stays the same in every direction.", True), 3.8, "dissolve"),
    ("illust", ("illust-three-directions.png", "Directions", "Graphite · Copper · Console", "Three voices. One shared system.", True), 3.6, "circleopen"),
    ("trio", (), 4.2, "slideup"),
    ("phone", ("graphite/02-answer-light.png", "Graphite · quiet", "Minimal monochrome", "Superscript citations. One cobalt accent. Close to a calm chat.", GRAPHITE, True), 4.0, "wipeleft"),
    ("phone", ("copper/02-answer-light.png", "Copper · brand", "Warm paper and soft cards", "Source-name pills. Rounded warnings. The strongest brand of the three.", COPPER, True), 4.2, "slideright"),
    ("phone", ("copper/04-source-light.png", "Copper · source", "Bottom sheet, not a maze", "Title, revision, passage, page image when we have it.", COPPER, False), 3.8, "fade"),
    ("phone", ("console/02-answer-light.png", "Console · dense", "A pro tool that fits more", "Teal [n] citations. Hairlines. Monospace values.", CONSOLE_TEAL, True), 4.0, "hlslice"),
    ("illust", ("illust-safety.png", "Safety", "Restricted stays closed", "Colour, icon, and a word — never the steps without cert-hv.", True), 3.6, "fadeblack"),
    ("phone", ("copper/03-restricted-light.png", "Copper · restricted", "Gates you can see", "Draft a work order when the procedure itself is withheld.", COPPER, True), 3.8, "dissolve"),
    ("illust", ("illust-source-sheet.png", "Trust", "Open the page", "Technicians believe answers they can check.", True), 3.4, "smoothright"),
    ("overview", ("copper", "Copper overview", "Light above, dark below — five screens, one voice."), 4.0, "fade"),
    ("end", (), 3.0, None),
]


def render_frame(kind: str, args: tuple, progress: float) -> Image.Image:
    if kind == "title":
        return scene_title(progress)
    if kind == "illust":
        name, eyebrow, title, body, dark = args
        return scene_full_illust(ILLUST / name, eyebrow=eyebrow, title=title, body=body, progress=progress, dark_text=dark)
    if kind == "trio":
        return scene_trio(progress)
    if kind == "phone":
        rel, eyebrow, title, body, accent, right = args
        return scene_phone_on_paper(DESIGN / rel, eyebrow=eyebrow, title=title, body=body, progress=progress, accent=accent, phone_right=right)
    if kind == "overview":
        direction, title, body = args
        return scene_overview_pan(direction, progress, title, body)
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
    parts = []
    prev = "[0:v]"
    cum = holds[0]
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
    missing = [p for p in ILLUST.glob("illust-*.png")]
    if len(missing) < 5:
        raise SystemExit(f"Need illustrations in {ILLUST}")
    for d in (FRAMES, CLIPS):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)

    clips: list[Path] = []
    holds: list[float] = []
    transitions: list[str | None] = []

    for i, (kind, args, dur, trans) in enumerate(STORY):
        n = max(1, int(round(dur * FPS)))
        frames = []
        for f in range(n):
            progress = f / max(1, n - 1)
            fr = render_frame(kind, args, progress)
            frames.append(fr)
        mid = frames[n // 2]
        mid.save(FRAMES / f"{i:02d}-{kind}.png", optimize=True)
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
