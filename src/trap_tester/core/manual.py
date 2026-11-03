"""The in-app manual: chapter registry and the Markdown processing behind it.

Qt-free on purpose, so the bundled chapters can be checked headlessly (every
image present, every internal link resolving, every equation rendering).  The
GUI side lives in ``gui/widgets/manual_browser.py`` and ``gui/panels/manual_panel.py``.

The chapters are Markdown files under ``trap_tester/manual/`` (package data,
shipped in the frozen bundle).  ``frontend/`` is a pinned copy of the Analog
Frontend README written by ``scripts/sync_frontend_docs.py``.

Qt's Markdown renderer knows neither heading anchors nor LaTeX, so this module
supplies both:

* :func:`headings` lists a chapter's headings with GitHub-style slugs, which the
  viewer attaches to the rendered heading blocks so ``[x](#some-heading)`` links
  (and the table of contents) can jump to them.
* :func:`replace_math` swaps every ``$...$`` / ``$$...$$`` for an image link with
  the ``ttmath:`` scheme; the viewer resolves those through
  :func:`render_math_png` (matplotlib mathtext), in the current theme's colour.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from matplotlib.mathtext import MathTextParser

log = logging.getLogger(__name__)

MATH_SCHEME = "ttmath"


@dataclass(frozen=True)
class Chapter:
    key: str
    title: str
    relpath: str  # POSIX path below the manual root

    @property
    def path(self) -> Path:
        return manual_root() / self.relpath

    def text(self) -> str:
        return self.path.read_text(encoding="utf-8")

    def source_info(self) -> dict | None:
        """Provenance of a vendored chapter (its folder's ``SOURCE.json``), if any."""
        meta = self.path.with_name("SOURCE.json")
        if not meta.is_file():
            return None
        return json.loads(meta.read_text(encoding="utf-8"))


# In reading order.  The first chapter is what the Manual panel opens on.
CHAPTERS: tuple[Chapter, ...] = (
    Chapter("start", "Getting started", "getting-started.md"),
    Chapter("measurement", "Measurement", "measurement.md"),
    Chapter("analysis", "Analysis", "analysis.md"),
    Chapter("interfaces", "Interfaces", "interfaces.md"),
    Chapter("device", "Device Info", "device-info.md"),
    Chapter("selftest", "Self-Test", "self-test.md"),
    Chapter("settings", "Settings", "settings.md"),
    Chapter("layouts", "Custom layouts and mappings", "layouts.md"),
    Chapter("frontend", "Analog Frontend (hardware)", "frontend/README.md"),
)


def manual_root() -> Path:
    return Path(__file__).resolve().parents[1] / "manual"


def chapter_for_path(path: Path) -> Chapter | None:
    """The registered chapter stored at *path*, if any."""
    try:
        resolved = path.resolve()
    except OSError:
        return None
    for chapter in CHAPTERS:
        if chapter.path.resolve() == resolved:
            return chapter
    return None


# ---- Markdown structure ----------------------------------------------------

_FENCE = re.compile(r"^\s{0,3}(```|~~~)")
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*$")
_CODE_SPAN = re.compile(r"(`+)(.+?)\1")
# Inline links and images; group 1 is "!" for an image, group 2 the target.
_LINK = re.compile(
    r"(!?)\[(?:[^\[\]]|\[[^\]]*\])*\]"  # [text], one level of nested [] allowed
    r"\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)"  # (target "title")
)


@dataclass(frozen=True)
class Heading:
    level: int
    text: str  # plain text, inline markup removed
    slug: str


def _prose_lines(markdown: str):
    """Yield ``(index, line)`` for every line outside fenced code blocks."""
    in_fence = False
    for i, line in enumerate(markdown.splitlines()):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield i, line


def _plain(inline: str) -> str:
    """Inline Markdown reduced to its visible text (for headings / slugs)."""
    text = _CODE_SPAN.sub(lambda m: m.group(2), inline)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links, images
    text = re.sub(r"(\*\*|__|\*|_|~~)(?=\S)(.+?)(?<=\S)\1", r"\2", text)
    return text.strip()


def slugify(text: str) -> str:
    """GitHub's heading anchor: lower-case, punctuation dropped, spaces -> ``-``."""
    text = unicodedata.normalize("NFKC", text).strip().lower()
    text = "".join(ch for ch in text if ch.isalnum() or ch in " -_")
    return text.replace(" ", "-")


def headings(markdown: str) -> list[Heading]:
    """ATX headings outside code blocks, with unique (``-1``, ``-2``...) slugs."""
    out: list[Heading] = []
    seen: dict[str, int] = {}
    for _, line in _prose_lines(markdown):
        match = _HEADING.match(line)
        if not match:
            continue
        text = _plain(match.group(2))
        base = slugify(text)
        count = seen.get(base, 0)
        seen[base] = count + 1
        slug = base if count == 0 else f"{base}-{count}"
        out.append(Heading(len(match.group(1)), text, slug))
    return out


def links(markdown: str) -> list[str]:
    """Targets of the inline links (not images) outside code."""
    found: list[str] = []
    for _, line in _prose_lines(markdown):
        for bang, target in _LINK.findall(_CODE_SPAN.sub("", line)):
            if not bang:
                found.append(target)
    return found


def images(markdown: str) -> list[str]:
    """Targets of the inline images outside code."""
    found: list[str] = []
    for _, line in _prose_lines(markdown):
        for bang, target in _LINK.findall(_CODE_SPAN.sub("", line)):
            if bang:
                found.append(target)
    return found


def is_external(target: str) -> bool:
    """True for ``http:``, ``mailto:`` and other scheme-qualified targets."""
    return re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE) is not None


