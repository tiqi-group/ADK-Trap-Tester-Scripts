"""The Manual panel: two columns.

Left  — Contents (green, interactive): a search field for the whole manual, one
        node per chapter with its headings nested below, back/forward buttons,
        and where a vendored chapter came from.
Right — the chapter viewer (red): :class:`ManualBrowser`.

Keys: Ctrl+F focuses the search, Enter / F3 go to the next match and
Shift+Enter / Shift+F3 to the previous, Esc clears it.  F1 on any panel opens
that panel's chapter (see ``MainWindow``), through :meth:`ManualPanel.show_topic`.

The chapters are listed in ``core.manual.CHAPTERS``.  Nothing is rendered until
the panel is first shown, so the manual costs nothing at start-up.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from trap_tester.core import manual
from trap_tester.gui.widgets.manual_browser import ManualBrowser, chapter_at

_TARGET_ROLE = Qt.ItemDataRole.UserRole  # (chapter key, slug) on each tree item
_SEARCH_DELAY_MS = 250  # typing pause before the search jumps


class _SearchField(QLineEdit):
    """A line edit that reports Enter / Shift+Enter / Esc as search commands."""

    nextRequested = Signal()
    previousRequested = Signal()
    cancelled = Signal()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.previousRequested.emit()
            else:
                self.nextRequested.emit()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.clear()
            self.cancelled.emit()
            return
        super().keyPressEvent(event)


class ManualPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._items: dict[tuple[str, str], QTreeWidgetItem] = {}
        self._browser_counts = (0, 0)
        self._syncing = False
        self._started = False

        self._browser = ManualBrowser()
        self._browser.sourceChanged.connect(self._on_source_changed)
        self._browser.matchesChanged.connect(self._on_matches_changed)
        self._search_failed = False  # the last jump found nothing anywhere

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("columns")  # session: keeps its sizes
        splitter.addWidget(self._build_contents())
        splitter.addWidget(self._build_viewer())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 900])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        for keys, slot in (
            (QKeySequence.StandardKey.Find, self.focus_search),
            (QKeySequence.StandardKey.FindNext, self._find_next),
            (QKeySequence.StandardKey.FindPrevious, self._find_previous),
        ):
            shortcut = QShortcut(keys, self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)

    # ---- columns -------------------------------------------------------------
    def _build_contents(self) -> QWidget:
        col = QWidget()
        col.setMinimumWidth(220)
        layout = QVBoxLayout(col)

        header = QLabel("Contents")
        header.setProperty("role", "interactive")
        search_row = self._build_search()

        self._tree = QTreeWidget()
        self._tree.setProperty("role", "interactive")
        self._tree.setHeaderHidden(True)
        self._tree.currentItemChanged.connect(self._on_item_changed)
        self._fill_tree()

        nav = QHBoxLayout()
        self._back = QPushButton("◀ Back")
        self._forward = QPushButton("Forward ▶")
        for btn in (self._back, self._forward):
            btn.setProperty("role", "interactive")
            btn.setEnabled(False)
            nav.addWidget(btn)
        self._back.clicked.connect(self._browser.backward)
        self._forward.clicked.connect(self._browser.forward)
        self._browser.backwardAvailable.connect(self._back.setEnabled)
        self._browser.forwardAvailable.connect(self._forward.setEnabled)

        self._source_label = QLabel()
        self._source_label.setWordWrap(True)
        self._source_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        layout.addWidget(header)
        layout.addLayout(search_row)
        layout.addWidget(self._search_status)
        layout.addWidget(self._tree, 1)
        layout.addLayout(nav)
        layout.addWidget(self._source_label)
        return col

    def _build_search(self) -> QHBoxLayout:
        """The search field and its previous / next buttons (status label apart)."""
        self._search = _SearchField()
        self._search.setProperty("role", "interactive")
        self._search.setPlaceholderText("Search the manual (Ctrl+F)")
        self._search.setClearButtonEnabled(True)
        self._search.setToolTip(
            "Searches every chapter, ignoring case.\n"
            "Enter / F3: next match · Shift+Enter / Shift+F3: previous · Esc: clear"
        )
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(_SEARCH_DELAY_MS)
        self._search_timer.timeout.connect(self._search_as_typed)
        self._search.textChanged.connect(self._on_search_text)
        self._search.nextRequested.connect(self._find_next)
        self._search.previousRequested.connect(self._find_previous)
        self._search.cancelled.connect(self._browser.setFocus)
        self._prev_match = QPushButton("▲")
        self._next_match = QPushButton("▼")
        for btn, tip, slot in (
            (self._prev_match, "Previous match (Shift+Enter, Shift+F3)",
             self._find_previous),
            (self._next_match, "Next match (Enter, F3)", self._find_next),
        ):
            btn.setProperty("role", "interactive")
            btn.setToolTip(tip)
            btn.setFixedWidth(32)
            btn.setEnabled(False)
            btn.clicked.connect(slot)
        search_row = QHBoxLayout()
        search_row.addWidget(self._search, 1)
        search_row.addWidget(self._prev_match)
        search_row.addWidget(self._next_match)
        self._search_status = QLabel()
        self._search_status.setWordWrap(True)
        self._search_status.setVisible(False)
        return search_row

    def _build_viewer(self) -> QWidget:
        self._viewer_box = QGroupBox("Manual")
        self._viewer_box.setProperty("role", "viewer")
        inner = QVBoxLayout(self._viewer_box)
        inner.addWidget(self._browser)

        wrapper = QWidget()
        wl = QVBoxLayout(wrapper)
        wl.addWidget(self._viewer_box)
        return wrapper

    def _fill_tree(self) -> None:
        """One top-level node per chapter; its headings nested by level.

        A chapter's leading H1 is its title, so it is folded into the chapter node
        rather than repeated as the only child.
        """
        for chapter in manual.CHAPTERS:
            top = QTreeWidgetItem([chapter.title])
            top.setData(0, _TARGET_ROLE, (chapter.key, ""))
            self._tree.addTopLevelItem(top)
            self._items[(chapter.key, "")] = top

            found = manual.headings(chapter.text())
            if found and found[0].level == 1:
                found = found[1:]
            stack: list[tuple[int, QTreeWidgetItem]] = [(0, top)]
            for heading in found:
                while stack[-1][0] >= heading.level:
                    stack.pop()
                item = QTreeWidgetItem(stack[-1][1], [heading.text])
                item.setData(0, _TARGET_ROLE, (chapter.key, heading.slug))
                self._items[(chapter.key, heading.slug)] = item
                stack.append((heading.level, item))
            top.setExpanded(True)

    # ---- behaviour -------------------------------------------------------------
    def show_topic(self, key: str, slug: str = "") -> None:
        """Open chapter *key* (``core.manual.CHAPTERS``), at heading *slug*."""
        chapter = next((c for c in manual.CHAPTERS if c.key == key), None)
        if chapter is None:
            return
        self._started = True  # the first show must not replace it with chapter 1
        self._browser.show_chapter(chapter, slug)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._started:
            self._started = True
            self._browser.show_chapter(manual.CHAPTERS[0])

    def _on_item_changed(self, current: QTreeWidgetItem | None, _previous) -> None:
        if self._syncing or current is None:
            return
        key, slug = current.data(0, _TARGET_ROLE)
        chapter = next(c for c in manual.CHAPTERS if c.key == key)
        self._browser.show_chapter(chapter, slug)

    def _on_source_changed(self, url: QUrl) -> None:
        """Keep the tree, the viewer title and the source note on the shown spot."""
        chapter = chapter_at(url)  # not source(): Qt can emit before updating it
        if chapter is None:
            return
        self._viewer_box.setTitle(chapter.title)
        self._source_label.setText(_source_note(chapter))
        item = self._items.get((chapter.key, url.fragment())) or self._items.get(
            (chapter.key, "")
        )
        if item is not None and item is not self._tree.currentItem():
            self._syncing = True
            try:
                self._tree.setCurrentItem(item)
            finally:
                self._syncing = False

    # ---- search ------------------------------------------------------------------
    def focus_search(self) -> None:
        self._search.setFocus()
        self._search.selectAll()

    def _on_search_text(self, text: str) -> None:
        """Highlight at once; jump to a match once typing pauses."""
        self._search_failed = False
        self._browser.set_search(text.strip())
        has_term = bool(text.strip())
        self._prev_match.setEnabled(has_term)
        self._next_match.setEnabled(has_term)
        if has_term:
            self._search_timer.start()
        else:
            self._search_timer.stop()

    def _search_as_typed(self) -> None:
        self._jump(backward=False, incremental=True)

    def _find_next(self) -> None:
        self._search_timer.stop()
        self._jump(backward=False)

    def _find_previous(self) -> None:
        self._search_timer.stop()
        self._jump(backward=True)

    def _jump(self, backward: bool, incremental: bool = False) -> None:
        if not self._search.text().strip():
            return
        found = self._browser.find_next(backward=backward, incremental=incremental)
        self._search_failed = not found
        self._on_matches_changed(*self._browser_counts)

    def _on_matches_changed(self, current: int, total: int) -> None:
        self._browser_counts = (current, total)
        term = self._search.text().strip()
        if not term:
            self._search_status.setVisible(False)
            return
        if self._search_failed:
            text = "Not found anywhere in the manual."
        elif total and current:
            text = f"Match {current} of {total} in this chapter."
        elif total:
            text = f"{total} match(es) in this chapter."
        else:
            text = "No match in this chapter."
        self._search_status.setText(text)
        self._search_status.setVisible(True)

    def smoke_test(self) -> None:
        """Render every chapter once (used by ``--smoke-test`` on frozen builds)."""
        for chapter in manual.CHAPTERS:
            self._browser.show_chapter(chapter)
            if self._browser.current_chapter() != chapter:
                raise RuntimeError(f"manual chapter {chapter.relpath} did not load")
            # Laying the document out loads its figures and renders its equations.
            self._browser.document().documentLayout().documentSize()
        # search: a term in several chapters is found, and found again after
        # the chapter it was first found in runs out of matches
        self._browser.set_search("mapping")
        for _ in range(40):
            if not self._browser.find_next():
                raise RuntimeError("manual search found nothing for 'mapping'")
        self._browser.set_search("")
        self._started = True
        self._browser.show_chapter(manual.CHAPTERS[0])  # where a first show lands


def _source_note(chapter: manual.Chapter) -> str:
    info = chapter.source_info()
    if not info:
        return ""
    commit = str(info.get("commit", ""))[:7]
    date = str(info.get("commit_date", ""))[:10]
    return f"Copied from {_repo_name(info.get('repository', ''))} at {commit} ({date})."


def _repo_name(remote: str) -> str:
    """``git@github.com:org/Repo.git`` / ``https://.../Repo.git`` -> ``Repo``."""
    name = remote.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    return name.removesuffix(".git") or "the source repository"
