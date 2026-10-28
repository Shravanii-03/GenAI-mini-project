import re
import sys

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

src, out, title = sys.argv[1], sys.argv[2], sys.argv[3]
NAVY, TEAL, GREY = colors.HexColor("#1f3a5f"), colors.HexColor("#2a7f8e"), colors.HexColor("#6b7280")
ss = getSampleStyleSheet()
body = ParagraphStyle("b", parent=ss["Normal"], fontName="Helvetica", fontSize=10.2, leading=14.6, spaceAfter=6)
h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=15, textColor=NAVY, spaceBefore=14, spaceAfter=6)
h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=11.5, textColor=TEAL, spaceBefore=9, spaceAfter=3)
tt = ParagraphStyle("t", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=22, textColor=NAVY, alignment=0, leading=26, spaceAfter=8)
bullet = ParagraphStyle("bl", parent=body, leftIndent=16, bulletIndent=3, spaceAfter=3)
quote = ParagraphStyle("q", parent=body, leftIndent=12, rightIndent=6, backColor=colors.HexColor("#eef3f8"), borderPadding=7,
                       borderColor=TEAL, borderWidth=0.5, spaceBefore=4, spaceAfter=10, fontName="Helvetica-Oblique")
small = ParagraphStyle("s", parent=body, fontSize=9, textColor=GREY, fontName="Helvetica-Oblique")
cell = ParagraphStyle("c", parent=body, fontSize=8.8, leading=11.5, spaceAfter=0)
cellb = ParagraphStyle("cb", parent=cell, fontName="Helvetica-Bold", textColor=colors.white)


def inline(text):
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"`([^`]+)`", r'<font face="Courier" size="9">\1</font>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![*\w])\*([^*]+)\*(?![*\w])", r"<i>\1</i>", text)
    return text


story, lines, i = [], open(src, encoding="utf-8").read().splitlines(), 0
while i < len(lines):
    line = lines[i]
    if not line.strip():
        i += 1
    elif line.startswith("# "):
        story.append(Paragraph(inline(line[2:]), tt)); i += 1
    elif line.startswith("## "):
        story.append(Paragraph(inline(line[3:]), h1)); i += 1
    elif line.startswith("### "):
        story.append(Paragraph(inline(line[4:]), h2)); i += 1
    elif line.startswith("> "):
        block = []
        while i < len(lines) and lines[i].startswith(">"):
            block.append(lines[i][1:].strip()); i += 1
        for para in " ".join(block).split("  ") if False else [b for b in "\n".join(block).split("\n\n") if b.strip()] or ["".join(block)]:
            story.append(Paragraph(inline(para.replace("\n", " ")), quote))
    elif line.startswith("|"):
        rows = []
        while i < len(lines) and lines[i].startswith("|"):
            cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
            if not all(set(c) <= set("-: ") for c in cells):
                rows.append(cells)
            i += 1
        data = [[Paragraph(inline(c), cellb if r == 0 else cell) for c in row] for r, row in enumerate(rows)]
        width = (A4[0] - 4 * cm)
        t = Table(data, colWidths=[width * 0.22, width * 0.78] if len(rows[0]) == 2 else None, repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d1d9")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        story += [t, Spacer(1, 8)]
    elif re.match(r"^(- |\d+\. )", line):
        marker = "-" if line.startswith("- ") else line.split(".")[0] + "."
        text = line[2:] if line.startswith("- ") else line.split(". ", 1)[1]
        i += 1
        while i < len(lines) and lines[i].startswith("  ") and lines[i].strip():
            text += " " + lines[i].strip(); i += 1
        story.append(Paragraph(inline(text), bullet, bulletText=marker))
    elif line.startswith("---"):
        story.append(HRFlowable(width="100%", color=colors.HexColor("#c9d1d9"))); i += 1
    elif line.startswith("*") and line.rstrip().endswith("*") and not line.startswith("**"):
        story.append(Paragraph(inline(line.strip()), small)); i += 1
    else:
        para = line.strip(); i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#|>|\||- |\d+\. |---)", lines[i]):
            para += " " + lines[i].strip(); i += 1
        story.append(Paragraph(inline(para), body))


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(GREY)
    canvas.drawString(2 * cm, 1.2 * cm, title)
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Page {doc.page}")
    canvas.restoreState()


SimpleDocTemplate(out, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm, bottomMargin=2 * cm,
                  title=title).build(story, onFirstPage=footer, onLaterPages=footer)
print("built", out)
