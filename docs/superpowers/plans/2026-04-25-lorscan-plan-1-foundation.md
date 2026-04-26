# lorscan Plan 1 of 3 — Foundation + CLI Scanner

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the data layer and recognition pipeline so that running `lorscan scan path/to/photo.jpg` against a real binder-page photo prints the identified cards as a 3×3 grid table — proving the Claude-vision pipeline end-to-end before any web UI work begins.

**Architecture:** Python 3.12+, FastAPI deferred to Plan 2. Plan 1 builds the foundation: `Database` class with SQL migrations, catalog sync from `lorcana-api.com`, content-addressed photo storage, the Anthropic vision call (with prompt caching), strict JSON parsing, suffix-aware matching, and a CLI entry point.

**Tech Stack:** `uv` (dep mgmt), Python 3.12+, `httpx`, `Pillow`, `anthropic` SDK, `sqlite3` (stdlib), `pytest`, `pytest-asyncio`, `ruff`, `respx` (mock httpx), `freezegun`.

**Spec reference:** `docs/superpowers/specs/2026-04-25-lorscan-design.md` — read it before starting.

**Plan series:**
- **Plan 1 (this file)** — Foundation + CLI scanner. End state: `lorscan scan <photo>` works.
- **Plan 2 (deferred)** — Web UI: FastAPI app, /scan upload + review, /collection, /missing, /binders, /reorganize.
- **Plan 3 (deferred)** — 3D page-flip binder visualization, image cache, polish, v1 release.

Each subsequent plan will be authored by re-running the writing-plans skill against its scope.

---

## Phase Map (Plan 1)

| Phase | Name | Outcome |
|---|---|---|
| 0 | Scaffolding | `uv` project, package skeleton, lint clean, smoke test passes |
| 1 | Storage foundation | `Database` class with migrations 001–004; typed catalog ops |
| 2 | Catalog sync | `services/catalog.sync()` populates `sets` and `cards` from lorcana-api.com |
| 3 | Photos service | hash + save original + in-memory normalize for API |
| 4 | Recognition pipeline | `recognition.identify(bytes) → ParsedScan` works against stubbed Claude SDK |
| 5 | Matching algorithm | Suffix-aware match against catalog; full unit-test coverage |
| 6 | **MILESTONE: CLI scanner** | `lorscan scan photo.jpg` prints identified cards as a table |

---

## File structure (target at end of Plan 1)

```
lorscan/
├── pyproject.toml
├── uv.lock
├── src/lorscan/
│   ├── __init__.py
│   ├── config.py
│   ├── cli.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── catalog.py
│   │   ├── photos.py
│   │   ├── matching.py
│   │   └── recognition/
│   │       ├── __init__.py
│   │       ├── prompt.py
│   │       ├── client.py
│   │       └── parser.py
│   └── storage/
│       ├── __init__.py
│       ├── db.py
│       ├── models.py
│       └── migrations/
│           ├── 001_catalog.sql
│           ├── 002_collection.sql
│           ├── 003_scans.sql
│           └── 004_binders.sql
└── tests/
    ├── conftest.py
    ├── unit/
    │   ├── test_smoke.py
    │   ├── test_config.py
    │   ├── test_db_migrations.py
    │   ├── test_db_catalog_ops.py
    │   ├── test_catalog.py
    │   ├── test_photos.py
    │   ├── test_recognition_prompt.py
    │   ├── test_recognition_parser.py
    │   └── test_matching.py
    ├── integration/
    │   └── test_scan_pipeline.py
    └── fixtures/
        ├── api/
        │   └── cards-page-1.json
        ├── photos/
        │   └── (your example binder photos go here)
        └── claude/
            ├── good-3x3.json
            └── malformed.txt
```

---

## Phase 0 — Scaffolding

### Task 1: Initialize the uv project

**Files:**
- Create: `pyproject.toml`
- Create: `src/lorscan/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Verify uv is installed**

```bash
uv --version
```

Expected: a version string. If missing: `curl -LsSf https://astral.sh/uv/install.sh | sh`.

- [ ] **Step 2: Initialize the project**

```bash
uv init --package --name lorscan --python 3.12
```

This creates `pyproject.toml`, `src/lorscan/__init__.py`, and `.venv/`. Verify with `ls src/lorscan`.

- [ ] **Step 3: Replace `pyproject.toml`**

```toml
[project]
name = "lorscan"
version = "0.1.0"
description = "Local Lorcana collection manager with Claude-vision card recognition"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "anthropic>=0.40",
    "httpx>=0.28",
    "Pillow>=11.0",
]

[project.scripts]
lorscan = "lorscan.cli:main"

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "respx>=0.21",
    "freezegun>=1.5",
    "ruff>=0.7",
    "syrupy>=4.7",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "N", "SIM"]
ignore = ["E501"]

[tool.pytest.ini_options]
addopts = "-ra -q"
testpaths = ["tests"]
markers = [
    "live: hits real external APIs; requires --runlive flag",
]
```

(Note: FastAPI/Uvicorn/Jinja2/python-multipart are intentionally **not** in Plan 1's deps — they're added in Plan 2.)

- [ ] **Step 4: Sync deps**

```bash
uv sync
```

Expected: creates `uv.lock`, populates `.venv/`.

- [ ] **Step 5: Smoke-import the package**

```bash
uv run python -c "import lorscan; print(lorscan.__name__)"
```

Expected: `lorscan`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/lorscan/__init__.py tests/__init__.py
git commit -m "chore: scaffold uv project with python 3.12 + plan-1 deps"
```

---

### Task 2: Package version + smoke test

**Files:**
- Modify: `src/lorscan/__init__.py`
- Create: `tests/unit/__init__.py`, `tests/integration/__init__.py`, `tests/fixtures/`
- Create: `tests/unit/test_smoke.py`

- [ ] **Step 1: Write `src/lorscan/__init__.py`**

```python
"""lorscan — Lorcana collection manager."""

__version__ = "0.1.0"
__all__ = ["__version__"]
```

- [ ] **Step 2: Create test directories**

```bash
mkdir -p tests/unit tests/integration tests/fixtures/api tests/fixtures/photos tests/fixtures/claude
touch tests/unit/__init__.py tests/integration/__init__.py
```

- [ ] **Step 3: Write the smoke test**

`tests/unit/test_smoke.py`:

```python
"""Package smoke test."""
import lorscan


def test_version_is_set():
    assert lorscan.__version__ == "0.1.0"


def test_import_does_not_error():
    import lorscan  # noqa: F401
```

- [ ] **Step 4: Run the test**

```bash
uv run pytest tests/unit/test_smoke.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Lint clean**

```bash
uv run ruff check src tests
uv run ruff format --check src tests
```

If format check fails: `uv run ruff format src tests`.

- [ ] **Step 6: Commit**

```bash
git add src/lorscan/__init__.py tests
git commit -m "test: add package smoke test"
```

---

### Task 3: Config loader (TOML + env)

**Files:**
- Create: `src/lorscan/config.py`
- Create: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_config.py`:

```python
"""Config loads from TOML with env-var overrides."""
from pathlib import Path

import pytest

from lorscan.config import load_config


def test_load_config_from_toml(tmp_path: Path):
    toml = tmp_path / "config.toml"
    toml.write_text(
        '[anthropic]\n'
        'api_key = "sk-ant-test-from-toml"\n'
        'model = "claude-sonnet-4-6"\n'
        '[budget]\n'
        'per_scan_usd = 0.50\n'
        'monthly_usd = 5.00\n'
    )

    cfg = load_config(toml_path=toml, env={})

    assert cfg.anthropic_api_key == "sk-ant-test-from-toml"
    assert cfg.anthropic_model == "claude-sonnet-4-6"
    assert cfg.per_scan_budget_usd == 0.50
    assert cfg.monthly_budget_usd == 5.00


def test_env_overrides_toml(tmp_path: Path):
    toml = tmp_path / "config.toml"
    toml.write_text('[anthropic]\napi_key = "from-toml"\n')
    cfg = load_config(toml_path=toml, env={"ANTHROPIC_API_KEY": "from-env"})
    assert cfg.anthropic_api_key == "from-env"


def test_missing_api_key_raises(tmp_path: Path):
    toml = tmp_path / "config.toml"
    toml.write_text('[anthropic]\nmodel = "claude-sonnet-4-6"\n')
    with pytest.raises(ValueError, match="anthropic.api_key"):
        load_config(toml_path=toml, env={})


