# Roadmap

> Living document of planned work, priorities, and ideas. Items are grouped by
> theme and roughly ordered within each group. Nothing here is committed until
> it becomes a task and is implemented.
>
> Status legend: **🔍 exploring** · **📋 planned** · **🚧 in progress** · **✅ done**

## Current state (v1.5.0)

- ✅ PySide6 GUI with sortable/filterable table, detail panel, scan dialog
- ✅ Folder scanning with library-root descent, smart name detection, store detection
- ✅ Smart game-name detection — 6-priority chain (Steam manifest → GOG metadata →
  GOG setup .exe → folder name → largest non-launcher .exe → folder name fallback)
- ✅ Disk conflict detection during scan — pauses and prompts user (new / old / both)
- ✅ RAWG primary + TheGamesDB fallback with fuzzy matching and retry/backoff
- ✅ TheGamesDB merge step — fills ESRB rating after RAWG succeeds
- ✅ ESRB age ratings from TheGamesDB (stored in `esrb_rating` column)
- ✅ Cover images from TheGamesDB boxart (`include=boxart`) — no RAWG dependency
- ✅ SQLite storage with `v_excel` view matching the 6-column reference Excel layout
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
- ✅ Cross-platform support (Windows + Linux) — scanner detects Linux system
  folders and ELF/AppImage/.sh executables; volume labels resolved via
  `/proc/mounts`; `.desktop` file generation on Linux
- ✅ 164 tests passing, ruff clean
- ✅ Close-after-scan fix (2026-09-03) — the scan dialog's Close button and
  the main window's close (X) stopped working after a finished scan/refetch
  because `finished -> deleteLater` destroyed the worker's C++ object while
  Python references lingered (`RuntimeError: Internal C++ object already
  deleted` before `reject()` / `event.accept()` ran). References are now
  cleared on thread finish and all `isRunning()` guards tolerate dead wrappers
  (`qtutils.worker_is_running`). 168 tests passing, ruff clean.
- ✅ Evidence-based game-name detection (2026-09-03) — installer filenames in
  any shape (`Name-Setup.exe`, `name_installer.exe`, `DoomEternalSetup.exe`,
  repack installers with group names stripped), Windows PE
  ProductName/FileDescription of the largest exes (rescues bare `setup.exe`
  repacks and generic `game.exe` binaries), parent-folder fallback for
  generic folder names, and one-level-deeper exe search for multi-disc
  layouts. Candidates are scored (source weight x title-quality + agreement
  bonus) instead of a rigid priority chain.
- ✅ Post-scan duplicate purge — after a scan dialog closes, exact-name
  (case-insensitive) duplicates are removed automatically, keeping the most
  complete copy (ok status → most fields → newest). Fuzzy duplicates stay
  manual via Find Duplicates… 191 tests passing, ruff clean.
- ✅ Game archive scanning (2026-09-04) — `.zip`/`.7z`/`.rar`/`.iso` files
  found during a scan are catalogued as games in their own right, with the
  title parsed from the archive filename (versions, `(id)` tags, repack
  groups, download-site URL prefixes and multi-part RAR numbering stripped).
  Folders that hold only archives yield the archives instead of a junk
  folder row; folders with game executables stay normal game folders.
  209 tests passing, ruff clean.

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
  in code, not exposed in the UI). *The original `Game_Library.xlsx` reference
  file is no longer bundled with the repo — it contained personal catalog data.*
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

- **✅ Portable Windows release** — PyInstaller one-dir bundle zipped as
  `PlayCache-vX.Y.Z-windows-portable.zip`. User extracts and runs
  `PlayCache.exe`. No Python install required. Built automatically via CI
  on tag push.
- **✅ Linux AppImage** — `PlayCache-vX.Y.Z-linux-x86_64.AppImage`. Built
  via PyInstaller + linuxdeploy on CI. Download, `chmod +x`, and run.
  No Python install required.
