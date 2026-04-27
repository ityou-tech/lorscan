"""Config loads from TOML with env-var overrides."""

from pathlib import Path

from lorscan.config import load_config
from lorscan.services.buy_links import DEFAULT_CARDMARKET_FILTERS


def test_load_config_from_toml(tmp_path: Path):
    toml = tmp_path / "config.toml"
    toml.write_text(
        "[anthropic]\n"
        'api_key = "sk-ant-test-from-toml"\n'
        'model = "claude-sonnet-4-6"\n'
        "[budget]\n"
        "per_scan_usd = 0.50\n"
        "monthly_usd = 5.00\n"
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


def test_missing_api_key_is_allowed(tmp_path: Path):
    """No api_key required — the claude CLI handles credential discovery itself."""
    toml = tmp_path / "config.toml"
    toml.write_text('[anthropic]\nmodel = "claude-sonnet-4-6"\n')
    cfg = load_config(toml_path=toml, env={})
    assert cfg.anthropic_api_key is None
    assert cfg.anthropic_model == "claude-sonnet-4-6"


def test_defaults_when_toml_missing():
    cfg = load_config(
        toml_path=Path("/definitely/not/here.toml"),
        env={"ANTHROPIC_API_KEY": "from-env-only"},
    )
    assert cfg.anthropic_api_key == "from-env-only"
    assert cfg.anthropic_model == "claude-opus-4-7"
    assert cfg.per_scan_budget_usd == 0.50
    assert cfg.monthly_budget_usd is None


def test_no_credential_at_all_returns_none(tmp_path: Path):
    """Neither config nor env: api_key is None, no error raised."""
    cfg = load_config(toml_path=tmp_path / "missing.toml", env={})
    assert cfg.anthropic_api_key is None


def test_empty_env_var_does_not_bypass_toml(tmp_path: Path):
    """Empty/whitespace ANTHROPIC_API_KEY must not silently overshadow TOML."""
    toml = tmp_path / "config.toml"
    toml.write_text('[anthropic]\napi_key = "from-toml"\n')

    cfg = load_config(toml_path=toml, env={"ANTHROPIC_API_KEY": ""})
    assert cfg.anthropic_api_key == "from-toml"

    cfg = load_config(toml_path=toml, env={"ANTHROPIC_API_KEY": "   "})
    assert cfg.anthropic_api_key == "from-toml"


def test_whitespace_only_in_both_sources_yields_none(tmp_path: Path):
    toml = tmp_path / "config.toml"
    toml.write_text('[anthropic]\napi_key = "   "\n')
    cfg = load_config(toml_path=toml, env={"ANTHROPIC_API_KEY": ""})
    assert cfg.anthropic_api_key is None


def test_default_buy_link_filters(tmp_path: Path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("")
    cfg = load_config(toml_path=cfg_path, env={})
    assert cfg.buy_links.cardmarket_filters == DEFAULT_CARDMARKET_FILTERS


def test_user_overrides_partial_buy_link_filters(tmp_path: Path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        "[buy_links.cardmarket]\n"
        "sellerCountry = [23, 5]\n"
        "minCondition  = 2\n"
    )
    cfg = load_config(toml_path=cfg_path, env={})
    f = cfg.buy_links.cardmarket_filters
    assert f["sellerCountry"] == [23, 5]
    assert f["minCondition"] == 2
    # Unmentioned keys keep their defaults.
    assert f["language"] == DEFAULT_CARDMARKET_FILTERS["language"]
    assert f["sellerReputation"] == DEFAULT_CARDMARKET_FILTERS["sellerReputation"]


def test_user_can_add_extra_buy_link_filter_keys(tmp_path: Path):
    """Cardmarket has filters lorscan doesn't default (e.g. isFoil) — user
    config should be able to surface them."""
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        "[buy_links.cardmarket]\n"
        'isFoil = "Y"\n'
    )
    cfg = load_config(toml_path=cfg_path, env={})
    assert cfg.buy_links.cardmarket_filters["isFoil"] == "Y"
    # Defaults still present.
    assert cfg.buy_links.cardmarket_filters["sellerCountry"] == DEFAULT_CARDMARKET_FILTERS["sellerCountry"]
