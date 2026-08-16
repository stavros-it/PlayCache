# Roadmap

> Living document of planned work, priorities, and ideas. Items are grouped by
> theme and roughly ordered within each group. Nothing here is committed until
> it becomes a task and is implemented.
>
> Status legend: **🔍 exploring** · **📋 planned** · **🚧 in progress** · **✅ done**

## Current state (v1.0.0)

- ✅ PySide6 GUI with sortable/filterable table, detail panel, scan dialog
- ✅ Folder scanning with library-root descent, smart name detection, store detection
- ✅ Smart game-name detection — 6-priority chain (Steam manifest → GOG metadata →
  GOG setup .exe → folder name → largest non-launcher .exe → folder name fallback)
- ✅ Disk conflict detection during scan — pauses and prompts user (new / old / both)
- ✅ TheGamesDB primary + RAWG fallback with fuzzy matching and retry/backoff
- ✅ RAWG merge step — fills numeric rating, Metacritic, cover, website after TGDB
- ✅ ESRB age ratings from TheGamesDB (stored in `esrb_rating` column)
- ✅ Cover images from TheGamesDB boxart (`include=boxart`) — no RAWG dependency
- ✅ SQLite storage with `v_excel` view matching `Game_Library.xlsx`
- ✅ Manual overrides — user edits persist across rescans
- ✅ Manual game adding — "Add Game…" toolbar button (Ctrl+N), no folder required
- ✅ Multi-row selection (Ctrl/Shift) with bulk re-fetch and bulk delete
- ✅ Auto-resizing table columns (Excel-like AutoFit) with header context menu
- ✅ Custom sort keys — Game (case-insensitive), Released (chronological),
  Rating (numeric) despite display format
- ✅ Disk column — shows volume label + drive letter per game
- ✅ Released column — release date in DD-MM-YYYY (Greek regional format)
- ✅ ESRB column in table — age ratings from TheGamesDB
- ✅ TGDB quota tracking — status bar shows `TGDB: N/1000` with reset-timer tooltip
- ✅ App icon (custom multi-resolution `.ico`) in window title, taskbar, Alt-Tab
- ✅ Async cover-image loading with disk cache
- ✅ Excel export, settings dialog, context menu (re-fetch / open folder / delete)
- ✅ Backup/Restore — compressed JSON (`.json.gz`) catalog snapshots. "Backup…"
  (Ctrl+B) exports the full catalog with a versioned envelope
  (`format_version`, `app_version`, `exported_at`, `count`). "Restore…"
  (Ctrl+I) imports with merge (upsert by `folder_path`) or replace-all mode.
  Forward/backward compatible (unknown columns ignored, missing columns get
  defaults). Uses only stdlib `gzip` + `json` — no extra deps.
- ✅ Find Duplicates… (Ctrl+D) — fuzzy name matching (char similarity + token
  Jaccard + substring + Roman numerals), suggests which copies to remove, bulk-delete
- ✅ Polished Stats dialog — metric cards (totals + completeness) and bar charts
  (status, source, platform, store, ESRB, disk, release year), color-coded status bars.
  "By disk" chart shows **volume labels** (e.g. "TOSHIBA 2TB") instead of drive letters.
  Smart in-bar text color via WCAG luminance (white on dark fills, dark slate on light).
- ✅ About dialog + copyright info — app icon, version, "© 2026 Stavros Antoniou"
  in toolbar About dialog and a permanent label in the status bar.
- ✅ Full dark theme — centralized palette in `playcache/gui/theme.py` (slate-based,
  eye-friendly). Applied to main window, table, filters, detail panel, scrollbars,
  menus, toolbars, inputs. Zebra striping + indigo selection state.
- ✅ Smart table row coloring — `GamesItemDelegate` renders the Status column as a
  colored badge (green=ok, amber=not_found, red=error, blue=pending) with smart
  contrast text (WCAG luminance). Source column gets a subtle accent color.