- **✅ GitHub Releases** — tag push (`git tag v1.0.0 && git push --tags`)
  triggers the release workflow, which builds both artifacts and creates a
  GitHub Release with auto-generated release notes.
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

### 2026-09-04 — Game archives (.zip/.7z/.rar/.iso) as game entries

**Trigger**: user asked the folder-scan parser to identify a game from the
filename of an archive. Two interpretations were considered — archives as
name evidence inside game folders vs. archives as game entries in their own
right — and the user chose **archive = game entry** with extension set
zip/7z/rar/iso.

**Changes** (`folder_scanner.py`):
- `_archive_entries(folder)` lists a folder's files and yields a
  `ScannedFolder` per game archive; `folder_path` is the archive file path
  (works as the DB upsert key; "Open folder" opens the parent directory).
- `_clean_archive_name()` parses the title: extension stripped, URL-ish
  prefixes (`fitgirl-repacks.site-…`) removed, then the existing
  `clean_folder_name` pipeline handles versions, `(id)` tags and repack
  groups. `setup_*.zip`-style archives delegate to the GOG setup parser
  (`_GOG_SETUP_RE` extended with archive extensions). CamelCase stems are
  split (`DoomEternal.zip` → `Doom Eternal`). Junk stems (readme, data,
  saves, …) are rejected via `_ARCHIVE_JUNK_NAMES`.
- Traversal rules: archives are collected at the scan root, inside library
  containers, and replace a folder that contains archives but **no game
  executables** (an archive holder such as `Backups/` no longer becomes a
  junk "Backups" row). A folder with archives **and** game exes stays a
  normal game folder — its archives are ignored (repack-folder layout).
- Multi-part RAR: only `Game.part1.rar` yields an entry; `.part2+` and
  `.r00`-style volumes are skipped. Split `.zip.001` volumes are naturally
  excluded (unknown extension).

**Tests** (19 added, 191 → 209): name parsing (versions/ids/URL prefixes/
CamelCase/GOG setup/part tokens/junk/hyphen preservation) and scan behavior
(loose archives, each extension, multi-part dedupe, holder folders with and
without exes, container store detection, recursive grouping, data-zip
folders).

**Trade-offs**: name parsing is filename-only (nothing is extracted), so a
misnamed archive yields a wrong-but-plausible row — covered by manual
overrides. A game folder that legitimately contains only a data zip and no
executable now yields nothing (rare layout; the zip's stem is usually in the
junk list, which falls back to the folder row). An installed game and its
archived copy both appear until the post-scan exact-name purge keeps the
most complete copy.

### 2026-09-03 — Evidence-based game-name detection + post-scan duplicate purge

**Trigger**: user asked for game names to be obtained from exe filenames
during folder scans — including installer exes — and for duplicates retrieved
by a scan to be purged automatically. After review, a fixed pattern list was
rejected as unable to "cover all circumstances"; the user approved an
evidence-scoring design.

**Detection changes** (`folder_scanner.py`):
- `smart_detect_game_name` keeps Steam manifest → GOG metadata → GOG setup
  exe as authoritative sources, then replaces the old folder-name/exe-stem
  priority chain with `_best_name_from_evidence`.
- Installer filenames of any shape are parsed (`_looks_like_installer` +
  `_clean_installer_name`): separated tokens (`Hollow Knight-Setup.exe`),
  CamelCase-attached suffixes (`DoomEternalSetup.exe`), repack-group names
  (fitgirl/dodi/elamigos/…) stripped, dotted versions and `(id)` tags dropped.
- **PE VERSIONINFO reading** (`_read_pe_metadata`, Windows-only ctypes
  `version.dll`) extracts `ProductName`/`FileDescription` from the ≤3 largest
  executables — the only signal that works when BOTH the folder name and the
  filename are useless (bare `setup.exe` repacks, `game.exe`, `main.exe`).
- Executables are searched one subfolder level deeper when the top level
  yields nothing (multi-disc layouts); the parent folder name is a last-resort
  candidate only when the folder name itself is junk.
