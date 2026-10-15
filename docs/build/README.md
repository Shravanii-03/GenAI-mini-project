# Building the PDFs

These scripts were used to produce `docs/PROJECT_EXPLAINED.pdf` and `docs/INTERVIEW_GUIDE.pdf`. They need `reportlab`, `matplotlib` and `Pillow`
(the system Python on the author's machine has them; the project venv does not).

    python docs/build/make_figs.py                   # figures into docs/figs
    python docs/build/make_pdf.py                    # docs/PROJECT_EXPLAINED.pdf
    python docs/build/md_to_pdf.py docs/INTERVIEW_GUIDE.md docs/INTERVIEW_GUIDE.pdf "Project interview guide"

The paths inside `make_figs.py` and `make_pdf.py` are absolute (`C:\Users\Shimona\Documents\GenAI_project`); edit them if the repository moves.
If the experiment numbers change, update the values near the top of `make_figs.py` and the tables in `make_pdf.py` from `experiments/RESULTS.md`.
