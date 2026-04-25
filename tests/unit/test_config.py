"""Config loads from TOML with env-var overrides."""

from pathlib import Path

import pytest

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
