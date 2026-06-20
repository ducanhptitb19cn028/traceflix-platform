#!/usr/bin/env python3
"""Parse new_rqs_refs.bib and emit LBU-Harvard in-text + full reference entries.

Writes lbu_refs.json:  {citekey: {"intext": "...", "short": "...", "full": "..."}}
and lbu_reference_list.txt (alphabetical full list).
"""
import json
import re
from pathlib import Path

BIB = Path("D:/ResearchWithDrSatish/traceflix-platform/aiops/docs/new_rqs_refs.bib")
OUT = Path("D:/ResearchWithDrSatish/traceflix-platform/dissertation")

# --- LaTeX -> unicode/plain cleanup ---
PARTICLES = {"van", "von", "de", "der", "den", "da", "di", "del", "la", "'t", "vande"}


def deTeX(s: str) -> str:
    # accent commands of form \c{x}, \'{x}, \"{x}, \~{x}, \^{x}, \`{x}, \v{x}, \H{x}, \={x}, \.{x}
    s = re.sub(r"\\[`'\"~^=.cvHurd]\{(\w)\}", r"\1", s)
    s = re.sub(r"\\[`'\"~^=.]([A-Za-z])", r"\1", s)
    s = re.sub(r"\\[ij]\b", lambda m: m.group(0)[1], s)   # \i -> i, \j -> j (dotless)
    s = re.sub(r"\\[lL]\b", lambda m: m.group(0)[1], s)
    s = s.replace("{", "").replace("}", "")
    s = re.sub(r"\\[a-zA-Z]+", "", s)
    s = s.replace("\\", "")
    s = s.replace("--", "–")                          # en-dash for ranges in titles
    return re.sub(r"\s+", " ", s).strip()


def parse_entries(text):
    entries = []
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,]+),", text):
        kind, key = m.group(1).lower(), m.group(2).strip()
        start = m.end()
        depth, i = 1, m.start() + text[m.start():].index("{") + 1
        # find matching close brace from the entry's opening brace
        ob = text.index("{", m.start())
        depth, i = 1, ob + 1
        while i < len(text) and depth:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        body = text[ob + 1:i - 1]
        fields = {}
        for fm in re.finditer(r"(\w+)\s*=\s*", body):
            fkey = fm.group(1).lower()
            j = fm.end()
            if body[j] == "{":
                d, k = 1, j + 1
                while k < len(body) and d:
                    if body[k] == "{":
                        d += 1
                    elif body[k] == "}":
                        d -= 1
                    k += 1
                fields[fkey] = body[j + 1:k - 1].strip()
            else:
                k = body.index(",", j) if "," in body[j:] else len(body)
                m2 = re.match(r"\s*([^,\n]+)", body[j:])
                fields[fkey] = m2.group(1).strip() if m2 else ""
        if "author" in fields and "title" in fields:
            entries.append((kind, key, fields))
    return entries


def split_authors(auth):
    return [a.strip() for a in re.split(r"\s+and\s+", auth) if a.strip()]


def surname_initials(name):
    name = deTeX(name)
    if "," in name:                       # "Surname, First"
        sur, rest = [p.strip() for p in name.split(",", 1)]
        firsts = rest.split()
    else:                                  # "First M. Surname"
        parts = name.split()
        # pull leading lowercase particles (van, von, de, 't, ...) into the surname
        k = len(parts) - 1
        while k > 1 and parts[k - 1].lower() in PARTICLES:
            k -= 1
        sur, firsts = " ".join(parts[k:]), parts[:k]
    inits = " ".join(f"{p[0]}." for p in firsts if p and p[0].isalpha())
    return sur, inits


def fmt_authorlist(names):
    pairs = [surname_initials(n) for n in names]
    formatted = [f"{s}, {i}" if i else s for s, i in pairs]
    if len(formatted) == 1:
        return formatted[0]
    return ", ".join(formatted[:-1]) + " and " + formatted[-1]


def intext(names, year):
    surs = [surname_initials(n)[0] for n in names]
    if len(surs) == 1:
        lead = surs[0]
    elif len(surs) == 2:
        lead = f"{surs[0]} and {surs[1]}"
    else:
        lead = f"{surs[0]} et al."
    return lead, f"({lead}, {year})"


def doi_url(f):
    if "doi" in f:
        return f"https://doi.org/{f['doi']}"
    if "url" in f:
        return f["url"]
    return None


def full_ref(kind, f):
    names = split_authors(f["author"])
    authors = fmt_authorlist(names)
    year = f.get("year", "n.d.")
    title = deTeX(f["title"])
    url = doi_url(f)
    journal = deTeX(f.get("journal", ""))
    is_arxiv = "arxiv" in journal.lower()
    parts = [f"{authors} ({year}) '{title}',"]
    if kind == "inproceedings" or "booktitle" in f:
        venue = deTeX(f.get("booktitle", ""))
        seg = f" in {venue}."
        if "pages" in f:
            seg = seg[:-1] + f", pp. {f['pages'].replace('--', '-')}."
        parts.append(seg)
    elif is_arxiv:
        parts.append(" arXiv preprint.")
    else:
        seg = f" {journal}"
        if f.get("volume"):
            seg += f", {f['volume']}"
            if f.get("number"):
                seg += f"({f['number']})"
        if f.get("pages"):
            seg += f", pp. {f['pages'].replace('--', '-')}"
        seg += "."
        parts.append(seg)
    ref = "".join(parts)
    if url:
        ref += f" Available at: {url} (Accessed: 19 June 2026)."
    return re.sub(r"\s+", " ", ref).strip()


def main():
    text = BIB.read_text(encoding="utf-8")
    entries = parse_entries(text)
    out = {}
    rows = []
    for kind, key, f in entries:
        names = split_authors(f["author"])
        year = f.get("year", "n.d.")
        lead, cite = intext(names, year)
        full = full_ref(kind, f)
        out[key] = {"intext": cite, "short": lead, "year": year, "full": full}
        rows.append((surname_initials(names[0])[0].lower() + year, full))
    rows.sort()
    (OUT / "lbu_refs.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    (OUT / "lbu_reference_list.txt").write_text(
        "\n\n".join(r[1] for r in rows), encoding="utf-8")
    print(f"parsed {len(entries)} entries -> lbu_refs.json + lbu_reference_list.txt\n")
    for r in rows[:4]:
        print("  •", r[1][:130], "...")
    print(f"\nsample in-text: {out[list(out)[0]]['intext']}")


if __name__ == "__main__":
    main()
