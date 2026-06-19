# Build an ACM acmart (acmsmall) version of the paper from sn-article.tex.
# Body, tables, figures, equations, algorithm and bibliography port unchanged;
# only the preamble, title block, abstract/keywords, back-matter and \botrule->\bottomrule differ.
import re, io

src = open('sn-article.tex', encoding='utf-8').read()

# --- extract abstract text from \abstract{...} (single line) ---
m = re.search(r'\\abstract\{', src)
i = m.end()
depth = 1
buf = []
while depth:
    c = src[i]
    if c == '{': depth += 1
    elif c == '}': depth -= 1
    if depth: buf.append(c)
    i += 1
abstract = ''.join(buf).strip()

# --- body: from \section{Introduction} up to \backmatter ---
body = src[src.index(r'\section{Introduction}'):src.index(r'\backmatter')].rstrip()

# --- appendix inner: between \begin{appendices} and \end{appendices} ---
ap = src[src.index(r'\begin{appendices}')+len(r'\begin{appendices}'):src.index(r'\end{appendices}')].strip()

# sn-jnl \botrule -> booktabs \bottomrule
body = body.replace(r'\botrule', r'\bottomrule')
ap   = ap.replace(r'\botrule', r'\bottomrule')

preamble = r'''\documentclass[acmsmall]{acmart}

\let\Bbbk\relax % avoid clash: acmart already defines \Bbbk
\usepackage{amssymb,amsfonts}
\usepackage{multirow}
\usepackage{algorithm}
\usepackage{algpseudocode}
\usepackage{tikz}
\usetikzlibrary{arrows.meta,positioning,fit,backgrounds,calc,shapes.geometric}

%% ACM journal metadata --- set to the target venue on submission.
\acmJournal{TOSEM}
\acmYear{2026}
\acmVolume{1}
\acmNumber{1}
\acmArticle{1}
\acmMonth{1}
\acmDOI{}
\copyrightyear{2026}
\setcopyright{rightsretained}
\settopmatter{printacmref=true}

\begin{document}

\title{Does Observability Matter in Cloud-Native Systems? An Empirical Study on Real-Time Anomaly Detection}

\author{Ngoc Duc Anh Nguyen}
\affiliation{%
  \institution{Leeds Beckett University}
  \city{Leeds}
  \country{UK}}
\email{N.Nguyen3896@student.leedsbeckett.ac.uk}

\author{Satish Kumar}
\affiliation{%
  \institution{Leeds Beckett University}
  \city{Leeds}
  \country{UK}}
\email{s.kumar@leedsbeckett.ac.uk}

\author{Nawar Jawad}
\affiliation{%
  \institution{Leeds Beckett University}
  \city{Leeds}
  \country{UK}}
\email{n.jawad@leedsbeckett.ac.uk}

\renewcommand{\shortauthors}{Nguyen et al.}

\begin{abstract}
__ABSTRACT__
\end{abstract}

\begin{CCSXML}
<ccs2012>
 <concept>
  <concept_id>10011007.10011074.10011099</concept_id>
  <concept_desc>Software and its engineering~Software reliability</concept_desc>
  <concept_significance>500</concept_significance>
 </concept>
 <concept>
  <concept_id>10010147.10010257.10010258.10010259</concept_id>
  <concept_desc>Computing methodologies~Supervised learning by classification</concept_desc>
  <concept_significance>500</concept_significance>
 </concept>
 <concept>
  <concept_id>10010147.10010178.10010179.10003352</concept_id>
  <concept_desc>Computing methodologies~Online learning settings</concept_desc>
  <concept_significance>500</concept_significance>
 </concept>
 <concept>
  <concept_id>10003456.10010927</concept_id>
  <concept_desc>Social and professional topics~Computing / technology policy</concept_desc>
  <concept_significance>100</concept_significance>
 </concept>
</ccs2012>
\end{CCSXML}
\ccsdesc[500]{Software and its engineering~Software reliability}
\ccsdesc[500]{Computing methodologies~Supervised learning by classification}
\ccsdesc[500]{Computing methodologies~Online learning settings}

\keywords{Observability, anomaly detection, concept drift, online learning, cloud-native systems, machine learning, microservices}

\maketitle
'''.replace('__ABSTRACT__', abstract)

backmatter = r'''
\begin{acks}
The authors thank colleagues at the School of Built Environment, Engineering and Computing, Leeds Beckett University, for discussion and feedback. No specific grant funded this work, and the authors declare no competing interests. The research involves no human participants or personal data; all data are generated on a self-contained testbed with fault injection confined to an isolated environment, in line with Leeds Beckett University research-ethics guidance. The testbed configuration and the result datasets supporting the findings are available from the authors on reasonable request.
\end{acks}

\bibliographystyle{ACM-Reference-Format}
\bibliography{sn-bibliography}

\appendix
''' + ap + '\n\n\\end{document}\n'

open('acm-article.tex', 'w', encoding='utf-8').write(preamble + '\n' + body + '\n' + backmatter)
print('wrote acm-article.tex')
print('abstract chars:', len(abstract))
print('body chars:', len(body))
print('appendix chars:', len(ap))
print('bottomrule count:', (preamble+body+backmatter).count(r'\bottomrule'))
