"""Local F1 scorer: the house's copy of the (hidden) contest metric.

DEFINITION (reference; changes only through a new task with review: always)

Layout
  <gold>/<case>/*.json and <pred>/<case>/*.json. Case folders must have the same name
  (`przyklad_NN`); `--cases` filters by the number at the end of the case name ("41-60",
  "01,07", "01-05,60"). Gold cases without a pred folder count as all-FN. Pred cases that
  do not exist in gold are ignored. Gold JSONs are plain JSON.

Document type
  Taken from top-level keys, never from the file name: `OdwolanieKIO` or `Odwolujacy` ->
  odwolanie, `mocodawca` or `pelnomocnicy` -> pelnomocnictwo, `przelew_bankowy` -> przelew.
  `--types` restricts scoring to some types (applied to gold and pred alike). Several
  documents of one type in a case are paired by maximum leaf agreement (Hungarian).
  A pred file of unknown type counts as an extra document (all its leaves FP); a pred
  file that is not valid JSON is skipped with a warning (so it counts as missing).

Leaves and counting (field-level micro F1 over non-null leaves)
  * pred leaf equals gold leaf            -> TP
  * both non-null but different           -> 1 FP + 1 FN (a wrong value costs both)
  * pred non-null, gold null or missing   -> FP
  * gold non-null, pred null or missing   -> FN
  * both null / missing                   -> ignored
  * gold document with no pred partner    -> all its non-null leaves FN
  * pred document with no gold partner    -> all its non-null leaves FP
    (e.g. a document that should have been rejected)
  * lists (of objects or scalars) are aligned by maximum leaf agreement (Hungarian,
    ties broken by fewer errors); unmatched items count fully as FN / FP.
  * dict vs non-dict at the same place: every leaf on both sides is an error.
  F1 = 2TP / (2TP + FP + FN); 0.0 when the denominator is 0. Micro-averaged over every
  leaf of every selected document (so documents with more fields weigh more).

Equality
  exact       : JSON type-aware. Numbers by value (50 == 50.0), bool is not a number,
                strings compared exactly (no strip, no case folding).
  normalized  : exact, or both strings equal after NFC, casefold, strip, whitespace
                collapse and dropping surrounding quotes; or both strings are made only of
                digits, spaces and hyphens and have equal digit sequences.

Output: per-type table (exact mode), `normalized: <F1>`, and as the LAST line
`score: <F1>` (exact mode, 4 decimals). `--report FILE.md` writes per-type and per-field
precision / recall / F1 and the worst fields.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

DOC_TYPES = ("odwolanie", "pelnomocnictwo", "przelew")
_TYPE_KEYS = (
    ("odwolanie", ("OdwolanieKIO", "Odwolujacy", "Zamawiajacy", "ZamowieniePubliczne")),
    ("pelnomocnictwo", ("mocodawca", "pelnomocnicy")),
    ("przelew", ("przelew_bankowy",)),
)


def doc_type(doc):
    """Document type from top-level keys, or None."""
    if not isinstance(doc, dict):
        return None
    for name, keys in _TYPE_KEYS:
        if any(k in doc for k in keys):
            return name
    return None


# ---------------------------------------------------------------- equality

def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def eq_exact(a, b):
    if _is_num(a) and _is_num(b):
        return a == b
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    return type(a) is type(b) and a == b


_QUOTES = "\"'“”„«»‘’"
_DIGITSEP = re.compile(r"^[\d\s\-]+$")


def _norm_str(s):
    s = unicodedata.normalize("NFC", s).casefold().strip()
    s = re.sub(r"\s+", " ", s)
    return s.strip(_QUOTES).strip()


def eq_norm(a, b):
    if eq_exact(a, b):
        return True
    if isinstance(a, str) and isinstance(b, str):
        if _norm_str(a) == _norm_str(b):
            return True
        if _DIGITSEP.match(a) and _DIGITSEP.match(b):
            da, db = re.sub(r"\D", "", a), re.sub(r"\D", "", b)
            return da != "" and da == db
    return False


# ---------------------------------------------------------------- counting

class Counts:
    """TP/FP/FN totals plus the same per field (path with list indices as `[]`)."""

    def __init__(self):
        self.tp = self.fp = self.fn = 0
        self.fields = {}

    def add(self, field, tp=0, fp=0, fn=0):
        self.tp += tp
        self.fp += fp
        self.fn += fn
        f = self.fields.setdefault(field, [0, 0, 0])
        f[0] += tp
        f[1] += fp
        f[2] += fn

    def merge(self, other):
        for field, (tp, fp, fn) in other.fields.items():
            self.add(field, tp, fp, fn)

    @property
    def precision(self):
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self):
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def f1(self):
        d = 2 * self.tp + self.fp + self.fn
        return 2 * self.tp / d if d else 0.0


def _sub(path, key):
    return f"{path}.{key}" if path else str(key)


def _only(c, x, path, side):
    """Every non-null leaf of x is FP (side 'fp') or FN (side 'fn')."""
    if x is None:
        return
    if isinstance(x, dict):
        for k, v in x.items():
            _only(c, v, _sub(path, k), side)
    elif isinstance(x, list):
        for v in x:
            _only(c, v, path + "[]", side)
    else:
        c.add(path, **{side: 1})


def _hungarian(cost):
    """Min-cost assignment on a square matrix; returns col index per row."""
    n = len(cost)
    INF = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], INF, 0
            for j in range(1, n + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    res = [0] * n
    for j in range(1, n + 1):
        res[p[j] - 1] = j - 1
    return res


def _align(preds, golds, cmp_fn):
    """Pair items by max agreement.

    Returns (pairs [(i, j, Counts)], unmatched pred indices, unmatched gold indices).
    """
    if not preds or not golds:
        return [], list(range(len(preds))), list(range(len(golds)))
    cache = [[cmp_fn(p, g) for g in golds] for p in preds]
    n = max(len(preds), len(golds))
    big = 10 ** 6
    cost = [[0.0] * n for _ in range(n)]
    for i in range(len(preds)):
        for j in range(len(golds)):
            c = cache[i][j]
            cost[i][j] = -(c.tp * big) + (c.fp + c.fn)
    assign = _hungarian(cost)
    pairs, up = [], []
    used_g = set()
    for i, j in enumerate(assign):
        if i < len(preds) and j < len(golds):
            pairs.append((i, j, cache[i][j]))
            used_g.add(j)
        elif i < len(preds):
            up.append(i)
    ug = [j for j in range(len(golds)) if j not in used_g]
    return pairs, up, ug


def compare(pred, gold, eq, path=""):
    """Counts for one value pair (recursive)."""
    c = Counts()
    if pred is None and gold is None:
        return c
    if isinstance(pred, dict) and isinstance(gold, dict):
        for k in list(gold) + [k for k in pred if k not in gold]:
            c.merge(compare(pred.get(k), gold.get(k), eq, _sub(path, k)))
        return c
    if isinstance(pred, list) and isinstance(gold, list):
        pairs, up, ug = _align(pred, gold, lambda p, g: compare(p, g, eq, path + "[]"))
        for _, _, pc in pairs:
            c.merge(pc)
        for i in up:
            _only(c, pred[i], path + "[]", "fp")
        for j in ug:
            _only(c, gold[j], path + "[]", "fn")
        return c
    if pred is None or gold is None or isinstance(pred, (dict, list)) or isinstance(gold, (dict, list)):
        if pred is None:
            _only(c, gold, path, "fn")
        elif gold is None:
            _only(c, pred, path, "fp")
        else:  # structural mismatch (scalar vs container, dict vs list)
            _only(c, pred, path, "fp")
            _only(c, gold, path, "fn")
        return c
    if eq(pred, gold):
        c.add(path, tp=1)
    else:
        c.add(path, fp=1, fn=1)
    return c


def compare_docs(pred, gold, eq):
    return compare(pred, gold, eq)


# ---------------------------------------------------------------- directories

def parse_cases(spec):
    """'41-60', '01,07', '01-05,60' -> set of ints; None -> None."""
    if spec is None:
        return None
    out = set()
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


def _case_no(name):
    m = re.search(r"(\d+)$", name)
    return int(m.group(1)) if m else None


def _load_docs(case_dir, strict):
    docs = []
    if case_dir is None or not case_dir.is_dir():
        return docs
    for f in sorted(case_dir.glob("*.json")):
        try:
            doc = json.loads(f.read_text(encoding="utf-8-sig"))
            if strict and doc_type(doc) is None:
                print(f"warning: gold document {f} has unknown type, ignored", file=sys.stderr)
            docs.append((f.name, doc))
        except (OSError, ValueError) as e:
            if strict:
                raise SystemExit(f"cannot read gold {f}: {e}")
            print(f"warning: skipping unreadable pred {f}: {e}", file=sys.stderr)
    return docs


def _score_case(pred_docs, gold_docs, types, eq):
    """Returns {type: Counts} for one case."""
    result = {}
    by_type_g, by_type_p = {}, {}
    for _, d in gold_docs:
        t = doc_type(d)
        if t is None:
            continue
        by_type_g.setdefault(t, []).append(d)
    for _, d in pred_docs:
        by_type_p.setdefault(doc_type(d) or "unknown", []).append(d)
    for t in set(by_type_g) | set(by_type_p):
        if types and t not in types:
            continue
        gs, ps = by_type_g.get(t, []), by_type_p.get(t, [])
        c = Counts()
        pairs, up, ug = _align(ps, gs, lambda p, g: compare(p, g, eq))
        for _, _, pc in pairs:
            c.merge(pc)
        for i in up:
            _only(c, ps[i], "", "fp")
        for j in ug:
            _only(c, gs[j], "", "fn")
        result[t] = c
    return result


def score_dirs(pred_dir, gold_dir, cases=None, types=None):
    """Score two directory trees.

    Returns {'exact': Counts, 'normalized': Counts,
             'by_type': {mode: {type: Counts}}, 'cases': {case: {mode: Counts}}}.
    """
    pred_dir, gold_dir = Path(pred_dir), Path(gold_dir)
    wanted = cases if isinstance(cases, (set, frozenset)) else parse_cases(cases)
    types = set(types) if types else None
    out = {"exact": Counts(), "normalized": Counts(),
           "by_type": {"exact": {}, "normalized": {}}, "cases": {}}
    gold_cases = sorted(d for d in gold_dir.iterdir() if d.is_dir()) if gold_dir.is_dir() else []
    if pred_dir.is_dir():
        known = {d.name for d in gold_cases}
        stray = sorted(d.name for d in pred_dir.iterdir() if d.is_dir() and d.name not in known)
        if stray:
            print("warning: pred case folders with no gold folder (ignored): " + ", ".join(stray),
                  file=sys.stderr)
    for gdir in gold_cases:
        no = _case_no(gdir.name)
        if wanted is not None and no not in wanted:
            continue
        gdocs = _load_docs(gdir, True)
        pdocs = _load_docs(pred_dir / gdir.name, False)
        out["cases"][gdir.name] = {}
        for mode, eq in (("exact", eq_exact), ("normalized", eq_norm)):
            per_type = _score_case(pdocs, gdocs, types, eq)
            case_total = Counts()
            for t, c in per_type.items():
                out["by_type"][mode].setdefault(t, Counts()).merge(c)
                case_total.merge(c)
            out["cases"][gdir.name][mode] = case_total
            out[mode].merge(case_total)
    return out


# ---------------------------------------------------------------- output

def _fmt(c):
    return f"P={c.precision:.4f} R={c.recall:.4f} F1={c.f1:.4f} (TP={c.tp} FP={c.fp} FN={c.fn})"


def write_report(path, res):
    L = ["# Scorer report", "",
         f"- exact F1: **{res['exact'].f1:.4f}**  ({_fmt(res['exact'])})",
         f"- normalized F1: **{res['normalized'].f1:.4f}**  ({_fmt(res['normalized'])})", "",
         "## Per type (exact)", "", "| type | P | R | F1 | TP | FP | FN |", "|---|---|---|---|---|---|---|"]
    for t, c in sorted(res["by_type"]["exact"].items()):
        L.append(f"| {t} | {c.precision:.4f} | {c.recall:.4f} | {c.f1:.4f} | {c.tp} | {c.fp} | {c.fn} |")
    L += ["", "## Per field (exact)", "", "| field | P | R | F1 | TP | FP | FN |", "|---|---|---|---|---|---|---|"]
    rows = []
    for t, c in res["by_type"]["exact"].items():
        for field, (tp, fp, fn) in c.fields.items():
            f = Counts()
            f.add(field, tp, fp, fn)
            rows.append((f"{t}:{field}", f))
    for name, f in sorted(rows, key=lambda r: r[0]):
        L.append(f"| {name} | {f.precision:.4f} | {f.recall:.4f} | {f.f1:.4f} | {f.tp} | {f.fp} | {f.fn} |")
    worst = sorted((r for r in rows if r[1].fp + r[1].fn), key=lambda r: -(r[1].fp + r[1].fn))[:20]
    L += ["", "## Worst fields (by FP+FN, exact)", ""]
    L += [f"- `{n}`: {f.fp + f.fn} errors (FP={f.fp}, FN={f.fn}, TP={f.tp})" for n, f in worst] or ["- none"]
    L += ["", "## Worst cases (exact)", ""]
    cs = sorted(res["cases"].items(), key=lambda kv: kv[1]["exact"].f1)[:10]
    L += [f"- {n}: F1={m['exact'].f1:.4f} (FP={m['exact'].fp}, FN={m['exact'].fn})" for n, m in cs] or ["- none"]
    Path(path).write_text("\n".join(L) + "\n", encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="eval.score", description="Local F1 scorer (see module docstring).")
    ap.add_argument("--pred", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--cases", help="e.g. 41-60 or 01,07")
    ap.add_argument("--types", help="comma list of: " + ",".join(DOC_TYPES))
    ap.add_argument("--report", help="write markdown report to this file")
    a = ap.parse_args(argv)
    types = [t.strip() for t in a.types.split(",") if t.strip()] if a.types else None
    for t in types or []:
        if t not in DOC_TYPES:
            ap.error(f"unknown type {t!r}")
    try:
        cases = parse_cases(a.cases)
    except ValueError:
        ap.error(f"malformed --cases {a.cases!r} (use e.g. 41-60 or 01,07)")
    res = score_dirs(a.pred, a.gold, cases, types)
    print(f"cases scored: {len(res['cases'])}")
    for t, c in sorted(res["by_type"]["exact"].items()):
        print(f"  {t:<15} {_fmt(c)}")
    if a.report:
        write_report(a.report, res)
    print(f"normalized: {res['normalized'].f1:.4f}")
    print(f"score: {res['exact'].f1:.4f}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