- ✅ App launches maximized — `showMaximized()` in `run.py` and `run.pyw`.
- ✅ Default alphabetical sort — Game column (col 0) sorted ascending on startup;
  case-insensitive so "portal" doesn't sort after "Half-Life".
- ✅ Code audit pass (2026-08-16) — 30+ bugs and improvements fixed across
  all layers (see PROJECT_CONTEXT.md §9 for the full list). Highlights:
  search query no longer strips hyphens/years from game titles; scanner has
  symlink cycle protection and Steam manifest caching; cataloger preserves
  overrides on conflict-replace and survives single-game failures; table edits
  persist to DB; image cache validates before caching and cancels in-flight on
  clear; API clients honor Retry-After and don't retry 4xx; settings use atomic
  writes; main window guards against concurrent workers and client-swap races.
- ✅ 103 tests passing, ruff clean

## Priorities

The themes below are ordered by my current judgment of value-to-effort. Pick
from the top of each list first; reorder if priorities change.

---

## 1. Robustness & real-world validation

The app was built in a sandbox with blocked network. First priority is making
sure it holds up against live APIs and real game libraries.

- **📋 Live API integration test** — add an opt-in test (gated by an env var
  like `RUN_LIVE_API_TESTS=1`) that hits RAWG/TheGamesDB with a known game
  (e.g. "Hollow Knight") and asserts the response shape matches what the
  clients parse. Skip by default so CI stays network-free.
- **📋 RAWG response-shape audit** — run one real scan against a live RAWG key
  and confirm every field parsed in `rawg_client.py::_apply` is present and
  correctly typed. Fix any schema drift.
- **📋 TheGamesDB response-shape audit** — same, for the fallback path.
  The `include` block (genres/developers/publishers as id→name maps) is the
  most likely place for surprises.
- **📋 Error reporting in UI** — surface `fetch_message` somewhere visible
  (a "Problems" filter or a tooltip) so users can see *why* a game is
  `not_found` without opening the DB.
- **📋 Rate-limit handling** — the current 0.3s delay is hardcoded; consider
  respecting `Retry-After` headers on 429s (currently we just back off
  exponentially).

## 2. UX polish

The functional core is solid; these make the app feel professional.

- **✅ Dark mode** — full dark theme via a centralized palette in
  `playcache/gui/theme.py` (slate-based for eye comfort). Covers toolbar,
  splitter, inputs, table (zebra striping + indigo selection), headers,
  scrollbars, menus, group boxes, checkboxes, progress bars, status bar.
  Hover states use slate-600 with indigo accent borders on focus.
- **📋 Column visibility** — let users hide/show columns and persist their
  layout (header state via `QHeaderView.saveState()` to `config.ini`).
  *(Auto-fit sizing is done; only visibility/persistence remains.)*
- **✅ Multi-row re-fetch** — extend the context menu to "Re-fetch selected"
  with a count. Single-row stays synchronous; 2+ rows use the background worker.
- **✅ Bulk delete** — same, for the delete action.
- **📋 Double-click to open** — double-clicking a row should open the game
  folder in Explorer (currently right-click only).
- **📋 Keyboard navigation** — ensure Up/Down/PageUp/PageDown work in the
  table and refresh the detail panel; add `Enter` to open folder.
- **📋 Cover image in table** — optional small thumbnail column (would need
  a `QStyledItemDelegate` for performance). Should be opt-in to keep memory
  low for large libraries.
- **📋 Progress for "Rescan All"** — `_run_refetch_all` currently only updates
  the status bar; wire it to a real `QProgressBar` like the scan dialog does.
- **📋 Cancel button for "Rescan All"** — the worker supports `cancel()` but
  the UI doesn't expose it during a full rescan.
- **✅ Polished Stats dialog** — replaced the plain `QMessageBox` text dump with
  a dedicated dialog: metric cards (total, with metadata, with cover, with
  release date, with ESRB, with Metacritic, manually edited) and horizontal bar
  charts for status / source / platform / store / ESRB / disk / release year.
  Status bars are color-coded (green=ok, amber=not_found, red=error).