def test_defaults_when_toml_missing():
    cfg = load_config(
        toml_path=Path("/definitely/not/here.toml"),
        env={"ANTHROPIC_API_KEY": "from-env-only"},
    )
    assert cfg.anthropic_api_key == "from-env-only"
    assert cfg.anthropic_model == "claude-sonnet-4-6"
    assert cfg.per_scan_budget_usd == 0.50
    assert cfg.monthly_budget_usd is None
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/unit/test_config.py -v
```

Expected: ImportError on `from lorscan.config import load_config`.

- [ ] **Step 3: Implement `src/lorscan/config.py`**

```python
"""Configuration: TOML file + env-var overrides."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_PER_SCAN_BUDGET_USD = 0.50
DEFAULT_MONTHLY_BUDGET_USD: float | None = None
DEFAULT_DATA_DIR = Path.home() / ".lorscan"
DEFAULT_CATALOG_API_BASE = "https://api.lorcana-api.com"


@dataclass(frozen=True)
class Config:
    anthropic_api_key: str
    anthropic_model: str
    per_scan_budget_usd: float
    monthly_budget_usd: float | None
    data_dir: Path
    catalog_api_base: str = DEFAULT_CATALOG_API_BASE

    @property
    def db_path(self) -> Path:
        return self.data_dir / "lorscan.db"

    @property
    def photos_dir(self) -> Path:
        return self.data_dir / "photos"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"


def load_config(
    *,
    toml_path: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Config:
    """Load config — defaults → TOML → env (later wins)."""
    env = env if env is not None else {}
    toml_path = toml_path if toml_path is not None else DEFAULT_DATA_DIR / "config.toml"

    data: dict = {}
    if toml_path.exists():
        with toml_path.open("rb") as f:
            data = tomllib.load(f)

    anthropic = data.get("anthropic", {})
    budget = data.get("budget", {})
    storage = data.get("storage", {})

    api_key = env.get("ANTHROPIC_API_KEY") or anthropic.get("api_key")
    if not api_key:
        raise ValueError(
            "Missing anthropic.api_key — set it in ~/.lorscan/config.toml "
            "or via the ANTHROPIC_API_KEY environment variable."
        )

    model = env.get("LORSCAN_MODEL") or anthropic.get("model") or DEFAULT_MODEL
    per_scan = float(budget.get("per_scan_usd", DEFAULT_PER_SCAN_BUDGET_USD))
    monthly_raw = budget.get("monthly_usd", DEFAULT_MONTHLY_BUDGET_USD)
    monthly = float(monthly_raw) if monthly_raw is not None else None

    data_dir_str = env.get("LORSCAN_DATA_DIR") or storage.get("data_dir")
    data_dir = Path(data_dir_str).expanduser() if data_dir_str else DEFAULT_DATA_DIR

    return Config(
        anthropic_api_key=api_key,
        anthropic_model=model,
        per_scan_budget_usd=per_scan,
        monthly_budget_usd=monthly,
        data_dir=data_dir,
    )
```

- [ ] **Step 4: Run to verify pass**

```bash
uv run pytest tests/unit/test_config.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/lorscan/config.py tests/unit/test_config.py
git commit -m "feat(config): TOML + env-var configuration loader"
```

---

## Phase 1 — Storage Foundation

### Task 4: Migration files (001–004)

**Files:**
- Create: `src/lorscan/storage/__init__.py`
- Create: `src/lorscan/storage/migrations/__init__.py`
- Create: `src/lorscan/storage/migrations/001_catalog.sql`
- Create: `src/lorscan/storage/migrations/002_collection.sql`
- Create: `src/lorscan/storage/migrations/003_scans.sql`
- Create: `src/lorscan/storage/migrations/004_binders.sql`

- [ ] **Step 1: Create the storage package**

```bash
mkdir -p src/lorscan/storage/migrations
touch src/lorscan/storage/__init__.py src/lorscan/storage/migrations/__init__.py
```

- [ ] **Step 2: Write `001_catalog.sql`**

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
  version    TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE sets (
  set_code     TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  released_on  TEXT,
  total_cards  INTEGER NOT NULL,
  icon_url     TEXT,
  synced_at    TEXT NOT NULL
);

CREATE TABLE cards (
  card_id          TEXT PRIMARY KEY,
  set_code         TEXT NOT NULL REFERENCES sets(set_code),
  collector_number TEXT NOT NULL,
  name             TEXT NOT NULL,
  subtitle         TEXT,
  rarity           TEXT NOT NULL,
  ink_color        TEXT,
  cost             INTEGER,
  inkable          INTEGER,
  card_type        TEXT,
  body_text        TEXT,
  image_url        TEXT,
  api_payload      TEXT NOT NULL,
  UNIQUE(set_code, collector_number)
);
CREATE INDEX cards_name_idx ON cards(name);
CREATE INDEX cards_set_idx  ON cards(set_code);
```

- [ ] **Step 3: Write `002_collection.sql`**

```sql
CREATE TABLE collection_items (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  card_id       TEXT NOT NULL REFERENCES cards(card_id),
  finish        TEXT NOT NULL DEFAULT 'regular',
  finish_label  TEXT,
  quantity      INTEGER NOT NULL DEFAULT 1,
  notes         TEXT,
  updated_at    TEXT NOT NULL,
  UNIQUE(card_id, finish, COALESCE(finish_label, ''))
);
CREATE INDEX collection_items_card_idx ON collection_items(card_id);
```

- [ ] **Step 4: Write `003_scans.sql`**

```sql
CREATE TABLE scans (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  photo_hash            TEXT NOT NULL UNIQUE,
  photo_path            TEXT NOT NULL,
  status                TEXT NOT NULL,
  error_message         TEXT,
  api_request_payload   TEXT,
  api_response_payload  TEXT,
  cost_usd              REAL,
  created_at            TEXT NOT NULL,
  completed_at          TEXT
);
CREATE INDEX scans_status_idx     ON scans(status);
CREATE INDEX scans_created_at_idx ON scans(created_at);

CREATE TABLE scan_results (
  id                       INTEGER PRIMARY KEY AUTOINCREMENT,
  scan_id                  INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
  grid_position            TEXT NOT NULL,
  claude_name              TEXT,
  claude_subtitle          TEXT,
  claude_collector_number  TEXT,
  claude_set_hint          TEXT,
  claude_ink_color         TEXT,
  claude_finish            TEXT,
  confidence               TEXT NOT NULL,
  matched_card_id          TEXT REFERENCES cards(card_id),
  match_method             TEXT,
  user_decision            TEXT,
  user_replaced_card_id    TEXT REFERENCES cards(card_id),
  applied_at               TEXT
);
CREATE INDEX scan_results_scan_idx ON scan_results(scan_id);
```

- [ ] **Step 5: Write `004_binders.sql`**

```sql
CREATE TABLE binders (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL,
  set_code    TEXT REFERENCES sets(set_code),
  finish      TEXT,
  notes       TEXT,
  created_at  TEXT NOT NULL
);

ALTER TABLE scans ADD COLUMN binder_id    INTEGER REFERENCES binders(id);
ALTER TABLE scans ADD COLUMN page_number  INTEGER;

ALTER TABLE scan_results ADD COLUMN position_anomaly             TEXT;
ALTER TABLE scan_results ADD COLUMN position_anomaly_detail      TEXT;
ALTER TABLE scan_results ADD COLUMN position_anomaly_resolved_at TEXT;
```

- [ ] **Step 6: Commit**

```bash
git add src/lorscan/storage
git commit -m "feat(storage): add SQL migrations 001-004"
```

---

### Task 5: `Database` class with migration runner

**Files:**
- Create: `src/lorscan/storage/db.py`
- Create: `tests/conftest.py`
- Create: `tests/unit/test_db_migrations.py`

- [ ] **Step 1: Write `tests/conftest.py`**

```python
"""Shared pytest fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest

from lorscan.storage.db import Database


@pytest.fixture()
def db() -> Database:
    """A fresh in-memory SQLite database with all migrations applied."""
    database = Database.connect(":memory:")
    database.migrate()
    yield database
    database.close()


@pytest.fixture()
def tmp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway ~/.lorscan/-style directory for tests that touch disk."""
    data_dir = tmp_path / "lorscan-data"
    data_dir.mkdir()
    monkeypatch.setenv("LORSCAN_DATA_DIR", str(data_dir))
    return data_dir
```

- [ ] **Step 2: Write the failing test**

`tests/unit/test_db_migrations.py`:

```python
"""Migrations: forward-only, idempotent, version-tracked."""
from __future__ import annotations

import sqlite3

import pytest

from lorscan.storage.db import Database


def test_migrate_creates_all_tables(db: Database):
    cursor = db.connection.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    tables = [row[0] for row in cursor.fetchall()]
    assert tables == [
        "binders", "cards", "collection_items",
        "scan_results", "scans", "schema_migrations", "sets",
    ]


def test_migrate_records_versions(db: Database):
    cursor = db.connection.cursor()
    cursor.execute("SELECT version FROM schema_migrations ORDER BY version")
    versions = [row[0] for row in cursor.fetchall()]
    assert versions == ["001_catalog", "002_collection", "003_scans", "004_binders"]


def test_migrate_is_idempotent(db: Database):
    db.migrate()  # second run should no-op
    cursor = db.connection.cursor()
    cursor.execute("SELECT COUNT(*) FROM schema_migrations")
    (count,) = cursor.fetchone()
    assert count == 4


def test_foreign_keys_are_enforced(db: Database):
    (enabled,) = db.connection.execute("PRAGMA foreign_keys").fetchone()
    assert enabled == 1


def test_collection_items_unique_constraint(db: Database):
    cursor = db.connection.cursor()
    cursor.execute(
        "INSERT INTO sets (set_code, name, total_cards, synced_at) "
        "VALUES ('1', 'TFC', 204, '2026-04-25T00:00:00')"
    )
    cursor.execute(
        "INSERT INTO cards (card_id, set_code, collector_number, name, rarity, api_payload) "
        "VALUES ('c1', '1', '1', 'Mickey', 'Common', '{}')"
    )
    cursor.execute(
        "INSERT INTO collection_items (card_id, finish, quantity, updated_at) "
        "VALUES ('c1', 'regular', 1, '2026-04-25T00:00:00')"
    )
    db.connection.commit()

    with pytest.raises(sqlite3.IntegrityError):
        cursor.execute(
            "INSERT INTO collection_items (card_id, finish, quantity, updated_at) "
            "VALUES ('c1', 'regular', 1, '2026-04-25T00:00:00')"
        )
```

- [ ] **Step 3: Run to verify failure**

```bash
uv run pytest tests/unit/test_db_migrations.py -v
```

Expected: ImportError on `from lorscan.storage.db import Database`.

- [ ] **Step 4: Implement `src/lorscan/storage/db.py`**

```python
"""SQLite Database wrapper + forward-only migration runner."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lorscan.storage.models import Card, CardSet


class Database:
    """Owns one sqlite3 connection and the migration runner."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    @classmethod
    def connect(cls, path: str | Path) -> "Database":
        conn = sqlite3.connect(str(path), detect_types=sqlite3.PARSE_DECLTYPES)
        conn.execute("PRAGMA foreign_keys = ON")
        if str(path) != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
        conn.row_factory = sqlite3.Row
        return cls(conn)

    def close(self) -> None:
        self.connection.close()

    def migrate(self) -> None:
        """Apply pending migrations in alphabetical order. Idempotent."""
        self._ensure_migrations_table()
        applied = self._applied_versions()

        for migration_path in self._discover_migrations():
            version = migration_path.stem
            if version in applied:
                continue
            sql = migration_path.read_text()
            self.connection.executescript(sql)
            self.connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, datetime.now(UTC).isoformat()),
            )
            self.connection.commit()

    def _ensure_migrations_table(self) -> None:
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='schema_migrations'"
        )
        if cursor.fetchone() is None:
            cursor.execute(
                "CREATE TABLE schema_migrations ("
                "  version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            self.connection.commit()

    def _applied_versions(self) -> set[str]:
        cursor = self.connection.cursor()
        cursor.execute("SELECT version FROM schema_migrations")
        return {row[0] for row in cursor.fetchall()}

    @staticmethod
    def _discover_migrations() -> list[Path]:
        package = resources.files("lorscan.storage.migrations")
        files = [Path(str(f)) for f in package.iterdir() if f.name.endswith(".sql")]
        return sorted(files, key=lambda p: p.name)
```

- [ ] **Step 5: Run to verify pass**

```bash
uv run pytest tests/unit/test_db_migrations.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add src/lorscan/storage/db.py tests/conftest.py tests/unit/test_db_migrations.py
git commit -m "feat(storage): Database class with forward-only migration runner"
```

---

### Task 6: Domain dataclasses + catalog upsert/get methods

**Files:**
- Create: `src/lorscan/storage/models.py`
- Modify: `src/lorscan/storage/db.py`
- Create: `tests/unit/test_db_catalog_ops.py`

- [ ] **Step 1: Write `src/lorscan/storage/models.py`**

```python
"""Plain dataclasses for domain types."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CardSet:
    set_code: str
    name: str
    total_cards: int
    released_on: str | None = None
    icon_url: str | None = None


