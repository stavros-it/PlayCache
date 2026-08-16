# Project Context

> Single source of truth for any contributor (human or AI) working on PlayCache.
> Captures what the project is, how it's structured, and the conventions to follow.

## 1. What this project is

**PlayCache** is a Windows desktop application (PySide6 GUI) that scans a
drive or folder of installed games, fetches metadata from free online services
(TheGamesDB primary, RAWG fallback + merge step), and catalogues them into a
local SQLite database. The data model and Excel export follow a 6-column
reference layout (GAME NAME, PLATFORM, GOG / STEAM, USER RATING, GAME TYPE,
SHORT DESCRIPTION).

Development was led by **Stavros Antoniou** with the assistance of AI tools
(Claude and GLM-5.2 via the OpenCode CLI). All code, tests, and docs were
produced in collaboration with AI assistants and reviewed by the author.

### Primary user workflow
1. Launch `python run.pyw` → the GUI opens **maximized** (stdout/stderr
   redirected to `playcache.log`). App icon shows in the window title bar,
   taskbar, and Alt-Tab (Windows AppUserModelID set to `PlayCache.App`). The
   games table is **sorted alphabetically by name (case-insensitive)** on
   startup.
2. Click **Scan Drive…** → pick a drive/folder → options (rescan, only-missing,
   recursive, dry-run, filter, limit) → **Start Scan**. Or click **Add Game…**
   (Ctrl+N) to manually add a game by name without a folder on disk.
3. Background thread scans folders, calls APIs, upserts to SQLite; live progress
   shown in the scan dialog and the status bar. The status bar also shows the
   TheGamesDB monthly quota (e.g. `TGDB: 890/1000`) after the first API call.
4. Browse the sortable/filterable games table — columns auto-fit to content
   (Excel-style); select multiple rows with Ctrl/Shift. The table uses a
   **dark slate theme** with subtle zebra striping and an indigo selection
   state. The Status column renders as a **colored badge** (green=ok,
   amber=not_found, red=error, blue=pending) with smart contrast text chosen
   by WCAG luminance. The Source column gets a subtle accent color (indigo for
   TGDB, sky for RAWG). Right-click for context-aware actions (Re-fetch N
   games, Delete N games). Click a row to see cover image + full metadata in
   the detail panel. Edit fields inline — edits persist as *manual overrides*
   that survive rescans. Click **Find Duplicates…** (Ctrl+D) to fuzzy-match
   similar games and bulk-remove the redundant copies.
5. Click **Stats** for a polished overview: metric cards (total, with metadata,
   with cover art, with release date, with ESRB, with Metacritic, manually
   edited) and bar charts (by status, source, platform, store, ESRB, disk,
   release year). Status bars are color-coded (green=ok, amber=not_found,
   red=error). The "By disk" chart shows **volume labels** (e.g. "TOSHIBA 2TB")
   instead of drive letters. In-bar text color is chosen automatically via WCAG
   luminance (white on dark fills, dark slate on light fills).
6. Export to Excel anytime. Or **Backup…** (Ctrl+B) to save a compressed
   JSON snapshot of the entire catalog (`.json.gz`), and **Restore…**
   (Ctrl+I) to import one — merge (upsert by `folder_path`) or replace-all.
7. Click **About** in the toolbar for app info and copyright notice. The status
   bar also shows a permanent "© 2026 Stavros Antoniou" label.

### Non-goals (intentionally out of scope)
- No cloud sync, no accounts, no telemetry.
- No launcher / install / play functionality — cataloguing only.
- No auto-update of game binaries; folders on disk are never modified.
- Not a web app or a CLI tool (the CLI was removed in favour of GUI-only).

## 2. Tech stack

| Layer | Choice | Notes |
|-------|--------|-------|
| Language | Python 3.12+ | Uses `from __future__ import annotations` for PEP 604 unions |
| GUI framework | PySide6 6.11 (LGPL) | Qt's model/view architecture, signals/slots, QThread. Cross-platform (Windows + Linux). |
| GUI theme | Hand-rolled QSS in `playcache/gui/theme.py` | Centralized slate-based dark palette; smart text color via WCAG luminance |
| Storage | SQLite (stdlib `sqlite3`) | Single-file DB; `v_excel` view mirrors the xlsx layout |
| HTTP | `requests` | Synchronous calls; runs inside background threads |
| Excel export | `openpyxl` | Matches the 6-column reference Excel layout |
| Backup format | gzip-compressed JSON (`.json.gz`) | stdlib `gzip` + `json`; versioned envelope |
| Fuzzy matching | stdlib `difflib.SequenceMatcher` | No extra deps |
| Image loading | `QNetworkAccessManager` | Async, non-blocking, disk-cached |
| Icon generation | `QPainter` + `Pillow` | Multi-resolution `.ico` (16–256px) |
| Testing | `pytest` | 121 tests, all use mocked API responses (no network) |
| Linting | `ruff` | All source + tests are ruff-clean |