- **✅ Smart text color (WCAG)** — in-bar labels pick white or dark slate text
  based on the fill color's luminance, so green/amber/yellow bars get dark text
  (was unreadable with hardcoded white). Crossover at luminance 0.20.
- **✅ Smart table row coloring** — `GamesItemDelegate` renders the Status
  column as a colored rounded badge with smart contrast text. The Source
  column gets a subtle accent color (indigo for TGDB, sky for RAWG).
- **✅ Launch maximized** — `showMaximized()` in both `run.py` and `run.pyw`.
- **✅ Default alphabetical sort** — Game column sorted ascending on startup,
  case-insensitive (with stable tiebreak).

## 3. Data model & matching

- **📋 Manual override UI** — there's no way to *clear* an override from the
  GUI. Add a "Reset to API value" button in the detail panel that calls
  `db.clear_override()` and re-fetches. The README already mentions this gap.
- **📋 Better platform detection** — currently Windows-only guesses. Add
  macOS (`/Applications`, `~/Library/Application Support/Steam/steamapps/common`)
  and Linux (`~/.steam/steam/steamapps/common`) roots and skip folders.
- **✅ Manual game add** — let the user add a game by typing its name, without
  a folder on disk. Useful for cataloguing games not currently installed.
  Implemented as "Add Game…" (Ctrl+N) with a synthetic `/manual/<name>` path.
- **📋 Search-only games** — for `not_found` games, a "Search RAWG manually"
  button that opens a small picker showing the top 10 RAWG results and lets
  the user choose one to fetch in full.
- **📋 Alternate titles / disambiguation** — store `alternative_names` from
  RAWG and use them as additional fuzzy-match candidates.

## 4. Performance

- **📋 Image cache pruning** — `ImageCache.clear()` exists but isn't wired to
  the UI. Add a "Clear cover cache" button to Settings and/or an auto-prune
  based on a max size (e.g. LRU eviction over 200MB).
- **📋 Concurrent API requests** — scans are currently sequential. Use a small
  thread pool (3–4 workers) inside `Cataloger` to parallelise RAWG/TheGamesDB
  fetches. Must respect the rate limit across all workers (shared token bucket).
- **📋 Virtualized table** — the `QTableView` will be sluggish past ~2,000
  rows. Consider `QAbstractTableModel` fetching rows lazily from SQLite
  instead of loading all records into memory.

## 5. Storage & export

- **📋 CSV export** — add a "Export to CSV" toolbar item alongside Excel.
  Trivial to add (the `v_excel` view is already right there).
- **📋 JSON export** — for interop with other tools; one game = one object.
- **✅ Backup/Restore** — compressed JSON (`.json.gz`) catalog snapshots.
  "Backup…" (Ctrl+B) and "Restore…" (Ctrl+I) in the toolbar. Merge (upsert)
  or replace-all mode. Versioned envelope for forward/backward compat.
- **📋 Import from existing catalog** — let users import their existing
  `Game_Library.xlsx` into the DB (currently the round-trip is only tested
  in code, not exposed in the UI).
- **📋 Backup/restore** — a "Backup database…" menu item that copies the
  `.db` file to a timestamped path. Useful before big rescans.
- **📋 Schema versioning** — replace the ad-hoc `_migrate()` with a proper
  `schema_version` table and ordered migration scripts. Needed if the schema
  keeps evolving.

## 6. Code health & infrastructure

- **📋 First commit** — the repo has zero commits. Establish `main` with the
  current tree and a clean `.gitignore` (already in place).
- **📋 CI workflow** — GitHub Actions running `ruff check` + `pytest` on push.
  Use `QT_QPA_PLATFORM=offscreen` so GUI imports work headless.
- **📋 `pyproject.toml`** — migrate from ad-hoc files to a modern
  `pyproject.toml` with `[project]`, `[tool.ruff]`, `[tool.pytest.ini_options]`.
  Consider making `playcache` an installable package.
- **📋 Type checking** — add `mypy` or `pyright` to CI. The codebase is fully
  type-hinted so this should be low-friction.
