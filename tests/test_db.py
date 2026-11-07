"""Tests for the reference database seeds, the builder and the regulatory config."""

from __future__ import annotations

import csv
import shutil
import sqlite3
from pathlib import Path

import pytest
import yaml

from db import build_db
from db.build_db import SeedError
from src import regulatory

SEED = build_db.SEED_DIR


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> sqlite3.Connection:
    out = tmp_path_factory.mktemp("db") / "materials.sqlite"
    build_db.build(out)
    con = sqlite3.connect(out)
    con.row_factory = sqlite3.Row
    return con


def _copy_seeds(tmp_path: Path) -> Path:
    d = tmp_path / "seed"
    shutil.copytree(SEED, d)
    return d


def _rewrite(path: Path, mutate) -> None:
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0].keys())
    mutate(rows)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


# --- built database ---------------------------------------------------------------------

def test_build_counts(built: sqlite3.Connection) -> None:
    n = built.execute("SELECT COUNT(*) FROM materials").fetchone()[0]
    assert n >= 60
    info = dict(built.execute("SELECT key, value FROM build_info").fetchall())
    assert len(info["seed_sha256"]) == 64


def test_mlit_rows_are_verified_with_source(built: sqlite3.Connection) -> None:
    rows = built.execute("SELECT * FROM materials WHERE material_id LIKE 'T0%' "
                         "AND verification='verified'").fetchall()
    assert len(rows) >= 40
    assert all(r["source_url"].startswith("https://www.mlit.go.jp/") for r in rows)


def test_spot_check_mlit_periods(built: sqlite3.Connection) -> None:
    # Values transcribed from MLIT 目で見るアスベスト建材(第2版) pp.8-9.
    expect = {"吹付け石綿": (1956, 1975), "せっこうボード": (1970, 1986),
              "ロックウール吸音天井板": (1961, 1987), "ビニル床タイル": (1952, 1987),
              "けい酸カルシウム板第1種": (1960, 2004), "スレート波板・小波": (1918, 2004)}
    for name, period in expect.items():
        r = built.execute("SELECT production_start_year, production_end_year FROM materials "
                          "WHERE material_type_jp=? AND entry_level='type'", (name,)).fetchone()
        assert tuple(r) == period, name


def test_placeholders_are_unmistakable(built: sqlite3.Connection) -> None:
    for r in built.execute("SELECT * FROM materials WHERE entry_level='product'"):
        assert r["verification"] == "placeholder"
        assert "PLACEHOLDER" in r["manufacturer"]
        assert r["product_name"].startswith("PH-")


def test_type_level_no_is_never_verified(built: sqlite3.Connection) -> None:
    bad = built.execute("SELECT material_id FROM materials WHERE entry_level='type' "
                        "AND contains_asbestos='no' AND verification='verified'").fetchall()
    assert bad == []


def test_aliases_resolve(built: sqlite3.Connection) -> None:
    def ids(alias: str) -> set[str]:
        return {r[0] for r in built.execute(
            "SELECT material_id FROM aliases WHERE alias=?", (alias,))}
    assert ids("ケイカル板") == {"T044"}
    assert ids("PB") == {"T024"}
    assert ids("石綿含有せっこうボード") == {"T024"}       # derived mlit_name
    assert ids("gypsum board") == {"T024"}                  # derived english
    assert ids("PH-ビニタイル K") == {"P005"}               # derived product name


def test_parent_links(built: sqlite3.Connection) -> None:
    orphans = built.execute(
        "SELECT m.material_id FROM materials m LEFT JOIN materials p "
        "ON m.parent_type_id = p.material_id "
        "WHERE m.parent_type_id IS NOT NULL AND p.material_id IS NULL").fetchall()
    assert orphans == []


def test_derived_union_periods_cover_children(built: sqlite3.Connection) -> None:
    for parent in ("T042", "T043", "T044"):
        p = built.execute("SELECT production_start_year s, production_end_year e FROM materials "
                          "WHERE material_id=?", (parent,)).fetchone()
        for c in built.execute("SELECT production_start_year s, production_end_year e "
                               "FROM materials WHERE parent_type_id=? AND entry_level='type'",
                               (parent,)):
            assert p["s"] <= c["s"] and c["e"] <= p["e"]


# --- seed validation rejects bad data ------------------------------------------------------

@pytest.mark.parametrize("mutate, msg", [
    (lambda rows: rows[0].update(contains_asbestos="maybe"), "contains_asbestos"),
    (lambda rows: rows[0].update(production_start_year="1999", production_end_year="1980"),
     "start_year >"),
    (lambda rows: rows[0].update(source_url=""), "source_url"),
    (lambda rows: rows[1].update(material_id=rows[0]["material_id"]), "duplicate"),
    (lambda rows: rows[0].update(usage_parts="attic"), "usage_parts"),
    (lambda rows: next(r for r in rows if r["material_id"] == "N001").update(
        verification="verified", source_url="https://example.org"), "type-level 'no'"),
    (lambda rows: next(r for r in rows if r["material_id"] == "P001").update(
        parent_type_id="ZZZ"), "parent_type_id"),
])
def test_bad_material_rows_rejected(tmp_path: Path, mutate, msg: str) -> None:
    seed = _copy_seeds(tmp_path)
    _rewrite(seed / "materials.csv", mutate)
    with pytest.raises(SeedError, match=msg):
        build_db.load_seeds(seed)


def test_alias_to_unknown_material_rejected(tmp_path: Path) -> None:
    seed = _copy_seeds(tmp_path)
    _rewrite(seed / "aliases.csv", lambda rows: rows[0].update(material_id="T999"))
    with pytest.raises(SeedError, match="unknown material_id"):
        build_db.load_seeds(seed)


# --- regulatory config -----------------------------------------------------------------------

def test_regulatory_config_loads() -> None:
    cfg = regulatory.load()
    ban = cfg.year_logic.full_ban
    assert ban.date_text == "2006-09-01" and ban.verification == "primary"
    assert ban.threshold_pct == 0.1
    assert cfg.year_logic.post_ban_start_rule_verified is False


def test_year_only_milestone_bounds() -> None:
    m = regulatory.load().milestones["spray_ban_1975"]
    assert (m.earliest_date.isoformat(), m.latest_date.isoformat()) == ("1975-01-01", "1975-12-31")


def test_unverified_ban_date_is_refused(tmp_path: Path) -> None:
    raw = yaml.safe_load(regulatory.CONFIG_PATH.read_text(encoding="utf-8"))
    for m in raw["milestones"]:
        if m["id"] == raw["year_logic"]["full_ban_milestone"]:
            m["verification"] = "secondary"
    p = tmp_path / "reg.yaml"
    p.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(regulatory.RegulatoryConfigError, match="primary"):
        regulatory.load(p)
