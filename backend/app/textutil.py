import re
import unicodedata

_WORD = re.compile(r"[a-z0-9][a-z0-9+#./-]*")
STOP = set("""a an and are as at be by for from has have in into is it its of on or that the to was were with
will this these those our your their his her i we you they them he she also using used via per over under""".split())

# numbers incl. 1,200 / 3.5 / 40% / $2M / 2k / S$120k
_NUM = re.compile(r"(?<![a-z])(\d[\d,]*(?:\.\d+)?)\s*(%|percent|k|m|mm|bn|b|million|billion|thousand|x)?(?![a-z])", re.I)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = s.replace("–", "-").replace("—", "-").replace("’", "'")
    return re.sub(r"\s+", " ", s).strip()


def tokens(s: str, drop_stop: bool = True) -> list[str]:
    out = [t.strip(".-/") for t in _WORD.findall(norm(s))]
    return [t for t in out if t and (not drop_stop or t not in STOP)]


def support_score(snippet: str, source: str) -> float:
    """Fraction of snippet content tokens present in source."""
    st = tokens(snippet)
    if not st:
        return 1.0
    src = set(tokens(source))
    return sum(1 for t in st if t in src) / len(st)


_MULT = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}


def numbers(s: str) -> set[str]:
    """Canonicalised numeric claims in text. Years (1950-2099) are excluded; dates are checked separately."""
    out: set[str] = set()
    for m in _NUM.finditer(norm(s)):
        raw, unit = m.group(1).replace(",", ""), (m.group(2) or "").lower()
        try:
            v = float(raw)
        except ValueError:
            continue
        if not unit and 1950 <= v <= 2099 and "." not in raw:
            continue
        if unit in ("%", "percent"):
            out.add(f"{v:g}%")
        elif unit == "x":
            out.add(f"{v:g}x")
        else:
            out.add(f"{v * _MULT.get(unit, 1):g}")
    return out


def jaccard(a: str, b: str) -> float:
    A, B = set(tokens(a)), set(tokens(b))
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", norm(s)).strip("-")[:60] or "x"