- **📋 Logging configuration** — add a `--verbose` / `-v` flag and a file
  logger (`logs/catalog.log`) so users can share diagnostics.
- **✅ App icon + window title** — custom multi-resolution `.ico` (16–256px)
  in window title bar, taskbar, and Alt-Tab. Desktop shortcut generator included.
  Generated via `scripts/make_icon.py` (QPainter-rendered "vault dial + play
  button" mark in indigo gradient).

## 7. Packaging & distribution

- **📋 PyInstaller / Nuitka build** — produce a single `.exe` for distribution
  to non-developer users. Must bundle PySide6 plugins and handle the
  `QT_QPA_PLATFORM` fallback.
- **📋 Windows installer** — wrap the `.exe` in an Inno Setup or WiX installer
  with Start Menu shortcuts and an uninstaller.
- **📋 Auto-update** — long-term, a "Check for updates" feature. Out of scope
  for v1.x but worth planning the architecture now.

## 8. Exploratory / nice-to-have

- **🔍 IGDB integration** — add IGDB (Twitch) as a third data source, between
  RAWG and TheGamesDB in the fallback chain. Rich data but requires OAuth.
- **🔍 HowLongToBeat integration** — fetch completion-time estimates and show
  them in the detail panel.
- **🔍 Tags / collections** — user-defined tags for organising games
  (e.g. "Finished", "Want to play", "Co-op"). Would need a `tags` table and
  a many-to-many join.
- **🔍 Playtime tracking** — read Steam playtime from `steamapps` manifests
  and display it alongside the rating.
- **🔍 Extended charts** — extend the Stats dialog with a ratings histogram,
  genres distribution, and a completion-over-time chart. (Basic bar charts for
  status / source / platform / store / ESRB / disk / release year are done.)
- **🔍 Watch mode** — a tray icon that re-scans a drive on startup or on
  a schedule, so the catalog stays current.

---

## Decision log

A chronological record of significant product decisions. Add new entries at
the top so the most recent context is first.

### 2026-08-16 — Compressed JSON backup/restore
Added catalog backup and restore via **compressed JSON** (`.json.gz`):
- **`playcache/backup.py`** — `export_backup(db, path)` serializes every row
  (all 22 columns) to a gzip-compressed JSON file. `import_backup(db, path,
  replace_all=False)` reads it back and upserts each row.
- **Format**: versioned envelope `{format_version, app_version, exported_at,
  count, games: [...]}`. Current version is 1. Future format changes can
  branch on `format_version` in `import_backup`. Versions newer than the
  running app's `FORMAT_VERSION` are rejected with a clear "upgrade" message;
  older versions import fine (unknown columns ignored, missing columns get
  dataclass defaults).
- **Merge vs. replace**: import defaults to **merge** (upsert by
  `folder_path` — existing rows overwritten, rows not in the backup left
  untouched). If the DB already has games, the user is prompted: "Replace
  all" (delete everything first) or "Merge". An empty DB skips the prompt.
- **Why JSON not the .db file?** JSON is human-readable, diffable, and
  schema-tolerant — a backup from v1.0 imports cleanly into v1.5 even if
  columns were added. Copying the raw `.db` file would break on schema
  changes (missing columns, type mismatches).
- **Why gzip?** Stdlib-only, universal, ~5-10× compression on JSON (a 1000-
  game catalog is ~300KB raw → ~40KB compressed). No extra dependencies.
- **Toolbar**: "Backup…" (Ctrl+B) and "Restore…" (Ctrl+I), next to the
  existing Excel export.
- **Tests**: 16 tests in `test_backup.py` cover export, round-trip, merge,
  replace-all, bad envelopes, corrupt gzip, legacy columns, missing columns,
  and skipped rows.

### 2026-08-16 — Launch maximized + default alphabetical sort
Two UX changes to make the app feel more polished on first launch:
- **Maximized window** — `run.py` and `run.pyw` now call `window.showMaximized()`
  instead of `window.show()`. The `resize(1280, 800)` in `MainWindow.__init__`
  is kept as the fallback size for when the user un-maximizes.
- **Default sort** — `self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)`
  is called right after `setSortingEnabled(True)`, so the Game column is sorted
  ascending on startup. The sort persists across model resets because the proxy
  re-applies it on `endResetModel`.
- **Case-insensitive Game sort** — added a custom `lessThan` branch for the Game
  column (col 0) that compares `.lower()` versions. Without this, Qt's default
  string comparison is case-sensitive, so "portal" would sort *after* "Half-Life"
  (lowercase letters have higher ASCII codes than uppercase). Includes a stable
  tiebreak (`left.row() < right.row()`) so games with identical names preserve
  their original order.

### 2026-08-16 — Full dark theme + smart table coloring
Replaced the per-dialog duplicated color palettes with a centralized
`playcache/gui/theme.py` module. All dark-theme colors (backgrounds, text,
accents, status semantics) live in one place; dialogs import from it so
changing a color updates everywhere. **Slate-based** cool grays (not pure
black) reduce eye strain — pure black at full screen brightness is harsh;
slate-800 (`#1F2937`) feels softer and more "premium".

**Smart text color via WCAG luminance** — `contrast_text(bg_hex)` computes the
fill's relative luminance and returns white or dark slate (`#0F172A`) based on
which has the higher contrast ratio. The crossover (0.20) is the mathematical
equality point, so every color gets the optimal choice — green/amber/yellow
bars get dark text (was unreadable with white), indigo/blue/gray keep white.

**Table zebra striping (subtle, not distracting)** — even rows: slate-800,
alternate rows: slate-700 variant (slightly lighter), selected: indigo-800,
selected-alt: indigo-900. The contrast between zebra rows is intentionally
very subtle (~5% lightness difference) so it doesn't fatigue the eyes.

**Status column = colored badge** — `GamesItemDelegate` renders the Status
column as a rounded pill badge with the semantic color (green=ok,
amber=not_found, red=error, blue=pending, gray=none) and smart contrast text.
The user can scan scan results at a glance — failed rows literally glow red.

**Source column = subtle accent text** — "thegamesdb" → indigo-400, "rawg" →
sky-400, others → default text. Adds visual variety without being noisy.

**Full dark theme QSS** — covers toolbar, splitter handles, inputs (combo/spin/
lineedit), table view + headers, scrollbars (slim, rounded, indigo on hover),
menus, group boxes, checkboxes, progress bars, status bar. Hover states use
`BG_HOVER` (slate-600) with indigo accent borders on focus.

Removed the duplicated palette constants from `stats_dialog.py` and
`about_dialog.py` — both now import from `theme.py`.

### 2026-08-16 — Full code audit (5 subagents, 30+ fixes)
Launched 5 parallel audit agents (data layer, API clients, scanner+cataloger,
GUI modules, image_cache+exporter+run scripts). Each agent did a deep read of
its files and reported bugs/improvements with file:line references and
suggested fixes. All confirmed issues were then applied in a single pass.

**Critical bugs fixed (data loss / crashes / incorrect behavior):**
- `clean_search_query` was stripping everything after ASCII hyphens, breaking
  searches for "Half-Life", "Counter-Strike", etc. Now only strips colon,
  en-dash, or spaced-hyphen subtitles.
- `clean_folder_name` was stripping standalone 4-digit years, breaking
  "Cyberpunk 2077", "Battlefield 1942". Years are now preserved (release-year
  tags in brackets are still stripped).
- `_clean_gog_setup_name` used `.title()` which mis-capitalizes apostrophes
  ("Assassin's" → "Assassin'S"). Switched to `capwords`.
- `table_model.setData` only updated in-memory — edits were lost on next
  refresh. Added a `fieldEdited` signal that `MainWindow` connects to
  `db.set_field`.
- Cataloger lost manual overrides when the user chose "new" (replace) on a
  disk conflict — now migrates overrides from the old entry before deletion.
- Cataloger aborted the entire scan on a single-game fetch exception. Now
  wraps each game in try/except, marks the record as error, and continues.
- `_resolve` could infinite-loop on NTFS junctions / symlink cycles. Added a
  visited-set of real paths.
- `_read_steam_manifest` was O(N²) — re-read every manifest for every game.
  Now caches parsed manifests per `steamapps/` dir.
- `_read_gog_metadata` could return a DLC name instead of the base game (GOG
  folders often contain multiple `goggame-*.info` files). Now prefers the
  entry whose filename ID matches its JSON `gameId`.
- Image cache validated data AFTER writing to disk — corrupt responses
  poisoned the cache and triggered redundant re-downloads forever. Now
  validates before persisting and removes corrupt cache files.
- `ImageCache.clear()` didn't abort in-flight requests, so files reappeared
  after clearing. Now aborts pending replies first.
- Duplicates safety check used exact-name grouping instead of fuzzy grouping,
  which could wrongly block removal of all variants or fail to protect a
  real fuzzy group. Now tracks the fuzzy group key per checkbox.
- Duplicates substring heuristic flagged "Doom"/"Doom Eternal" as duplicates.
  Tightened to require the shorter name to be ≥4 chars and the longer ≤1.3×
  the shorter.
- Settings dialog mutated the in-memory config BEFORE writing to disk — a
  failed write left config inconsistent with the file. Now uses atomic write
  (temp file + replace) and only mutates config after success. Also uses
  `Config.config_path` instead of CWD.
- Main window could swap API clients while a worker thread was mid-scan
  (race on `self.rawg`/`self.tgdb`). Now guards against running workers.
- Main window could start a second refetch worker while the first was still
  running (orphaning it, racing on the DB). Now checks `isRunning()` first.
- Scan dialog `_on_close` destroyed a running QThread if `wait(3000)` timed
  out (crash). Now detaches the worker (connects `finished` → `deleteLater`).
- `release_date_display` didn't actually zero-pad day/month (only worked by
  accident when input was already padded). Now uses `:02d` formatting.