@dataclass(frozen=True)
class Card:
    card_id: str
    set_code: str
    collector_number: str
    name: str
    rarity: str
    subtitle: str | None = None
    ink_color: str | None = None
    cost: int | None = None
    inkable: bool | None = None
    card_type: str | None = None
    body_text: str | None = None
    image_url: str | None = None
    api_payload: str = "{}"


@dataclass(frozen=True)
class CollectionItem:
    card_id: str
    finish: str
    quantity: int
    finish_label: str | None = None
    notes: str | None = None
    id: int | None = None


@dataclass(frozen=True)
class Binder:
    name: str
    set_code: str | None = None
    finish: str | None = None
    notes: str | None = None
    id: int | None = None
```

- [ ] **Step 2: Write the failing test**

`tests/unit/test_db_catalog_ops.py`:

```python
"""Catalog operations: upsert + read for sets and cards."""
from __future__ import annotations

from lorscan.storage.db import Database
from lorscan.storage.models import Card, CardSet


def test_upsert_set_inserts_then_updates(db: Database):
    db.upsert_set(CardSet(set_code="1", name="The First Chapter", total_cards=204))
    db.upsert_set(CardSet(set_code="1", name="TFC (renamed)", total_cards=204))
    rows = db.get_sets()
    assert len(rows) == 1
    assert rows[0].name == "TFC (renamed)"


def test_upsert_card_inserts_then_updates(db: Database):
    db.upsert_set(CardSet(set_code="1", name="TFC", total_cards=204))
    db.upsert_card(Card(card_id="c-127", set_code="1", collector_number="127",
                        name="Mickey", rarity="Common"))
    db.upsert_card(Card(card_id="c-127", set_code="1", collector_number="127",
                        name="Mickey Mouse", rarity="Rare"))
    found = db.get_card_by_id("c-127")
    assert found is not None
    assert found.name == "Mickey Mouse"
    assert found.rarity == "Rare"


def test_get_card_by_collector_number_with_suffix(db: Database):
    db.upsert_set(CardSet(set_code="X", name="Adventure Set", total_cards=27))
    db.upsert_card(Card(card_id="x-1a", set_code="X", collector_number="1a",
                        name="Story A", rarity="Common"))
    db.upsert_card(Card(card_id="x-1b", set_code="X", collector_number="1b",
                        name="Story B", rarity="Common"))

    a = db.get_card_by_collector_number("X", "1a")
    b = db.get_card_by_collector_number("X", "1b")
    assert a is not None and a.card_id == "x-1a"
    assert b is not None and b.card_id == "x-1b"
    assert db.get_card_by_collector_number("X", "1") is None


def test_search_cards_by_name(db: Database):
    db.upsert_set(CardSet(set_code="1", name="TFC", total_cards=204))
    db.upsert_card(Card(card_id="c1", set_code="1", collector_number="1",
                        name="Mickey Mouse", subtitle="Brave Little Tailor",
                        rarity="Legendary"))
    db.upsert_card(Card(card_id="c2", set_code="1", collector_number="2",
                        name="Mickey Mouse", subtitle="Detective",
                        rarity="Rare"))

    matches = db.search_cards_by_name("Mickey Mouse")
    assert len(matches) == 2
    matches_in_set = db.search_cards_by_name("Mickey Mouse", set_code="1")
    assert len(matches_in_set) == 2
    miss = db.search_cards_by_name("Donald Duck")
    assert miss == []
```

- [ ] **Step 3: Run to verify failure**

```bash
uv run pytest tests/unit/test_db_catalog_ops.py -v
```

Expected: AttributeError on `db.upsert_set`.

- [ ] **Step 4: Append catalog methods to `src/lorscan/storage/db.py`**

Inside the `Database` class, add the following methods (place after `_discover_migrations`):

```python
    # ---------- catalog ops ----------

    def upsert_set(self, s: "CardSet") -> None:
        from lorscan.storage.models import CardSet  # noqa: F401

        self.connection.execute(
            "INSERT INTO sets (set_code, name, released_on, total_cards, icon_url, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(set_code) DO UPDATE SET "
            "  name = excluded.name, "
            "  released_on = excluded.released_on, "
            "  total_cards = excluded.total_cards, "
            "  icon_url = excluded.icon_url, "
            "  synced_at = excluded.synced_at",
            (
                s.set_code, s.name, s.released_on, s.total_cards, s.icon_url,
                datetime.now(UTC).isoformat(),
            ),
        )
        self.connection.commit()

    def get_sets(self) -> list["CardSet"]:
        from lorscan.storage.models import CardSet
        rows = self.connection.execute(
            "SELECT set_code, name, released_on, total_cards, icon_url FROM sets "
            "ORDER BY set_code"
        ).fetchall()
        return [
            CardSet(
                set_code=r["set_code"], name=r["name"],
                released_on=r["released_on"], total_cards=r["total_cards"],
                icon_url=r["icon_url"],
            )
            for r in rows
        ]

    def upsert_card(self, c: "Card") -> None:
        self.connection.execute(
            "INSERT INTO cards (card_id, set_code, collector_number, name, subtitle, "
            "                   rarity, ink_color, cost, inkable, card_type, body_text, "
            "                   image_url, api_payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(card_id) DO UPDATE SET "
            "  set_code = excluded.set_code, "
            "  collector_number = excluded.collector_number, "
            "  name = excluded.name, "
            "  subtitle = excluded.subtitle, "
            "  rarity = excluded.rarity, "
            "  ink_color = excluded.ink_color, "
            "  cost = excluded.cost, "
            "  inkable = excluded.inkable, "
            "  card_type = excluded.card_type, "
            "  body_text = excluded.body_text, "
            "  image_url = excluded.image_url, "
            "  api_payload = excluded.api_payload",
            (
                c.card_id, c.set_code, c.collector_number, c.name, c.subtitle,
                c.rarity, c.ink_color, c.cost,
                int(c.inkable) if c.inkable is not None else None,
                c.card_type, c.body_text, c.image_url, c.api_payload,
            ),
        )
        self.connection.commit()

    def get_card_by_id(self, card_id: str) -> "Card | None":
        row = self.connection.execute(
            "SELECT * FROM cards WHERE card_id = ?", (card_id,)
        ).fetchone()
        return self._row_to_card(row)

    def get_card_by_collector_number(
        self, set_code: str, collector_number: str
    ) -> "Card | None":
        row = self.connection.execute(
            "SELECT * FROM cards WHERE set_code = ? AND collector_number = ?",
            (set_code, collector_number),
        ).fetchone()
        return self._row_to_card(row)

    def search_cards_by_name(
        self, name: str, *, set_code: str | None = None
    ) -> list["Card"]:
        if set_code:
            rows = self.connection.execute(
                "SELECT * FROM cards WHERE set_code = ? AND name = ? "
                "ORDER BY collector_number",
                (set_code, name),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM cards WHERE name = ? ORDER BY set_code, collector_number",
                (name,),
            ).fetchall()
        return [self._row_to_card(r) for r in rows if r is not None]

    @staticmethod
    def _row_to_card(row: sqlite3.Row | None) -> "Card | None":
        if row is None:
            return None
        from lorscan.storage.models import Card
        return Card(
            card_id=row["card_id"],
            set_code=row["set_code"],
            collector_number=row["collector_number"],
            name=row["name"],
            subtitle=row["subtitle"],
            rarity=row["rarity"],
            ink_color=row["ink_color"],
            cost=row["cost"],
            inkable=bool(row["inkable"]) if row["inkable"] is not None else None,
            card_type=row["card_type"],
            body_text=row["body_text"],
            image_url=row["image_url"],
            api_payload=row["api_payload"],
        )
