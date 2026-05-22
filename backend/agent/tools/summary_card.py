"""Generate a modern summary card image for the daily WhatsApp message."""

import logging
import os
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Card dimensions
CARD_W = 800
CARD_PAD = 40
CONTENT_W = CARD_W - (CARD_PAD * 2)

# Colors — modern dark theme
BG_COLOR = (18, 18, 32)          # Deep navy
HEADER_BG = (30, 30, 55)         # Slightly lighter navy
CARD_BG = (28, 28, 48)           # Section card background
TEXT_PRIMARY = (240, 240, 250)    # Almost white
TEXT_SECONDARY = (160, 165, 190)  # Muted lavender
TEXT_ACCENT = (255, 255, 255)     # Pure white for emphasis
DIVIDER = (50, 50, 80)           # Subtle divider

# Section accent colors
COLOR_CALENDAR = (99, 102, 241)   # Indigo
COLOR_REMINDER = (245, 158, 11)   # Amber
COLOR_WEATHER = (34, 197, 94)     # Emerald
COLOR_VERSE = (168, 85, 247)      # Purple


def _find_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Find the best available font."""
    if bold:
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]
    else:
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]

    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue

    logger.warning("No TrueType font found, using default")
    return ImageFont.load_default()


def _draw_rounded_rect(draw: ImageDraw.Draw, xy: tuple, radius: int, fill: tuple):
    """Draw a rounded rectangle."""
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle(xy, radius=radius, fill=fill)


def _draw_accent_dot(draw: ImageDraw.Draw, x: int, y: int, color: tuple, size: int = 12):
    """Draw a colored accent dot."""
    draw.ellipse([x, y, x + size, y + size], fill=color)


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Wrap text to fit within max_width."""
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


def generate_summary_card(
    date_str: str,
    events_text: str,
    reminders_text: str,
    weather_text: str,
    verse_ref: str,
    verse_text: str,
) -> str:
    """Generate a modern dark-theme summary card.

    Returns the filename (saved in /tmp).
    """
    # Fonts
    font_title = _find_font(36, bold=True)
    font_date = _find_font(20)
    font_section_title = _find_font(18, bold=True)
    font_body = _find_font(17)
    font_verse = _find_font(16)
    font_verse_ref = _find_font(14, bold=True)
    font_brand = _find_font(13)

    # Pre-calculate content heights to size the card
    sections = []

    # Calendar section
    event_lines = [l.strip() for l in events_text.strip().split("\n") if l.strip()]
    cal_height = 50 + len(event_lines) * 28
    sections.append(("AGENDA", COLOR_CALENDAR, event_lines, cal_height))

    # Reminders section (only if there are reminders)
    if reminders_text and "No tienes" not in reminders_text:
        reminder_lines = [l.strip() for l in reminders_text.strip().split("\n") if l.strip()]
        # Skip the header line "Recordatorios pendientes:"
        reminder_lines = [l for l in reminder_lines if not l.lower().startswith("recordatorios")]
        if reminder_lines:
            rem_height = 50 + len(reminder_lines) * 28
            sections.append(("RECORDATORIOS", COLOR_REMINDER, reminder_lines, rem_height))

    # Weather section
    if weather_text:
        weather_wrapped = _wrap_text(weather_text, font_body, CONTENT_W - 60)
        wthr_height = 50 + len(weather_wrapped) * 26
        sections.append(("CLIMA", COLOR_WEATHER, weather_wrapped, wthr_height))

    # Verse section
    if verse_text:
        verse_wrapped = _wrap_text(f'"{verse_text}"', font_verse, CONTENT_W - 60)
        verse_height = 60 + len(verse_wrapped) * 24 + 24
        sections.append(("VERSICULO", COLOR_VERSE, verse_wrapped, verse_height))

    # Calculate total height
    header_h = 120
    sections_h = sum(s[3] + 16 for s in sections)  # 16px gap between sections
    footer_h = 50
    total_h = header_h + sections_h + footer_h + CARD_PAD

    # Create image
    img = Image.new("RGB", (CARD_W, total_h), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # --- Header ---
    _draw_rounded_rect(draw, (0, 0, CARD_W, header_h), radius=0, fill=HEADER_BG)

    # Decorative gradient line at top
    for i in range(4):
        r = int(99 + (168 - 99) * i / 3)
        g = int(102 + (85 - 102) * i / 3)
        b = int(241 + (247 - 241) * i / 3)
        segment_w = CARD_W // 4
        draw.rectangle([i * segment_w, 0, (i + 1) * segment_w, 4], fill=(r, g, b))

    draw.text((CARD_PAD, 28), "GLITCH", font=font_section_title, fill=TEXT_SECONDARY)
    draw.text((CARD_PAD, 55), date_str, font=font_title, fill=TEXT_PRIMARY)

    # --- Sections ---
    y = header_h + 16

    for section_name, color, lines, section_h in sections:
        # Section card background
        _draw_rounded_rect(
            draw,
            (CARD_PAD - 8, y, CARD_W - CARD_PAD + 8, y + section_h),
            radius=16,
            fill=CARD_BG,
        )

        # Colored left accent bar
        _draw_rounded_rect(
            draw,
            (CARD_PAD - 8, y, CARD_PAD - 2, y + section_h),
            radius=8,
            fill=color,
        )

        # Section title
        inner_y = y + 14
        _draw_accent_dot(draw, CARD_PAD + 10, inner_y + 3, color, 10)
        draw.text(
            (CARD_PAD + 28, inner_y),
            section_name,
            font=font_section_title,
            fill=color,
        )
        inner_y += 32

        if section_name == "VERSICULO":
            # Verse text in italic style (lighter color)
            for line in lines:
                draw.text((CARD_PAD + 20, inner_y), line, font=font_verse, fill=TEXT_SECONDARY)
                inner_y += 24
            # Reference
            draw.text((CARD_PAD + 20, inner_y + 4), f"  {verse_ref}", font=font_verse_ref, fill=color)
        else:
            # Regular content lines
            for line in lines:
                # Clean up bullet points
                display = line.lstrip("- ").lstrip("* ").strip()
                if not display:
                    continue
                draw.text(
                    (CARD_PAD + 20, inner_y),
                    display,
                    font=font_body,
                    fill=TEXT_PRIMARY,
                )
                inner_y += 28

        y += section_h + 16

    # --- Footer ---
    draw.text(
        (CARD_PAD, y + 8),
        "Powered by Glitch",
        font=font_brand,
        fill=DIVIDER,
    )

    # Save
    filename = f"summary_{uuid.uuid4().hex[:8]}.png"
    filepath = os.path.join("/tmp", filename)
    img.save(filepath, "PNG", optimize=True)
    logger.info("Summary card generated: %s (%dx%d)", filename, CARD_W, total_h)

    return filename