- `esrb_rating` schema was nullable in new DBs but NOT NULL in migrations —
  inconsistent. Now `NOT NULL DEFAULT ''` in both.
- `by_year` accepted any 4-char string as a year (e.g. "abcd"). Now requires
  `isdigit()`.
- API clients retried 4xx errors (bad key, 404) 3 times, wasting 4s+ and
  burning TGDB quota. 4xx (except 429) is now non-retryable.
- API clients ignored `Retry-After` header on 429. Now honors it (capped 60s).
- `_load_genres` cached failures permanently (empty dict). Now leaves
  `_genres = None` on failure so the next call retries.
- `_platform_label` matched "pc" as a substring, so "PC Engine" / "PC-FX"
  were misclassified as "PC". Now matches tokens.
- RAWG `format_rating(float(rating) * 2.0)` could raise TypeError if the API
  returned a non-numeric rating. Now guards with `isinstance`.

**Improvements:**
- API clients expose `close()` for session cleanup; `MainWindow._open_settings`
  closes old clients before replacing them.
- Image cache deduplicates in-flight requests for the same URL and adds a 15s
  transfer timeout.
- Workers are cleaned up via `finished` → `deleteLater` (was lingering).
- `by_disk` query simplified (folder_path is UNIQUE, so GROUP BY was a no-op).
- `_volume_label` resolved via `os.path.splitdrive` (was manual `[:2]` parsing
  that mishandled UNC and Unix paths).
