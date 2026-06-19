import re
tex = open('paper/sn-article.tex', encoding='utf-8').read()
bib = open('paper/sn-bibliography.bib', encoding='utf-8').read()
bibkeys = set(re.findall(r'@\w+\{([A-Za-z0-9_]+)\s*,', bib))
cited = set()
for m in re.findall(r'\\cite\{([^}]+)\}', tex):
    for k in m.split(','):
        cited.add(k.strip())
print("bib entries:", len(bibkeys))
print("distinct cited keys:", len(cited))
print("undefined (cited, not in bib):", sorted(cited - bibkeys))
print("uncited (in bib, never cited):", sorted(bibkeys - cited))
