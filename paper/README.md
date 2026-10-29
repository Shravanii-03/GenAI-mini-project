# Paper draft

`main.tex` is an IEEE conference paper (IEEEtran, double-blind: no author names). It has 5 figures and 3 tables and is about
4,100 words, which should come to roughly 6.5-7.5 pages in two columns. **It has not been compiled on this machine (no TeX
installed); `check_tex.py` only checks structure** (environments, citations, references, figure files).

## Compile (Overleaf, free)
1. New project -> Upload project -> select `main.tex` and the whole `figs/` folder (keep the folder name).
2. Menu -> Compiler: pdfLaTeX. `IEEEtran` is built in; nothing to install.
3. Fix any red errors (tell me the message and I will fix the source), then check the page count.

Before submission replace the venue's template if it differs (CONECCT: use the template on its call-for-papers page), and replace
`[anonymous repository link to be inserted]` with an anonymised repository link.

## Regenerate the figures
```bash
python paper/make_figs.py        # needs matplotlib
python paper/check_tex.py        # static checks on main.tex
```
`fig_bound` numbers come from `sdv.analysis.bounds.latency_bound_ms` for the headline scenario (60 km/h, obstacle at 24 m, load 0.3)
and `latest_safe_latency_ms`; the others are copied from `experiments/RESULTS.md` (E12, E13 run 4, E15).

## Before you submit (checklist)
* Check the bibliography details against the sources (a few entries have no volume/venue because I could not verify them: the 2023
  Akowuah et al. paper, the Zhang dissertation's first name, the ROAD authors, the 2026 Applied Sciences article).
* Confirm the venue's page limit, template, double-blind rules and whether the PDF must pass IEEE PDF eXpress.
* Do not submit the same work to a second venue.