### Runtime dependencies (`requirements.txt`)
```
requests>=2.28
openpyxl>=3.0
PySide6>=6.5
```
No other third-party packages. SQLite, `difflib`, `json`, `configparser`,
`hashlib`, `unicodedata`, `re`, `pathlib` are all stdlib.

## 3. Repository layout

```
Game DB/
├── run.pyw                     # GUI entry point — launches QApplication maximized (no console)
├── run.py                     # Console entry point (same app, stdout visible, maximized)
├── requirements.txt
├── playcache.spec               # PyInstaller build spec (portable releases)
├── config.example.ini          # Copy to config.ini and fill in API keys
├── README.md                   # User-facing docs
├── PROJECT_CONTEXT.md          # ← this file
├── ROADMAP.md                  # planned work
├── scripts/                    # Developer utilities
│   ├── make_icon.py           # Regenerate app icon (.png + .ico)
│   └── make_shortcut.py       # Create Windows desktop shortcut
├── playcache/                  # The library (importable package)
│   ├── __init__.py             # version = "1.0.0"
│   ├── models.py              # GameRecord dataclass + computed disk/release props
│   ├── config.py              # Config loader: ini + env vars
│   ├── db.py                  # SQLite schema, upsert, overrides, stats
│   ├── folder_scanner.py      # smart game-name detection from folders/files/metadata
│   ├── textutils.py           # HTML strip, truncate, ratings, fuzzy match
│   ├── rawg_client.py         # RAWG API client — fallback + merge source
│   ├── thegamesdb_client.py   # TheGamesDB primary client; genres/devs/pubs/boxart/quota
│   ├── cataloger.py           # scan → fetch → merge → upsert + conflict detection
│   ├── image_cache.py         # async Qt cover-image fetcher + disk cache
│   ├── exporter.py            # SQLite → .xlsx matching reference
│   ├── backup.py              # compressed JSON backup/restore (.json.gz)
│   ├── assets/                # App icon resources
│   │   ├── app.ico            # multi-resolution (16–256px) Windows icon
│   │   └── app.png            # 256px PNG (reference / Linux)
│   └── gui/                   # PySide6 GUI package
│       ├── __init__.py        # exports MainWindow
│       ├── theme.py           # centralized dark palette + DARK_QSS + contrast_text()
│       ├── item_delegate.py    # GamesItemDelegate — status badges + source accents
│       ├── table_model.py     # QAbstractTableModel (fieldEdited signal)
│       ├── scan_dialog.py     # scan config + ScanWorker QThread + conflict prompt
│       ├── detail_panel.py    # cover + YouTube search + metadata + edits
│       ├── settings_dialog.py # API keys / scan params editor (atomic write)
│       ├── stats_dialog.py    # polished stats overview: cards + bar charts (data-driven)
│       ├── about_dialog.py    # About dialog: app icon, version, copyright
│       ├── duplicates_dialog.py # fuzzy duplicate finder + resolver
│       └── main_window.py     # toolbar, filters, table, proxy, status bar
└── tests/                     # pytest suite
    ├── test_textutils.py             # 27 tests (includes clean_search_query)
    ├── test_folder_scanner.py        # 53 tests (smart detection + year/apostrophe)
    ├── test_db.py                    # 8 tests (upsert + stats distributions + overrides)
    ├── test_cataloger_integration.py # 5 end-to-end tests (mocked APIs + merge)
    ├── test_manual_overrides.py      # 10 tests + schema migration
    └── test_backup.py               # 16 tests (compressed JSON round-trip)
```

**Total**: ~5,881 LOC source + ~1,500 LOC tests = ~7,381 LOC (plus `run.pyw` / `run.py`).

## 4. Architecture at a glance