- Candidates score `source weight × _title_quality` (junk-token penalties,
  word-count curve) + 0.10 when two sources agree; plain exe stems (0.55)
  rank below the folder name (0.60) so exe names only fill gaps, per the
  user's choice. `_find_game_exes` was superseded by the shared
  `_collect_exe_paths` walker and removed.

**Purge** (`db.py` + `main_window.py`):
- `Database.purge_exact_duplicates()` removes rows sharing an exact
  case-insensitive `game_name`, keeping the most complete copy (fetch_status
  ok → most populated fields incl. manual overrides → newest updated_at);
  empty-name rows are never grouped, and at least one copy always survives.
- Called in `_open_scan_dialog` after the dialog closes; failures are logged
  and never block the table refresh. Fuzzy duplicates remain manual.

**Tests** (23 added, 168 → 191): installer shapes, repack stripping, bare
`setup.exe` fallback, PE rescue/beat-stem/junk-rejection (PE monkeypatched —
CI never touches ctypes), depth-2 search, parent fallback, and 9 purge tests
including the never-remove-all and override-completeness cases.

**Trade-offs**: installer names drop intra-word hyphens (`Half-Life-Setup` →
`Half Life`) — fine for API search, not for display. PE reading is
Windows-only (ELF has no standard title metadata). `_title_quality` is
heuristic; a wrong-but-plausible candidate can still win and end up
`not_found` after the API call — the manual-overrides flow covers it.

### 2026-09-03 — Fix: windows stopped closing after a finished scan

**Symptom**: after scanning a folder, pressing Close did nothing — neither the
scan dialog nor (once a refetch had run) the main window would close.
`playcache.log` showed repeated
`RuntimeError: libshiboken: Internal C++ object (ScanWorker/RefetchWorker)
already deleted` at `scan_dialog.py:_on_close` and `main_window.py:closeEvent`.