- `to_int`/`to_float` no longer silently override `0` values with defaults.
- Exporter adds Excel auto-filter and a friendly `PermissionError` message.
- `run.py` configures logging (was dropping all diagnostics).
- `run.pyw` removes a redundant import and falls back to stderr when Qt is
  unavailable.
- Scanner logs swallowed exceptions at debug level (was silent).

### 2026-08-16 — Copyright info and About dialog
Added attribution for the author **Stavros Antoniou** in three places:
- **`AboutDialog`** (`playcache/gui/about_dialog.py`) — a polished dark-themed
  modal showing the app icon (96px), app name, version, tagline,
  "Copyright (c) 2026 Stavros Antoniou", and "All rights reserved." Opened via
  the **About** toolbar button.
- **Status bar permanent label** — "© 2026 Stavros Antoniou" shown at the
  right edge of the main window's status bar at all times.
- **README.md License section** — copyright notice + "All rights reserved" +
  note about third-party API terms.

The About dialog reuses the dark palette from the Stats dialog (slate-800
background, indigo accent for the app name, muted gray for secondary text).

### 2026-08-16 — Polished Stats dialog (replaces QMessageBox dump)
The stats view was a plain `QMessageBox.information` text dump (just totals
plus `by_status` / `by_source` lists). Replaced with a dedicated `StatsDialog`
(`playcache/gui/stats_dialog.py`) that renders:
- **Metric cards** — total games, with metadata (ok status), with cover art,
  with release date, with ESRB, with Metacritic, manually edited. Each card has
  a colored left border keyed to its semantic meaning.
