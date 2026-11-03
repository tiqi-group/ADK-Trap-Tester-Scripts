"""Headless tests for the in-app manual (``core.manual``) and its bundled chapters.

No Qt: the chapter files, their images and links, the heading slugs, the
equation extraction and the mathtext rendering are all checked without a GUI.
The frontend-docs sync script's section filter is tested here too.
"""

from __future__ import annotations

import importlib.util
import logging
import re
from pathlib import Path

import pytest

from trap_tester.core import manual

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def sync_script():
    path = REPO_ROOT / "scripts" / "sync_frontend_docs.py"
    spec = importlib.util.spec_from_file_location("sync_frontend_docs", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---- the bundled chapters ----------------------------------------------------


def test_chapters_exist_with_unique_keys():
    assert manual.CHAPTERS
    assert len({c.key for c in manual.CHAPTERS}) == len(manual.CHAPTERS)
    for chapter in manual.CHAPTERS:
        assert chapter.path.is_file(), chapter.relpath
        assert manual.chapter_for_path(chapter.path) == chapter


@pytest.mark.parametrize("chapter", manual.CHAPTERS, ids=lambda c: c.key)
def test_every_image_is_bundled(chapter):
    for target in manual.images(chapter.text()):
        if manual.is_external(target):
            continue
        assert (chapter.path.parent / target).is_file(), target


@pytest.mark.parametrize("chapter", manual.CHAPTERS, ids=lambda c: c.key)
def test_every_internal_link_resolves(chapter):
    for target in manual.links(chapter.text()):
        if not manual.is_external(target):
            assert manual.resolve_link(chapter, target) is not None, target


@pytest.mark.parametrize("chapter", manual.CHAPTERS, ids=lambda c: c.key)
def test_every_equation_renders(chapter, caplog):
    _, equations = manual.replace_math(chapter.text())
    with caplog.at_level(logging.WARNING, logger=manual.__name__):
        for eq in equations.values():
            png, depth = manual.render_math_png(eq, color="#202020", size_pt=9, dpi=96)
            assert png.startswith(b"\x89PNG")
            assert 0 <= depth < 1
    assert not caplog.records, [r.getMessage() for r in caplog.records]


def test_frontend_copy_is_pinned_and_trimmed():
    chapter = next(c for c in manual.CHAPTERS if c.key == "frontend")
    info = chapter.source_info()
    assert info is not None
    assert re.fullmatch(r"[0-9a-f]{40}", info["commit"])
    assert "Order Information" in info["skipped_sections"]
    titles = {h.text for h in manual.headings(chapter.text())}
    assert "Order Information" not in titles
    assert "Debugging Common Faults" in titles  # the rest is kept


def test_frontend_links_back_into_the_manual():
    """Its links to this app's repository open the app's own chapters instead."""
    chapter = next(c for c in manual.CHAPTERS if c.key == "frontend")
    targets = manual.links(chapter.text())
    assert "../getting-started.md" in targets
    assert not [t for t in targets if "trap-tester-adk-script" in t]


# ---- headings and links --------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "slug"),
    [
        ("Measuring DC Resistances", "measuring-dc-resistances"),
        (
            "Shorts on the Filter Board or Wiring Faults",
            "shorts-on-the-filter-board-or-wiring-faults",
        ),
        ("What's new? (v1.0)", "whats-new-v10"),
        ("snake_case and dash-ed", "snake_case-and-dash-ed"),
    ],
)
def test_slugify_matches_github(text, slug):
    assert manual.slugify(text) == slug


def test_headings_skip_code_and_dedupe_slugs():
    md = (
        "# Top\n\n## Notes\n\n```\n# not a heading\n```\n\n"
        "### Notes\n\n## `code` *em*\n"
    )
    found = manual.headings(md)
    assert [(h.level, h.slug) for h in found] == [
        (1, "top"),
        (2, "notes"),
        (3, "notes-1"),
        (2, "code-em"),
    ]


