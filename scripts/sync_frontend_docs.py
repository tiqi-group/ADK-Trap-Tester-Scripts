#!/usr/bin/env python3
"""Vendor the Analog Frontend README (and the images it uses) into the app's manual.

The in-app manual shows the hardware documentation of the ADK-Trap-Tester-Frontend
repository next to the GUI's own chapters.  The frozen app cannot read a sibling
checkout, and CI only checks out this repository, so a pinned copy is stored as
package data under ``src/trap_tester/manual/frontend/``:

* ``README.md``   the frontend README, verbatim except for the sections listed in
                  ``SKIP_SECTIONS`` (manufacturing notes an operator does not need)
                  and links back to this app's repository, which ``LINK_REWRITES``
                  points at the manual's own chapters
* ``docs/*.jpg``  only the images the README references, at their original
                  relative paths, so the Markdown needs no rewriting
* ``SOURCE.json`` where the copy came from: remote, ref, commit and its date

Content is read from a *commit* (``git show <ref>:<path>``), never the working tree,
so the recorded commit really describes what was copied.  Uncommitted README edits
in the source checkout are reported and left out; commit them first.

The output folder is owned by this script and is replaced on every run.

Usage (stdlib only, any Python >= 3.11)::

    python scripts/sync_frontend_docs.py            # ../ADK-Trap-Tester-Frontend @ HEAD
    python scripts/sync_frontend_docs.py --source PATH --ref v1.0
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT.parent / "ADK-Trap-Tester-Frontend"
TARGET = REPO_ROOT / "src" / "trap_tester" / "manual" / "frontend"

README = "README.md"

# Headings (any level) whose whole section is left out of the manual.
SKIP_SECTIONS = {
    "Order Information",  # PCB manufacturing notes
}

# Links back to *this* app's repository (its old GitLab home and the GitHub one)
# point at the manual's own first chapter instead, so a reader in the app stays in
# the app.  A deep link into the repository counts too.  Targets are relative to
# the copied README, i.e. to ``manual/frontend/``.
LINK_REWRITES = {
    "https://gitlab.phys.ethz.ch/tiqi-projects/tiqi-trap-tester/trap-tester-adk-script":
        "../getting-started.md",
    "https://github.com/tiqi-group/ADK-Trap-Tester-Scripts": "../getting-started.md",
}

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_IMAGE = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
# An inline link (not an image); group "target" is what gets rewritten.
_LINK = re.compile(
    r"(?<!!)(?P<text>\[[^\]]*\]\(\s*)<?(?P<target>[^)\s>]+)>?(?P<rest>(?:\s+\"[^\"]*\")?\s*\))"
)


def _git(source: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(source), *args], capture_output=True, check=False
    )
    if result.returncode != 0:
        msg = result.stderr.decode(errors="replace").strip()
        raise SystemExit(f"git {' '.join(args)} failed in {source}:\n{msg}")
    return result.stdout


def drop_sections(markdown: str, titles: set[str]) -> tuple[str, set[str]]:
    """Remove each section whose heading text is in *titles*.

    A section runs from its heading up to the next heading of the same or a
    higher level.  Lines inside fenced code blocks are never taken as headings.
    Returns the new text and the titles that were actually found.
    """
    out: list[str] = []
    found: set[str] = set()
    skip_level: int | None = None  # level of the section being dropped
    in_fence = False
    for line in markdown.splitlines(keepends=True):
        if _FENCE.match(line):
            in_fence = not in_fence
        heading = None if in_fence else _HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            if skip_level is not None and level <= skip_level:
                skip_level = None
            if skip_level is None and heading.group(2) in titles:
                found.add(heading.group(2))
                skip_level = level
        if skip_level is None:
            out.append(line)
    return "".join(out).rstrip() + "\n", found


def _rewrite_target(target: str, rewrites: dict[str, str]) -> str | None:
    """The replacement for *target*, if it is (a page within) a rewritten URL."""
    bare = target.rstrip("/")
    for base, replacement in rewrites.items():
        if bare == base or bare.startswith(base + "/") or bare.startswith(base + "?"):
            return replacement
    return None


def rewrite_links(markdown: str, rewrites: dict[str, str]) -> tuple[str, list[str]]:
    """Point links at the URLs in *rewrites* to their replacements.

    Images and fenced code are left alone.  Returns the new text and the original
    targets that were rewritten, in order.
    """
    out: list[str] = []
    changed: list[str] = []
    in_fence = False

    def sub(match: re.Match[str]) -> str:
        new = _rewrite_target(match["target"], rewrites)
        if new is None:
            return match[0]
        changed.append(match["target"])
        return f"{match['text']}{new}{match['rest']}"

    for line in markdown.splitlines(keepends=True):
        if _FENCE.match(line):
            in_fence = not in_fence
        out.append(line if in_fence else _LINK.sub(sub, line))
    return "".join(out), changed


def local_images(markdown: str) -> list[str]:
    """Repository-relative paths of the images the Markdown embeds (no URLs)."""
    paths: list[str] = []
    for ref in _IMAGE.findall(markdown):
        if re.match(r"^[a-z][a-z0-9+.-]*:", ref, re.IGNORECASE):  # http:, data:, ...
            continue
        path = PurePosixPath(ref.split("#", 1)[0])
        if path.is_absolute() or ".." in path.parts:
            raise SystemExit(f"image path {ref!r} points outside the repository")
        normalized = path.as_posix()  # also drops a leading "./"
        if normalized not in paths:
            paths.append(normalized)
    return paths


def _read_source(source: Path, ref: str) -> tuple[str, dict[str, bytes], dict]:
    """The trimmed README, its images and the provenance record, all from *ref*."""
    if not (source / ".git").exists():
        raise SystemExit(f"{source} is not a git checkout")
    commit = _git(source, "rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()
    date = _git(source, "show", "-s", "--format=%cI", commit).decode().strip()
    try:
        remote = _git(source, "remote", "get-url", "origin").decode().strip()
    except SystemExit:
        remote = ""

    original = _git(source, "show", f"{commit}:{README}").decode("utf-8")
    worktree = source / README
    if ref == "HEAD" and worktree.read_text(encoding="utf-8") != original:
        print(
            f"warning: {worktree} has uncommitted changes; they are NOT copied "
            "(commit them and re-run to include them)",
            file=sys.stderr,
        )

    text, found = drop_sections(original, SKIP_SECTIONS)
    for title in sorted(SKIP_SECTIONS - found):
        print(f"warning: section {title!r} not found, so not dropped", file=sys.stderr)
    text, rewritten = rewrite_links(text, LINK_REWRITES)

    images = {p: _git(source, "show", f"{commit}:{p}") for p in local_images(text)}
    meta = {
        "repository": remote,
        "ref": ref,
        "commit": commit,
        "commit_date": date,
        "skipped_sections": sorted(found),
        "rewritten_links": rewritten,
        "images": list(images),
    }
    return text, images, meta


def _write_target(text: str, images: dict[str, bytes], meta: dict) -> None:
    """Replace TARGET with the new copy.

    The folder is built aside and swapped in, so a failure never leaves a
    half-written copy behind.
    """
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=TARGET.parent) as tmp:
        staging = Path(tmp) / "frontend"
        staging.mkdir()
        (staging / README).write_text(text, encoding="utf-8", newline="\n")
        for path, data in images.items():
            dest = staging / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        (staging / "SOURCE.json").write_text(
            json.dumps(meta, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        if TARGET.exists():
            shutil.rmtree(TARGET)
        staging.rename(TARGET)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"checkout of the frontend repository (default: {DEFAULT_SOURCE})",
    )
    parser.add_argument(
        "--ref", default="HEAD", help="commit, tag or branch (default: HEAD)"
    )
    args = parser.parse_args()

    text, images, meta = _read_source(args.source.resolve(), args.ref)
    _write_target(text, images, meta)

    print(
        f"synced {README} + {len(images)} image(s) from {meta['commit'][:10]} "
        f"({meta['commit_date']}) into"
    )
    print(f"  {TARGET.relative_to(REPO_ROOT)}")
    if meta["skipped_sections"]:
        print(f"  skipped: {', '.join(meta['skipped_sections'])}")
    if meta["rewritten_links"]:
        print(f"  links into the manual: {', '.join(meta['rewritten_links'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
