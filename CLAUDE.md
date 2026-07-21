# CLAUDE.md

## Harness: Deep Research

**Goal:** Investigate any topic from three independent angles (web, academic,
community), cross-validate the findings, and produce a comprehensive, cited report
with calibrated confidence.

**Trigger:** For any request to deep-research / investigate / thoroughly research a
topic, produce a comprehensive report, or assess the evidence/consensus/sentiment on
something — use the `deep-research` orchestrator skill. It fans out to the
`web-researcher`, `academic-researcher`, and `community-analyst` agents (parallel),
then `cross-validator`, then `report-writer`. Simple one-off lookups can be answered
directly without the harness.

**Execution mode:** sub-agent (Agent tool, parallel via `run_in_background`); agents
coordinate through files in `_workspace/deep-research/<slug>/`. All agents use
`model: "opus"`.

**Change log:**
| Date | Change | Target | Reason |
|------|--------|--------|--------|
| 2026-06-18 | Initial build (5 agents, 6 skills) | whole harness | — |

## Harness: Paper & Dissertation

**Goal:** Keep the IEEE journal paper and the two MSc dissertations (LaTeX
`Alex_Dissertation` + Word `.docx`) correct, readable, human-sounding, in-register,
consistent with each other, and rubric-ready — and produce the defence deck from them.

**Trigger:** This is a **skill-triggered suite, not a fan-out orchestration** — there is
no single orchestrator agent. Each skill self-triggers on its own description; invoke the
one matching the task:
- Compile / trim / page-limit the paper → `paper` (owns the 20-page limit)
- Section-by-section quality pass on the LaTeX dissertation → `dissertation`
- Clarity / coherence / grammar of paper + dissertations → `clarify`
- Define-before-you-name terminology audit → `explain-before-naming`
- De-slop prose (paper + Word `.docx`) → `non-ai-humanizer`; LaTeX dissertation only →
  `non-ai-humanizer-dissertation`
- Grade the dissertation against the LBU rubric → `mark-dissertation`
- Grade the presentation video + Q&A against its LBU rubric (honest/confess mode) →
  `mark-presentation`
- Mirror a paper edit → LaTeX dissertation → `sync-paper-alexdissertation`; → Word
  `.docx` → `sync-paper-dissertation`; → viva deck/pptx → `sync-paper-pptx`
- Build the deck + speaker script (first time / big restructure) → `pptx-script`
- Keep the paper and its presentation deck/script clear + consistent with each other →
  `sync-paper-script`

The skills cross-reference each other via `[[links]]`; follow those hand-offs (e.g.
trimming in `paper` calls `clarify`, then the two `sync-*` skills). No dedicated agent
definitions — these run in the main thread.

**Change log:**
| Date | Change | Target | Reason |
|------|--------|--------|--------|
| 2026-07-19 | Registered existing suite (10 skills, built over Jul 2026) | this section | Drift: suite existed in `.claude/skills/` but was undocumented in CLAUDE.md |
| 2026-07-20 | Added `sync-paper-script` (+ `check_deck_script.py`) | presentation coherence | No skill kept the paper and its viva deck/script clear + consistent with each other |
| 2026-07-20 | Added `mark-presentation` (+ `fill_presentation_sheet.py`) | presentation grading | Presentation+Q&A rubric had no marking skill; marks materials honestly in confess mode (no video/live Q&A observed) |
| 2026-07-20 | `mark-presentation`: added top-of-band (85–90+) standard + clarity/brevity principle | presentation grading | Mark toward the ceiling; short/clear/self-contained materials that pre-empt clarification are a genuine top-band signal — target *no clarification, only depth*, earned not awarded |
| 2026-07-20 | Added `sync-paper-pptx` (+ `refresh_figure.sh`) | paper→deck mirror | The deck was the one paper-mirror target with no dedicated *mechanical* sync (dissertations had `sync-paper-alexdissertation`/`-dissertation`); `sync-paper-script` owns whole-talk coherence, not per-edit propagation. New skill owns the deck's unique need: TikZ→PNG figure refresh (a diagram change can't be pasted as it can into the LaTeX targets). Boundary: mechanical per-edit mirror here → hands whole-talk coherence/timing to `sync-paper-script` |
| 2026-07-20 | `sync-paper-dissertation`: added the `.docx` figure pipeline (+ `swap_docx_figure.py`) | paper→.docx figure mirror | Skill mirrored prose only; a changed paper *diagram* had no path into the `.docx` (figures are raster PNGs in `word/media/`, not prose XML). New helper rasterises the paper TikZ and swaps the embedded image by caption, aspect-preserved — the Word counterpart of `sync-paper-pptx`'s TikZ→PNG refresh. The `.docx` takes the paper's *full* figure (not the deck's simplified one) |
