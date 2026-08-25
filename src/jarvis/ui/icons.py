"""Menu-bar icons, generated rather than shipped.

Drawing them with Pillow at runtime avoids carrying a dozen PNGs through py2app and
makes the state colours a one-line change. Cheap: six small images, once at startup.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw

from jarvis.events import State

# An arc-reactor palette: cool when idle, warm when working.
STATE_COLOURS: dict[State, tuple[int, int, int]] = {
    State.IDLE: (120, 130, 140),
    State.LISTENING: (0, 190, 255),
    State.THINKING: (255, 175, 40),
    State.SPEAKING: (60, 220, 130),
    State.ACTING: (175, 120, 255),
    State.ERROR: (240, 70, 70),
}

STATE_LABELS: dict[State, str] = {
    State.IDLE: "Idle",
    State.LISTENING: "Listening",
    State.THINKING: "Thinking",
    State.SPEAKING: "Speaking",
    State.ACTING: "Working",
    State.ERROR: "Unavailable",
}


def render(state: State, size: int = 64) -> Image.Image:
    """A ring with a filled core, in the colour for this state."""
    colour = STATE_COLOURS.get(state, STATE_COLOURS[State.IDLE])
    # Supersample and downscale: PIL has no antialiased ellipse.
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = s * 0.10
    ring_width = max(1, int(s * 0.09))
    draw.ellipse(
        [pad, pad, s - pad, s - pad],
        outline=colour + (255,),
        width=ring_width,
    )

    core = s * 0.31
    centre = s / 2
    draw.ellipse(
        [centre - core, centre - core, centre + core, centre + core],
        fill=colour + (255,),
    )

    return img.resize((size, size), Image.LANCZOS)


@lru_cache(maxsize=None)
def icon_path(state: State, cache_dir: Path, size: int = 44) -> Path:
    """Render to a PNG on disk and return the path.

    rumps takes a file path, not an image object. Size 44 is the 22pt menu-bar slot
    at 2x, which is what Retina displays want.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"tray-{state.value}-{size}.png"
    if not path.exists():
        render(state, size).save(path, format="PNG")
    return path
