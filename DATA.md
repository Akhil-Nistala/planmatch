# DATA.md: reference data sources and licensing

> PlanMatch is a **screening aid**. It does not replace sampling and laboratory analysis by a
> qualified asbestos surveyor (in Japan, since 2023-10-01 building surveys must be done by a
> person who completed the MHLW-designated course).

## 1. The official database: why it is **not** in this repo

| | |
|---|---|
| Name | 石綿（アスベスト）含有建材データベース (MLIT 国土交通省 + METI 経済産業省) |
| URL | https://www.asbestos-database.jp/ (operated by 一般財団法人建材試験センター) |
| Terms | https://asbestos-database.jp/notice/ (ご利用上の注意, §1.4 著作権等) |
| Last checked | 2026-11-06 (site live; latest registry update listed 2026-03-26) |

What the terms say (paraphrased; the Japanese text is authoritative):

* Reproduction (転載等) without MLIT/METI permission is **not allowed**, except for private use
  or quotation permitted by copyright law. Modification (改変) without permission is not allowed.
  The site footer adds that reproduction/reuse of all text and images and commercial sale are
  strictly prohibited.
* Citations must use 「国土交通省・経済産業省　石綿（アスベスト）含有建材データベース（〇年〇月〇日参照）」.
* The terms say nothing either way about automated or programmatic access, and the site has no
  API or bulk download. Searching requires clicking 「上記内容に同意する」.
* The data is supplied or confirmed by manufacturers. Some manufacturers deliberately reported
  long production periods to stay on the safe side, and accuracy is not guaranteed.

**Decision:** no records from this database are scraped, stored or committed. Programmatic use
and redistribution are not permitted, and a public portfolio repo is redistribution. Instead:

1. **Type-level entries** are taken from MLIT's own published guide (section 2), which is public.
2. **Product-level entries** in the repo are **fictional placeholders** that exist only to test
   the product/manufacturer logic (section 3).
3. A user who obtains permission, or who looks up products by hand for one building, can put
   rows in a local, git-ignored CSV with the same columns. The builder will take a
   `--seed-dir` override in a later milestone.

## 2. Verified type-level data (`verification = verified`)

**Source:** 国土交通省「目で見るアスベスト建材（第2版）」, 平成20年3月 (March 2008),
https://www.mlit.go.jp/kisha/kisha08/01/010425_3/01.pdf, pp. 8–9 「アスベスト含有建材と製造時期」.

* Rows T001–T041 copy the material-type names and **製造時期** (the period in which
  *asbestos-containing* versions were made) exactly as printed. "～1980" is stored as
  start = NULL, end = 1980.
* MLIT corrected gypsum board (せっこうボード) from 1970–2000 in the first edition to
  **1970–1986**. The second edition value is the one used here.
* `dust_level` (発じん性レベル 1/2/3) follows the guide's grouping: sprayed materials are level 1,
  insulation/fireproofing is level 2, and molded boards are level 3.
* T042–T044 are **derived** rows ("slate board, subtype unspecified", "corrugated slate,
  unspecified", "calcium silicate board, type unspecified"). Their periods are the union of the
  verified child rows. They exist because drawings usually say only 「ケイカル板」 or
  「スレートボード」.
* `contains_asbestos = yes` is used only where the material name itself is asbestos-based
  (吹付け石綿, 石綿保温材, 石綿セメント管 …). Every other MLIT type is `varies`: the same
  material type was made both with and without asbestos. For these types the decision depends
  on the product, the manufacturer and the year, not on the type name.

## 3. Assumption and placeholder rows

| verification | rows | meaning | how decide.py will treat it |
|---|---|---|---|
| `assumption` | N001–N012 | Material classes that appear on none of the ACM lists consulted (wood flooring, glass, steel sheet, tatami …). `contains_asbestos = no`. | May support DOES_NOT_CONTAIN only with a confident match and high OCR confidence. The report always states that **adhesives, substrates and coatings were not assessed**. |
| `placeholder` | T045 仕上塗材 | Known ACM category, but no production period has been sourced yet. | Always NEEDS_REVIEW. |
| `placeholder` | P001–P010 | **Fictional** products. Their names start with `PH-` and their manufacturer contains `（PLACEHOLDER）`. They are not real products. | Used in tests and evaluation only. |

The builder rejects any type-level `contains_asbestos = no` row that is marked `verified`.

## 4. Alias table

`db/seed/aliases.csv` holds hand-written variants: kana/kanji variants (ケイ酸/けい酸/珪酸), drawing
shorthand (ケイカル板, PB, フレキ, 長尺シート), older names (Pタイル, 岩綿吸音板, プラスターボード),
JIS A 6901 gypsum-board symbols (GB-R/S/F/NC) and English names. They are all marked
`assumption` because they come from common drawing practice, not from a cited source.
The builder adds canonical names, MLIT list names (「石綿含有」 + type) and product names
automatically.

## 5. Regulatory dates

See `configs/regulatory.yaml`. Each milestone has a URL, a verbatim quote and a verification level:

| Milestone | Date | Verification |
|---|---|---|
| Spraying ban (>5%) | 1975 (exact day not found) | secondary: MHLW asbestos portal |
| Amosite/crocidolite ban (>1%) | 1995-04-01 | **primary**: 平成18年政令第257号 附則第2条 |
| 10 listed product groups (>1%) | 2004-10-01 | **primary**: same 附則 |
| 石綿障害予防規則 in force | 2005-07-01 | secondary: portal |
| All products >0.1% banned | **2006-09-01** | **primary**: 平成18年政令第257号 附則第1条 |
| Remaining exemptions closed | 2012-03-01 | secondary: portal (instrument: 平成23年政令第4号) |

Only the 2006-09-01 date may drive a year-based DOES_NOT_CONTAIN, and the config loader refuses
to start unless that entry is a full date from a primary source. The often-quoted survey
shortcut 「2006年9月1日以降着工なら石綿なし」 was **not** found in a primary source. It is
recorded as unverified, and safety margins are applied on top of the ban date
(`year_logic` in the config).

## 6. Rebuilding

```
python -m db.build_db        # validates seeds -> db/build/materials.sqlite (git-ignored)
```
