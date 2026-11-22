"""Generic case step. Relations between document classes come from `recipes/case/relations.yaml`; nothing here names a class.

relation:
  name       text of the resulting Check
  a, b       {class, path}: where the values live (path language: see paths.py)
  compare    digits | text | contains   (contains: each `a` value occurs in the `b` text)
  quantifier a_in_b (default) | b_in_a | any   which values must be found on the other side
  soft       true: a miss gives ok=None (not applicable) instead of False
  validator  optional checksum validator name (nip, regon, krs, pesel, iban) enabling repairs
  repair     true: replace a value that fails the validator (or has low confidence) with the other document's
             checksum-valid value when both differ only by OCR-confusable characters; recorded in the evidence

A check is emitted only when both classes are present in the case, so a single-document case yields no checks.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ..engine.normalise import VALIDATORS
from ..model import CaseResult, Check, DocumentResult, Evidence
from .paths import assign, expand

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "recipes" / "case" / "relations.yaml"
_PL = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


@lru_cache(maxsize=4)
def _load(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def load_config(path: str | Path | None = None) -> dict:
    return _load(str(path or CONFIG_PATH))


def _fold(s: Any) -> str:
    s = unicodedata.normalize("NFKD", str(s).translate(_PL).casefold())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", s))


def _norm(v: Any, mode: str) -> str:
    if mode == "digits":
        return re.sub(r"\D", "", str(v))
    return _fold(v)


def _confusable_pairs(cfg: dict) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for group in cfg.get("confusable", []):
        for x in group:
            for y in group:
                if x != y:
                    pairs.add((x, y))
    return pairs


def _confusable_equal(x: str, y: str, pairs: set[tuple[str, str]], max_diff: int) -> bool:
    if len(x) != len(y) or x == y:
        return False
    diff = [(a, b) for a, b in zip(x, y) if a != b]
    return len(diff) <= max_diff and all((a, b) in pairs for a, b in diff)


def _values(docs: list[DocumentResult], spec: dict) -> list[tuple[DocumentResult, str, Any]]:
    out = []
    for d in docs:
        if d.classification.doc_class == spec["class"] and d.extraction is not None:
            for p, v in expand(d.extraction.data, spec["path"]):
                if isinstance(v, (str, int, float)) and not isinstance(v, bool) and str(v).strip():
                    out.append((d, p, v))
    return out


def _has_class(docs: list[DocumentResult], cls: str) -> bool:
    return any(d.classification.doc_class == cls and d.extraction is not None for d in docs)


def _confidence(d: DocumentResult, path: str) -> float:
    cs = [e.confidence for e in d.extraction.evidence if e.path == path and e.rule != "case.repair"]
    return min(cs) if cs else 1.0


_LEGAL = {"sp", "z", "o", "oo", "s", "a", "k", "j", "p", "spolka", "ka", "sa", "ska", "spk", "spj", "spp", "sc"}


def _contains(x: Any, text: Any) -> bool:
    """`x` occurs in `text`: folded phrase, an ISO date in d.m.Y style, or (names) all significant tokens
    (legal-form abbreviations ignored, so "Acme sp. z o.o." matches "ACME")."""
    hay, nx = f" {_fold(text)} ", _fold(x)
    if not nx:
        return False
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", str(x).strip())
    if m:
        y, mo, d = m.groups()
        return any(f" {_fold(f'{dd}{sep}{mm}{sep}{y}')} " in hay for dd in (d, d.lstrip("0")) for mm in (mo, mo.lstrip("0"))
                   for sep in (".", "-", "/")) or f" {y} {mo} {d} " in hay
    if f" {nx} " in hay:
        return True
    toks = [t for t in nx.split() if t not in _LEGAL]
    return len(toks) >= 2 and all(f" {t} " in hay for t in toks)


def _matches(x: Any, others: list[Any], mode: str) -> bool:
    if mode == "contains":
        return any(_contains(x, o) for o in others)
    nx = _norm(x, mode)
    return bool(nx) and any(nx == _norm(o, mode) for o in others)


def _evaluate(rel: dict, a_vals, b_vals) -> Check:
    name, mode = rel["name"], rel.get("compare", "text")
    if not a_vals or not b_vals:
        return Check(name, None, "no value on " + ("both sides" if not a_vals and not b_vals else "one side"))
    a, b = [v for _, _, v in a_vals], [v for _, _, v in b_vals]
    q = rel.get("quantifier", "a_in_b")
    if mode == "contains" or q == "a_in_b":
        miss = [str(x) for x in a if not _matches(x, b, mode)]
    elif q == "b_in_a":
        miss = [str(x) for x in b if not _matches(x, a, mode)]
    else:
        miss = [] if any(_matches(x, b, mode) for x in a) else [str(x) for x in a]
    if miss and rel.get("soft"):  # e.g. a title that need not name the party (stamp duty vs entry fee)
        return Check(name, None, "not mentioned: " + "; ".join(miss))
    if miss:
        return Check(name, False, "not found on the other side: " + "; ".join(miss))
    return Check(name, True, f"{len(a)} value(s) agree")


def _repair(rel: dict, cfg: dict, a_vals, b_vals, pairs) -> int:
    """Replace a failing/low-confidence identifier with the other side's checksum-valid, confusable-equal value."""
    validator = VALIDATORS.get(rel.get("validator", ""))
    if not (rel.get("repair") and validator and rel.get("compare") == "digits"):
        return 0
    low, max_diff = cfg.get("low_confidence", 0.6), cfg.get("max_substitutions", 2)
    n = 0
    for mine, others in ((a_vals, b_vals), (b_vals, a_vals)):
        for doc, path, value in mine:
            cur = _norm(value, "digits")
            if validator(cur) and _confidence(doc, path) >= low:
                continue
            if any(cur == _norm(v, "digits") for _, _, v in others):
                continue
            cands = {_norm(v, "digits") for _, _, v in others if validator(_norm(v, "digits"))}
            cands = {c for c in cands if _confusable_equal(cur, c, pairs, max_diff)}
            if len(cands) != 1:
                continue
            new = cands.pop()
            if not assign(doc.extraction.data, path, new if isinstance(value, str) else int(new)):
                continue
            doc.extraction.evidence.append(Evidence(
                path, new, snippet=f"repaired {value!r} -> {new!r} from {rel['name']}", rule="case.repair",
                confidence=0.9))
            n += 1
    return n


def run_case(docs: list[DocumentResult], cfg: dict | None = None) -> list[Check]:
    """Evaluate every configured relation, repairing identifiers first. Mutates `docs` only through repairs."""
    cfg = cfg if cfg is not None else load_config()
    pairs = _confusable_pairs(cfg)
    checks: list[Check] = []
    for rel in cfg.get("relations", []):
        if not (_has_class(docs, rel["a"]["class"]) and _has_class(docs, rel["b"]["class"])):
            continue
        a_vals, b_vals = _values(docs, rel["a"]), _values(docs, rel["b"])
        if _repair(rel, cfg, a_vals, b_vals, pairs):
            a_vals, b_vals = _values(docs, rel["a"]), _values(docs, rel["b"])
        checks.append(_evaluate(rel, a_vals, b_vals))
    return checks


def apply_case(result: CaseResult) -> CaseResult:
    """Pipeline hook: fill `result.checks` (and apply repairs to the documents in place)."""
    result.checks = run_case(result.documents)
    return result
