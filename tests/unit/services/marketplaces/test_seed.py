"""TOML loader for the per-set category seed file."""

from __future__ import annotations

from pathlib import Path

from lorscan.services.marketplaces.seed import load_set_map


def test_load_set_map(tmp_path: Path):
    f = tmp_path / "set_map.toml"
    f.write_text(
        '[[set]]\n'
        'code = "ROF"\n'
        'category_id = "1000676"\n'
        'category_path = "/nl-NL/c/rise-of-the-floodborn/1000676"\n'
        '\n'
        '[[set]]\n'
        'code = "ITI"\n'
        'category_id = "1000697"\n'
        'category_path = "/nl-NL/c/into-the-inklands/1000697"\n'
    )
    entries = load_set_map(f)
    assert {e.set_code for e in entries} == {"ROF", "ITI"}
    rof = next(e for e in entries if e.set_code == "ROF")
    assert rof.category_id == "1000676"
    assert rof.category_path == "/nl-NL/c/rise-of-the-floodborn/1000676"


def test_load_set_map_handles_empty_file(tmp_path: Path):
    f = tmp_path / "empty.toml"
    f.write_text("")
    assert load_set_map(f) == []


def test_load_set_map_handles_no_set_entries(tmp_path: Path):
    f = tmp_path / "no_sets.toml"
    f.write_text('[other_section]\nfoo = "bar"\n')
    assert load_set_map(f) == []
