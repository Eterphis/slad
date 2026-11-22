# eval/ - local F1 scorer

Local copy of the hidden contest metric. Reference implementation: `eval/score.py` (the full
definition is in its module docstring; this file summarises it). Later tasks must not change it.

    python -m eval.score --pred <dir> --gold <dir> [--cases 41-60|01,07] [--types odwolanie,pelnomocnictwo,przelew] [--report out.md]

Prints a per-type table, `normalized: <F1>` and, as the last line, `score: <F1>` (exact mode).

- Layout `<dir>/<case>/*.json`, case names must match (`przyklad_NN`); `--cases` filters by trailing number.
  Missing pred case = all FN. Pred file names do not matter.
- Document type from top-level keys (`OdwolanieKIO`/`Odwolujacy` -> odwolanie, `mocodawca`/`pelnomocnicy` ->
  pelnomocnictwo, `przelew_bankowy` -> przelew). Several documents of a type are paired by best agreement.
- Micro F1 over non-null leaves: equal = TP; different = 1 FP + 1 FN; pred only = FP; gold only = FN; null/null ignored.
  Missing document = all FN; extra document = all FP. F1 = 2TP / (2TP + FP + FN).
- Lists (Odwolujacy, Zamawiajacy, mocodawca, podpisujacy, pelnomocnicy, ...) are aligned by maximum leaf
  agreement (Hungarian); unmatched items are FN/FP.
- exact: type-aware equality (50 == 50.0, strings verbatim). normalized: also NFC, casefold, strip, whitespace
  collapse, surrounding quotes dropped, digit-only comparison for digit strings with spaces/hyphens.
- Gold is never copied into the repo; unit tests use small inline fixtures. Standard library only.

Sanity numbers: gold vs gold = 1.0; empty pred = 0.0; case 01 without the przelew document = 0.8966.

Caveats for extractors:
- List items are matched by best agreement, not by position, so the local F1 is an upper bound if the hidden
  grader compares lists by index. Keep document order in lists anyway.
- An empty string `""` counts as a value (FP when gold is null). Emit `null` for absent fields.
- Exact mode does not bridge types (`"34.00"` vs `34.0`).

## make_synth.py - varied synthetic cases (outside the UZP layouts)

    python -m eval.make_synth --out ../uzp-data-synth/synth --cases 20 [--seed 2026] [--scan-share 0.35]
    python -m odw2json --input ../uzp-data-synth/synth/input --output ../uzp-data-synth/synth/output
    python -m eval.score --pred ../uzp-data-synth/synth/output --gold ../uzp-data-synth/synth/gold

Cases built like real filings (appeal, 0-2 powers of attorney, 1-2 transfers, sometimes a non-class document that
must give `{}`), with layouts modelled on public templates and real appeals: 6 appeal layouts, 5 power-of-attorney
layouts (company / individual / consortium / table / dative prose), 6 bank confirmation layouts (fictitious banks),
4 negative kinds, 4 scan modes (office, fax, copy, phone photo). Everything is fictitious; `manifest.json` lists the
layout, font and scan mode per document for breakdowns. Needs `reportlab` (BSD, dev only, not in requirements.txt).
