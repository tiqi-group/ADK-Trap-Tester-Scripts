"""A ``QTextBrowser`` that renders the manual's Markdown chapters.

On top of Qt's own Markdown support it adds what the chapters need:

* **Equations.**  ``core.manual.replace_math`` turns ``$...$`` into ``ttmath:``
  image links while a chapter loads; :meth:`loadResource` renders them with
  matplotlib mathtext in the theme's text colour, at the screen's pixel density,
  padded so the equation's baseline sits on the line's baseline.  An equation
  that is a paragraph of its own is set larger and centred.
* **Heading anchors.**  Qt's importer gives headings no anchor names, so after a
  load each heading block is tagged with its GitHub slug (from
  ``core.manual.headings``) and ``#slug`` links / ``scrollToAnchor`` work.
* **Links.**  ``#slug`` and ``other.md#slug`` navigate inside the browser (with
  back/forward history); web links open in the system browser.
* **Figures** are scaled down to the viewport width, never up.
* **Boxes.**  Code blocks and block quotes (the manual's warnings) are wrapped in
  a padded, bordered frame in theme colours; inline code gets a background.
* **Search** across the whole manual: :meth:`set_search` highlights every match
  in the shown chapter, :meth:`find_next` moves to the next (or previous) one,
  continuing into the following chapters when this one has no more.
* **Qt quirks** are evened out: ``_emphasis_`` is shown italic (as on GitHub),
  not underlined, and list items that start with an equation lose the extra
  indent Qt's importer gives every one but the first.

Navigation is Qt's own (``setSource`` / ``backward`` / ``forward``).  A chapter
is (re)loaded through :meth:`loadResource`, which flags it; the decoration runs
on the following ``sourceChanged``, then the fragment is scrolled to again,
since Qt tried that before the anchors existed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QImage,
    QImageReader,
    QPainter,
    QTextBlock,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextFrameFormat,
    QTextImageFormat,
)
from PySide6.QtWidgets import QTextBrowser, QTextEdit

from trap_tester.core import manual
from trap_tester.gui import theme

_FIGURE_MARGIN = 24  # px kept free beside a scaled-down figure
_MARKDOWN = QTextDocument.ResourceType.MarkdownResource
_IMAGE = QTextDocument.ResourceType.ImageResource
_KEEP = QTextCursor.MoveMode.KeepAnchor
_BACKWARD = QTextDocument.FindFlag.FindBackward
_NO_FLAGS = QTextDocument.FindFlag(0)
_MAX_HIGHLIGHTS = 2000  # matches painted at once (a one-letter search is cheap)
_BOX_PADDING = 8  # px inside a code / callout frame
_BOX_MARGIN = 6  # px above and below one


def _local_path(url: QUrl) -> Path:
    return Path(url.toLocalFile())


def chapter_at(url: QUrl) -> manual.Chapter | None:
    """The registered chapter a ``file:`` URL points at (fragment ignored)."""
    if url.isEmpty() or not url.isLocalFile():
        return None
    return manual.chapter_for_path(_local_path(url))


def chapter_url(chapter: manual.Chapter, slug: str = "") -> QUrl:
    url = QUrl.fromLocalFile(str(chapter.path))
    if slug:
        url.setFragment(slug)
    return url


@dataclass
class _Scan:
    """What :meth:`ManualBrowser._decorate` changes, found in one pass."""

    headings: list[QTextBlock] = field(default_factory=list)
    links: list[tuple[int, int]] = field(default_factory=list)  # (pos, length)
    equations: list[tuple[int, bool]] = field(default_factory=list)  # (pos, centre)
    figures: list[tuple[int, QSize]] = field(default_factory=list)  # (pos, size)
    underlined: list[tuple[int, int]] = field(default_factory=list)  # (pos, length)
    indented_items: list[int] = field(default_factory=list)  # block positions
    inline_code: list[tuple[int, int]] = field(default_factory=list)  # (pos, length)


class ManualBrowser(QTextBrowser):
    # (current, total) matches of the search term in the shown chapter; current
    # is 0 when no match is selected.
    matchesChanged = Signal(int, int)

    def __init__(self) -> None:
        super().__init__()
        self.setOpenLinks(False)  # every click goes through _on_anchor_clicked
        self.anchorClicked.connect(self._on_anchor_clicked)
        self.sourceChanged.connect(self._on_source_changed)

        self._fresh = False  # a chapter was just loaded and is not decorated yet
        self._shown = QUrl()  # the chapter being decorated (relative links' base)
        self._math: dict[str, manual.Equation] = {}  # ttmath key -> equation
        self._math_cache: dict[tuple, QImage] = {}
        self._figures: list[tuple[int, QSize]] = []
        self._term = ""  # the search term ("" = no search)
        self._match: tuple[int, int] | None = None  # current match (start, end)

        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(100)
        self._fit_timer.timeout.connect(self._fit_figures)

    # ---- navigation ----------------------------------------------------------
    def show_chapter(self, chapter: manual.Chapter, slug: str = "") -> None:
        self.setSource(chapter_url(chapter, slug), _MARKDOWN)

    def current_chapter(self) -> manual.Chapter | None:
        return chapter_at(self.source())

    def _on_anchor_clicked(self, url: QUrl) -> None:
        if url.scheme() not in ("", "file"):
            QDesktopServices.openUrl(url)  # http(s), mailto, ...
            return
        target = self.source().resolved(url)
        path = _local_path(target)
        if manual.chapter_for_path(path) is not None:
            self.setSource(target, _MARKDOWN)  # recorded in the history
        elif path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _on_source_changed(self, url: QUrl) -> None:
        if not self._fresh:
            return
        self._fresh = False
        # The URL argument, not self.source(): Qt can emit before updating that.
        self._shown = url
        self._decorate(chapter_at(url))
        if url.fragment():
            self.scrollToAnchor(url.fragment())
        self._match = None  # positions of the previous chapter mean nothing here
        self._rehighlight()

    def rerender(self) -> None:
        """Re-render the current chapter in place (e.g. after a theme switch)."""
        if self.source().isEmpty():
            return
        bar = self.verticalScrollBar()
        pos = bar.value()
        self.reload()
        bar.setValue(pos)

    # ---- resources -------------------------------------------------------------
    def loadResource(self, type_: int, url: QUrl):  # noqa: N802
        if type_ == _MARKDOWN and url.isLocalFile():
            text = _local_path(url).read_text(encoding="utf-8")
            markdown, maths = manual.replace_math(text)
            self._math.update(maths)
            self._fresh = True
            return markdown
        if type_ == _IMAGE and url.scheme() == manual.MATH_SCHEME:
            eq = self._math.get(url.path())
            if eq is not None:
                return self._math_image(eq)
        return super().loadResource(type_, url)

    def _math_image(self, eq: manual.Equation) -> QImage:
        self.ensurePolished()  # the stylesheet's font size applies from here on
        dpr = self.devicePixelRatioF()
        color = theme.palette()["text"]
        font = self.font()
        size_pt = font.pointSizeF()
        if size_pt <= 0:
            size_pt = font.pixelSize() * 0.75
        x_height = self.fontMetrics().xHeight() * dpr
        key = (eq, color, size_pt, dpr, x_height)
        if key not in self._math_cache:
            dpi = self.logicalDpiY() * dpr
            png, depth = manual.render_math_png(
                eq, color=color, size_pt=size_pt, dpi=dpi
            )
            image = QImage.fromData(png)
            self._math_cache[key] = _baseline_padded(image, depth, x_height, dpr)
        return self._math_cache[key]

    # ---- post-load decoration --------------------------------------------------
    def _decorate(self, chapter: manual.Chapter | None) -> None:
        """Anchors on headings, link colour, equation alignment, figure sizes."""
        # First, as it inserts frames and so moves every position after them.
        self._box_blocks()
        scan = self._scan()
        cursor = QTextCursor(self.document())
        self._tag_headings(cursor, scan.headings, chapter)

        link_fmt = QTextCharFormat()
        link_fmt.setForeground(QColor(theme.palette()["section"]))
        for pos, length in scan.links:
            _merge(cursor, pos, length, link_fmt)

        middle = QTextImageFormat()
        middle.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignMiddle)
        centred = QTextBlockFormat()
        centred.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        for pos, centre in scan.equations:
            _merge(cursor, pos, 1, middle)
            if centre:
                cursor.mergeBlockFormat(centred)

        italic = QTextCharFormat()
        italic.setFontUnderline(False)
        italic.setFontItalic(True)
        for pos, length in scan.underlined:
            _merge(cursor, pos, length, italic)

        flush = QTextBlockFormat()
        flush.setIndent(0)
        for pos in scan.indented_items:
            cursor.setPosition(pos)
            cursor.mergeBlockFormat(flush)

        code = QTextCharFormat()
        code.setBackground(QColor(theme.palette()["code_bg"]))
        for pos, length in scan.inline_code:
            _merge(cursor, pos, length, code)

        self._figures = scan.figures
        self._fit_figures()

    def _scan(self) -> _Scan:
        scan = _Scan()
        block = self.document().begin()
        while block.isValid():
            if block.blockFormat().headingLevel() > 0:
                scan.headings.append(block)
            if block.textList() is not None and block.blockFormat().indent() > 0:
                scan.indented_items.append(block.position())
            it = block.begin()
            while not it.atEnd():
                self._scan_fragment(scan, block, it.fragment())
                it += 1
            block = block.next()
        return scan

    def _scan_fragment(self, scan: _Scan, block: QTextBlock, frag) -> None:
        fmt = frag.charFormat()
        span = (frag.position(), frag.length())
        if fmt.isImageFormat():
            self._scan_image(scan, block, frag.position(), fmt)
        elif fmt.isAnchor() and fmt.anchorHref():
            scan.links.append(span)
        elif fmt.fontUnderline():  # only `_emphasis_` underlines in Markdown
            scan.underlined.append(span)
        elif fmt.fontFixedPitch() and _box_kind(block) is None:
            scan.inline_code.append(span)  # `code` in running text

    def _scan_image(
        self, scan: _Scan, block: QTextBlock, pos: int, fmt: QTextCharFormat
    ) -> None:
        name = fmt.toImageFormat().name()
        scheme, _, key = name.partition(":")
        if scheme == manual.MATH_SCHEME:
            eq = self._math.get(key)
            # A display equation is centred, unless it is a list item.
            centre = eq is not None and eq.display and block.textList() is None
            scan.equations.append((pos, centre))
            return
        # Read the size from the file header: the document's resource cache is
        # not reliably keyed by the relative name the Markdown uses.
        url = self._shown.resolved(QUrl(name))
        if url.isLocalFile():
            size = QImageReader(url.toLocalFile()).size()
            if size.isValid():
                scan.figures.append((pos, size))

    @staticmethod
    def _tag_headings(
        cursor: QTextCursor, blocks: list[QTextBlock], chapter: manual.Chapter | None
    ) -> None:
        """Give heading i of the document the slug of heading i of the Markdown.

        Should the counts ever disagree, the rendered text is slugged instead.
        """
        slugs = [h.slug for h in manual.headings(chapter.text())] if chapter else []
        use_parsed = len(slugs) == len(blocks)
        for i, block in enumerate(blocks):
            fmt = QTextCharFormat()
            fmt.setAnchor(True)
            slug = slugs[i] if use_parsed else manual.slugify(block.text())
            fmt.setAnchorNames([slug])
            _merge(cursor, block.position(), max(block.length() - 1, 1), fmt)

    def _box_blocks(self) -> None:
        """Wrap each code block and each block quote in a framed box.

        Qt's importer gives a code block one unstyled block per line and a quote
        only an indent, so neither stands out (and a warning must).  A block
        background alone would leave gaps and no padding; a frame has both.
        Runs are wrapped last to first, so the positions still to be wrapped
        stay valid.
        """
        cursor = QTextCursor(self.document())
        unindent = QTextBlockFormat()
        unindent.setLeftMargin(0)  # the frame is the indent now
        for kind, start, end in reversed(_box_runs(self.document())):
            cursor.setPosition(start)
            cursor.setPosition(end, _KEEP)
            if kind == "quote":
                cursor.mergeBlockFormat(unindent)
            frame = cursor.insertFrame(_box_format(kind))
            # Qt leaves an empty paragraph on each side of a new frame; they are
            # structural, so flatten them instead of deleting them.
            doc = self.document()
            for pos in (frame.firstPosition() - 1, frame.lastPosition() + 1):
                block = doc.findBlock(pos)
                if block.isValid() and block.length() == 1:
                    cursor.setPosition(block.position())
                    cursor.setBlockFormat(_flat_block())

    def _fit_figures(self) -> None:
        """Scale figures down to the viewport width (never up)."""
        if self._figures:
            self._scale_figures()
        # Qt's incremental relayout after format changes can leave paragraphs
        # with no laid-out lines (they vanish: no height, nothing painted), so
        # lay the whole, small, document out again.
        doc = self.document()
        doc.markContentsDirty(0, doc.characterCount())

    def _scale_figures(self) -> None:
        margin = 2 * self.document().documentMargin() + _FIGURE_MARGIN
        room = max(self.viewport().width() - margin, 50)
        cursor = QTextCursor(self.document())
        for pos, natural in self._figures:
            if natural.width() <= 0:
                continue
            scale = min(1.0, room / natural.width())
            fmt = QTextImageFormat()
            fmt.setWidth(natural.width() * scale)
            fmt.setHeight(natural.height() * scale)
            _merge(cursor, pos, 1, fmt)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_timer.start()

    # ---- search ------------------------------------------------------------------
    def set_search(self, term: str) -> None:
        """Highlight every match of *term* (case-insensitive) in the shown chapter."""
        if term != self._term:
            self._term = term
            self._match = None
        self._rehighlight()

    def find_next(self, backward: bool = False, incremental: bool = False) -> bool:
        """Select the next (or previous) match of the search term.

        Starts after the current match, or from the top of the view when there is
        none; *incremental* (typing) starts at the current match instead, so a
        longer term keeps the match it extends.  When the chapter has no more
        matches the search continues in the following (preceding) chapters and
        finally wraps round to this one.  Returns whether anything was found.
        """
        if not self._term:
            return False
        flags = _BACKWARD if backward else _NO_FLAGS
        if self._match is not None:
            start, end = self._match
            pos = start if backward or incremental else end
        else:
            pos = self.cursorForPosition(QPoint(0, 0)).position()
        found = self.document().find(self._term, pos, flags)
        if found.isNull():
            found = self._find_in_other_chapters(backward)
        if found.isNull():
            self._rehighlight()
            return False
        self._select_match(found)
        return True

    def _find_in_other_chapters(self, backward: bool) -> QTextCursor:
        """The first match in the following chapters, wrapping round to this one.

        Shows the chapter it is found in; a null cursor when there is none.
        """
        flags = _BACKWARD if backward else _NO_FLAGS
        for chapter in _search_order(self.current_chapter(), backward):
            if not _chapter_contains(chapter, self._term):
                continue
            if chapter != self.current_chapter():
                self.show_chapter(chapter)
            doc = self.document()
            pos = doc.characterCount() - 1 if backward else 0
            found = doc.find(self._term, pos, flags)
            if not found.isNull():
                return found
        return QTextCursor()

    def _select_match(self, found: QTextCursor) -> None:
        self._match = (found.selectionStart(), found.selectionEnd())
        cursor = QTextCursor(self.document())
        cursor.setPosition(found.selectionStart())
        self.setTextCursor(cursor)  # collapsed: the highlight shows the match
        # put the match a third of the way down, not on the bottom edge
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() + self.cursorRect(cursor).top()
                     - self.viewport().height() // 3)
        self._rehighlight()

    def _rehighlight(self) -> None:
        """Paint every match, the current one stronger, and report the count."""
        selections: list[QTextEdit.ExtraSelection] = []
        current = 0
        if self._term:
            p = theme.palette()
            every = QTextCharFormat()
            every.setBackground(QColor(p["find_bg"]))
            strong = QTextCharFormat()
            strong.setBackground(QColor(p["find_current_bg"]))
            doc = self.document()
            found = doc.find(self._term, 0)
            while not found.isNull() and len(selections) < _MAX_HIGHLIGHTS:
                span = (found.selectionStart(), found.selectionEnd())
                selection = QTextEdit.ExtraSelection()
                selection.cursor = found
                selection.format = strong if span == self._match else every
                selections.append(selection)
                if span == self._match:
                    current = len(selections)
                found = doc.find(self._term, found)
        self.setExtraSelections(selections)
        self.matchesChanged.emit(current, len(selections))

    # ---- theming -----------------------------------------------------------------
    def apply_theme(self) -> None:
        """Equations, links, boxes and highlights carry theme colours: re-render."""
        self.rerender()


def _flat_block() -> QTextBlockFormat:
    """A paragraph format that takes no vertical space (for empty spacers)."""
    fmt = QTextBlockFormat()
    fmt.setTopMargin(0)
    fmt.setBottomMargin(0)
    fmt.setLineHeight(0, QTextBlockFormat.LineHeightTypes.FixedHeight.value)
    return fmt


def _box_runs(doc: QTextDocument) -> list[tuple[str, int, int]]:
    """``(kind, start, end)`` of each run of consecutive code / quote blocks."""
    runs: list[tuple[str, int, int]] = []
    block = doc.begin()
    previous: str | None = None
    while block.isValid():
        kind = _box_kind(block)
        end = block.position() + block.length() - 1
        if kind is not None and kind == previous:
            runs[-1] = (kind, runs[-1][1], end)
        elif kind is not None:
            runs.append((kind, block.position(), end))
        previous = kind
        block = block.next()
    return runs


def _box_format(kind: str) -> QTextFrameFormat:
    """The frame around a code block or a quote (warning), in theme colours."""
    p = theme.palette()
    background, border = {
        "code": (p["code_bg"], p["code_border"]),
        "quote": (p["warn_bg"], p["warn_border"]),
    }[kind]
    fmt = QTextFrameFormat()
    fmt.setBackground(QColor(background))
    fmt.setBorder(1)
    fmt.setBorderBrush(QBrush(QColor(border)))
    fmt.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_Solid)
    fmt.setPadding(_BOX_PADDING)
    fmt.setTopMargin(_BOX_MARGIN)
    fmt.setBottomMargin(_BOX_MARGIN)
    return fmt


def _box_kind(block: QTextBlock) -> str | None:
    """``"code"`` for a line of a code block, ``"quote"`` for a block quote."""
    fmt = block.blockFormat()
    if fmt.nonBreakableLines() or fmt.hasProperty(QTextFormat.Property.BlockCodeFence):
        return "code"
    if fmt.intProperty(QTextFormat.Property.BlockQuoteLevel) > 0:
        return "quote"
    return None


# Each chapter's text as Qt renders it, for "does it contain the term?" without
# loading the chapter into the view.  Built on first search; the files are
# package data and never change while the app runs.
_SEARCH_DOCS: dict[str, QTextDocument] = {}


def _chapter_contains(chapter: manual.Chapter, term: str) -> bool:
    doc = _SEARCH_DOCS.get(chapter.relpath)
    if doc is None:
        doc = QTextDocument()
        doc.setMarkdown(manual.replace_math(chapter.text())[0])
        _SEARCH_DOCS[chapter.relpath] = doc
    return not doc.find(term).isNull()


def _search_order(
    current: manual.Chapter | None, backward: bool
) -> list[manual.Chapter]:
    """The chapters after *current* in reading order, wrapping round to it."""
    chapters = list(manual.CHAPTERS)
    if current not in chapters:
        return chapters[::-1] if backward else chapters
    i = chapters.index(current)
    if backward:
        return chapters[:i][::-1] + chapters[i:][::-1]
    return chapters[i + 1:] + chapters[: i + 1]


def _merge(cursor: QTextCursor, pos: int, length: int, fmt: QTextCharFormat) -> None:
    cursor.setPosition(pos)
    cursor.setPosition(pos + length, _KEEP)
    cursor.mergeCharFormat(fmt)


def _baseline_padded(
    image: QImage, depth: float, x_height: float, dpr: float
) -> QImage:
    """Pad *image* vertically so ``AlignMiddle`` puts its baseline on the text's.

    For an ``AlignMiddle`` inline object of height ``H``, Qt's layout puts the
    line's baseline ``(H - x_height / 2) / 2`` above the object's bottom.  The
    equation's own baseline is ``depth * h`` above its bottom, so with padding
    the two coincide when ``p_bottom - p_top = h - 2 * depth * h - x_height / 2``.
    """
    h = image.height()
    delta = h - 2 * depth * h - x_height / 2
    pad_bottom = max(round(delta), 0)
    pad_top = max(round(-delta), 0)
    fmt = QImage.Format.Format_ARGB32_Premultiplied
    padded = QImage(image.width(), h + pad_top + pad_bottom, fmt)
    padded.fill(Qt.GlobalColor.transparent)
    painter = QPainter(padded)
    painter.drawImage(0, pad_top, image)
    painter.end()
    padded.setDevicePixelRatio(dpr)
    return padded