```

- [ ] **Step 5: Run to verify pass**

```bash
uv run pytest tests/unit/test_db_catalog_ops.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add src/lorscan/storage/db.py src/lorscan/storage/models.py tests/unit/test_db_catalog_ops.py
git commit -m "feat(storage): catalog upsert/get/search operations + domain dataclasses"
```

---

## Phase 2 — Catalog Sync

### Task 7: Recorded API fixture + LoraCanaApiClient

**Files:**
- Create: `tests/fixtures/api/cards-page-1.json`
- Create: `src/lorscan/services/__init__.py`
- Create: `src/lorscan/services/catalog.py`
- Create: `tests/unit/test_catalog.py`

- [ ] **Step 1: Create the fixture**

`tests/fixtures/api/cards-page-1.json` — a small representative page of 4 cards for testing. Shape mirrors what lorcana-api.com returns; add fields conservatively (the real API returns more, but our parser uses only what's listed):

```json
[
  {
    "Unique_ID": "TFC-001",
    "Set_Num": 1,
    "Set_Name": "The First Chapter",
    "Card_Num": 1,
    "Card_Number": "1",
    "Name": "Ariel",
    "Subtitle": "On Human Legs",
    "Rarity": "Common",
    "Color": "Amber",
    "Cost": 4,
    "Inkable": true,
    "Type": "Character",
    "Body_Text": "",
    "Flavor_Text": "...",
    "Image": "https://example.com/img/tfc-001.png"
  },
  {
    "Unique_ID": "TFC-127",
    "Set_Num": 1,
    "Set_Name": "The First Chapter",
    "Card_Num": 127,
    "Card_Number": "127",
    "Name": "Mickey Mouse",
    "Subtitle": "Brave Little Tailor",
    "Rarity": "Legendary",
    "Color": "Steel",
    "Cost": 8,
    "Inkable": false,
    "Type": "Character",
    "Body_Text": "...",
    "Image": "https://example.com/img/tfc-127.png"
  },
  {
    "Unique_ID": "ADV-001A",
    "Set_Num": 99,
    "Set_Name": "Adventure Set",
    "Card_Num": 1,
    "Card_Number": "1a",
    "Name": "Story Card",
    "Subtitle": "Path A",
    "Rarity": "Common",
    "Color": null,
    "Cost": null,
    "Inkable": false,
    "Type": "Story",
    "Body_Text": "...",
    "Image": "https://example.com/img/adv-001a.png"
  },
  {
    "Unique_ID": "ADV-001B",
    "Set_Num": 99,
    "Set_Name": "Adventure Set",
    "Card_Num": 1,
    "Card_Number": "1b",
    "Name": "Story Card",
    "Subtitle": "Path B",
    "Rarity": "Common",
    "Color": null,
    "Cost": null,
    "Inkable": false,
    "Type": "Story",
    "Body_Text": "...",
    "Image": "https://example.com/img/adv-001b.png"
  }
]
```

(The actual API returns more fields — the sync code below picks what we need. If real API returns differ when we hit it live, we adjust the parser; the fixture is intentionally minimal.)

- [ ] **Step 2: Create the services package**

```bash
mkdir -p src/lorscan/services
touch src/lorscan/services/__init__.py
```

- [ ] **Step 3: Write the failing test**

`tests/unit/test_catalog.py`:

```python
"""Catalog sync: pulls from lorcana-api.com (mocked) into the database."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from lorscan.services.catalog import sync_catalog
from lorscan.storage.db import Database


FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "api" / "cards-page-1.json"


@pytest.mark.asyncio
async def test_sync_inserts_sets_and_cards(db: Database):
    fixture_payload = json.loads(FIXTURE_PATH.read_text())

    with respx.mock(base_url="https://api.lorcana-api.com") as mock:
        # First page returns our fixture; second page returns empty (end signal).
        mock.get("/cards/all", params={"pagesize": "1000", "page": "1"}).mock(
            return_value=httpx.Response(200, json=fixture_payload)
        )
        mock.get("/cards/all", params={"pagesize": "1000", "page": "2"}).mock(
            return_value=httpx.Response(200, json=[])
        )

        result = await sync_catalog(db, base_url="https://api.lorcana-api.com")

    assert result.cards_synced == 4
    assert result.sets_synced == 2

    sets = db.get_sets()
    set_codes = {s.set_code for s in sets}
    assert set_codes == {"1", "99"}

    mickey = db.get_card_by_collector_number("1", "127")
    assert mickey is not None
    assert mickey.name == "Mickey Mouse"
    assert mickey.subtitle == "Brave Little Tailor"
    assert mickey.rarity == "Legendary"
    assert mickey.ink_color == "Steel"
    assert mickey.inkable is False

    a = db.get_card_by_collector_number("99", "1a")
    b = db.get_card_by_collector_number("99", "1b")
    assert a is not None and a.subtitle == "Path A"
    assert b is not None and b.subtitle == "Path B"


@pytest.mark.asyncio
async def test_sync_is_idempotent(db: Database):
    fixture_payload = json.loads(FIXTURE_PATH.read_text())

    with respx.mock(base_url="https://api.lorcana-api.com") as mock:
        mock.get("/cards/all", params={"pagesize": "1000", "page": "1"}).mock(
            return_value=httpx.Response(200, json=fixture_payload)
        )
        mock.get("/cards/all", params={"pagesize": "1000", "page": "2"}).mock(
            return_value=httpx.Response(200, json=[])
        )

        await sync_catalog(db, base_url="https://api.lorcana-api.com")

    with respx.mock(base_url="https://api.lorcana-api.com") as mock:
        mock.get("/cards/all", params={"pagesize": "1000", "page": "1"}).mock(
            return_value=httpx.Response(200, json=fixture_payload)
        )
        mock.get("/cards/all", params={"pagesize": "1000", "page": "2"}).mock(
            return_value=httpx.Response(200, json=[])
        )

        result = await sync_catalog(db, base_url="https://api.lorcana-api.com")

    assert result.cards_synced == 4  # upsert: still 4, no duplicates
    cursor = db.connection.cursor()
    (count,) = cursor.execute("SELECT COUNT(*) FROM cards").fetchone()
    assert count == 4
```

Add `pytest-asyncio` config to `pyproject.toml` under the existing `[tool.pytest.ini_options]`:

```toml
asyncio_mode = "auto"
```

- [ ] **Step 4: Run to verify failure**

```bash
uv run pytest tests/unit/test_catalog.py -v
```

Expected: ImportError on `from lorscan.services.catalog import sync_catalog`.

- [ ] **Step 5: Implement `src/lorscan/services/catalog.py`**

```python
"""Catalog sync from lorcana-api.com."""
from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from lorscan.storage.db import Database
from lorscan.storage.models import Card, CardSet


PAGE_SIZE = 1000


@dataclass(frozen=True)
class SyncResult:
    cards_synced: int
    sets_synced: int


async def sync_catalog(db: Database, *, base_url: str) -> SyncResult:
    """Pull all cards from lorcana-api.com into the local SQLite catalog.

    Idempotent — uses upsert semantics, so re-running is safe.
    """
    sets_seen: dict[str, CardSet] = {}
    cards_total = 0

    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        page = 1
        while True:
            response = await client.get(
                "/cards/all", params={"pagesize": str(PAGE_SIZE), "page": str(page)}
            )
            response.raise_for_status()
            payload = response.json()
            if not payload:
                break

            for raw in payload:
                set_code = str(raw.get("Set_Num"))
                set_name = raw.get("Set_Name", f"Set {set_code}")
                total_in_set = sets_seen.get(set_code)
                if total_in_set is None:
                    sets_seen[set_code] = CardSet(
                        set_code=set_code,
                        name=set_name,
                        total_cards=0,  # provisional; updated below
                    )

                card = _parse_card(raw, set_code)
                db.upsert_card(card)
                cards_total += 1

            page += 1

    # Compute total_cards per set from what we just inserted, then upsert sets.
    for set_code, partial in sets_seen.items():
        (count,) = db.connection.execute(
            "SELECT COUNT(*) FROM cards WHERE set_code = ?", (set_code,)
        ).fetchone()
        db.upsert_set(
            CardSet(
                set_code=partial.set_code,
                name=partial.name,
                total_cards=int(count),
            )
        )

    return SyncResult(cards_synced=cards_total, sets_synced=len(sets_seen))


def _parse_card(raw: dict, set_code: str) -> Card:
    """Map a lorcana-api.com card object into our Card dataclass."""
    inkable_raw = raw.get("Inkable")
    inkable = bool(inkable_raw) if inkable_raw is not None else None
    cost = raw.get("Cost")
    cost = int(cost) if cost is not None else None

    return Card(
        card_id=str(raw["Unique_ID"]),
        set_code=set_code,
        collector_number=str(raw.get("Card_Number")),
        name=str(raw["Name"]),
        subtitle=raw.get("Subtitle") or None,
        rarity=str(raw.get("Rarity") or "Common"),
        ink_color=raw.get("Color") or None,
        cost=cost,
        inkable=inkable,
        card_type=raw.get("Type") or None,
        body_text=raw.get("Body_Text") or None,
        image_url=raw.get("Image") or None,
        api_payload=json.dumps(raw, ensure_ascii=False),
    )
```

- [ ] **Step 6: Run to verify pass**

```bash
uv run pytest tests/unit/test_catalog.py -v
```

Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add src/lorscan/services/__init__.py src/lorscan/services/catalog.py tests/unit/test_catalog.py tests/fixtures/api/cards-page-1.json pyproject.toml
git commit -m "feat(catalog): sync from lorcana-api.com with httpx + respx tests"
```

---

## Phase 3 — Photos Service

### Task 8: Photo hashing + saving + normalization

**Files:**
- Create: `src/lorscan/services/photos.py`
- Create: `tests/unit/test_photos.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_photos.py`:

```python
"""Photo service: hashing, saving, normalizing for the API."""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from lorscan.services.photos import (
    hash_bytes,
    normalize_for_api,
    save_original,
)


def _make_test_jpeg(width: int, height: int) -> bytes:
    """Build a tiny RGB JPEG of the requested dimensions."""
    import io
    img = Image.new("RGB", (width, height), color=(123, 45, 67))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def test_hash_bytes_is_deterministic():
    payload = b"hello world"
    assert hash_bytes(payload) == hash_bytes(payload)
    assert hash_bytes(payload) != hash_bytes(b"hello, world")
    assert len(hash_bytes(payload)) == 64  # sha256 hex


def test_save_original_writes_content_addressed_file(tmp_path: Path):
    payload = b"binary photo bytes"
    path = save_original(payload, photos_dir=tmp_path, extension="jpg")
    assert path.exists()
    assert path.parent == tmp_path
    assert path.read_bytes() == payload
    assert path.stem == hash_bytes(payload)
    assert path.suffix == ".jpg"


def test_save_original_dedupes_same_bytes(tmp_path: Path):
    payload = b"same exact bytes"
    p1 = save_original(payload, photos_dir=tmp_path, extension="jpg")
    p2 = save_original(payload, photos_dir=tmp_path, extension="jpg")
    assert p1 == p2
    assert len(list(tmp_path.iterdir())) == 1


def test_normalize_for_api_downscales_large_image():
    big = _make_test_jpeg(3000, 2000)
    normalized = normalize_for_api(big)
    img = Image.open_io_bytes(normalized) if hasattr(Image, "open_io_bytes") else None
    # Use PIL.Image.open with BytesIO instead — keep test independent of helper.
    import io
    img = Image.open(io.BytesIO(normalized))
    assert max(img.size) <= 1568


def test_normalize_for_api_preserves_small_image():
    small = _make_test_jpeg(800, 600)
    normalized = normalize_for_api(small)
    import io
    img = Image.open(io.BytesIO(normalized))
    assert img.size == (800, 600)


def test_normalize_for_api_strips_exif():
    # Synthesize an image with EXIF.
    import io
    img = Image.new("RGB", (1000, 1000), color=(10, 20, 30))
    buf = io.BytesIO()
    exif_data = img.getexif()
    exif_data[0x0112] = 6  # Orientation
    img.save(buf, format="JPEG", quality=90, exif=exif_data.tobytes())
    src = buf.getvalue()
    out = normalize_for_api(src)
    out_img = Image.open(io.BytesIO(out))
    assert out_img.getexif() == {} or len(out_img.getexif()) == 0
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/unit/test_photos.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `src/lorscan/services/photos.py`**

```python
"""Photo service: hashing, saving, in-memory normalization for the API."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

from PIL import Image


MAX_LONG_EDGE_PX = 1568  # Anthropic's recommended max for vision input
NORMALIZED_QUALITY = 85


def hash_bytes(payload: bytes) -> str:
    """Return the lowercase sha256 hex digest of payload."""
    return hashlib.sha256(payload).hexdigest()


