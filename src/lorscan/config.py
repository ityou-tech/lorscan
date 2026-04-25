"""Configuration: TOML file + env-var overrides."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_PER_SCAN_BUDGET_USD = 0.50
DEFAULT_MONTHLY_BUDGET_USD: float | None = None
DEFAULT_DATA_DIR = Path.home() / ".lorscan"
DEFAULT_CATALOG_API_BASE = "https://api.lorcana-api.com"


@dataclass(frozen=True)
class Config:
    anthropic_model: str
    per_scan_budget_usd: float
    monthly_budget_usd: float | None
    data_dir: Path
    # Optional — lorscan no longer requires this. The `claude` CLI
    # handles credential discovery itself (keychain via `claude setup-token`,
    # then ANTHROPIC_API_KEY env var, etc.). The field is preserved for
    # users who want to centralize their key in the config file.
    anthropic_api_key: str | None = None
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
    """Load config — defaults → TOML → env (later wins).

    Auth is no longer validated at load time. The `claude` CLI subprocess
    handles credential discovery on its own; lorscan simply forwards an
    optional API key when present.
    """
    env = env if env is not None else {}
    toml_path = toml_path if toml_path is not None else DEFAULT_DATA_DIR / "config.toml"

    data: dict[str, object] = {}
    if toml_path.exists():
        with toml_path.open("rb") as f:
            data = tomllib.load(f)

    anthropic = data.get("anthropic", {})
    budget = data.get("budget", {})
    storage = data.get("storage", {})

    env_key = (env.get("ANTHROPIC_API_KEY") or "").strip()
    toml_key = (anthropic.get("api_key") or "").strip()
    api_key = env_key or toml_key or None

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