**Root cause**: the audit's cleanup pattern `worker.finished.connect(
worker.deleteLater)` destroys the QThread's C++ object when the event loop
resumes after `run()` returns, but `self._worker` / `self._refetch_worker`
kept pointing at the dead Python wrapper. The next access — the Close
button's `isRunning()` check, or `closeEvent` — raised RuntimeError, aborting
the slot before `reject()` / `event.accept()` could run, so the close was
silently swallowed.

**Fix**:
- `ScanDialog._on_worker_thread_finished` /
  `MainWindow._on_refetch_thread_finished`: connected to `finished`, they call
  `deleteLater()` on the sender and clear the instance reference (root cause:
  no dangling wrapper).
- New `playcache/gui/qtutils.py::worker_is_running()` returns False instead of
  raising when the wrapper is dead (defense in depth); used by the dialog's
  Close handler, the re-fetch/settings busy-guards, and `closeEvent`.
- Regression tests in `tests/test_close_after_scan.py` (4) reproduce the exact
  RuntimeError against headless Qt before the fix and assert
  `reject()` / `event.accept()` now run.

**Trade-offs**: `self.sender()` inside the cleanup handlers relies on Qt's
signal introspection (safe within a directly-connected slot). The guarded
`isRunning()` could mask a genuinely-deleted worker's state, but "not running"
is the correct semantic for a destroyed thread.

### 2026-08-18 — Switch primary API from TheGamesDB to RAWG

**Trigger**: RAWG's API is active again (was returning HTTP 522 since
2025-08-16). The user requested switching the primary provider to RAWG with
TheGamesDB as the fallback.

**Changes**:
- `Cataloger._fetch`: now tries RAWG first; on not_found/error falls back to
  TheGamesDB (previously the reverse).
- `Cataloger._merge_from_rawg` → `_merge_from_tgdb`: after RAWG succeeds, TGDB
  is queried to fill `esrb_rating`, `thegamesdb_id`, and `cover_url` (if
  empty). Previously RAWG filled `user_rating`, `metacritic_score`,
  `cover_url`, `website` after TGDB.
- Status bar now shows `RAWG: N calls (primary) | TGDB: M/L (fallback)`.
  Both clients now track `request_count` per session. The status bar
  refreshes after every refetch progress callback so the call count updates
  live during multi-row refetches.
- Startup quota fetch still queries TGDB `/Genres` to populate the genre
  cache and quota — this is still needed because TGDB is the fallback and
  its genre cache is required for TGDB's `_apply()` to resolve genre IDs.
- Integration tests rewritten: `test_pipeline_rawg_fetch_and_store`,
  `test_pipeline_rawg_merge_from_tgdb`, `test_pipeline_fallback_to_tgdb`.
- Docs updated across README, PROJECT_CONTEXT, and client docstrings.

**Trade-offs**:
- RAWG has a generous free tier (20k req/month, effectively unlimited for a
  desktop cataloguer), so the primary path no longer has a quota ceiling.
- TGDB's ESRB ratings are now filled in the merge step (one extra API call
  per game when TGDB is available). This is a fair trade — ESRB is the only
  field TGDB provides that RAWG doesn't.
- If RAWG goes down again, TGDB takes over as fallback. The user would lose
  `user_rating`, `metacritic_score`, and `website` until RAWG recovers, but
  would still get ESRB, description, and cover from TGDB.

### 2026-08-18 — Full-codebase audit: atomicity, injection, and crash fixes

**Trigger**: user requested a full code audit with bug fixes and
improvements. Four parallel explore agents covered the data layer
(`db.py`, `models.py`, `backup.py`, `config.py`), API clients
(`rawg_client.py`, `thegamesdb_client.py`, `cataloger.py`), scanner/utils
(`folder_scanner.py`, `textutils.py`, `exporter.py`, `image_cache.py`),
and all GUI modules.

**Critical / high-severity fixes**:
- **Backup atomicity** (`backup.py`): export now writes to a `.tmp` file,
  `fsync`s, and atomically renames — a crash or disk-full can no longer leave
  a corrupt-looking `.json.gz`. `replace_all=True` import now does
  `DELETE` + all upserts in a **single transaction** via the new
  `Database.upsert_many()` — a crash mid-restore rolls back and the existing
  catalog is preserved (previously the DB was wiped before any upsert).
- **Cataloger conflict-replace atomicity** (`cataloger.py`): when resolving a
  same-name conflict on a different disk with "Keep new", the `DELETE` of
  the old row and the `upsert` of the new row now run in one transaction —
  a crash can no longer lose the old entry without storing the new one.
- **GOG base-game selection** (`folder_scanner.py:_read_gog_metadata`):
  the "prefer base game" condition was a logical contradiction
  (`gid == cid ... if cid != gid`) and never fired; it always returned the
  first candidate (often a DLC/soundtrack). Now stores `(file_id, game_id,
  name)` tuples and returns the entry where `file_id == game_id`.
- **Excel formula injection** (`exporter.py`): game names / descriptions
  from external APIs that start with `=`, `+`, `-`, or `@` are now prefixed
  with `'` so Excel/LibreOffice treat them as text, not formulas. This
  prevents DDE-based command execution from a malicious API response.
- **Image cache `file://` rejection** (`image_cache.py`): non-`http(s)://`
  URLs are now rejected before `QNetworkAccessManager.get()`, preventing
  local-file reads via a malicious `cover_url` in an API response. Cache
  writes are now atomic (`.tmp` + `os.replace`). `clear()` now uses
  `rglob("*")` so subdirectories are also cleaned.
- **`clean_folder_name` hyphen preservation** (`folder_scanner.py`):
  intra-word hyphens are now preserved (`Half-Life`, `Counter-Strike`),
  while noise tokens attached by hyphens (`Doom Eternal-CODEX`) are still
  stripped. Previously the function split on ALL hyphens, destroying
  hyphenated game titles.
- **Store detection false positives** (`folder_scanner.py`): the overly
  broad `\bgog\b`, `\bepic\b`, `\borigin\b` patterns matched game folders
  *named* "Epic" or "Origin". Tightened to require a path separator after
  the store name (`\bgog\b[\\/]`) or a multi-word library root
  (`epic games[\\/]+`).