def save_original(payload: bytes, *, photos_dir: Path, extension: str) -> Path:
    """Write payload to <photos_dir>/<sha256>.<extension>. Idempotent."""
    photos_dir.mkdir(parents=True, exist_ok=True)
    digest = hash_bytes(payload)
    path = photos_dir / f"{digest}.{extension.lstrip('.')}"
    if not path.exists():
        path.write_bytes(payload)
    return path


def normalize_for_api(payload: bytes) -> bytes:
    """Build a normalized derivative for the Anthropic vision API.

    - Downscales long edge to MAX_LONG_EDGE_PX if larger.
    - Strips EXIF.
    - Re-encodes JPEG @ NORMALIZED_QUALITY.
    """
    src = Image.open(io.BytesIO(payload))
    src.load()

    if src.mode not in ("RGB", "L"):
        src = src.convert("RGB")

    long_edge = max(src.size)
    if long_edge > MAX_LONG_EDGE_PX:
        scale = MAX_LONG_EDGE_PX / long_edge
        new_size = (int(src.size[0] * scale), int(src.size[1] * scale))
        src = src.resize(new_size, Image.Resampling.LANCZOS)

    out = io.BytesIO()
    # exif='' strips EXIF; subsampling=2 is JPEG default; optimize for size.
    src.save(out, format="JPEG", quality=NORMALIZED_QUALITY, optimize=True, exif=b"")
    return out.getvalue()
```

- [ ] **Step 4: Run to verify pass**

```bash
uv run pytest tests/unit/test_photos.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/lorscan/services/photos.py tests/unit/test_photos.py
git commit -m "feat(photos): hash + save original + Pillow-based API normalization"
```

---

## Phase 4 — Recognition Pipeline

### Task 9: Prompt builders (with snapshot test)

**Files:**
- Create: `src/lorscan/services/recognition/__init__.py`
- Create: `src/lorscan/services/recognition/prompt.py`
- Create: `tests/unit/test_recognition_prompt.py`
- Create: `tests/__snapshots__/` (auto-created by syrupy)

- [ ] **Step 1: Create the recognition subpackage**

```bash
mkdir -p src/lorscan/services/recognition
touch src/lorscan/services/recognition/__init__.py
```

- [ ] **Step 2: Write the failing test**

`tests/unit/test_recognition_prompt.py`:

```python
"""Recognition prompts: snapshot-tested system + user message builders."""
from __future__ import annotations

import base64

from syrupy.assertion import SnapshotAssertion

from lorscan.services.recognition.prompt import (
    build_system_prompt,
    build_user_message,
)


def test_system_prompt_snapshot(snapshot: SnapshotAssertion):
    """Snapshot-test the entire system prompt. Drift breaks cache + recognition."""
    prompt = build_system_prompt()
    assert prompt == snapshot


def test_system_prompt_contains_required_lexicon():
    prompt = build_system_prompt()
    # Lexicon membership tests — these are robust to wording changes.
    for ink in ("Amber", "Amethyst", "Emerald", "Ruby", "Sapphire", "Steel"):
        assert ink in prompt
    for finish in ("regular", "cold_foil", "promo", "enchanted"):
        assert finish in prompt
    # Suffix preservation rule must be present verbatim.
    assert "exactly as it appears" in prompt.lower() or "exact" in prompt.lower()
    assert "1a" in prompt or "letter suffix" in prompt.lower()


def test_user_message_includes_image_and_instruction():
    image_bytes = b"\xff\xd8\xff fake jpeg"
    msg = build_user_message(image_bytes=image_bytes, media_type="image/jpeg")

    assert msg["role"] == "user"
    content = msg["content"]
    assert isinstance(content, list)
    # First block: the image.
    assert content[0]["type"] == "image"
    assert content[0]["source"]["type"] == "base64"
    assert content[0]["source"]["media_type"] == "image/jpeg"
    assert content[0]["source"]["data"] == base64.standard_b64encode(image_bytes).decode("ascii")
    # Second block: the text instruction.
    assert content[1]["type"] == "text"
    assert "binder" in content[1]["text"].lower() or "identify" in content[1]["text"].lower()
```

- [ ] **Step 3: Run to verify failure**

```bash
uv run pytest tests/unit/test_recognition_prompt.py -v
```

Expected: ImportError.

- [ ] **Step 4: Implement `src/lorscan/services/recognition/prompt.py`**

```python
"""Builders for the Anthropic Messages API request used in recognition."""
from __future__ import annotations

import base64
from typing import Any


_INK_COLORS = ("Amber", "Amethyst", "Emerald", "Ruby", "Sapphire", "Steel")
_FINISHES = ("regular", "cold_foil", "promo", "enchanted")


def build_system_prompt() -> str:
    """The cached system prompt. Edits invalidate the prompt cache."""
    inks = ", ".join(_INK_COLORS)
    finishes = ", ".join(_FINISHES)
    return f"""You identify Disney Lorcana TCG cards in photos of binder pages.

Each photo is typically a 3x3 grid of cards in plastic sleeves on a binder page.
Cards may also be in 3x4 grids, single-card photos, or loose layouts.

For each card you can see, return its identity using the keys below.

Lexicon (constrain your output to these values):
- ink_color: one of {inks}
- finish: one of {finishes}
- rarity: one of Common, Uncommon, Rare, Super Rare, Legendary, Enchanted

Rules:
1. Report collector_number EXACTLY as it appears on the card, including any
   trailing letter suffix (1a, 12b, 127). Never normalize or drop the suffix.
2. If the suffix is unreadable due to glare or angle, omit the suffix and
   set confidence to "medium" or "low".
3. confidence is one of "high", "medium", "low".
4. If you can see the set symbol, report a short set_hint code (whatever is
   readable). If not, set set_hint to null.
5. grid_position is "rNcM" where N is the row (1-indexed from the top) and
   M is the column (1-indexed from the left). For a single-card photo,
   use "single".
6. Output ONLY a single JSON object — no prose, no markdown fences,
   no commentary.

Output schema:
{{
  "page_type": "binder_3x3" | "binder_3x4" | "loose_layout" | "single_card",
  "cards": [
    {{
      "grid_position": "r1c1",
      "name": "Hermes",
      "subtitle": "Messenger of the Gods" | null,
      "set_hint": "URS" | null,
      "collector_number": "127a" | null,
      "ink_color": "Amber" | ... | null,
      "finish": "regular" | "cold_foil" | "promo" | "enchanted",
      "confidence": "high" | "medium" | "low",
      "candidates": []
    }}
  ],
  "issues": ["row 2 col 3 has heavy glare"]
}}
"""


def build_user_message(
    *, image_bytes: bytes, media_type: str = "image/jpeg"
) -> dict[str, Any]:
    """Build the user-role message (image + instruction)."""
    encoded = base64.standard_b64encode(image_bytes).decode("ascii")
    return {
        "role": "user",
        "content": [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": encoded,
                },
            },
            {
                "type": "text",
                "text": "Identify the cards in this binder page.",
            },
        ],
    }
```

- [ ] **Step 5: Run the test**

```bash
uv run pytest tests/unit/test_recognition_prompt.py -v --snapshot-update
```

Expected: 3 passed (snapshot is created on first run with `--snapshot-update`).

- [ ] **Step 6: Run again without `--snapshot-update` to verify**

```bash
uv run pytest tests/unit/test_recognition_prompt.py -v
```

Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add src/lorscan/services/recognition tests/unit/test_recognition_prompt.py tests/__snapshots__
git commit -m "feat(recognition): system + user prompt builders with snapshot test"
```

---

### Task 10: JSON parser (strict, with retry-on-prose)

**Files:**
- Create: `src/lorscan/services/recognition/parser.py`
- Create: `tests/fixtures/claude/good-3x3.json`
- Create: `tests/fixtures/claude/malformed.txt`
- Create: `tests/unit/test_recognition_parser.py`

- [ ] **Step 1: Create good fixture**

`tests/fixtures/claude/good-3x3.json`:

```json
{
  "page_type": "binder_3x3",
  "cards": [
    {"grid_position": "r1c1", "name": "Hermes", "subtitle": "Messenger of the Gods",
     "set_hint": "1", "collector_number": "127", "ink_color": "Amber",
     "finish": "regular", "confidence": "high", "candidates": []},
    {"grid_position": "r1c2", "name": "Fairy Godmother", "subtitle": null,
     "set_hint": "1", "collector_number": "12", "ink_color": "Amethyst",
     "finish": "regular", "confidence": "high", "candidates": []},
    {"grid_position": "r1c3", "name": "Chip the Teacup", "subtitle": null,
     "set_hint": "1", "collector_number": "45", "ink_color": "Amethyst",
     "finish": "regular", "confidence": "medium", "candidates": []}
  ],
  "issues": []
}
```

- [ ] **Step 2: Create malformed fixture**

`tests/fixtures/claude/malformed.txt`:

```
Here is the analysis of your binder page:

The cards I can see are:
- Hermes (top-left)
- Fairy Godmother (top-middle)
...
```

- [ ] **Step 3: Write the failing test**

`tests/unit/test_recognition_parser.py`:

```python
"""Recognition response parser: strict JSON, lenient extraction, error taxonomy."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lorscan.services.recognition.parser import (
    ParseError,
    ParsedScan,
    parse_response,
)


FIXTURES = Path(__file__).parent.parent / "fixtures" / "claude"


def test_parse_valid_response():
    raw = (FIXTURES / "good-3x3.json").read_text()
    parsed = parse_response(raw)
    assert isinstance(parsed, ParsedScan)
    assert parsed.page_type == "binder_3x3"
    assert len(parsed.cards) == 3
    first = parsed.cards[0]
    assert first.grid_position == "r1c1"
    assert first.name == "Hermes"
    assert first.collector_number == "127"
    assert first.confidence == "high"


def test_parse_strips_markdown_fences():
    raw = "```json\n" + (FIXTURES / "good-3x3.json").read_text() + "\n```"
    parsed = parse_response(raw)
    assert len(parsed.cards) == 3


def test_parse_extracts_first_json_object_when_surrounded_by_prose():
    payload = json.loads((FIXTURES / "good-3x3.json").read_text())
    raw = "Sure! " + json.dumps(payload) + "\nHope that helps."
    parsed = parse_response(raw)
    assert len(parsed.cards) == 3


def test_parse_raises_on_total_garbage():
    raw = (FIXTURES / "malformed.txt").read_text()
    with pytest.raises(ParseError):
        parse_response(raw)


def test_parse_normalizes_missing_optional_fields():
    minimal = json.dumps({
        "page_type": "single_card",
        "cards": [{
            "grid_position": "single",
            "name": "Mickey",
            "confidence": "high",
        }],
    })
    parsed = parse_response(minimal)
    card = parsed.cards[0]
    assert card.name == "Mickey"
    assert card.subtitle is None
    assert card.collector_number is None
    assert card.set_hint is None
    assert card.ink_color is None
    assert card.finish == "regular"  # default
    assert card.candidates == []


def test_parse_raises_on_missing_required_fields():
    bad = json.dumps({"cards": [{"name": "Mickey"}]})  # no page_type, no confidence
    with pytest.raises(ParseError):
        parse_response(bad)
```