def test_links_and_images_are_told_apart():
    md = "see [a](#x) and ![pic](img.png) and [b](https://e.org)\n`[c](#no)`\n"
    assert manual.links(md) == ["#x", "https://e.org"]
    assert manual.images(md) == ["img.png"]


def test_resolve_link_rejects_unknown_targets():
    chapter = manual.CHAPTERS[0]
    assert manual.resolve_link(chapter, "#no-such-heading") is None
    assert manual.resolve_link(chapter, "missing.md") is None
    assert manual.resolve_link(chapter, "https://example.org") is None
    assert manual.resolve_link(chapter, "") == manual.Target(chapter, "")


# ---- equations -------------------------------------------------------------------


def test_replace_math_leaves_prices_code_and_escapes():
    md = "costs $5 and $10, `$x$` is code, \\$y\\$ is escaped\n"
    out, found = manual.replace_math(md)
    assert out == md
    assert found == {}


def test_replace_math_marks_display_equations():
    md = "inline $a_1$ here\n\n$b^2$\n\n* $c$\n\nand $$d$$ too\n"
    out, found = manual.replace_math(md)
    kinds = {eq.tex: eq.display for eq in found.values()}
    assert kinds == {"a_1": False, "b^2": True, "c": False, "d": True}
    assert "$" not in out
    for key in found:
        assert f"({manual.MATH_SCHEME}:{key})" in out


def test_replace_math_skips_fenced_code():
    md = "```\n$x$\n```\n$y$\n"
    out, found = manual.replace_math(md)
    assert out.startswith("```\n$x$\n```\n")
    assert [eq.tex for eq in found.values()] == ["y"]


def test_bad_tex_falls_back_to_raw_text(caplog):
    with caplog.at_level(logging.WARNING, logger=manual.__name__):
        png, _ = manual.render_math_png(
            manual.Equation(r"\frac{1}{", display=False),
            color="#202020",
            size_pt=9,
            dpi=96,
        )
    assert png.startswith(b"\x89PNG")
    assert "cannot render equation" in caplog.text


# ---- sync script -------------------------------------------------------------------


def test_drop_sections_removes_nested_content_only(sync_script):
    md = (
        "# Doc\n\nintro\n\n## Keep\n\nk\n\n## Order Information\n\nx\n\n"
        "### Sub\n\ny\n\n```\n## not a heading\n```\n\n## After\n\nz\n"
    )
    out, found = sync_script.drop_sections(md, {"Order Information"})
    assert found == {"Order Information"}
    assert "## Keep" in out
    assert "## After" in out
    assert "\nx\n" not in out
    assert "### Sub" not in out
    assert "not a heading" not in out


def test_local_images_skips_urls_and_rejects_escapes(sync_script):
    md = "![a](./docs/A.jpg) ![b](https://e.org/b.png) ![a2](docs/A.jpg)"
    assert sync_script.local_images(md) == ["docs/A.jpg"]
    with pytest.raises(SystemExit):
        sync_script.local_images("![x](../secret.png)")


def test_rewrite_links_points_repo_links_into_the_manual(sync_script):
    rewrites = {"https://example.org/app": "../start.md"}
    md = (
        "[home](https://example.org/app) [deep](https://example.org/app/-/blob/x.md)"
        ' [titled](<https://example.org/app/> "t") [other](https://example.org/apple)'
        " ![img](https://example.org/app/a.png)\n"
        "```\n[code](https://example.org/app)\n```\n"
    )
    out, changed = sync_script.rewrite_links(md, rewrites)
    assert "[home](../start.md)" in out
    assert "[deep](../start.md)" in out
    assert '[titled](../start.md "t")' in out
    assert "[other](https://example.org/apple)" in out  # a prefix is not a match
    assert "![img](https://example.org/app/a.png)" in out  # images are left alone
    assert "[code](https://example.org/app)" in out  # so is fenced code
    assert len(changed) == 3
