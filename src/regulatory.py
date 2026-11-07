"""Load and validate ``configs/regulatory.yaml``.

All regulatory dates live in that file with a source URL and a verification level. Code asks
this module for them; nothing in ``src/`` hard-codes a ban date.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[1] / "configs" / "regulatory.yaml"
VERIFICATION_LEVELS = ("primary", "secondary", "unverified")
_DATE_RE = re.compile(r"^\d{4}(-\d{2}-\d{2})?$")


class RegulatoryConfigError(ValueError):
    """The regulatory config is malformed or would let an unverified date drive a decision."""


@dataclass(frozen=True)
class Milestone:
    """One regulatory milestone with its provenance."""

    id: str
    date_text: str          # "YYYY" or "YYYY-MM-DD" exactly as recorded
    threshold_pct: float | None
    scope: str
    instrument: str
    source_url: str
    quote: str
    verification: str

    @property
    def earliest_date(self) -> date:
        """Earliest date the milestone could mean (Jan 1 for a year-only entry)."""
        if len(self.date_text) == 4:
            return date(int(self.date_text), 1, 1)
        return date.fromisoformat(self.date_text)

    @property
    def latest_date(self) -> date:
        """Latest date the milestone could mean (Dec 31 for a year-only entry)."""
        if len(self.date_text) == 4:
            return date(int(self.date_text), 12, 31)
        return date.fromisoformat(self.date_text)


@dataclass(frozen=True)
class YearLogic:
    """Parameters for the year-based rules in decide.py."""

    full_ban: Milestone
    post_ban_start_rule_verified: bool
    completion_to_start_lag_years: int
    post_ban_margin_years: int
    post_production_margin_years: int


@dataclass(frozen=True)
class RegulatoryConfig:
    """Parsed regulatory config."""

    checked_on: date
    milestones: dict[str, Milestone]
    year_logic: YearLogic


def load(path: Path = CONFIG_PATH) -> RegulatoryConfig:
    """Parse and validate the config.

    Raises:
        RegulatoryConfigError: on missing fields, bad dates, unknown verification levels, or if
            the milestone used for DOES_NOT_CONTAIN-by-year is not a full-date ``primary`` entry.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    milestones: dict[str, Milestone] = {}
    for m in raw.get("milestones", []):
        try:
            ms = Milestone(id=m["id"], date_text=str(m["date"]),
                           threshold_pct=m.get("threshold_pct"), scope=m["scope"],
                           instrument=m["instrument"], source_url=m["source_url"],
                           quote=m["quote"], verification=m["verification"])
        except KeyError as exc:
            raise RegulatoryConfigError(f"milestone {m.get('id')!r} missing {exc}") from exc
        if ms.id in milestones:
            raise RegulatoryConfigError(f"duplicate milestone id {ms.id}")
        if not _DATE_RE.match(ms.date_text):
            raise RegulatoryConfigError(f"{ms.id}: date must be YYYY or YYYY-MM-DD")
        if ms.verification not in VERIFICATION_LEVELS:
            raise RegulatoryConfigError(f"{ms.id}: verification {ms.verification!r}")
        if not ms.source_url.startswith("https://"):
            raise RegulatoryConfigError(f"{ms.id}: source_url must be https")
        milestones[ms.id] = ms

    yl = raw["year_logic"]
    ban_id = yl["full_ban_milestone"]
    if ban_id not in milestones:
        raise RegulatoryConfigError(f"year_logic.full_ban_milestone {ban_id!r} not defined")
    ban = milestones[ban_id]
    if ban.verification != "primary" or len(ban.date_text) != 10:
        raise RegulatoryConfigError(
            f"{ban_id} drives DOES_NOT_CONTAIN decisions and must be a full date verified "
            f"from a primary source (got {ban.verification}, {ban.date_text})")
    year_logic = YearLogic(
        full_ban=ban,
        post_ban_start_rule_verified=bool(yl["post_ban_start_rule_verified"]),
        completion_to_start_lag_years=int(yl["completion_to_start_lag_years"]),
        post_ban_margin_years=int(yl["post_ban_margin_years"]),
        post_production_margin_years=int(yl["post_production_margin_years"]),
    )
    for name in ("completion_to_start_lag_years", "post_ban_margin_years",
                 "post_production_margin_years"):
        if getattr(year_logic, name) < 0:
            raise RegulatoryConfigError(f"year_logic.{name} must be >= 0")
    return RegulatoryConfig(checked_on=date.fromisoformat(str(raw["checked_on"])),
                            milestones=milestones, year_logic=year_logic)
