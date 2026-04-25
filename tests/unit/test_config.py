"""Config loads from TOML with env-var overrides."""

from pathlib import Path

from lorscan.config import load_config


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
    assert cfg.anthropic_model == "claude-sonnet-4-6"
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