```
┌─────────────────────────────────────────────────────────────┐
│                        run.pyw (GUI, maximized)              │
├─────────────────────────────────────────────────────────────┤
│  playcache/gui/                                            │
│    MainWindow ──► GamesTableModel ◄── GamesProxyModel       │
│      │              ▲                  (sort: case-insensitive│
│      │              │ set_records()      Game col by default) │
│      │              │ columns: Game, Platform, Store, Disk,  │
│      │              │   Released, Rating, ESRB, Type,         │
│      │              │   Source, Status                        │
│      │              │   (auto-fit; GamesItemDelegate renders  │
│      │              │    Status as colored badge + Source as  │
│      │              │    accent text)                         │
│      ▼              │                                        │
│    ScanWorker ──► Cataloger ──► Database.upsert() ──┐       │
│      (QThread)     │                                 │       │
│      AddGame… ─────┤ uses                             │       │
│      FindDups… ───► DuplicatesDialog (fuzzy match)   │       │
│      QuotaWorker ─►│                                 │       │
│      (startup)     ├─► TheGamesDBClient (primary)    │       │
│                    │     • genres/devs/pubs resolve   │       │
│                    │     • boxart → cover_url         │       │
│                    │     • quota: remaining/1000       │       │
│                    └─► RAWGClient      (fallback)      │       │
│                    │   + _merge_from_rawg() fills      │       │
│                    │     rating/metacritic/cover       │       │
│                    │     after TGDB succeeds            │       │
│                    │                                   │       │
│    theme.py ──► DARK_QSS (centralized palette)       │       │
│    item_delegate.py ─► GamesItemDelegate              │       │
│                                                         ▼     │
│                                                  SQLite games  │
│                    FolderScanner ─────────────►  table + v_excel view
│                      (drives, containers,           │           │
│                       smart name detection,          │           │
│                       conflict detection)            │           │
│                                                     ▼           │
│                  ImageCache ──► QNetworkAccessManager ──► covers/ │
│    backup.py ──► export_backup / import_backup (.json.gz)        │
└─────────────────────────────────────────────────────────────────┘
```

### Data flow
1. **Scan** (`FolderScanner`): walks the drive, skips Windows system folders,
   descends library containers (`steamapps/common`, `GOG Games`, `Epic Games`),
   and **smart-detects the game name** using a 6-priority chain:
   1. Steam `appmanifest_*.acf` manifest (matched by `installdir`)
   2. GOG `goggame-*.info` JSON metadata
   3. GOG setup executable filename (`setup_achilles_legends_untold_1.4.0.0_(74603).exe` → `Achilles Legends Untold`)
   4. Cleaned folder name (if it looks like a real game name)
   5. Largest non-launcher `.exe` file (CamelCase split, architecture suffix strip)
   6. Cleaned folder name (final fallback)
   Then detects store + platform. If a game is found that already exists in the
   DB on a **different disk**, a conflict handler prompts the user to choose
   which copy to keep (new / old / both).
2. **Fetch** (`Cataloger._fetch`): tries TheGamesDB first; on no-confident-match
   or error, falls back to RAWG. Fuzzy `SequenceMatcher` picks the best result
   above `fuzzy_threshold` (default 60). Retries 429/5xx with backoff.
3. **Merge** (`Cataloger._merge_from_rawg`): when TheGamesDB succeeds, RAWG is
   *also* queried to fill fields TGDB lacks — numeric `user_rating` (RAWG
   rating ×2 → /10), `metacritic_score`, `cover_url` (if TGDB had no boxart),
   `website`. Only empty fields are filled; TGDB-sourced data is never
   overwritten. Skipped silently if RAWG is unavailable. TheGamesDB's ESRB text
   rating (e.g. `"T - Teen"`) is stored in the separate `esrb_rating` column
   and is not a numeric score. TGDB boxart (front cover) is extracted from the
   `include=boxart` block and stored in `cover_url`.
4. **Overrides** (`Cataloger._apply_overrides`): after fetch + merge, the
   cataloger re-applies the game's `manual_overrides` map so user edits are
   never overwritten by fresh API data.
5. **Persist** (`Database.upsert`): SQLite `INSERT ... ON CONFLICT(folder_path)
   DO UPDATE`; the `v_excel` view reproduces the 6-column reference Excel layout
   columns for export.

## 5. Data model

### `GameRecord` dataclass (`models.py`) — the canonical record

