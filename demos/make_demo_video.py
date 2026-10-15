#!/usr/bin/env python3
"""Build demos/handy-manual-demo.mp4 from React walkthrough screenshots on the real API.

Uses specs/004-mobile-web-client/screenshots-react-real/ (produced by
`node web-react/dev/screenshots_real.mjs` against `tests/api/serve_scratch.py` with
WEB_DIR=web-react/dist), so every answer on screen is a real engine answer.

  uv run --with pillow python demos/make_demo_video.py
"""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "specs/004-mobile-web-client/screenshots-react-real"
OUT_DIR = ROOT / "demos"
FRAMES = OUT_DIR / "frames"
CLIPS = OUT_DIR / "clips"
VIDEO = OUT_DIR / "handy-manual-demo.mp4"

W, H = 1080, 1920
FPS = 30

# Layout: reserved caption band so text never clips under the phone.
TOP_BAR = 96
CAPTION_BAND = 240
PHONE_PAD = 18
PHONE_W = 720
PHONE_H = H - TOP_BAR - CAPTION_BAND - 56  # ~1528 → plenty of caption room
PHONE_X = (W - PHONE_W) // 2
PHONE_Y = TOP_BAR + 28
CAPTION_TOP = PHONE_Y + PHONE_H + PHONE_PAD + 28

BG = (18, 22, 28)
FRAME = (36, 42, 50)
ACCENT = (232, 140, 72)
TEXT = (245, 242, 236)
MUTED = (170, 178, 186)
BAND = (14, 17, 22)

# (file | __title__/__end__, headline, sub, hold_seconds, transition_into_next)
# Transitions are ffmpeg xfade names; last slide ignores transition.
STORY = [
    ("__title__", "Field Service Copilot", "Real answers, recorded on the live API", 2.4, "circleopen"),
    ("01-sign-in.png", "Sign in", "Pick a test technician", 2.8, "slideleft"),
    ("02-ask-empty.png", "Ask on site", "Type or paste a question from the machine", 2.6, "fade"),
    ("03-answer-q04.png", "A short answer you can check", "Every sentence cites a source; the bulletin that applies is named", 4.6, "wipeup"),
    ("04-source-bulletin.png", "Check the source", "Tap a citation to open the passage", 3.4, "slideright"),
    ("06-source-scan-translated.png", "Old scans, translated", "A 1998 German manual, with its English translation", 4.0, "dissolve"),
    ("10-restricted.png", "Certification gates", "Restricted procedures never show the steps", 3.8, "fadeblack"),
    ("12-clarify.png", "Pick the machine", "Asks when more than one machine fits", 3.0, "slideup"),
    ("20-did-you-mean.png", "Close the typo gap", "Suggests the nearest model in the documents", 3.0, "diagtl"),
    ("15a-answer-bx12-gdansk-conflict.png", "Sources disagree", "Both sides shown, with which one applies and why", 4.6, "hlslice"),
    ("13-draft-form-needs-approval.png", "Draft a work order", "Prefilled from the answer, then edit", 4.0, "circleclose"),
    ("14b-draft-approver-view.png", "Lead approval", "Restricted work waits for the right person", 3.6, "wiperight"),
    ("14c-draft-approved-with-note.png", "Approved with a note", "The decision travels with the draft", 3.4, "fade"),
    ("15-draft-confirm-servio.png", "Confirm the handoff", "Names the maintenance system before sending", 3.0, "slideleft"),
    ("16-draft-submitted.png", "Submitted", "The draft goes to MaintPro or Servio", 3.0, "smoothleft"),
    ("__end__", "Handy Manual", "Field answers with sources you can trust", 2.8, None),
]

XFADE_DUR = 0.55


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


TITLE_FONT = font(62, bold=True)
SUB_FONT = font(30)
CAP_FONT = font(38, bold=True)
BODY_FONT = font(26)
BRAND_FONT = font(20, bold=True)


def draw_bg_flat(img: Image.Image) -> None:
    d = ImageDraw.Draw(img)
    for y in range(H):
        p = y / H
        c = (int(BG[0] + 10 * p), int(BG[1] + 8 * p), int(BG[2] + 14 * p), 255)
        d.line([(0, y), (W, y)], fill=c)


def ease_in_out(u: float) -> float:
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font_: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font_) <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def scale_screen(src: Image.Image) -> Image.Image:
    img = src.convert("RGB")
    if img.width != PHONE_W:
        ratio = PHONE_W / img.width
        img = img.resize((PHONE_W, max(1, int(img.height * ratio))), Image.Resampling.LANCZOS)
    return img


def crop_viewport(screen: Image.Image, scroll_y: float) -> Image.Image:
    max_y = max(0, screen.height - PHONE_H)
    y = int(round(max_y * scroll_y))
    y = max(0, min(max_y, y))
    if screen.height < PHONE_H:
        canvas = Image.new("RGB", (PHONE_W, PHONE_H), (248, 246, 242))
        canvas.paste(screen, (0, 0))
        return canvas
    return screen.crop((0, y, PHONE_W, y + PHONE_H))