- **Detail panel "Re-fetch" button** (`detail_panel.py`): the button was
  created with `setEnabled(False)` and never enabled — the "Re-fetch"
  button in the detail panel was permanently dead. Now enabled/disabled
  alongside the other action buttons in `_set_enabled`.
- **`esrb_rating` / `metacritic_score` editability** (`detail_panel.py`):
  these fields were marked editable in the detail panel form but are NOT
  in `db.EDITABLE_COLUMNS`, so every Save attempt raised
  `ValueError("Field 'metacritic_score' is not editable")`. Moved to the
  read-only metadata section.
- **`ScanWorker.finished` signal shadowing** (`scan_dialog.py`): the
  custom `finished = Signal(dict)` shadowed `QThread.finished`, so
  `deleteLater` (connected to the built-in `finished`) never fired on the
  exception path — leaking the worker. Renamed to `result`.
- **Detached scan worker parenting** (`scan_dialog.py:_on_close`): when
  the worker didn't stop within 3 s, the previous code left it parented
  to the dialog — destroying the dialog on `exec()` return would destroy
  a still-running `QThread` (Qt abort). Now calls `setParent(None)` before
  detaching so the worker can self-delete via `finished → deleteLater`.
- **`closeEvent` worker cleanup** (`main_window.py`): increased wait to
  5 s and added `terminate()` + `wait(2000)` as a last resort so closing
  the window can't trigger "QThread: Destroyed while still running".
- **Single-row refetch concurrency guard** (`main_window.py`): the
  single-row path bypassed the `_refetch_worker.isRunning()` guard, racing
  on `requests.Session` and `self._db` with an in-flight multi-row refetch.
  Guard is now hoisted above the branch.
- **`_select_by_folder_path` clear-selection** (`main_window.py`): in
  `ExtendedSelection` mode, `selectRow()` *adds* to the selection. After
  "Add Game", the detail panel showed a stale (top-most) row. Now calls
  `clearSelection()` first.
- **`sqlite3.Error` handling** (`main_window.py:_on_field_edited`,
  `detail_panel.py:_save`): both slots only caught `ValueError`/`OSError`,
  so a "database is locked" error during a concurrent refetch would crash
  the GUI thread. Now catches `Exception` broadly with a log warning.