| Field | Type | Notes |
|-------|------|-------|
| `folder_name`, `folder_path` | `str` | From filesystem; `folder_path` is the unique key |
| `game_name` | `str` | Cleaned for search; replaced with API title on match |
| `platform` | `str` | `"PC"` (default), `"PC (Linux)"`, `"PC (Fan Port)"`, `"PC (Mod)"` |
| `store` | `str` | `"Steam"`, `"GOG"`, `"Epic"`, `"GOG / Steam"`, `"Other"` |
| `user_rating` | `str` | `"9/10"`, `"8.5/10"` — API rating normalised to /10 |
| `esrb_rating` | `str` | ESRB text from TheGamesDB (e.g. `"T - Teen"`, `"E - Everyone"`) |
| `game_type` | `str` | Genres joined with `" / "` (e.g. `"Action / RPG"`) |
| `short_description` | `str` | HTML-stripped, truncated to 320 chars |
| `rawg_id`, `rawg_slug` | `int?`, `str?` | RAWG identifiers for re-fetch |
| `thegamesdb_id` | `int?` | TheGamesDB identifier for re-fetch |
| `release_date` | `str?` | ISO date (`YYYY-MM-DD`) |
| `developer`, `publisher` | `str` | From API |
| `metacritic_score` | `int?` | RAWG's Metacritic score (merge step) |
| `cover_url` | `str?` | Background image URL (RAWG) |
| `website` | `str?` | Official site |
| `data_source` | `str` | `"thegamesdb"`, `"rawg"`, `""` |
| `fetch_status` | `str` | `"ok"`, `"not_found"`, `"error"`, `"skipped"`, `"pending"` |
| `fetch_message` | `str` | Error / debug context |
| `manual_overrides` | `str` | JSON: `{"user_rating": "10/10", ...}` |

**Computed properties** (not stored in DB — derived from other fields):

| Property | Type | Notes |
|----------|------|-------|
| `disk` | `str` | Volume label + drive letter from `folder_path` (e.g. `"TOSHIBA 2TB (D:)"`). Uses the Windows API (`GetVolumeInformationW`) with caching. Returns `"Manual"` for manually-added games (`/manual/…` paths). |
| `release_date_display` | `str` | `release_date` reformatted as DD-MM-YYYY (Greek regional format). Handles partial dates: `2023-05` → `??-05-2023`, `2023` → `2023`. Returns `""` if unknown. |

### SQLite schema (`db.py`)

- **Table `games`**: 24 columns. `folder_path` is `UNIQUE` (upsert key).
  `manual_overrides TEXT NOT NULL DEFAULT ''`, `esrb_rating TEXT NOT NULL
  DEFAULT ''`. `created_at` / `updated_at` timestamps.
- **Indexes**: `game_name`, `fetch_status`, `store`.
- **View `v_excel`**: reproduces the 6 Excel columns exactly, ordered by name.
- **Migration**: `_migrate()` adds new columns to pre-existing DBs — currently
  handles `manual_overrides` and `esrb_rating` additions (both with
  `NOT NULL DEFAULT ''` so old rows get empty strings, not NULL).
- **Editable columns** (`EDITABLE_COLUMNS`): `game_name`, `platform`, `store`,
  `user_rating`, `game_type`, `short_description`, `release_date`, `developer`,
  `publisher`, `website`. Everything else is read-only in the GUI.

## 6. Configuration

`Config.load()` (`config.py`) reads from (in priority order):
1. Environment variables: `RAWG_API_KEY`, `THEGAMESDB_API_KEY`, and
   `PLAYCACHE_<SECTION>_<KEY>` for any config value.
2. `config.ini` in the working directory (or `~/.playcache/config.ini`).
3. `config.example.ini` as a reference template.

Key settings: `db_path`, `request_delay` (0.3s), `request_timeout` (20s),
`max_retries` (3), `fuzzy_threshold` (60), `description_max_chars` (320),
`skip_folders` (Windows system folders).

**API keys** (in `[thegamesdb]` and `[rawg]` sections of `config.ini`):
- TheGamesDB — https://api.thegamesdb.net/login (free, required — this is the
  primary data source). Key goes in `[thegamesdb] api_key`. Public-tier limit
  is 1000 requests/month; the API returns `remaining_monthly_allowance`,
  `extra_allowance`, and `allowance_refresh_timer` with each response, which
  the client captures and the status bar displays (e.g. `TGDB: 890/1000`).