- [ ] **Step 4: Run to verify failure**

```bash
uv run pytest tests/unit/test_recognition_parser.py -v
```

Expected: ImportError.

- [ ] **Step 5: Implement `src/lorscan/services/recognition/parser.py`**

```python
"""Strict JSON parsing of Claude's recognition response."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


VALID_FINISHES = {"regular", "cold_foil", "promo", "enchanted"}
VALID_CONFIDENCES = {"high", "medium", "low"}
VALID_PAGE_TYPES = {"binder_3x3", "binder_3x4", "loose_layout", "single_card"}


class ParseError(ValueError):
    """The model's response could not be parsed into a ParsedScan."""


@dataclass(frozen=True)
class ParsedCard:
    grid_position: str
    name: str | None
    subtitle: str | None
    set_hint: str | None
    collector_number: str | None
    ink_color: str | None
    finish: str
    confidence: str
    candidates: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedScan:
    page_type: str
    cards: list[ParsedCard]
    issues: list[str] = field(default_factory=list)


def parse_response(raw: str) -> ParsedScan:
    """Parse a Claude response string into a ParsedScan.

    Tolerant of: leading/trailing prose, ```json fences. Rejects: garbage
    that doesn't contain a JSON object.
    """
    payload = _extract_json(raw)
    if payload is None:
        raise ParseError("No JSON object found in response.")

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        raise ParseError(f"Invalid JSON: {e}") from e

    if not isinstance(data, dict):
        raise ParseError("Top-level JSON must be an object.")

    page_type = data.get("page_type")
    if page_type not in VALID_PAGE_TYPES:
        raise ParseError(f"Invalid or missing page_type: {page_type!r}")

    cards_raw = data.get("cards")
    if not isinstance(cards_raw, list):
        raise ParseError("Missing 'cards' array.")

    cards = [_parse_card(item) for item in cards_raw]
    issues = data.get("issues") or []
    if not isinstance(issues, list):
        issues = []

    return ParsedScan(page_type=page_type, cards=cards, issues=list(issues))


def _parse_card(item: dict) -> ParsedCard:
    if not isinstance(item, dict):
        raise ParseError("Card entry must be an object.")
    grid_position = item.get("grid_position")
    if not isinstance(grid_position, str):
        raise ParseError("Card missing required string 'grid_position'.")
    confidence = item.get("confidence")
    if confidence not in VALID_CONFIDENCES:
        raise ParseError(f"Invalid or missing confidence: {confidence!r}")

    finish = item.get("finish") or "regular"
    if finish not in VALID_FINISHES:
        finish = "regular"

    candidates = item.get("candidates") or []
    if not isinstance(candidates, list):
        candidates = []

    return ParsedCard(
        grid_position=grid_position,
        name=item.get("name"),
        subtitle=item.get("subtitle"),
        set_hint=item.get("set_hint"),
        collector_number=(str(item["collector_number"])
                          if item.get("collector_number") is not None else None),
        ink_color=item.get("ink_color"),
        finish=finish,
        confidence=confidence,
        candidates=candidates,
    )


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def _extract_json(raw: str) -> str | None:
    """Return the JSON object substring from raw, or None if not found."""
    raw = raw.strip()
    if not raw:
        return None

    # Strip markdown code fence if present.
    fence_match = _FENCE_RE.search(raw)
    if fence_match:
        raw = fence_match.group(1).strip()

    # If the whole string looks like JSON already, use it.
    if raw.startswith("{") and raw.endswith("}"):
        return raw

    # Otherwise, find the first balanced { ... } substring.
    start = raw.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return raw[start:i + 1]
    return None
```

- [ ] **Step 6: Run to verify pass**

```bash
uv run pytest tests/unit/test_recognition_parser.py -v
```

Expected: 6 passed.

- [ ] **Step 7: Commit**

```bash
git add src/lorscan/services/recognition/parser.py tests/unit/test_recognition_parser.py tests/fixtures/claude
git commit -m "feat(recognition): strict JSON parser with fence + prose tolerance"
```

---

### Task 11: Anthropic client wrapper

**Files:**
- Create: `src/lorscan/services/recognition/client.py`
- Create: `tests/integration/test_recognition_client.py`

- [ ] **Step 1: Write the failing test (mocks the Anthropic SDK)**

`tests/integration/test_recognition_client.py`:

```python
"""Recognition client: orchestrates prompt → SDK call → parser."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from lorscan.services.recognition.client import RecognitionResult, identify


FIXTURE = Path(__file__).parent.parent / "fixtures" / "claude" / "good-3x3.json"


class FakeAnthropicMessage:
    def __init__(self, text: str, input_tokens: int, output_tokens: int,
                 cache_read_tokens: int = 0, cache_creation_tokens: int = 0):
        self.content = [type("TextBlock", (), {"type": "text", "text": text})()]
        self.usage = type("Usage", (), {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": cache_read_tokens,
            "cache_creation_input_tokens": cache_creation_tokens,
        })()


def test_identify_calls_sdk_with_cache_control_and_returns_parsed_result():
    fake_response_text = FIXTURE.read_text()
    fake_message = FakeAnthropicMessage(
        text=fake_response_text, input_tokens=1500, output_tokens=400,
    )

    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_message

    result = identify(
        image_bytes=b"\xff\xd8\xff fake jpeg",
        media_type="image/jpeg",
        anthropic_client=fake_client,
        model="claude-sonnet-4-6",
    )

    assert isinstance(result, RecognitionResult)
    assert result.parsed.page_type == "binder_3x3"
    assert len(result.parsed.cards) == 3
    assert result.usage.input_tokens == 1500
    assert result.usage.output_tokens == 400

    create_call = fake_client.messages.create.call_args
    kwargs = create_call.kwargs
    assert kwargs["model"] == "claude-sonnet-4-6"
    # System prompt must be in the cached form (list of blocks with cache_control).
    system = kwargs["system"]
    assert isinstance(system, list) and len(system) == 1
    assert system[0]["type"] == "text"
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    # User message must be present.
    messages = kwargs["messages"]
    assert messages[0]["role"] == "user"


def test_identify_retries_once_on_unparseable_response():
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = [
        FakeAnthropicMessage(text="here is the result, not JSON", input_tokens=100, output_tokens=50),
        FakeAnthropicMessage(text=FIXTURE.read_text(), input_tokens=80, output_tokens=400),
    ]

    result = identify(
        image_bytes=b"\xff\xd8\xff",
        media_type="image/jpeg",
        anthropic_client=fake_client,
        model="claude-sonnet-4-6",
    )

    assert len(result.parsed.cards) == 3
    assert fake_client.messages.create.call_count == 2

    # Second call must include the strictness reminder in the messages list.
    second_call = fake_client.messages.create.call_args_list[1]
    msgs = second_call.kwargs["messages"]
    last = msgs[-1]
    flat_text = json.dumps(last)
    assert "JSON only" in flat_text or "no markdown" in flat_text.lower()
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/integration/test_recognition_client.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `src/lorscan/services/recognition/client.py`**

```python
"""Anthropic Messages API call orchestration with prompt caching + retry-on-prose."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from lorscan.services.recognition.parser import ParseError, ParsedScan, parse_response
from lorscan.services.recognition.prompt import build_system_prompt, build_user_message


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


@dataclass(frozen=True)
class RecognitionResult:
    parsed: ParsedScan
    usage: TokenUsage
    request_payload: dict
    response_text: str


class AnthropicClient(Protocol):
    """Minimal interface for the parts of anthropic.Anthropic we use."""

    @property
    def messages(self) -> Any: ...


def identify(
    *,
    image_bytes: bytes,
    media_type: str,
    anthropic_client: AnthropicClient,
    model: str,
    max_tokens: int = 1500,
) -> RecognitionResult:
    """Call Claude vision and return a parsed scan.

    Retries once with a strictness reminder if the first response is unparseable.
    """
    system_prompt = build_system_prompt()
    user_message = build_user_message(image_bytes=image_bytes, media_type=media_type)

    system_blocks = [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    messages: list[dict] = [user_message]

    request_payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_blocks,
        "messages": messages,
    }

    response = anthropic_client.messages.create(**request_payload)
    response_text = _extract_text(response)
    usage = _extract_usage(response)

    try:
        parsed = parse_response(response_text)
        return RecognitionResult(
            parsed=parsed,
            usage=usage,
            request_payload=request_payload,
            response_text=response_text,
        )
    except ParseError:
        # One retry with stricter instruction.
        messages_retry = list(messages) + [
            {"role": "assistant", "content": response_text},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Reply with a single JSON object only. "
                            "No prose, no markdown fences. JSON only."
                        ),
                    }
                ],
            },
        ]
        retry_payload = {**request_payload, "messages": messages_retry}
        response2 = anthropic_client.messages.create(**retry_payload)
        response_text2 = _extract_text(response2)
        usage2 = _extract_usage(response2)
        parsed2 = parse_response(response_text2)
        return RecognitionResult(
            parsed=parsed2,
            usage=TokenUsage(
                input_tokens=usage.input_tokens + usage2.input_tokens,
                output_tokens=usage.output_tokens + usage2.output_tokens,
                cache_read_tokens=usage.cache_read_tokens + usage2.cache_read_tokens,
                cache_creation_tokens=usage.cache_creation_tokens + usage2.cache_creation_tokens,
            ),
            request_payload=retry_payload,
            response_text=response_text2,
        )


def _extract_text(response: Any) -> str:
    blocks = getattr(response, "content", None) or []
    parts: list[str] = []
    for block in blocks:
        kind = getattr(block, "type", None)
        if kind == "text":
            parts.append(getattr(block, "text", ""))
    return "".join(parts)


def _extract_usage(response: Any) -> TokenUsage:
    u = getattr(response, "usage", None)
    if u is None:
        return TokenUsage(input_tokens=0, output_tokens=0)
    return TokenUsage(
        input_tokens=int(getattr(u, "input_tokens", 0) or 0),
        output_tokens=int(getattr(u, "output_tokens", 0) or 0),
        cache_read_tokens=int(getattr(u, "cache_read_input_tokens", 0) or 0),
        cache_creation_tokens=int(getattr(u, "cache_creation_input_tokens", 0) or 0),
    )
```

