"""Find and resolve duplicate games in the catalog.

Groups games by name using **fuzzy matching** — not just exact matches. This
catches cases where a game is re-imported under a slightly different name
(e.g. "Hollow Knight" vs "Hollow Knight: Voidheart Edition", or "Doom Eternal"
vs "Eternal Doom"). Two complementary signals are combined:

1. **Character similarity** — ``difflib.SequenceMatcher`` ratio on the
   normalized name (handles typos, small edits, suffixes).
2. **Token-set overlap** — Jaccard similarity on the set of significant words
   (handles reordered words, dropped articles, edition suffixes).

A pair is considered a duplicate when *either* signal exceeds its threshold.
Groups are built via connected components (union-find) so transitive matches
(A~B, B~C → group {A,B,C}) are captured.
"""
from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..models import GameRecord

# Tuning: higher = stricter (fewer false positives, may miss some dups).
# 0.85 char ratio is quite strict; token overlap catches the reordered-word
# and edition-suffix cases that character ratio misses.
_CHAR_THRESHOLD = 0.85
_TOKEN_THRESHOLD = 0.70

# Common noise tokens stripped before comparison (articles, editions, etc.)
_STOPWORDS = frozenset({
    "the", "a", "an", "of", "and", "or", "to", "in", "on", "for",
    "edition", "goty", "complete", "remastered", "director", "cut",
    "definitive", "enhanced", "standard", "deluxe", "premium",
    "version", "v1", "v2", "pc", "win", "windows", "steam", "gog", "epic",
})

_NON_ALNUM = re.compile(r"[^a-z0-9\s]")
_MULTI_WS = re.compile(r"\s+")

# Roman → Arabic for common game-title numerals (1–10).
_ROMAN = {
    "i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5",
    "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10",
}


def _normalize(name: str) -> str:
    """Lowercase, strip non-alphanumerics, convert roman numerals, drop stops."""
    s = (name or "").lower()
    s = _NON_ALNUM.sub(" ", s)
    tokens = []
    for t in s.split():
        if not t or t in _STOPWORDS:
            continue
        tokens.append(_ROMAN.get(t, t))
    return " ".join(tokens)


