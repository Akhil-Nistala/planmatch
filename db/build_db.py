"""Build the PlanMatch reference database (SQLite) from the CSV seeds.

Usage::

    python -m db.build_db                 # -> db/build/materials.sqlite
    python -m db.build_db --out other.sqlite

The seeds are validated before anything is written; a validation error aborts the build.
Canonical names, MLIT full names ("石綿含有" + type), English names and product names are
added to the alias table automatically so the hand-written alias CSV only holds real variants.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

DB_DIR = Path(__file__).resolve().parent
SEED_DIR = DB_DIR / "seed"
SCHEMA_PATH = DB_DIR / "schema.sql"
DEFAULT_OUT = DB_DIR / "build" / "materials.sqlite"

MATERIAL_COLUMNS = (
    "material_id", "entry_level", "parent_type_id", "material_type_jp", "material_type_en",
    "product_name", "manufacturer", "asbestos_type", "production_start_year",
    "production_end_year", "contains_asbestos", "dust_level", "usage_parts", "verification",
    "source_url", "source_note",
)
ALIAS_COLUMNS = ("alias", "material_id", "kind", "verification", "note")

CONTAINS_VALUES = {"yes", "no", "varies"}
VERIFICATION_VALUES = {"verified", "assumption", "placeholder"}
ALIAS_KINDS = {"canonical", "kana_variant", "kanji_variant", "abbreviation", "old_name",
               "english", "shorthand", "mlit_name"}
USAGE_PARTS = {"floor", "baseboard", "wall", "ceiling", "partition", "exterior_wall", "eaves",
               "roof", "steel_fireproofing", "machine_room", "piping", "equipment", "chimney"}
YEAR_RANGE = (1900, 2030)


class SeedError(ValueError):
    """Raised when a seed file violates the schema or a cross-reference rule."""


@dataclass
class Seeds:
    """Validated seed rows ready to be inserted."""

    materials: list[dict[str, object]]
    aliases: list[dict[str, object]]
    warnings: list[str] = field(default_factory=list)


def _read_csv(path: Path, expected: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != expected:
            raise SeedError(f"{path.name}: header {reader.fieldnames} != {list(expected)}")
        return [{k: (v or "").strip() for k, v in row.items()} for row in reader]


def _opt_int(value: str, where: str) -> int | None:
    if value == "":
        return None
    try:
        year = int(value)
    except ValueError as exc:
        raise SeedError(f"{where}: not an integer: {value!r}") from exc
    if not YEAR_RANGE[0] <= year <= YEAR_RANGE[1]:
        raise SeedError(f"{where}: year {year} outside {YEAR_RANGE}")
    return year


def validate_materials(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    """Type-check material rows and enforce the cross-row rules.

    Rules beyond the SQL CHECKs: unique ids; parents exist and are types; products carry a
    product name and manufacturer; ``verified`` rows carry a source URL; anything with
    ``contains_asbestos='no'`` must NOT be ``verified`` unless it is a product (type-level
    "no" is always a domain assumption and decide.py treats it more strictly).
    """
    out: list[dict[str, object]] = []
    ids: set[str] = set()
    for i, r in enumerate(rows, start=2):
        where = f"materials.csv line {i} ({r['material_id'] or '?'})"
        mid = r["material_id"]
        if not mid or mid in ids:
            raise SeedError(f"{where}: missing or duplicate material_id")
        ids.add(mid)
        if r["entry_level"] not in {"type", "product"}:
            raise SeedError(f"{where}: bad entry_level {r['entry_level']!r}")
        if r["contains_asbestos"] not in CONTAINS_VALUES:
            raise SeedError(f"{where}: bad contains_asbestos {r['contains_asbestos']!r}")
        if r["verification"] not in VERIFICATION_VALUES:
            raise SeedError(f"{where}: bad verification {r['verification']!r}")
        if not r["material_type_jp"] or not r["material_type_en"]:
            raise SeedError(f"{where}: material_type_jp/en required")
        if r["verification"] == "verified" and not r["source_url"].startswith("http"):
            raise SeedError(f"{where}: verified rows need a source_url")
        if r["entry_level"] == "product":
            if not (r["product_name"] and r["manufacturer"] and r["parent_type_id"]):
                raise SeedError(f"{where}: products need product_name, manufacturer, parent_type_id")
        elif r["contains_asbestos"] == "no" and r["verification"] == "verified":
            raise SeedError(f"{where}: type-level 'no' cannot be 'verified' (use 'assumption')")
        parts = [p for p in r["usage_parts"].split(";") if p]
        unknown = set(parts) - USAGE_PARTS
        if unknown:
            raise SeedError(f"{where}: unknown usage_parts {sorted(unknown)}")
        start = _opt_int(r["production_start_year"], where)
        end = _opt_int(r["production_end_year"], where)
        if start is not None and end is not None and start > end:
            raise SeedError(f"{where}: production_start_year > production_end_year")
        dust = r["dust_level"]
        if dust not in {"", "1", "2", "3"}:
            raise SeedError(f"{where}: bad dust_level {dust!r}")
        row: dict[str, object] = {k: (r[k] or None) for k in MATERIAL_COLUMNS}
        row.update(production_start_year=start, production_end_year=end,
                   dust_level=int(dust) if dust else None)
        out.append(row)

    by_id = {str(m["material_id"]): m for m in out}
    for m in out:
        parent = m["parent_type_id"]
        if parent is None:
            continue
        if parent not in by_id or by_id[parent]["entry_level"] != "type":
            raise SeedError(f"{m['material_id']}: parent_type_id {parent} is not a known type")
        if parent == m["material_id"]:
            raise SeedError(f"{m['material_id']}: is its own parent")
    return out


def derive_aliases(materials: list[dict[str, object]]) -> list[dict[str, object]]:
    """Aliases implied by the material rows themselves (canonical / MLIT / English / product)."""
    derived: list[dict[str, object]] = []
    for m in materials:
        mid, ver = m["material_id"], m["verification"]
        if m["entry_level"] == "product":
            derived.append(dict(alias=m["product_name"], material_id=mid, kind="canonical",
                                verification=ver, note="product name"))
            continue
        jp = str(m["material_type_jp"])
        derived.append(dict(alias=jp, material_id=mid, kind="canonical", verification=ver,
                            note=None))
        derived.append(dict(alias=str(m["material_type_en"]), material_id=mid, kind="english",
                            verification=ver, note=None))
        if m["contains_asbestos"] == "varies" and m["source_url"] and "mlit.go.jp" in str(m["source_url"]):
            derived.append(dict(alias="石綿含有" + jp, material_id=mid, kind="mlit_name",
                                verification=ver, note="MLIT list name"))
    return derived


def validate_aliases(rows: list[dict[str, str]], material_ids: set[str]) -> list[dict[str, object]]:
    """Type-check hand-written alias rows."""
    out: list[dict[str, object]] = []
    for i, r in enumerate(rows, start=2):
        where = f"aliases.csv line {i} ({r['alias']!r})"
        if not r["alias"]:
            raise SeedError(f"{where}: empty alias")
        if r["material_id"] not in material_ids:
            raise SeedError(f"{where}: unknown material_id {r['material_id']}")
        if r["kind"] not in ALIAS_KINDS:
            raise SeedError(f"{where}: bad kind {r['kind']!r}")
        if r["verification"] not in VERIFICATION_VALUES:
            raise SeedError(f"{where}: bad verification {r['verification']!r}")
        out.append({k: (r[k] or None) for k in ALIAS_COLUMNS})
    return out


def load_seeds(seed_dir: Path = SEED_DIR) -> Seeds:
    """Read and validate all seed files; merge derived and hand-written aliases."""
    materials = validate_materials(_read_csv(seed_dir / "materials.csv", MATERIAL_COLUMNS))
    ids = {str(m["material_id"]) for m in materials}
    manual = validate_aliases(_read_csv(seed_dir / "aliases.csv", ALIAS_COLUMNS), ids)

    merged: dict[tuple[str, str], dict[str, object]] = {}
    warnings: list[str] = []
    for a in derive_aliases(materials) + manual:
        key = (str(a["alias"]), str(a["material_id"]))
        if key in merged:
            raise SeedError(f"duplicate alias {key}")
        merged[key] = a

    # Same surface form pointing at several entries is allowed (e.g. a type and its product),
    # but worth knowing about: the matcher must then rank, not look up.
    seen: dict[str, list[str]] = {}
    for alias, mid in merged:
        seen.setdefault(alias, []).append(mid)
    for alias, mids in sorted(seen.items()):
        if len(mids) > 1:
            warnings.append(f"ambiguous alias {alias!r} -> {sorted(mids)}")
    return Seeds(materials=materials, aliases=list(merged.values()), warnings=warnings)


def _seed_hash(seed_dir: Path) -> str:
    h = hashlib.sha256()
    for name in ("materials.csv", "aliases.csv"):
        h.update((seed_dir / name).read_bytes())
    h.update(SCHEMA_PATH.read_bytes())
    return h.hexdigest()


def build(out: Path = DEFAULT_OUT, seed_dir: Path = SEED_DIR) -> Seeds:
    """Validate seeds and (re)write the SQLite database atomically."""
    seeds = load_seeds(seed_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    try:
        con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        # Types first so product -> parent foreign keys resolve.
        ordered = sorted(seeds.materials, key=lambda m: (m["entry_level"] != "type",
                                                         m["parent_type_id"] is not None))
        con.executemany(
            f"INSERT INTO materials ({', '.join(MATERIAL_COLUMNS)}) "
            f"VALUES ({', '.join('?' * len(MATERIAL_COLUMNS))})",
            [tuple(m[c] for c in MATERIAL_COLUMNS) for m in ordered])
        con.executemany(
            f"INSERT INTO aliases ({', '.join(ALIAS_COLUMNS)}) VALUES (?, ?, ?, ?, ?)",
            [tuple(a[c] for c in ALIAS_COLUMNS) for a in seeds.aliases])
        con.executemany("INSERT INTO build_info VALUES (?, ?)", [
            ("seed_sha256", _seed_hash(seed_dir)),
            ("built_at_utc", datetime.now(timezone.utc).isoformat(timespec="seconds")),
            ("n_materials", str(len(seeds.materials))),
            ("n_aliases", str(len(seeds.aliases))),
        ])
        con.commit()
    finally:
        con.close()
    tmp.replace(out)
    return seeds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    try:
        seeds = build(args.out)
    except SeedError as exc:
        print(f"seed validation failed: {exc}", file=sys.stderr)
        return 1
    counts: dict[str, int] = {}
    for m in seeds.materials:
        key = f"{m['entry_level']}/{m['verification']}/{m['contains_asbestos']}"
        counts[key] = counts.get(key, 0) + 1
    print(f"wrote {args.out}  materials={len(seeds.materials)}  aliases={len(seeds.aliases)}")
    for key in sorted(counts):
        print(f"  {key:32s} {counts[key]}")
    for w in seeds.warnings:
        print(f"  note: {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