- RAWG — https://rawg.io/apiauth (free, 20k req/day). Optional but
  **recommended** — provides the numeric `user_rating`, `metacritic_score`, and
  `cover_url` that TheGamesDB lacks. Without it those fields stay empty. Key
  goes in `[rawg] api_key`. If RAWG is unreachable (e.g. HTTP 522), the merge
  step is skipped silently and the rest of the data still populates.

## 7. Key conventions

- **No comments in code** unless explicitly requested by the user. (Module
  docstrings and section dividers are OK; inline `# ...` comments are not added.)
- **Type hints** everywhere; `from __future__ import annotations` at the top of
  every module so `X | None` syntax works on Python 3.9+.
- **Dataclasses** for value objects (`GameRecord`, `ScannedFolder`, `Config`).
- **Context manager** for DB connections (`Database.connect()`) — always commits
  on success, rolls back on exception, closes in `finally`.
- **Background threads** for any blocking work (scans, refetch-all). Qt signals
  carry progress back to the UI; never touch widgets directly from a worker.
- **Mocked APIs in tests** — no network calls. Each API client has a fake
  substitute returning canned JSON matching the documented response shape.
- **Defensive parsing** of API JSON — use `.get()` with defaults; tolerate
  missing keys (the fake test clients prove this works with sparse data).
- **Dark theme is centralized** — all colors live in `playcache/gui/theme.py`.
  Never hardcode hex colors in dialogs/widgets; import from `theme.py` so the
  palette stays consistent. `contrast_text(bg_hex)` picks white or dark slate
  text based on WCAG luminance — use it for any text rendered on a colored fill.