@dataclass(frozen=True)
class Target:
    chapter: Chapter
    slug: str  # "" = top of the chapter


def resolve_link(chapter: Chapter, target: str) -> Target | None:
    """Where an internal link of *chapter* points, or ``None`` if it leads nowhere.

    Handles ``#slug`` (same chapter) and relative ``other.md#slug`` paths.
    External targets are not resolved (``None``); check :func:`is_external` first.
    """
    if is_external(target):
        return None
    path_part, _, slug = target.partition("#")
    if path_part:
        rel = PurePosixPath(chapter.relpath).parent / path_part
        dest = chapter_for_path(manual_root() / rel)
        if dest is None:
            return None
    else:
        dest = chapter
    if slug and slug not in {h.slug for h in headings(dest.text())}:
        return None
    return Target(dest, slug)


# ---- math ------------------------------------------------------------------

# $$...$$ on one line, or $...$ GitHub-style: the opening $ is not followed by
# whitespace, the closing $ not preceded by it nor followed by a digit, so
# prices like "$5 and $10" stay text.  A backslash-escaped \$ never delimits.
_MATH = re.compile(
    r"(?<![\\$])\$\$(?P<display>[^\n]+?)\$\$"
    r"|(?<![\\$])\$(?![\s$])(?P<inline>(?:\\.|[^$\\\n])+?)(?<![\s\\])\$(?!\d)"
)


@dataclass(frozen=True)
class Equation:
    tex: str
    display: bool  # a paragraph of its own (or $$...$$): larger, display-style


def math_key(eq: Equation) -> str:
    raw = f"{int(eq.display)}{eq.tex}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def replace_math(markdown: str) -> tuple[str, dict[str, Equation]]:
    """Swap each equation for ``![equation](ttmath:<key>)``.

    Returns the rewritten Markdown and ``{key: Equation}`` for every equation in
    it.  An equation is *display* when written ``$$...$$`` or when it is the whole
    of its line (a paragraph of its own; a list item stays inline).  Code blocks
    and code spans are left alone.
    """
    found: dict[str, Equation] = {}

    def outside_code(line: str) -> str:
        alone = _MATH.fullmatch(line.strip()) is not None

        def sub(match: re.Match[str]) -> str:
            display = match.group("display")
            tex = (display or match.group("inline")).strip()
            eq = Equation(tex, bool(display) or alone)
            key = math_key(eq)
            found[key] = eq
            return f"![equation]({MATH_SCHEME}:{key})"

        # split() keeps both groups: [text, ticks, code, text, ticks, code, ...]
        parts = _CODE_SPAN.split(line)
        out = [_MATH.sub(sub, parts[0])]
        for ticks, code, text in zip(
            parts[1::3], parts[2::3], parts[3::3], strict=True
        ):
            out += [ticks, code, ticks, _MATH.sub(sub, text)]
        return "".join(out)

    lines = markdown.splitlines(keepends=True)
    prose = {i for i, _ in _prose_lines(markdown)}
    rewritten = [
        outside_code(line) if i in prose else line for i, line in enumerate(lines)
    ]
    return "".join(rewritten), found


DISPLAY_SCALE = 1.2  # display equations are set this much larger than the text


def render_math_png(
    eq: Equation, *, color: str, size_pt: float, dpi: float
) -> tuple[bytes, float]:
    """Render *eq* with matplotlib mathtext as a transparent PNG.

    Returns ``(png, depth)``: *depth* is the fraction of the image height that
    lies below the baseline, which the viewer needs to line the equation up
    with the surrounding text.  TeX that mathtext rejects is rendered as its raw
    source instead (and logged), so one bad equation never blanks a chapter.
    """
    tex = eq.tex
    if eq.display:
        # mathtext has no \displaystyle; \dfrac gives display-size fractions.
        tex = re.sub(r"\\frac(?![a-zA-Z])", r"\\dfrac", tex)
        size_pt *= DISPLAY_SCALE
    prop = FontProperties(size=size_pt)
    parser = MathTextParser("path")
    text = f"${tex}$"
    try:
        width, height, depth, _, _ = parser.parse(text, dpi=72, prop=prop)
    except ValueError as exc:
        log.warning("cannot render equation %r: %s", tex, " ".join(str(exc).split()))
        text = tex  # no "$" (the math pattern excludes them): rendered as plain text
        width, height, depth, _, _ = parser.parse(text, dpi=72, prop=prop)

    # Same construction as matplotlib.mathtext.math_to_image, but transparent.
    fig = Figure(figsize=(width / 72, height / 72))
    fig.text(0, depth / height, text, fontproperties=prop, color=color)
    buf = io.BytesIO()
    fig.savefig(buf, dpi=dpi, format="png", transparent=True)
    return buf.getvalue(), depth / height


__all__ = [
    "CHAPTERS",
    "DISPLAY_SCALE",
    "MATH_SCHEME",
    "Chapter",
    "Equation",
    "Heading",
    "Target",
    "chapter_for_path",
    "headings",
    "images",
    "is_external",
    "links",
    "manual_root",
    "math_key",
    "render_math_png",
    "replace_math",
    "resolve_link",
    "slugify",
]