- [ ] **Step 4: Run to verify pass**

```bash
uv run pytest tests/integration/test_recognition_client.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/lorscan/services/recognition/client.py tests/integration/test_recognition_client.py
git commit -m "feat(recognition): Anthropic client with prompt caching + retry-on-prose"
```

---

## Phase 5 — Matching Algorithm

### Task 12: `match_card` with all four branches

**Files:**
- Create: `src/lorscan/services/matching.py`
- Create: `tests/unit/test_matching.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_matching.py`:

```python
"""Suffix-aware matching algorithm — full branch coverage."""
from __future__ import annotations

import pytest

from lorscan.services.matching import MatchResult, match_card
from lorscan.services.recognition.parser import ParsedCard
from lorscan.storage.db import Database
from lorscan.storage.models import Card, CardSet


def _seed_catalog(db: Database):
    db.upsert_set(CardSet(set_code="1", name="TFC", total_cards=204))
    db.upsert_set(CardSet(set_code="2", name="ROF", total_cards=204))
    db.upsert_set(CardSet(set_code="X", name="Adventure", total_cards=27))

    db.upsert_card(Card(card_id="tfc-127", set_code="1", collector_number="127",
                        name="Mickey Mouse", subtitle="Brave Little Tailor",
                        rarity="Legendary"))
    db.upsert_card(Card(card_id="tfc-12", set_code="1", collector_number="12",
                        name="Fairy Godmother", rarity="Common"))
    db.upsert_card(Card(card_id="rof-12", set_code="2", collector_number="12",
                        name="Fairy Godmother", rarity="Uncommon"))
    db.upsert_card(Card(card_id="x-1a", set_code="X", collector_number="1a",
                        name="Story", subtitle="Path A", rarity="Common"))
    db.upsert_card(Card(card_id="x-1b", set_code="X", collector_number="1b",
                        name="Story", subtitle="Path B", rarity="Common"))


@pytest.fixture()
def seeded_db(db: Database) -> Database:
    _seed_catalog(db)
    return db


def _claude(name: str | None = None, set_hint: str | None = None,
            collector: str | None = None, confidence: str = "high",
            subtitle: str | None = None) -> ParsedCard:
    return ParsedCard(
        grid_position="r1c1", name=name, subtitle=subtitle, set_hint=set_hint,
        collector_number=collector, ink_color=None, finish="regular",
        confidence=confidence, candidates=[],
    )


def test_collector_number_exact_match_with_set_hint(seeded_db: Database):
    claude = _claude(name="Mickey Mouse", set_hint="1", collector="127")
    result = match_card(claude, db=seeded_db)
    assert isinstance(result, MatchResult)
    assert result.matched_card_id == "tfc-127"
    assert result.match_method == "collector_number"
    assert result.confidence == "high"  # not demoted
    assert result.candidates == []


def test_suffix_preserved_when_distinct(seeded_db: Database):
    a = match_card(_claude(name="Story", set_hint="X", collector="1a"), db=seeded_db)
    b = match_card(_claude(name="Story", set_hint="X", collector="1b"), db=seeded_db)
    assert a.matched_card_id == "x-1a"
    assert b.matched_card_id == "x-1b"


def test_name_set_fallback_when_collector_unreadable(seeded_db: Database):
    claude = _claude(name="Mickey Mouse", set_hint="1", collector=None,
                     subtitle="Brave Little Tailor")
    result = match_card(claude, db=seeded_db)
    assert result.matched_card_id == "tfc-127"
    assert result.match_method == "name+set"
    assert result.confidence == "medium"  # demoted from high


def test_ambiguous_suffix_when_set_known_but_collector_missing(seeded_db: Database):
    # Both 1a and 1b share name "Story" in set X — ambiguous.
    claude = _claude(name="Story", set_hint="X", collector=None)
    result = match_card(claude, db=seeded_db)
    assert result.matched_card_id is None
    assert result.match_method == "ambiguous_suffix"
    assert {c["card_id"] for c in result.candidates} == {"x-1a", "x-1b"}


def test_name_only_cross_set_match(seeded_db: Database):
    # "Mickey Mouse" exists only once in the catalog → unique match.
    claude = _claude(name="Mickey Mouse", set_hint=None, collector=None)
    result = match_card(claude, db=seeded_db)
    assert result.matched_card_id == "tfc-127"
    assert result.match_method == "name_only"
    assert result.confidence == "low"


def test_unmatched_when_name_appears_in_multiple_sets(seeded_db: Database):
    # "Fairy Godmother" exists in sets 1 and 2 → no unique cross-set match.
    claude = _claude(name="Fairy Godmother", set_hint=None, collector=None)
    result = match_card(claude, db=seeded_db)
    assert result.matched_card_id is None
    assert result.match_method == "unmatched"


def test_unmatched_when_nothing_known(seeded_db: Database):
    claude = _claude(name=None, set_hint=None, collector=None)
    result = match_card(claude, db=seeded_db)
    assert result.matched_card_id is None
    assert result.match_method == "unmatched"


def test_binder_set_overrides_claude_set_hint(seeded_db: Database):
    """If the parent scan has a binder rule, that set wins over claude_set_hint."""
    claude = _claude(name="Fairy Godmother", set_hint="1", collector="12")
    # Caller supplies binder_set_code="2" — binder rule forces the lookup into set 2.
    result = match_card(claude, db=seeded_db, binder_set_code="2")
    assert result.matched_card_id == "rof-12"
    assert result.match_method == "collector_number"
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/unit/test_matching.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `src/lorscan/services/matching.py`**

```python
"""Suffix-aware card matching against the local catalog.

Implements the algorithm in spec §4.3:
1. collector_number exact match (suffix preserved) when set is known
2. name+set fallback (with subtitle disambig)
3. cross-set name-only fallback
4. unmatched
"""
from __future__ import annotations

from dataclasses import dataclass, field

from lorscan.services.recognition.parser import ParsedCard
from lorscan.storage.db import Database
from lorscan.storage.models import Card


_CONFIDENCE_DEMOTION = {"high": "medium", "medium": "low", "low": "low"}


@dataclass(frozen=True)
class MatchResult:
    matched_card_id: str | None
    match_method: str
    # 'collector_number' | 'name+set' | 'name_only' | 'ambiguous_suffix' | 'unmatched'
    confidence: str
    candidates: list[dict] = field(default_factory=list)


def match_card(
    claude_card: ParsedCard,
    *,
    db: Database,
    binder_set_code: str | None = None,
) -> MatchResult:
    """Match a single ParsedCard against the catalog.

    The 'known set' precedence is: binder_set_code → claude_card.set_hint → none.
    """
    known_set = binder_set_code or claude_card.set_hint
    confidence = claude_card.confidence

    # 1. collector_number + known_set
    if claude_card.collector_number and known_set:
        card = db.get_card_by_collector_number(known_set, claude_card.collector_number)
        if card is not None:
            return MatchResult(
                matched_card_id=card.card_id,
                match_method="collector_number",
                confidence=confidence,
            )

    # 2. name + known_set
    if claude_card.name and known_set:
        rows = db.search_cards_by_name(claude_card.name, set_code=known_set)
        if claude_card.subtitle:
            filtered = [c for c in rows if c.subtitle == claude_card.subtitle]
            if len(filtered) == 1:
                return MatchResult(
                    matched_card_id=filtered[0].card_id,
                    match_method="name+set",
                    confidence=_CONFIDENCE_DEMOTION[confidence],
                )
            elif len(filtered) > 1:
                return MatchResult(
                    matched_card_id=None,
                    match_method="ambiguous_suffix",
                    confidence=confidence,
                    candidates=[_card_summary(c) for c in filtered],
                )
        if len(rows) == 1:
            return MatchResult(
                matched_card_id=rows[0].card_id,
                match_method="name+set",
                confidence=_CONFIDENCE_DEMOTION[confidence],
            )
        if len(rows) > 1:
            return MatchResult(
                matched_card_id=None,
                match_method="ambiguous_suffix",
                confidence=confidence,
                candidates=[_card_summary(c) for c in rows],
            )

    # 3. name-only cross-set
    if claude_card.name:
        rows = db.search_cards_by_name(claude_card.name)
        if len(rows) == 1:
            return MatchResult(
                matched_card_id=rows[0].card_id,
                match_method="name_only",
                confidence="low",
            )

    # 4. unmatched
    return MatchResult(
        matched_card_id=None,
        match_method="unmatched",
        confidence=confidence,
    )


def _card_summary(c: Card) -> dict:
    return {
        "card_id": c.card_id,
        "set_code": c.set_code,
        "collector_number": c.collector_number,
        "name": c.name,
        "subtitle": c.subtitle,
    }