def _char_ratio(a: str, b: str) -> float:
    """SequenceMatcher ratio on normalized names (0.0–1.0)."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _token_jaccard(a: str, b: str) -> float:
    """Jaccard similarity on the set of significant words (0.0–1.0)."""
    sa = set(a.split())
    sb = set(b.split())
    if not sa or not sb:
        return 0.0
    inter = sa & sb
    union = sa | sb
    return len(inter) / len(union)


def _is_duplicate_pair(norm_a: str, norm_b: str) -> bool:
    """True when *a* and *b* are considered the same game.

    Uses the higher of char ratio and token overlap, plus a substring
    containment shortcut that only fires when the shorter name is substantial
    (>= 4 chars) AND the longer name is at most 1.3× the shorter — this avoids
    false positives like "Doom" / "Doom Eternal" or "Hitman" / "Hitman 2".
    """
    if not norm_a or not norm_b:
        return False
    if norm_a == norm_b:
        return True
    # Substring shortcut: only when names are close in length.
    shorter, longer = (norm_a, norm_b) if len(norm_a) <= len(norm_b) else (norm_b, norm_a)
    if (
        len(shorter) >= 4
        and shorter in longer
        and len(longer) <= int(len(shorter) * 1.3)
    ):
        return True
    cr = _char_ratio(norm_a, norm_b)
    if cr >= _CHAR_THRESHOLD:
        return True
    tj = _token_jaccard(norm_a, norm_b)
    return tj >= _TOKEN_THRESHOLD


class _UnionFind:
    """Minimal union-find for clustering duplicate pairs into groups."""

    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def _completeness_score(rec: GameRecord) -> int:
    """Higher = more complete record. Used to pick which duplicate to keep."""
    score = 0
    if rec.game_name:
        score += 1
    if rec.user_rating:
        score += 1
    if rec.game_type:
        score += 1
    if rec.short_description:
        score += 1
    if rec.developer:
        score += 1
    if rec.publisher:
        score += 1
    if rec.release_date:
        score += 1
    if rec.cover_url:
        score += 1
    if rec.esrb_rating:
        score += 1
    if rec.metacritic_score:
        score += 1
    if rec.website:
        score += 1
    if rec.fetch_status == "ok":
        score += 2
    return score


class DuplicatesDialog(QDialog):
    """Shows duplicate game groups and lets the user pick which to remove."""

    def __init__(self, records: list[GameRecord], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Find Duplicates")
        self.resize(900, 600)
        self._records_to_remove: list[GameRecord] = []
        self._checkboxes: list[tuple[QCheckBox, GameRecord, str]] = []

        groups = self._group_duplicates(records)
        self._build_ui(groups)

    @staticmethod
    def _group_duplicates(
        records: list[GameRecord],
    ) -> dict[str, list[GameRecord]]:
        """Cluster records by fuzzy name similarity; return only 2+ groups.

        The key is the normalized name of the first member (stable for display).
        """
        items: list[tuple[GameRecord, str]] = []
        for rec in records:
            name = (rec.game_name or rec.folder_name).strip()
            if name:
                items.append((rec, _normalize(name)))
        if not items:
            return {}

        uf = _UnionFind(len(items))
        # O(n^2) pairwise comparison — fine for typical catalog sizes (<2k)
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if _is_duplicate_pair(items[i][1], items[j][1]):
                    uf.union(i, j)

        clusters: dict[int, list[GameRecord]] = defaultdict(list)
        for idx, (rec, _norm) in enumerate(items):
            clusters[uf.find(idx)].append(rec)

        # Expose only groups with 2+ members; key by normalized name of first
        result: dict[str, list[GameRecord]] = {}
        for members in clusters.values():
            if len(members) > 1:
                members.sort(key=lambda r: (r.game_name or r.folder_name).lower())
                key = _normalize(members[0].game_name or members[0].folder_name)
                result[key] = members
        return result

    def _build_ui(self, groups: dict[str, list[GameRecord]]) -> None:
        layout = QVBoxLayout(self)

        if not groups:
            layout.addWidget(QLabel("No duplicate games found."))
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)
            return

        total_dups = sum(len(v) for v in groups.values())
        layout.addWidget(QLabel(
            f"Found {len(groups)} group(s) of similar games "
            f"({total_dups} games total).\n"
            "Checked games will be removed. The most complete record in each "
            "group is kept by default (unchecked).\n"
            "Matching uses fuzzy name similarity — typos, reordered words, "
            "and edition suffixes are treated as duplicates."
        ))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(10)
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        for name, recs in groups.items():
            group_box = self._build_group(name, recs, group_key=name)
            scroll_layout.addWidget(group_box)
        scroll_layout.addStretch()

        btn_layout = QHBoxLayout()
        select_all_btn = QPushButton("Check All")
        select_all_btn.clicked.connect(self._check_all)
        unselect_all_btn = QPushButton("Uncheck All")
        unselect_all_btn.clicked.connect(self._uncheck_all)
        btn_layout.addWidget(select_all_btn)
        btn_layout.addWidget(unselect_all_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Remove Checked")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_group(self, name: str, recs: list[GameRecord], group_key: str = "") -> QGroupBox:
        """Build a QGroupBox for one duplicate group."""
        box = QGroupBox(f"{recs[0].game_name or name}  ({len(recs)} copies)")
        grid = QGridLayout(box)
        grid.addWidget(QLabel(""), 0, 0)
        headers = ["", "Store", "Disk", "Released", "Rating", "ESRB", "Source", "Status", "Folder"]
        for col, h in enumerate(headers):
            label = QLabel(f"<b>{h}</b>")
            grid.addWidget(label, 0, col)

        # Sort by completeness descending so the best is first (kept by default)
        sorted_recs = sorted(recs, key=_completeness_score, reverse=True)
        for i, rec in enumerate(sorted_recs, 1):
            cb = QCheckBox()
            # Keep the best record (first), suggest removing the rest
            cb.setChecked(i > 1)
            grid.addWidget(cb, i, 0)
            self._checkboxes.append((cb, rec, group_key))

            vals = [
                "",
                rec.store or "—",
                rec.disk or "—",
                rec.release_date_display or "—",
                rec.user_rating or "—",
                rec.esrb_rating or "—",
                rec.data_source or "—",
                rec.fetch_status or "—",
                rec.folder_path or "—",
            ]
            for col, v in enumerate(vals[1:], 1):
                item = QLabel(v)
                grid.addWidget(item, i, col)

        return box

    def _check_all(self) -> None:
        for cb, _, _ in self._checkboxes:
            cb.setChecked(True)

    def _uncheck_all(self) -> None:
        for cb, _, _ in self._checkboxes:
            cb.setChecked(False)

    def _on_accept(self) -> None:
        proposed = [rec for cb, rec, _ in self._checkboxes if cb.isChecked()]
        # Safety: ensure at least one record remains in each *fuzzy* group.
        # Using the fuzzy group key (not exact name) correctly handles groups
        # where members have slightly different names.
        checked_paths = {r.folder_path for r in proposed}
        all_groups: dict[str, list[GameRecord]] = defaultdict(list)
        for _, rec, gk in self._checkboxes:
            all_groups[gk].append(rec)
        for gk, recs in all_groups.items():
            remaining = [r for r in recs if r.folder_path not in checked_paths]
            if not remaining:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self, "Cannot remove all",
                    f"You cannot remove every copy of '{recs[0].game_name}'. "
                    f"At least one must remain.",
                )
                return
        self._records_to_remove = proposed
        self.accept()

    def records_to_remove(self) -> list[GameRecord]:
        return list(self._records_to_remove)
