"""
Generates a graphical rank card (PNG bytes) for /rank, in the style of
popular leveling bots — avatar, level, and a drawn progress bar, instead of
a text-based bar (which renders inconsistently across Discord clients).
"""

import io
import os
import aiohttp
from PIL import Image, ImageDraw, ImageFont

FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
FONT_BOLD = os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")
FONT_REGULAR = os.path.join(FONT_DIR, "DejaVuSans.ttf")

WIDTH, HEIGHT = 700, 220

BG_COLOR = (43, 45, 49)        # Discord embed dark
ACCENT_COLOR = (221, 167, 49)  # brand gold
TRACK_COLOR = (30, 31, 34)     # darker track for the empty part of the bar
WHITE = (242, 243, 245)
MUTED = (148, 155, 164)


def _circular_avatar(avatar_bytes, size):
    img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((size, size))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    output.paste(img, (0, 0), mask)
    return output


async def _fetch_avatar_bytes(member):
    avatar_url = str(member.display_avatar.replace(size=256, format="png"))
    async with aiohttp.ClientSession() as session:
        async with session.get(avatar_url) as resp:
            return await resp.read()


async def generate_rank_card(member, level, rank, progress_in_level, needed_for_level):
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # left accent strip, matching the rest of the bot's branding
    draw.rectangle([0, 0, 8, HEIGHT], fill=ACCENT_COLOR)

    # avatar with a gold ring
    avatar_size = 140
    ring_padding = 6
    avatar_x, avatar_y = 45, (HEIGHT - avatar_size) // 2
    draw.ellipse(
        [
            avatar_x - ring_padding, avatar_y - ring_padding,
            avatar_x + avatar_size + ring_padding, avatar_y + avatar_size + ring_padding,
        ],
        fill=ACCENT_COLOR,
    )

    avatar_bytes = await _fetch_avatar_bytes(member)
    avatar_img = _circular_avatar(avatar_bytes, avatar_size)
    img.paste(avatar_img, (avatar_x, avatar_y), avatar_img)

    text_x = avatar_x + avatar_size + 45

    font_name = ImageFont.truetype(FONT_BOLD, 34)
    font_label = ImageFont.truetype(FONT_REGULAR, 20)
    font_level = ImageFont.truetype(FONT_BOLD, 26)
    font_xp = ImageFont.truetype(FONT_REGULAR, 18)

    draw.text((text_x, 28), member.display_name, font=font_name, fill=WHITE)
    draw.text((text_x, 78), f"LEVEL {level}", font=font_level, fill=ACCENT_COLOR)
    draw.text((text_x + 165, 84), f"Rank #{rank}", font=font_label, fill=MUTED)

    # progress bar
    bar_x, bar_y = text_x, 140
    bar_width, bar_height = WIDTH - text_x - 40, 26
    radius = bar_height // 2

    draw.rounded_rectangle(
        [bar_x, bar_y, bar_x + bar_width, bar_y + bar_height],
        radius=radius, fill=TRACK_COLOR,
    )

    ratio = max(0.0, min(progress_in_level / needed_for_level, 1.0)) if needed_for_level > 0 else 1.0
    fill_width = int(bar_width * ratio)

    if fill_width > radius:
        draw.rounded_rectangle(
            [bar_x, bar_y, bar_x + fill_width, bar_y + bar_height],
            radius=radius, fill=ACCENT_COLOR,
        )
    elif fill_width > 0:
        draw.ellipse([bar_x, bar_y, bar_x + bar_height, bar_y + bar_height], fill=ACCENT_COLOR)

    draw.text(
        (bar_x, bar_y + bar_height + 10),
        f"{max(progress_in_level, 0)} / {needed_for_level} XP",
        font=font_xp, fill=MUTED,
    )

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer
