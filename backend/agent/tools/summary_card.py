"""Generate a modern summary card image for the daily WhatsApp message."""

import logging
import math
import os
import uuid

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Card dimensions
CARD_W = 800
CARD_PAD = 40
CONTENT_W = CARD_W - (CARD_PAD * 2)

# Colors — modern dark theme
BG_COLOR = (15, 15, 30)
CARD_BG = (25, 28, 50)
CARD_BG_HIGHLIGHT = (38, 28, 55)
TEXT_PRIMARY = (240, 240, 250)
TEXT_SECONDARY = (150, 155, 180)
TEXT_ACCENT = (255, 255, 255)
DIVIDER = (50, 50, 80)

# Section accent colors
COLOR_CALENDAR = (99, 102, 241)
COLOR_REMINDER = (251, 191, 36)
COLOR_WEATHER = (52, 211, 153)
COLOR_ACTIVITY = (244, 114, 182)
COLOR_VERSE = (167, 139, 250)
COLOR_GLITCH = (129, 140, 248)

# Gradient
GRAD_START = (79, 70, 229)
GRAD_END = (236, 72, 153)

ICON_SIZE = 40


def _find_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Find the best available text font."""
    if bold:
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ]
    else:
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


# ═══════════════════════════════════════════════════════════════════
# Custom geometric icons — clean, minimal, professional
# ═══════════════════════════════════════════════════════════════════

def _icon_calendar(draw: ImageDraw.Draw, x: int, y: int, color: tuple):
    """Calendar grid — rounded body with top hooks and inner grid."""
    s = ICON_SIZE
    # Body
    draw.rounded_rectangle([x, y + 8, x + s, y + s], radius=6, fill=color)
    # Top bar (darker stripe)
    darker = tuple(max(0, c - 80) for c in color)
    draw.rectangle([x + 3, y + 8, x + s - 3, y + 16], fill=darker)
    # Hooks
    draw.rounded_rectangle([x + 10, y, x + 14, y + 14], radius=2, fill=color)
    draw.rounded_rectangle([x + s - 14, y, x + s - 10, y + 14], radius=2, fill=color)
    # Grid — 3x2 white squares
    white = (255, 255, 255)
    for row in range(2):
        for col in range(3):
            gx = x + 7 + col * 10
            gy = y + 20 + row * 9
            draw.rectangle([gx, gy, gx + 6, gy + 5], fill=white)


def _icon_bell(draw: ImageDraw.Draw, x: int, y: int, color: tuple):
    """Notification bell — clean silhouette with alert dot."""
    s = ICON_SIZE
    cx = x + s // 2
    # Bell dome (upper arc)
    draw.pieslice([cx - 14, y + 2, cx + 14, y + 30], start=180, end=0, fill=color)
    # Bell body (wider bottom)
    draw.polygon([
        (cx - 14, y + 16),
        (cx - 17, y + 30),
        (cx + 17, y + 30),
        (cx + 14, y + 16),
    ], fill=color)
    # Bell rim
    draw.rounded_rectangle([cx - 19, y + 28, cx + 19, y + 33], radius=2, fill=color)
    # Clapper
    draw.ellipse([cx - 4, y + 33, cx + 4, y + 39], fill=color)
    # Alert dot (red)
    draw.ellipse([cx + 10, y, cx + 20, y + 10], fill=(239, 68, 68))


def _icon_sun(draw: ImageDraw.Draw, x: int, y: int, color: tuple):
    """Sun — circle with radiating lines."""
    s = ICON_SIZE
    cx, cy = x + s // 2, y + s // 2
    # Rays
    lighter = tuple(min(255, c + 50) for c in color)
    for angle_deg in range(0, 360, 45):
        angle = math.radians(angle_deg)
        x1 = cx + int(12 * math.cos(angle))
        y1 = cy + int(12 * math.sin(angle))
        x2 = cx + int(18 * math.cos(angle))
        y2 = cy + int(18 * math.sin(angle))
        draw.line([(x1, y1), (x2, y2)], fill=lighter, width=3)
    # Core
    draw.ellipse([cx - 10, cy - 10, cx + 10, cy + 10], fill=color)
    # Inner highlight
    draw.ellipse([cx - 5, cy - 5, cx + 1, cy + 1], fill=(255, 255, 255, 80))


def _icon_bolt(draw: ImageDraw.Draw, x: int, y: int, color: tuple):
    """Lightning bolt — angular energy symbol."""
    s = ICON_SIZE
    cx = x + s // 2
    # Bold lightning bolt
    draw.polygon([
        (cx + 4, y + 1),
        (cx - 10, y + 18),
        (cx - 2, y + 18),
        (cx - 6, y + s - 1),
        (cx + 12, y + 16),
        (cx + 4, y + 16),
    ], fill=color)
    # Bright highlight line
    draw.line([(cx + 2, y + 5), (cx - 4, y + 18)], fill=(255, 255, 255), width=2)


def _icon_book(draw: ImageDraw.Draw, x: int, y: int, color: tuple):
    """Open book — two pages with spine."""
    s = ICON_SIZE
    cx = x + s // 2
    lighter = tuple(min(255, c + 50) for c in color)
    # Left page
    draw.polygon([
        (cx - 1, y + 4), (x + 1, y + 8),
        (x + 1, y + s - 4), (cx - 1, y + s - 1),
    ], fill=color)
    # Right page
    draw.polygon([
        (cx + 1, y + 4), (x + s - 1, y + 8),
        (x + s - 1, y + s - 4), (cx + 1, y + s - 1),
    ], fill=lighter)
    # Text lines on left page
    for i in range(3):
        ly = y + 14 + i * 7
        draw.line([(x + 6, ly), (cx - 5, ly)], fill=(255, 255, 255, 120), width=1)
    # Text lines on right page
    for i in range(3):
        ly = y + 14 + i * 7
        draw.line([(cx + 5, ly), (x + s - 6, ly)], fill=(255, 255, 255, 120), width=1)
    # Spine
    draw.line([(cx, y + 4), (cx, y + s - 1)], fill=(255, 255, 255), width=2)


# Map section name → icon draw function
_ICON_MAP = {
    "VERSICULO": _icon_book,
    "AGENDA": _icon_calendar,
    "RECORDATORIOS": _icon_bell,
    "CLIMA": _icon_sun,
    "ACTIVIDAD RECOMENDADA": _icon_bolt,
}


# ═══════════════════════════════════════════════════════════════════
# Utility functions
# ═══════════════════════════════════════════════════════════════════

def _lerp_color(c1: tuple, c2: tuple, t: float) -> tuple:
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def _draw_gradient_rect(draw: ImageDraw.Draw, xy: tuple, c_left: tuple, c_right: tuple):
    x0, y0, x1, y1 = xy
    width = x1 - x0
    for x in range(width):
        t = x / max(width - 1, 1)
        color = _lerp_color(c_left, c_right, t)
        draw.line([(x0 + x, y0), (x0 + x, y1)], fill=color)


def _draw_pill_badge(draw: ImageDraw.Draw, x: int, y: int, text: str,
                     font: ImageFont.FreeTypeFont, bg_color: tuple,
                     text_color: tuple = (255, 255, 255)) -> int:
    bbox = font.getbbox(text)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    pad_x, pad_y = 16, 8
    pill_w = text_w + pad_x * 2
    pill_h = text_h + pad_y * 2
    draw.rounded_rectangle((x, y, x + pill_w, y + pill_h),
                            radius=pill_h // 2, fill=bg_color)
    draw.text((x + pad_x, y + pad_y - 2), text, font=font, fill=text_color)
    return pill_w


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list:
    words = text.split()
    lines = []
    current_line = ""
    for word in words:
        test_line = f"{current_line} {word}".strip()
        bbox = font.getbbox(test_line)
        if bbox[2] - bbox[0] <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    return lines or [""]


# ═══════════════════════════════════════════════════════════════════
# Main card generator
# ═══════════════════════════════════════════════════════════════════

def generate_summary_card(
    date_str: str,
    events_text: str,
    reminders_text: str,
    weather_text: str,
    verse_ref: str,
    verse_text: str,
    uv_index: float = 0,
    uv_label: str = "",
    wind_avg: int = 0,
    wind_max: int = 0,
    wind_dir: str = "",
    activity_name: str = "",
    activity_emoji: str = "",
    activity_reason: str = "",
) -> str:
    """Generate a modern dark-theme summary card with geometric icons."""

    # Fonts
    font_title = _find_font(38, bold=True)
    font_brand = _find_font(14, bold=True)
    font_section_title = _find_font(18, bold=True)
    font_body = _find_font(17)
    font_detail = _find_font(15)
    font_pill = _find_font(14, bold=True)
    font_verse = _find_font(16)
    font_verse_ref = _find_font(14, bold=True)
    font_footer = _find_font(12)
    font_activity_name = _find_font(24, bold=True)

    TITLE_X = CARD_PAD + 54  # icon (40) + gap (14)

    # ═══ Build sections (ordered) ═══
    sections = []

    # 1. Verse — first
    if verse_text:
        verse_wrapped = _wrap_text(f'"{verse_text}"', font_verse, CONTENT_W - 80)
        verse_h = 60 + len(verse_wrapped) * 24 + 28
        sections.append({
            "name": "VERSICULO", "color": COLOR_VERSE,
            "type": "verse", "verse_lines": verse_wrapped,
            "verse_ref": verse_ref, "height": verse_h,
        })

    # 2. Calendar
    event_lines = [l.strip() for l in events_text.strip().split("\n") if l.strip()]
    cal_height = 56 + len(event_lines) * 28
    sections.append({
        "name": "AGENDA", "color": COLOR_CALENDAR,
        "type": "list", "lines": event_lines, "height": cal_height,
    })

    # 3. Reminders
    if reminders_text and "No tienes" not in reminders_text:
        reminder_lines = [l.strip() for l in reminders_text.strip().split("\n") if l.strip()]
        reminder_lines = [l for l in reminder_lines if not l.lower().startswith("recordatorios")]
        if reminder_lines:
            rem_height = 56 + len(reminder_lines) * 28
            sections.append({
                "name": "RECORDATORIOS", "color": COLOR_REMINDER,
                "type": "list", "lines": reminder_lines, "height": rem_height,
            })

    # 4. Weather
    if weather_text:
        weather_wrapped = _wrap_text(weather_text, font_body, CONTENT_W - 80)
        pills = []
        if uv_index:
            if uv_index <= 2:
                uv_color = (34, 197, 94)
            elif uv_index <= 5:
                uv_color = (251, 191, 36)
            elif uv_index <= 7:
                uv_color = (251, 146, 60)
            elif uv_index <= 10:
                uv_color = (239, 68, 68)
            else:
                uv_color = (168, 85, 247)
            pills.append((f"UV {uv_index} ({uv_label})", uv_color))

        if wind_avg:
            wind_text = f"Viento {wind_avg} km/h {wind_dir}"
            if wind_max > wind_avg + 10:
                wind_text += f" (raf. {wind_max})"
            w_color = (96, 165, 250) if wind_avg < 20 else (
                (251, 191, 36) if wind_avg < 35 else (239, 68, 68))
            pills.append((wind_text, w_color))

        uv_warning = "Usa protector solar!" if uv_index >= 6 else ""
        wthr_h = 56 + len(weather_wrapped) * 26 + (44 if pills else 0) + (26 if uv_warning else 0)
        sections.append({
            "name": "CLIMA", "color": COLOR_WEATHER,
            "type": "weather", "lines": weather_wrapped,
            "pills": pills, "warning": uv_warning, "height": wthr_h,
        })

    # 5. Activity
    if activity_name:
        reason_wrapped = _wrap_text(activity_reason, font_body, CONTENT_W - 80)
        act_h = 60 + 34 + len(reason_wrapped) * 26
        sections.append({
            "name": "ACTIVIDAD RECOMENDADA", "color": COLOR_ACTIVITY,
            "type": "activity", "activity_name": activity_name,
            "reason_lines": reason_wrapped, "height": act_h, "highlight": True,
        })

    # ═══ Calculate total height ═══
    header_h = 130
    sections_h = sum(s["height"] + 18 for s in sections)
    footer_h = 50
    total_h = header_h + sections_h + footer_h + CARD_PAD

    # ═══ Create image ═══
    img = Image.new("RGB", (CARD_W, total_h), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # ═══ Header gradient ═══
    _draw_gradient_rect(draw, (0, 0, CARD_W, header_h), GRAD_START, GRAD_END)

    # Scanlines
    for py in range(0, header_h, 3):
        draw.line([(0, py), (CARD_W, py)], fill=(0, 0, 0), width=1)

    # Brand + date
    draw.text((CARD_PAD, 28), "GLITCH", font=font_brand, fill=(255, 255, 255))
    draw.text((CARD_PAD, 56), date_str, font=font_title, fill=(255, 255, 255))

    # Decorative dots
    for i in range(5):
        dx = CARD_W - CARD_PAD - 15 - i * 20
        dot_c = _lerp_color(GRAD_END, (255, 255, 255), 0.4)
        draw.ellipse([dx, 35, dx + 8, 43], fill=dot_c)

    # ═══ Render sections ═══
    y = header_h + 18

    for sec in sections:
        sh = sec["height"]
        color = sec["color"]
        bg = CARD_BG_HIGHLIGHT if sec.get("highlight") else CARD_BG

        # Card background
        draw.rounded_rectangle(
            (CARD_PAD - 8, y, CARD_W - CARD_PAD + 8, y + sh),
            radius=16, fill=bg)

        # Left accent bar
        draw.rounded_rectangle(
            (CARD_PAD - 8, y + 10, CARD_PAD - 3, y + sh - 10),
            radius=3, fill=color)

        # Geometric icon
        icon_fn = _ICON_MAP.get(sec["name"])
        if icon_fn:
            icon_fn(draw, CARD_PAD + 8, y + 10, color)

        # Section title
        draw.text((TITLE_X, y + 16), sec["name"], font=font_section_title, fill=color)

        inner_y = y + 54

        # ─── Content rendering ───
        sec_type = sec["type"]

        if sec_type == "verse":
            for line in sec["verse_lines"]:
                draw.text((CARD_PAD + 24, inner_y), line,
                          font=font_verse, fill=TEXT_SECONDARY)
                inner_y += 24
            inner_y += 4
            draw.text((CARD_PAD + 24, inner_y),
                      f"— {sec['verse_ref']}", font=font_verse_ref, fill=color)

        elif sec_type == "list":
            for line in sec["lines"]:
                display = line.lstrip("-.* ").strip()
                if not display:
                    continue
                draw.text((CARD_PAD + 24, inner_y), display,
                          font=font_body, fill=TEXT_PRIMARY)
                inner_y += 28

        elif sec_type == "weather":
            for line in sec["lines"]:
                draw.text((CARD_PAD + 24, inner_y), line,
                          font=font_body, fill=TEXT_PRIMARY)
                inner_y += 26
            if sec["pills"]:
                inner_y += 8
                pill_x = CARD_PAD + 24
                for pill_text, pill_color in sec["pills"]:
                    pw = _draw_pill_badge(draw, pill_x, inner_y,
                                           pill_text, font_pill, pill_color)
                    pill_x += pw + 12
                inner_y += 36
            if sec["warning"]:
                draw.text((CARD_PAD + 24, inner_y), sec["warning"],
                          font=font_detail, fill=(251, 146, 60))

        elif sec_type == "activity":
            draw.text((CARD_PAD + 24, inner_y), sec["activity_name"],
                      font=font_activity_name, fill=TEXT_ACCENT)
            inner_y += 34
            for line in sec["reason_lines"]:
                draw.text((CARD_PAD + 24, inner_y), line,
                          font=font_body, fill=TEXT_SECONDARY)
                inner_y += 26

        y += sh + 18

    # ═══ Footer ═══
    draw.line([(CARD_PAD, y + 4), (CARD_W - CARD_PAD, y + 4)], fill=DIVIDER, width=1)
    draw.text((CARD_PAD, y + 14), "Powered by Glitch", font=font_footer, fill=COLOR_GLITCH)
    for i in range(3):
        dx = CARD_W - CARD_PAD - 10 - i * 14
        draw.ellipse([dx, y + 16, dx + 6, y + 22],
                      fill=_lerp_color(GRAD_START, GRAD_END, i / 2))

    # ═══ Save ═══
    filename = f"summary_{uuid.uuid4().hex[:8]}.png"
    filepath = os.path.join("/tmp", filename)
    img.save(filepath, "PNG", optimize=True)
    logger.info("Summary card generated: %s (%dx%d)", filename, CARD_W, total_h)
    return filename