```

- [ ] **Step 4: Run to verify pass**

```bash
uv run pytest tests/unit/test_matching.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/lorscan/services/matching.py tests/unit/test_matching.py
git commit -m "feat(matching): suffix-aware match against catalog with full branch coverage"
```

---

## Phase 6 — MILESTONE: CLI Scanner

### Task 13: CLI entry point + `scan` subcommand wiring

**Files:**
- Create: `src/lorscan/cli.py`
- Create: `tests/integration/test_cli_scan.py`

- [ ] **Step 1: Write the failing integration test**

`tests/integration/test_cli_scan.py`:

```python
"""End-to-end: lorscan scan <photo> identifies cards via stubbed Claude + matching."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lorscan.cli import scan_command
from lorscan.config import Config
from lorscan.storage.db import Database
from lorscan.storage.models import Card, CardSet


FIXTURE = Path(__file__).parent.parent / "fixtures" / "claude" / "good-3x3.json"


class FakeAnthropicMessage:
    def __init__(self, text: str):
        self.content = [type("TB", (), {"type": "text", "text": text})()]
        self.usage = type("U", (), {
            "input_tokens": 1500, "output_tokens": 400,
            "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
        })()


@pytest.fixture()
def seeded_db_path(tmp_path: Path) -> Path:
    db_path = tmp_path / "lorscan.db"
    database = Database.connect(str(db_path))
    database.migrate()
    database.upsert_set(CardSet(set_code="1", name="TFC", total_cards=204))
    database.upsert_card(Card(
        card_id="tfc-127", set_code="1", collector_number="127",
        name="Hermes", subtitle="Messenger of the Gods", rarity="Legendary",
    ))
    database.upsert_card(Card(
        card_id="tfc-12", set_code="1", collector_number="12",
        name="Fairy Godmother", rarity="Common",
    ))
    database.upsert_card(Card(
        card_id="tfc-45", set_code="1", collector_number="45",
        name="Chip the Teacup", rarity="Common",
    ))
    database.close()
    return db_path


def test_scan_command_prints_grid_table(
    capsys, tmp_path: Path, seeded_db_path: Path
):
    # Synthesize a tiny "photo" — content doesn't matter; the SDK is stubbed.
    photo = tmp_path / "binder-page.jpg"
    photo.write_bytes(b"\xff\xd8\xff fake jpeg payload")

    fake_anthropic = MagicMock()
    fake_anthropic.messages.create.return_value = FakeAnthropicMessage(
        text=FIXTURE.read_text()
    )

    config = Config(
        anthropic_api_key="sk-ant-test",
        anthropic_model="claude-sonnet-4-6",
        per_scan_budget_usd=0.50,
        monthly_budget_usd=None,
        data_dir=tmp_path,
    )

    with patch("lorscan.cli._build_anthropic_client", return_value=fake_anthropic):
        rc = scan_command(photo_path=photo, config=config, db_path=seeded_db_path)

    assert rc == 0
    captured = capsys.readouterr()
    assert "Hermes" in captured.out
    assert "Fairy Godmother" in captured.out
    assert "Chip the Teacup" in captured.out
    # Each row should show the matched card's collector number.
    assert "127" in captured.out
    assert "tfc-127" in captured.out or "MATCHED" in captured.out
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/integration/test_cli_scan.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `src/lorscan/cli.py`**

```python
"""lorscan CLI entry point."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from lorscan.config import Config, load_config
from lorscan.services.matching import match_card
from lorscan.services.photos import normalize_for_api
from lorscan.services.recognition.client import identify
from lorscan.storage.db import Database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lorscan", description="Lorcana collection manager.")
    sub = parser.add_subparsers(dest="command", required=True)

    scan_p = sub.add_parser("scan", help="Identify cards in a photo.")
    scan_p.add_argument("photo", type=Path, help="Path to a binder-page photo.")

    sync_p = sub.add_parser("sync-catalog", help="Sync card catalog from lorcana-api.com.")
    _ = sync_p

    version_p = sub.add_parser("version", help="Print version and exit.")
    _ = version_p

    args = parser.parse_args(argv)

    if args.command == "scan":
        cfg = load_config(env=os.environ)
        return scan_command(photo_path=args.photo, config=cfg)
    elif args.command == "version":
        from lorscan import __version__
        print(__version__)
        return 0
    elif args.command == "sync-catalog":
        # Deferred to Plan 2 expansion; placeholder ensures the subcommand is parseable.
        print("sync-catalog: not yet wired in Plan 1; coming in Plan 2.", file=sys.stderr)
        return 2
    return 2


def scan_command(
    *,
    photo_path: Path,
    config: Config,
    db_path: Path | None = None,
) -> int:
    """Run the recognition + matching pipeline against a single photo."""
    if not photo_path.exists():
        print(f"error: photo not found: {photo_path}", file=sys.stderr)
        return 2

    image_bytes = photo_path.read_bytes()
    normalized = normalize_for_api(image_bytes)

    anthropic_client = _build_anthropic_client(config.anthropic_api_key)

    result = identify(
        image_bytes=normalized,
        media_type="image/jpeg",
        anthropic_client=anthropic_client,
        model=config.anthropic_model,
    )

    db_file = db_path if db_path is not None else config.db_path
    db = Database.connect(str(db_file))
    db.migrate()

    print(f"\nScanned: {photo_path.name}")
    print(f"Page type: {result.parsed.page_type}")
    print(f"Cards detected: {len(result.parsed.cards)}\n")

    header = f"{'pos':<6}{'name':<32}{'#':<6}{'set':<5}{'conf':<8}{'match'}"
    print(header)
    print("-" * len(header))

    for card in result.parsed.cards:
        match = match_card(card, db=db)
        match_str = (
            match.matched_card_id if match.matched_card_id
            else f"({match.match_method})"
        )
        name = (card.name or "?")[:30]
        col = card.collector_number or "?"
        set_hint = card.set_hint or "-"
        print(
            f"{card.grid_position:<6}{name:<32}{col:<6}"
            f"{set_hint:<5}{card.confidence:<8}{match_str}"
        )

    if result.parsed.issues:
        print("\nIssues reported by the model:")
        for issue in result.parsed.issues:
            print(f"  - {issue}")

    print(
        f"\nTokens — input: {result.usage.input_tokens}, "
        f"output: {result.usage.output_tokens}, "
        f"cache_read: {result.usage.cache_read_tokens}"
    )

    db.close()
    return 0


def _build_anthropic_client(api_key: str) -> Any:
    """Indirection so tests can patch this to inject a fake client."""
    from anthropic import Anthropic
    return Anthropic(api_key=api_key)
```

- [ ] **Step 4: Run to verify pass**

```bash
uv run pytest tests/integration/test_cli_scan.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Verify the full unit + integration suite passes**

```bash
uv run pytest -v
uv run ruff check src tests
```

Expected: all green, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/lorscan/cli.py tests/integration/test_cli_scan.py
git commit -m "feat(cli): scan subcommand wires photos + recognition + matching end-to-end"
```

---

### Task 14: Manual smoke test against a real photo

This task does not write code — it exercises the system against reality.

**Files:**
- Create: `~/.lorscan/config.toml` (on your machine, not tracked)
- Use: `tests/fixtures/photos/<your-binder-page>.jpg`

- [ ] **Step 1: Drop one of your real binder photos into the test fixtures dir**

```bash
cp /Volumes/homes/epeters/Photos/MobileBackup/'Z Fold6 van Enri'/DCIM/Camera/2026/04/20260425_094706.jpg \
   tests/fixtures/photos/binder-page-1.jpg
```

(Adjust the path; the fixture file is gitignored or kept depending on whether you want to commit your photos.)

- [ ] **Step 2: Create your config**

```bash
mkdir -p ~/.lorscan
```

`~/.lorscan/config.toml`:

```toml
[anthropic]
api_key = "sk-ant-..."
model = "claude-sonnet-4-6"

[budget]
per_scan_usd = 0.50
```

- [ ] **Step 3: Run the catalog sync placeholder (will print not-yet-wired)**

```bash
uv run lorscan sync-catalog
```

Expected: prints "sync-catalog: not yet wired in Plan 1; coming in Plan 2." Exit 2. This confirms the CLI subcommand is wired even if the implementation is deferred.

- [ ] **Step 4: Manually seed the catalog for the smoke test**

Until Plan 2 wires `sync-catalog`, hand-load a few cards from `tests/fixtures/api/cards-page-1.json` into the real DB so matching has data. Run:

```bash
uv run python - <<'PY'
import json
from pathlib import Path
from lorscan.config import load_config
from lorscan.services.catalog import _parse_card
from lorscan.storage.db import Database
from lorscan.storage.models import CardSet
import os, asyncio

cfg = load_config(env=os.environ)
db = Database.connect(str(cfg.db_path))
db.migrate()

raw = json.loads(Path("tests/fixtures/api/cards-page-1.json").read_text())
sets_seen = set()
for entry in raw:
    set_code = str(entry.get("Set_Num"))
    if set_code not in sets_seen:
        db.upsert_set(CardSet(set_code=set_code, name=entry.get("Set_Name", set_code), total_cards=0))
        sets_seen.add(set_code)
    db.upsert_card(_parse_card(entry, set_code))
print(f"Seeded {len(raw)} cards across {len(sets_seen)} sets.")
db.close()
PY
```

- [ ] **Step 5: Run the scanner against your real photo**

```bash
uv run lorscan scan tests/fixtures/photos/binder-page-1.jpg
```

Expected output: a 3×3-style table listing identified cards, with `match` column showing matched card ids for any cards present in the seeded catalog and `(unmatched)` / `(name_only)` etc. for the rest.

- [ ] **Step 6: Record the result in this plan**

Add a note (commit message + edit this file) capturing how many of the 9 cards were correctly identified and matched. This is the empirical baseline for the system's accuracy.

```bash
git commit --allow-empty -m "chore: manual smoke — N/9 cards identified on real binder photo"
```

(Replace `N` with actual count.)

---

## Self-Review Notes

**Spec coverage (Plan 1 scope):**
- Spec §1 (Overview) — captured in the Goal; tools and stack reflected in Plan 1 deps
- Spec §2 (Architecture) — Phase 0 (scaffolding), Phase 1 (storage layer rules)
- Spec §3 (Data Model) — Tasks 4–6 implement migrations 001–004 and the Database catalog ops
- Spec §4 (Scan Flow) — Tasks 8–13 cover photos, recognition, matching, and the CLI orchestration
- Spec §4.3 (Matching algorithm) — Task 12 implements all four branches with full unit-test coverage
- Spec §4.4 (Anomaly detection) — deferred to Plan 2 (UI is where it surfaces)
- Spec §5 (UI Pages) — entirely Plan 2
- Spec §6 (Binder Visualization) — Plan 3
- Spec §7 (Error Handling) — partial: per-scan budget guard (deferred to Plan 2 alongside the cost service); catalog 5xx handling in Phase 2 falls out of httpx default behavior
- Spec §8 (Testing) — unit + integration tests in every phase; live-API tests deferred to Plan 3

**Placeholder scan:** Tasks 1–14 each have complete code blocks, exact commands with expected output, and concrete commit messages. Task 14's "manual smoke" step contains exact commands, not directives. The Plan 2 / Plan 3 references are explicit decomposition decisions, not "TBD" placeholders within Plan 1.

**Type consistency:**
- `Card`, `CardSet`, `CollectionItem`, `Binder` — defined in Task 6 (`storage/models.py`), imported by Tasks 7 (catalog sync), 12 (matching).
- `ParsedScan`, `ParsedCard`, `ParseError` — defined in Task 10, imported by Tasks 11 (client) and 12 (matching).
- `MatchResult` — defined in Task 12.
- `RecognitionResult`, `TokenUsage`, `AnthropicClient` — defined in Task 11.
- `Config` — defined in Task 3, imported by Task 13.
- `Database` — defined in Task 5, used in Tasks 6, 7, 12, 13.
- All names consistent across tasks.

**Command/API consistency:**
- `db.upsert_set`, `db.upsert_card`, `db.get_card_by_id`, `db.get_card_by_collector_number`, `db.search_cards_by_name`, `db.connection` — single names used in tests and implementations.
- `pytest`, `uv run`, `git add`, `git commit` — same idioms throughout.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-25-lorscan-plan-1-foundation.md`.

Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration with two-stage review.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints for review.

**Which approach?**