- **Bar charts** — a custom `BarChart` widget paints horizontal bars
  proportional to the max value in each distribution. Sections: by status,
  by data source, by platform, by store, by ESRB, by disk (drive letter),
  by release year.
- **Color-coded status bars** — `ok`=green, `not_found`=amber, `error`=red,
  `pending`=blue, `(none)`=gray; other charts use a single accent color.
- **`db.stats()` extended** to return `by_platform`, `by_store`, `by_esrb`,
  `by_disk`, `by_year`, and a `completeness` dict (counts of populated fields).
  Uses `COALESCE(NULLIF(field, ''), '(none)')` so empty strings group with
  NULLs rather than forming a phantom empty-key bucket.

The dialog uses pure `QPainter` rendering (no Qt Charts dependency) so it stays
lightweight and consistent across platforms.

### 2025-08-16 — Fuzzy duplicate detection
Added "Find Duplicates…" (Ctrl+D) to catch not just exact name matches but also
near-duplicates: typos ("Hollow Knight" vs "Hollow Night"), reordered words
("Doom Eternal" vs "Eternal Doom"), edition suffixes ("Hollow Knight" vs
"Hollow Knight: Voidheart Edition"), and Roman↔Arabic numerals ("Baldur's Gate
III" vs "Baldurs Gate 3"). Three complementary signals are combined: substring
containment, character similarity (`SequenceMatcher` ≥ 0.85), and token-set
Jaccard (≥ 0.70) after stop-word removal and Roman→Arabic conversion. Groups
are built via union-find so transitive matches (A~B, B~C) cluster together.
The dialog pre-selects the least-complete records for removal (based on a
completeness score across 11 fields), with a safety guard preventing removal
of every copy of a game. O(n²) pairwise comparison is fine for typical
catalog sizes (<2k games).

### 2025-08-16 — Custom sort keys for table columns
The table's Released and Rating columns display in non-sortable formats
(DD-MM-YYYY Greek regional format and "9/10" strings). Added a `lessThan()`
override in `GamesProxyModel` with custom sort keys: Released sorts by ISO date
padded to `YYYY-MM-DD` (handling partial dates); Rating sorts by the numeric
float before `/10`. Empty values sort first ascending, last descending. Other
columns use Qt's default string comparison.

### 2025-08-16 — TheGamesDB primary, RAWG as merge source
Switched the data-source order: TheGamesDB is now primary (rich genres,
developers, publishers, ESRB ratings, and boxart covers), with RAWG as a
*fallback* when TGDB has no match. Additionally, when TGDB succeeds, RAWG is
*also* queried in a merge step (`_merge_from_rawg`) to fill the numeric
`user_rating`, `metacritic_score`, and `website` that TGDB lacks. This split
was driven by RAWG becoming unreachable (HTTP 522) — TGDB alone now provides
enough data for a useful catalog, and RAWG's numeric fields fill in when
available. TGDB's `rating` field is ESRB text (e.g. "T - Teen"), stored in a
separate `esrb_rating` column, NOT a numeric score.

### 2025-08-16 — Boxart from TheGamesDB instead of RAWG screenshots
TheGamesDB's `include=boxart` parameter returns front-cover boxart, which is
more appropriate for a "cover" display than RAWG's `background_image`
(screenshots). Added `_extract_boxart()` to build the full CDN URL from the
include block. RAWG's `background_image` is now only used as a fallback in the
merge step when TGDB has no boxart.

### 2025-08-16 — TGDB quota tracking
TheGamesDB's public-tier limit is 1000 requests/month. The API returns
`remaining_monthly_allowance`, `extra_allowance`, and
`allowance_refresh_timer` with every response. The client captures these
(`_capture_quota`) and exposes `quota_info()`. The status bar displays
`TGDB: N/1000` with a tooltip showing the reset timer. A background
`/Genres` fetch on startup populates the quota immediately (and caches the
genre map for subsequent lookups).

### 2025-08-16 — Manual game adding
Added an "Add Game…" toolbar button (Ctrl+N) that creates a `GameRecord` with
a synthetic `folder_path` of `/manual/<name>`. This lets users catalog games
not currently installed. The context menu hides "Open folder in Explorer" for
these entries (detected by the `/manual/` prefix). Re-fetching, editing, and
exporting all work normally for manual games.

### 2025-08-16 — Multi-row selection + bulk operations
Switched the table from `SingleSelection` to `ExtendedSelection` (Ctrl-click
for non-contiguous, Shift-click for ranges). The context menu adapts:
"Re-fetch N games" / "Delete N games…". Single-row refetch stays synchronous
(instant detail-panel feedback); 2+ rows use the background worker with
status-bar progress. Bulk delete confirms with a count and lists up to 5 names.

### 2025-08-16 — Auto-resizing table columns
Replaced fixed `setColumnWidth()` calls with `resizeColumnsToContents()`
(Qt's built-in AutoFit) triggered after every data load/refresh. Each column
has min/max constraints so short columns don't collapse and long-text columns
(Description was since removed from the table, but Type/Game are capped).
Right-click the header for "Auto-fit all columns" / "Auto-fit this column" /
"Reset to default widths". Double-clicking a column divider auto-fits that
column (built-in Qt behavior).

### 2025-08-16 — GUI-only, drop the CLI
The original v1.0 had a `run.py` CLI (`argparse`) for scanning and a separate
GUI plan. User chose **GUI only**, so `cli.py` was removed and `run.py` now
launches `QApplication` directly. The library (`playcache/*`) remains
importable and scriptable — only the entry point changed.

### 2025-08-16 — Manual overrides as a feature, not an accident
When the GUI was added, the question arose: should user edits be overwritten
on rescan? Decision: **persist edits, protect on rescan**. Implemented via a
`manual_overrides` JSON column. `Cataloger._apply_overrides` re-applies them
after every fetch, so the API refreshes *non-edited* fields but leaves
user-touched fields alone. A future "Reset to API value" action will clear
overrides per-field.

### 2025-08-16 — RAWG primary, TheGamesDB fallback *(superseded — see above)*
Initially chose RAWG as the primary source because it has rich descriptions,
ratings, and Metacritic scores, with a generous free tier (20k req/day).
TheGamesDB was the fallback. This was later reversed when RAWG became
unreachable (HTTP 522) and TGDB proved to have richer structured data
(genres, developers, publishers, ESRB, boxart). IGDB was considered but
rejected for v1 due to the OAuth requirement.

### 2025-08-16 — SQLite, not Excel, as source of truth
The reference catalog was an Excel file, but SQLite was chosen for the live
database because it supports concurrent reads, indexed queries, upserts, and
a view layer (`v_excel`) that reproduces the Excel format for export. Excel is
now an *export target*, not the storage format.

### 2025-08-16 — PySide6 over tkinter
Chose PySide6 for the GUI because of its model/view architecture (essential
for a 135+ row sortable table), robust threading via signals/slots, native
image handling, and LGPL licensing. tkinter + ttk was rejected as too limited
for the table + detail panel layout; customtkinter was rejected for its weaker
table story.