- **Version single source of truth** — `playcache/__init__.py::__version__`
  is the only place the version is hardcoded. `pyproject.toml` reads it
  dynamically (`tool.setuptools.dynamic.version`). The window title
  (`PlayCache X.Y.Z`), the status bar permanent label (`vX.Y.Z`), the About
  dialog, the `--version` CLI flag, and the backup envelope all reference
  `__version__`. The release workflow stamps the version from the git tag
  during the build (doesn't commit it).
- **Lint**: `ruff check playcache/ tests/ run.py run.pyw` must pass.
- **Tests**: `python -m pytest tests/ -q` must pass (currently 121 passing).
- **No emojis** in source, docs, or UI strings unless explicitly requested.
- **No `print()` in library code** — use `logging` (`log = logging.getLogger(__name__)`).
  `run.pyw` redirects stdout/stderr to `playcache.log`; `run.py` (console entry)
  and smoke tests may `print` for user output.
- **No premature commits** — the repo currently has zero commits; only commit
  when the user explicitly asks.

## 8. Build / run / test commands

```powershell
# Install dependencies
python -m pip install -r requirements.txt

# Configure (one-time)
Copy-Item config.example.ini config.ini
notepad config.ini        # paste TheGamesDB API key; RAWG key optional

# Run the GUI (no console window; output goes to playcache.log)
python run.pyw

# Run the GUI (console visible — useful for debugging)
python run.py

# Run the test suite (no network required)
python -m pytest tests/ -q

# Lint
ruff check playcache/ tests/ run.py run.pyw scripts/

# Regenerate the app icon (requires PyQt/PySide6 + Pillow)
python scripts/make_icon.py

# Create a desktop shortcut (Windows; requires pywin32)
python scripts/make_shortcut.py

# Headless GUI smoke test (CI-friendly)
$env:QT_QPA_PLATFORM='offscreen'
python run.pyw

# Backup/restore the catalog programmatically (also available via toolbar)
python -c "from playcache.config import Config; from playcache.db import Database; from playcache.backup import export_backup; c=Config(); export_backup(Database(c.db_path), 'catalog_backup.json.gz')"
python -c "from playcache.config import Config; from playcache.db import Database; from playcache.backup import import_backup; c=Config(); print(import_backup(Database(c.db_path), 'catalog_backup.json.gz'))"

# Build a portable release locally (requires: pip install pyinstaller)
pyinstaller playcache.spec --noconfirm
# Windows: dist/PlayCache/PlayCache.exe
# Linux:   dist/PlayCache/PlayCache

# Create a GitHub release (triggers CI build of Windows zip + Linux AppImage)
git tag v1.0.0
git push --tags
```

## 9. Known limitations & gotchas

- **Code audit pass (2026-08-16)** — a full audit fixed 30+ bugs and improvements:
  - **Search query** no longer strips ASCII hyphens inside words (was breaking
    "Half-Life", "Counter-Strike"). Only colon/en-dash/spaced-hyphen subtitles
    are stripped. 4-digit years are preserved (was breaking "Cyberpunk 2077").
  - **GOG setup name** uses `capwords` instead of `.title()` (was producing
    "Assassin'S Creed" from apostrophes).
  - **Symlink/junction cycle protection** in the scanner (NTFS junctions could
    cause infinite recursion). Steam manifest lookups are now cached per
    steamapps dir (was O(N²) re-reading every manifest per game).
  - **Cataloger** preserves manual overrides on conflict-replace (was data
    loss), wraps each game in try/except (single-game failure no longer aborts
    the whole scan), and removed the unused `existing_same_path` parameter.
  - **Table edits** now persist to the DB via a `fieldEdited` signal (was only
    updating in-memory — edits were lost on next refresh).
  - **Scan dialog** "Descend into grouping folders" checkbox is now wired up
    (was a dead control). Thread-destroy-on-close crash fixed (detaches worker
    if it doesn't stop within 3s).
  - **Image cache** validates before caching (corrupt data no longer poisons
    the cache forever), cancels in-flight requests on `clear()`, tolerates
    disk write failures, deduplicates in-flight requests, and adds a 15s
    transfer timeout.
  - **Duplicates** safety check uses fuzzy group keys (was exact-name, which
    could wrongly block removal). Substring heuristic tightened to avoid
    "Doom"/"Doom Eternal" false positives.
  - **Settings** uses atomic write (temp file + replace) and only mutates the
    in-memory config after the file write succeeds (was leaving config
    inconsistent on write failure). Uses the actual config path from
    `Config.config_path` instead of CWD.
  - **Main window** guards against concurrent refetch workers, guards against
    swapping API clients during a running scan, cleans up workers via
    `deleteLater`, and shows a progress dialog during `_add_game` fetches.
  - **API clients** honor `Retry-After` on 429, don't retry 4xx (saves quota),
    don't cache genre load failures permanently, expose `close()` for session
    cleanup, validate `game_id` types, and fix `_platform_label` ("PC Engine"
    no longer misclassified as "PC").
  - **Release date** zero-pads day/month (was passing through unpadded values).
  - **DB schema** makes `esrb_rating NOT NULL DEFAULT ''` (was nullable in new
    DBs, contradicting migrations). `by_disk` query simplified, `by_year`
    validates digits, `_volume_label` resolved via `os.path.splitdrive`.
  - **Config** `to_int`/`to_float` no longer silently override `0` values with
    defaults.
  - **Exporter** adds Excel auto-filter and friendly `PermissionError` message
    (was raw traceback when file was open in Excel).
  - **Cross-platform tests** — `test_stats_distributions` now mocks
    `os.path.splitdrive` to simulate Windows drive letters on Linux CI;
    `export_backup` catches `OSError` (not just `PermissionError`) so
    `IsADirectoryError` on Linux also gets the friendly "may be open in
    another program" message.
  - **`run.py`** now configures logging (was dropping all diagnostics).
  - **`run.pyw`** removes redundant import and falls back to stderr when Qt is
    unavailable.
- **Dark theme is not user-toggleable** — the app is dark-only. A light theme
  would require a parallel palette in `theme.py` and a settings toggle; not
  planned for v1.x.
- **Status column rendering is custom** — `GamesItemDelegate` paints the Status
  cell as a colored badge (bypassing the default delegate). If a new column is
  inserted before Status (col 9) or Source (col 8) in `COLUMNS`, the
  `_STATUS_COL` / `_SOURCE_COL` constants in `item_delegate.py` must be updated
  to match.
- **Default sort is alphabetical by Game** — `sortByColumn(0, AscendingOrder)`
  is applied after `setSortingEnabled(True)`. The proxy's `lessThan` for the
  Game column is case-insensitive with a stable tiebreak by source row. If the
  user clicks another column header, that sort takes over until the next
  model reset (which reverts to the default).
- **Cross-platform support** — Windows and Linux. The scanner detects Linux
  system folders (`/etc`, `/var`, `/usr`, `/proc`, `/sys`, `/dev`, etc.) and
  skips them. Linux executables (ELF binaries, `.AppImage`, `.sh`, `.bin`)
  are detected alongside `.exe` files (Wine/Proton games). GOG `.sh`
  installers are recognized. Volume labels on Linux are resolved via
  `/proc/mounts` and `/dev/disk/by-label/`. The `disk` property uses
  mount-point resolution (walking `st_dev` changes) instead of drive letters.
  A `.desktop` file is generated on Linux by `scripts/make_shortcut.py`.
  macOS is not yet tested but the GUI (Qt) is cross-platform.
- **No commits yet** — the repo is in its initial uncommitted state. The first
  commit should establish `main` with the current tree.
- **RAWG currently unreachable** — as of 2025-08-16 the RAWG API returns HTTP
  522. The merge step is skipped silently; ESRB ratings, genres, descriptions,
  and developers still populate from TheGamesDB, but `user_rating`,
  `metacritic_score`, and `cover_url` stay empty until RAWG recovers. A rescan
  will pick them up automatically.
- **TheGamesDB null fields** — TGDB returns `null` (not `[]`) for
  `developers` / `publishers` / `genres` when a game has none. All `.get()`
  calls on list fields use the `(value or [])` pattern; new code touching TGDB
  JSON must maintain this.
- **TheGamesDB `include` param** — only supports `boxart` and `platform`. Genres,
  developers, and publishers come back as IDs only; the client caches genres via
  `/v1/Genres` and resolves dev/pub names via batch `/Developers/ByDeveloperID`
  and `/Publishers/ByPublisherID` lookups. Boxart front cover is extracted from
  the `include.boxart` block and stored in `cover_url`.
- **TheGamesDB quota** — public-tier limit is 1000 requests/month. The client
  captures `remaining_monthly_allowance` from each response; the status bar
  shows it after the first API call (triggered on startup via a background
  `/Genres` fetch). There's no UI warning when the quota is low yet.
- **Manual games** — added via "Add Game…" with a synthetic `folder_path` of
  `/manual/<name>`. These have no folder on disk, so "Open folder in Explorer"
  is hidden from their context menu. Re-fetching works normally.
- **Duplicate detection is fuzzy** — "Find Duplicates…" (Ctrl+D) uses three
  complementary signals (substring containment, character similarity ≥ 0.85,
  token-set Jaccard ≥ 0.70) with stop-word removal and Roman→Arabic numeral
  conversion. It catches typos, reordered words, and edition suffixes, but may
  produce false positives for games with very similar names (e.g. "Star Wars
  Jedi" vs "Star Wars Battlefront" are correctly rejected, but edge cases
  exist). The user always confirms removals in the dialog. Groups are built via
  union-find so transitive matches (A~B, B~C) cluster together.
- **Single-user, single-process** — SQLite is fine for one user, but the DB
  should not be opened by two GUI instances simultaneously (SQLite will block,
  not corrupt, but the UX is poor).
- **Image cache grows unbounded** — `covers/` directory is never auto-pruned.
  `ImageCache.clear()` exists but isn't wired to the UI yet.
- **Folder name cleaning is heuristic** — some release-group tags may slip
  through; the `NOISE_TOKENS` / `NOISE_REGEX` lists in `folder_scanner.py` are
  the place to extend if a pattern is missed.
- **Rescan refetches all rows** — `_run_refetch_all` in `main_window.py`
  re-fetches every record sequentially; for 135 games at 0.3s delay + network
  latency, a full rescan takes ~1–2 minutes. There's no per-row throttle UI yet.
- **Platform is Windows + Linux** — the scanner skips both Windows system
  folders and Linux system directories. macOS is not yet tested. The GUI
  itself is cross-platform via Qt.

## 10. Source of truth files

| File | Purpose |
|------|---------|
| `config.example.ini` | Template for all configurable settings. |
| `README.md` | User-facing documentation. |
| `PROJECT_CONTEXT.md` | This file — architectural and conventions reference. |
| `ROADMAP.md` | Planned features and priorities. |
| `tests/test_cataloger_integration.py` | Canned RAWG/TheGamesDB response shapes — the authoritative examples of what the API clients expect. |
| `playcache/backup.py` | Backup file format spec (`FORMAT_VERSION`, envelope schema). The authoritative reference for `.json.gz` backup structure. |
