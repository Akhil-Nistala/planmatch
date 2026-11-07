# PlanMatch: asbestos-material matching for building drawings

> **Screening aid only.** PlanMatch flags materials for a qualified surveyor to check. It
> is not a safety determination and does not replace sampling and laboratory analysis.

Third stage of the drawing pipeline:

```
drawing ─► PlanScope ─► PlanRead ─► PlanMatch
           layout &     OCR + conf  material mentions → DB match →
           tables       + top-k     CONTAINS / DOES_NOT_CONTAIN / NEEDS_REVIEW + reason
```

Status: milestone 1 (reference DB, alias table, regulatory config). See DATA.md.

```
python -m venv .venv && .venv/Scripts/activate
pip install -r requirements.txt
python -m db.build_db
python -m pytest
```