- **Env-var API key leak** (`settings_dialog.py`): if `RAWG_API_KEY` was
  set via environment variable, the Settings dialog pre-filled the field
  with the env value and Save wrote it to `config.ini` — a secret leak.
  Now detects env-var-sourced keys, disables the field with a placeholder,
  and preserves the env value (doesn't write it to disk).
- **UNC path disk grouping** (`models.py:GameRecord.disk`): UNC paths
  (`\\server\share\...`) returned `"—"` because `os.path.splitdrive`
  returns an empty drive for them. Now extracts `\\server\share` as the
  grouping key.
- **`from_row` int coercion** (`models.py`): `rawg_id`, `thegamesdb_id`,
  and `metacritic_score` are now coerced to `int | None` so SQLite's
  dynamic typing can't silently store a string where an int is expected.
- **Volume-label cache invalidation** (`models.py`): added
  `clear_volume_label_cache()` so tests (and future hot-swap handling) can
  invalidate the module-level `_drive_label_cache` without reaching into
  private state.
- **`db.connect()` rollback** (`db.py`): added explicit `rollback()` on
  exception (previously relied on SQLite's implicit rollback-on-close,
  which is fragile if `isolation_level` ever changes). Added
  `PRAGMA busy_timeout = 15000` so concurrent access doesn't immediately
  fail with "database is locked".
- **`textutils.format_rating` NaN/Inf/range** (`textutils.py`):
  `float("nan")` produced `"nan/10"`; `format_rating(85.0)` produced
  `"85/10"`. Now rejects non-finite values and values > 10.
- **`textutils.truncate(max_chars<=0)`** (`textutils.py`):
  `truncate("hello", 0)` produced `"…"`; `truncate("hello", -1)` produced
  `"hell…"`. Now returns `""` for non-positive `max_chars`.
- **`textutils.clean_search_query` em-dash** (`textutils.py`): the
  subtitle-stripping regex handled `-` and en-dash `–` but not em-dash
  `—`. Now handles all three.
- **`best_match` short-query false positives** (`textutils.py`): the
  substring boost (score → 90) fired for any substring match, so a
  3-letter query like "the" matched almost everything. Now requires
  `len(query) >= 3`.
- **Config BOM handling** (`config.py`): `parser.read(..., encoding="utf-8")`
  didn't strip a UTF-8 BOM, so a `config.ini` saved as "UTF-8 with BOM"
  (common on Windows Notepad) silently failed to parse — the API key was
  invisible and the user got `APIKeyMissingError`. Now uses
  `utf-8-sig`.
- **Config env-var TOCTOU** (`config.py`): `if os.getenv(k): return
  os.environ[k]` called `getenv` twice; consolidated to one call.
- **`item_delegate` column constants** (`item_delegate.py`):
  `_STATUS_COL = 9` / `_SOURCE_COL = 8` were hardcoded and would silently
  break if `COLUMNS` changed. Now derived from `COLUMNS` at import time
  (raises immediately if the column is missing instead of silently painting
  the wrong column).
- **`item_delegate` source-color dict** (`item_delegate.py`): the
  per-call dict allocation in `_paint_source` is now module-scoped.
- **`item_delegate` badge height** (`item_delegate.py`):
  `badge_h = min(rect.height() - 8, 20)` could go negative for very short
  cells; now clamped to `>= 0`.
- **`table_model.update_record` tooltip** (`table_model.py`): the
  `dataChanged` signal didn't include `ToolTipRole`, so the tooltip
  (which shows `fetch_message`) was stale after a refetch until a full
  reset. Now includes it.
- **`exporter` error handling** (`exporter.py`): only `PermissionError`
  was caught; `IsADirectoryError`, disk-full, etc. propagated as raw
  exceptions. Now catches `OSError` broadly with a contextual message.
  Column widths are now keyed by header name (dict) instead of position
  (list), so adding/reordering headers can't silently misalign widths.
  `auto_filter` is no longer set on an empty sheet.

**New tests** (30 added, 134 → 164 total):
- `test_folder_scanner.py`: GOG base-game preference, hyphen preservation,
  online-fix stripping.
- `test_backup.py`: atomic export (no `.tmp` left), non-string folder_path
  rejection, `replace_all` atomicity.
- `test_exporter.py` (new): formula injection sanitization (`=`, `+`, `@`),
  normal names unmodified, empty DB, parent dir creation, permission error.
- `test_db.py`: `upsert_many` batch insert / replace_all / empty list,
  UNC path disk grouping, `from_row` int coercion + invalid handling.
- `test_textutils.py`: NaN/Inf/over-10 ratings, `truncate(max_chars<=0)`,
  em-dash subtitle stripping.

**Trade-offs considered**:
- Atomic backup write adds a `.tmp` file briefly during export. On
  cross-device writes `os.replace` may fail — handled by falling back to
  a plain `OSError` with context.
- `upsert_many` materializes all records in memory before the
  `executemany`. For very large catalogs (100k+) this could be split into
  batches, but the simplicity is worth it for now.
- The env-var API key detection in Settings uses `os.getenv` at dialog
  open time; if the env var is set/cleared while the dialog is open, the
  field state won't update. Acceptable for a modal dialog.
- Catching `Exception` broadly in GUI slots masks programming errors. The
  alternative (crash the GUI on a locked DB) is worse for users. Logging
  at WARNING level preserves debuggability.

### 2026-08-18 — Fix table not updating after delete (PySide6 6.x enum scoping)

**Symptom**: user scanned a single game folder and got one row per subfolder
(`Binaries`, `Engine`, `ROTTGame`, `__support`). Right-click → Delete →
confirm, and the rows appeared to stay. The DB was actually updated, but the
table viewport never repainted.

**Root cause**: `GamesItemDelegate.paint()` referenced
`QStyleOptionViewItem.State_Selected` and `QStyleOptionViewItem.State_Alternate`.
Both were Qt5-era shortcuts that PySide6 6.x removed (enums are now proper
PEP 435 scoped enums). Every paint of the Status (col 9) or Source (col 8)
cell raised `AttributeError`; PySide6 swallowed it to stderr (→
`playcache.log` under `run.pyw`), but the viewport's paint cycle was aborted,
so the table showed stale pixels after any model reset (delete, edit,
rescan).

**Fix**:
- `option.state & QStyleOptionViewItem.State_Selected` →
  `option.state & QStyle.State_Selected` (the `state` field is a
  `QStyle.State` flag set).
- `option.state & QStyleOptionViewItem.State_Alternate` →
  `option.features & QStyleOptionViewItem.ViewItemFeature.Alternate`
  (the alternate-row flag moved to `option.features` in Qt6; `QStyle.State`
  no longer has `State_Alternate`).

**Regression test**: `tests/test_item_delegate.py` (13 tests) paints every
column with selected / alternate / normal option states and asserts no
exception escapes. Runs headless via `QT_QPA_PLATFORM=offscreen` (already
set in CI).

### 2026-08-16 — Single-source versioning across app + repo + releases
Before this change, `1.0.0` appeared in two places: `playcache/__init__.py`
(`__version__`) and `pyproject.toml` (`version = "1.0.0"`). They could drift.
Now `pyproject.toml` declares `dynamic = ["version"]` and reads from
`playcache.__version__` via `tool.setuptools.dynamic.version`, so there is
exactly one source of truth.

Additional version surface area added:

- **`--version` flag** on both `run.py` and `run.pyw` (via `argparse`):
  `python run.py --version` → `PlayCache 1.0.0`. Standard CLI convention.
- **Window title** now shows the version: `PlayCache 1.0.0` (was just
  `PlayCache`). Visible at a glance in the title bar + taskbar.
- **Status bar permanent label** on the right: `v1.0.0`. Doesn't interfere
  with the transient status messages (game counts, API quota) on the left.
- **`QApplication.setApplicationVersion(__version__)`** — sets the app
  version metadata on the Qt side (used by some platform integrations).
- **CI release workflow stamps the version from the git tag**: pushing
  `v1.2.3` rewrites `__version__ = "1.2.3"` in `__init__.py` *during the
  build only* (not committed), so the built `.exe` / AppImage reports the
  correct version. The committed `__version__` stays at the last manually
  bumped value (currently `1.0.0`) until we bump it on `main`.

**Convention going forward**: bump `__version__` in
`playcache/__init__.py` as the single source of truth. Tag pushes with a
matching `vX.Y.Z` trigger a release that will use that version. Tag pushes
with a *different* version override the in-source value during the build
(useful for `v1.0.1` hotfix releases off `main` without a version bump
commit).

### 2026-08-16 — Portable releases (Windows zip + Linux AppImage)
Added CI-driven release builds triggered on tag push (`v*`):

- **Windows portable** — PyInstaller `--onedir` bundle zipped as
  `PlayCache-vX.Y.Z-windows-portable.zip`. Contains `PlayCache.exe` + all
  DLLs + PySide6 plugins + `config.example.ini` + app icon. User extracts
  and runs — no Python install required.
- **Linux AppImage** — PyInstaller `--onedir` output wrapped with
  `linuxdeploy` into a standard AppImage (`PlayCache-vX.Y.Z-linux-x86_64.AppImage`).
  Includes `.desktop` entry + icon. User downloads, `chmod +x`, and runs.
- **Config auto-copy** — on first launch, if `config.ini` doesn't exist,
  `config.example.ini` is automatically copied to the working directory so
  the user just needs to paste their API key. Implemented in
  `config.py::_ensure_config_exists()`.
- **Release workflow** (`.github/workflows/release.yml`) — triggered on tag
  push. Three jobs: `build-windows` (windows-latest), `build-linux`
  (ubuntu-latest), `release` (downloads both artifacts and creates a GitHub
  Release with auto-generated notes via `softprops/action-gh-release`).
- **PyInstaller spec** (`playcache.spec`) — bundles `config.example.ini` and
  `playcache/assets/` (icon). Excludes tkinter/test/unittest. Console=False
  (GUI app). Uses UPX compression.
- **How to create a release**:
  ```powershell
  git tag v1.0.0
  git push --tags
  ```
  The CI builds both artifacts and creates the release automatically.

### 2026-08-16 — Linux support
Added cross-platform support for Linux alongside Windows:

- **Volume labels** — `_volume_label()` in `models.py` now has a Linux
  implementation that reads `/proc/mounts` and `/dev/disk/by-label/` to
  resolve filesystem labels (e.g. "nvme0n1p2", "Games HDD"). Previously
  returned `""` on Linux, making the disk-grouping feature useless.
- **Disk property** — `GameRecord.disk` on Linux walks up the path tree
  checking `st_dev` changes to find the mount boundary, then resolves the
  label. Previously returned `"—"` for every Linux game. The `db.stats()`
  `by_disk` distribution uses the same logic.
- **Scanner** — `DEFAULT_SKIP` now includes Linux system directories
  (`/etc`, `/var`, `/usr`, `/proc`, `/sys`, `/dev`, `/boot`, `/bin`, `/sbin`,
  `/lib`, `/run`, `/srv`, `/snap`, etc.). `_find_game_exes()` detects Linux
  executables (ELF binaries via magic bytes, `.AppImage`, `.sh`, `.bin`)
  alongside `.exe` files (Wine/Proton games). GOG `.sh` installers are
  recognized by `_GOG_SETUP_RE` and `_find_gog_setup_exe()`. Architecture
  suffixes include Linux variants (`linux`, `linux64`, `i386`, `arm`,
  `aarch64`, `appimage`, `gl`, `x11`, `wayland`).
- **Store detection** — added Linux launcher patterns: Heroic, Lutris,
  Bottles, Minigalaxy, GameHub, Legendary.
- **GUI** — "Open folder in Explorer" → "Open folder in Files" on Linux.
  Scan dialog placeholder shows Linux path examples (`/mnt/games`,
  `~/.steam/steam`) on Linux.
- **Shortcuts** — `scripts/make_shortcut.py` now generates a FreeDesktop
  `.desktop` entry on Linux (to `~/.local/share/applications/`) instead of
  aborting with "Windows-only".
- **Config** — `config.example.ini` `skip_folders` now includes both Windows
  and Linux system folders.
- **Tests** — added `test_stats_distributions_linux` and
  `test_disk_property_linux` to cover the Linux code paths on any OS.

### 2026-08-16 — Fix CI: cross-platform test compatibility
The GitHub Actions CI workflow runs on Ubuntu, but two tests were
Windows-specific and failed on Linux:

1. **`test_stats_distributions`** — used Windows-style paths (`C:/Games/Game1`)
   but on Linux `os.path.splitdrive("C:/Games/Game1")` returns `("", path)`
   because Linux doesn't recognize `C:` as a drive letter. All non-manual
   games grouped as "—" instead of "SSD"/"D:". Fixed by monkeypatching
   `os.path.splitdrive` in the test to simulate Windows drive-letter behavior.

2. **`test_export_permission_error_message`** — wrote to a directory path to
   trigger a permission error. On Windows this raises `PermissionError`; on
   Linux it raises `IsADirectoryError` (not caught by the `PermissionError`
   handler in `export_backup`). Fixed by catching `OSError` (parent class)
   and re-raising as `PermissionError` with the friendly "may be open in
   another program" message — covers both Windows and Linux I/O failures.

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
ratings, and Metacritic scores, with a generous free tier (20k req/month).
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