def draw_phone_chrome(base: Image.Image, screen: Image.Image, entrance: float = 1.0) -> None:
    """entrance 0→1: phone slides up + fades in."""
    d = ImageDraw.Draw(base)
    rise = int((1 - ease_in_out(entrance)) * 80)
    alpha = int(255 * ease_in_out(entrance))
    x, y = PHONE_X, PHONE_Y + rise

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    pad = PHONE_PAD
    ld.rounded_rectangle(
        [x - pad, y - pad, x + PHONE_W + pad, y + PHONE_H + pad],
        radius=40,
        fill=(*FRAME, alpha),
        outline=(80, 90, 100, alpha),
        width=2,
    )
    # status pill
    ld.rounded_rectangle(
        [W // 2 - 64, y - 4, W // 2 + 64, y + 16],
        radius=10,
        fill=(12, 14, 18, alpha),
    )
    phone = Image.new("RGBA", (PHONE_W, PHONE_H))
    phone.paste(screen.convert("RGB"), (0, 0))
    phone.putalpha(alpha)
    layer.paste(phone, (x, y), phone)
    base.alpha_composite(layer)


def draw_caption_band(base: Image.Image, headline: str, line: str, reveal: float = 1.0) -> None:
    """Solid band with wrapped text; reveal 0→1 slides caption up."""
    band = Image.new("RGBA", (W, CAPTION_BAND + 40), (*BAND, 230))
    bd = ImageDraw.Draw(band)
    # copper rule
    bd.rectangle([0, 0, W, 3], fill=(*ACCENT, int(255 * ease_in_out(reveal))))

    r = ease_in_out(reveal)
    slide = int((1 - r) * 36)
    max_w = W - 96

    hl_lines = wrap_text(bd, headline, CAP_FONT, max_w)
    sub_lines = wrap_text(bd, line, BODY_FONT, max_w)

    y = 28 + slide
    for hl in hl_lines[:2]:
        bd.text((W // 2, y), hl, font=CAP_FONT, fill=(*TEXT, int(255 * r)), anchor="ma")
        y += 44
    y += 6
    for sub in sub_lines[:3]:
        bd.text((W // 2, y), sub, font=BODY_FONT, fill=(*MUTED, int(255 * r)), anchor="ma")
        y += 34

    # place band so its top sits at CAPTION_TOP - 20, bottom has margin
    dest_y = H - CAPTION_BAND - 24
    base.alpha_composite(band, (0, dest_y))


def draw_brand(base: Image.Image) -> None:
    d = ImageDraw.Draw(base)
    d.rectangle([0, 0, W, 5], fill=ACCENT)
    d.text((W // 2, 48), "HANDY MANUAL", font=BRAND_FONT, fill=ACCENT, anchor="mm")


def title_frame(headline: str, line: str, t: float) -> Image.Image:
    img = Image.new("RGBA", (W, H), (*BG, 255))
    draw_bg_flat(img)
    # glow
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    pulse = 0.85 + 0.15 * math.sin(t * math.pi * 2)
    cx, cy, r = W // 2, H // 2 - 40, int(280 * pulse)
    for i in range(10, 0, -1):
        gd.ellipse([cx - r * i / 5, cy - r * i / 5, cx + r * i / 5, cy + r * i / 5], fill=(*ACCENT, int(14 * i / 10)))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(40)))

    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 5], fill=ACCENT)
    appear = ease_in_out(min(1.0, t * 2.2))
    rise = int((1 - appear) * 40)
    d.text((W // 2, H // 2 - 50 + rise), headline, font=TITLE_FONT, fill=(*TEXT, int(255 * appear)), anchor="mm")
    d.text((W // 2, H // 2 + 36 + rise), line, font=SUB_FONT, fill=(*MUTED, int(220 * appear)), anchor="mm")
    bar_w = int(80 * appear)
    d.rectangle([W // 2 - bar_w // 2, H // 2 + 88, W // 2 + bar_w // 2, H // 2 + 92], fill=ACCENT)
    d.text((W // 2, H - 90), "Corvane Field Services · demo", font=BODY_FONT, fill=MUTED, anchor="mm")
    return img.convert("RGB")


def scene_frame(
    screen: Image.Image | None,
    headline: str,
    line: str,
    progress: float,
    *,
    is_title: bool = False,
) -> Image.Image:
    if is_title or screen is None:
        return title_frame(headline, line, progress)

    img = Image.new("RGBA", (W, H), (*BG, 255))
    draw_bg_flat(img)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx = int(W * (0.5 + 0.12 * math.sin(progress * math.pi)))
    cy = int(H * 0.32)
    for i in range(6, 0, -1):
        gd.ellipse([cx - 200 * i / 3, cy - 160 * i / 3, cx + 200 * i / 3, cy + 160 * i / 3], fill=(*ACCENT, 10))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(36)))

    # entrance first ~18% of clip, then scroll, caption reveals early
    entrance = min(1.0, progress / 0.18)
    caption_reveal = min(1.0, max(0.0, (progress - 0.06) / 0.16))

    # scroll: hold top briefly, ease through content, hold bottom
    max_scroll = max(0, screen.height - PHONE_H)
    if max_scroll > 40:
        # dedicate middle of the clip to scrolling
        u = ease_in_out((progress - 0.22) / 0.58) if progress > 0.22 else 0.0
        u = min(1.0, max(0.0, u))
        scroll = u
    else:
        # subtle Ken Burns zoom via slight vertical nudge + scale simulation (letterbox crop)
        scroll = 0.0

    view = crop_viewport(screen, scroll)
    if max_scroll <= 40:
        # mild zoom: scale up then center-crop
        z = 1.0 + 0.04 * ease_in_out(progress)
        zw, zh = int(PHONE_W * z), int(PHONE_H * z)
        zoomed = view.resize((zw, zh), Image.Resampling.LANCZOS)
        left = (zw - PHONE_W) // 2
        top = (zh - PHONE_H) // 2
        view = zoomed.crop((left, top, left + PHONE_W, top + PHONE_H))

    draw_brand(img)
    draw_phone_chrome(img, view, entrance=entrance)
    draw_caption_band(img, headline, line, reveal=caption_reveal)
    return img.convert("RGB")


def write_clip(path: Path, frames: list[Image.Image]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmpdir")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()
    for i, fr in enumerate(frames):
        fr.save(tmp / f"{i:04d}.png")
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-framerate", str(FPS),
            "-i", str(tmp / "%04d.png"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "fast",
            str(path),
        ],
        check=True,
    )
    shutil.rmtree(tmp)


def stitch_with_xfade(clips: list[Path], transitions: list[str | None], holds: list[float]) -> None:
    """Chain clips with xfade. Each transition eats XFADE_DUR from the join."""
    if len(clips) == 1:
        shutil.copy(clips[0], VIDEO)
        return

    # Build filter_complex
    inputs: list[str] = []
    for c in clips:
        inputs.extend(["-i", str(c)])

    # offset for xfade n is sum(dur[0..n]) - xfade_dur * (n)  ... actually
    # offset = cumulative duration of stream so far minus xfade duration
    filter_parts: list[str] = []
    # normalize labels
    prev = "[0:v]"
    cum = holds[0]
    for i in range(1, len(clips)):
        td = XFADE_DUR
        offset = max(0.0, cum - td)
        trans = transitions[i - 1] or "fade"
        out = f"[v{i}]" if i < len(clips) - 1 else "[vout]"
        filter_parts.append(
            f"{prev}[{i}:v]xfade=transition={trans}:duration={td:.3f}:offset={offset:.3f}{out}"
        )
        prev = out
        cum = cum + holds[i] - td

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        *inputs,
        "-filter_complex", ";".join(filter_parts),
        "-map", "[vout]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium",
        "-movflags", "+faststart",
        str(VIDEO),
    ]
    subprocess.run(cmd, check=True)


def main() -> None:
    if not SRC.is_dir():
        raise SystemExit(f"Missing screenshots at {SRC}. Run the React walkthrough first.")

    for d in (FRAMES, CLIPS):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)

    print(f"Layout: phone {PHONE_W}x{PHONE_H}, caption band from y≈{H - CAPTION_BAND - 24}")

    clip_paths: list[Path] = []
    holds: list[float] = []
    transitions: list[str | None] = []

    for i, (name, headline, line, dur, trans) in enumerate(STORY):
        n_frames = max(1, int(round(dur * FPS)))
        frames: list[Image.Image] = []
        is_title = name.startswith("__")
        screen = None if is_title else scale_screen(Image.open(SRC / name))
        if not is_title and not (SRC / name).exists():
            raise SystemExit(f"Missing {SRC / name}")

        for f in range(n_frames):
            progress = f / max(1, n_frames - 1)
            fr = scene_frame(screen, headline, line, progress, is_title=is_title)
            frames.append(fr)
            if f == n_frames // 2:
                preview = FRAMES / f"{i:02d}-{'title' if name == '__title__' else Path(name).stem if not is_title else name.strip('_')}.png"
                fr.save(preview, optimize=True)

        clip = CLIPS / f"{i:02d}.mp4"
        write_clip(clip, frames)
        clip_paths.append(clip)
        holds.append(dur)
        transitions.append(trans)
        kind = "title" if is_title else f"scroll≈{max(0, (screen.height if screen else 0) - PHONE_H)}px"
        print(f"  clip {i:02d}: {dur:.1f}s  {kind}  → {trans or 'end'}")

    print("Stitching with xfade…")
    stitch_with_xfade(clip_paths, transitions, holds)
    for d in (FRAMES, CLIPS):
        shutil.rmtree(d)
    # approximate total
    total = sum(holds) - XFADE_DUR * (len(holds) - 1)
    print(f"\nWrote {VIDEO} (~{total:.0f}s with transitions)")


if __name__ == "__main__":
    main()
