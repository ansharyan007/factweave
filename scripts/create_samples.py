"""Generate synthetic demonstration PDFs. Not the assignment's missing starter data."""
from pathlib import Path
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
SAMPLES.mkdir(exist_ok=True)


def make(name, title, sentences, scanned=False):
    c = canvas.Canvas(str(SAMPLES / name), pagesize=(612, 792))
    c.setTitle(title + " - synthetic demonstration")
    c.setFillColor(colors.HexColor("#174D40"))
    c.rect(0, 680, 612, 112, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 25)
    c.drawString(48, 733, title)
    c.setFont("Helvetica", 11)
    c.drawString(48, 706, "FACTWEAVE / SYNTHETIC DEMONSTRATION DATA")
    y = 630
    for sentence in sentences:
        c.setFillColor(colors.HexColor("#233A33"))
        c.setFont("Helvetica", 12)
        # Wrap only at spaces; keep every claim in its own block.
        words, line = sentence.split(), ""
        for word in words:
            if c.stringWidth(line + " " + word, "Helvetica", 12) > 510:
                c.drawString(48, y, line)
                y -= 18
                line = word
            else:
                line = (line + " " + word).strip()
        c.drawString(48, y, line)
        y -= 65
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#718078"))
    c.drawString(48, 45, "Fictional companies and figures. Created to exercise the general extraction pipeline.")
    if scanned:
        c.showPage()
        image = Image.new("RGB", (1200, 1500), "white")
        draw = ImageDraw.Draw(image)
        try:
            font = ImageFont.truetype("arial.ttf", 31)
        except OSError:
            font = ImageFont.load_default(size=31)
        draw.text((80, 100), "SYNTHETIC SCANNED APPENDIX", fill="#174D40", font=font)
        draw.text((80, 250), "Aster Labs' operating profit was USD 3 million in FY2024.", fill="black", font=font)
        draw.text((80, 400), "This page intentionally contains pixels only.", fill="black", font=font)
        buffer = BytesIO()
        image.save(buffer, "PNG")
        buffer.seek(0)
        c.drawImage(ImageReader(buffer), 0, 0, width=612, height=765)
    c.save()


if __name__ == "__main__":
    make("01_annual_review.pdf", "Annual review", [
        "Aster Labs reported revenue of USD 12 million in FY2024.",
        "Aster Labs employed 240 employees in FY2024.",
        "Aster Labs' registered address was 18 Cedar Road, Pune in FY2024.",
        "Aster Labs' energy use was 2 MWh in FY2024.",
        "Aster Labs' recycling rate was 72 percent in FY2024.",
    ])
    make("02_investor_update.pdf", "Investor update", [
        "Aster Labs recorded sales of USD 12,000,000 in FY2024.",
        "Aster Labs' headcount was 275 in FY2024.",
        "Aster Labs' registered office was 18 Cedar Rd, Pune in FY2024.",
        "Aster Labs' energy use was 2000 kWh in FY2024.",
        "Aster Labs' recycling rate was 72% in FY2024.",
    ])
    make("03_context_and_scan.pdf", "Context and caveats", [
        "Aster Labs reported revenue of USD 9 million in FY2023.",
        "Aster Labs reported standalone revenue of USD 8 million in FY2024.",
        "Aster Labs reported consolidated revenue of USD 12 million in FY2024.",
        "Aster Labs' revenue was USD 9 million and USD 12 million in FY2023 and FY2024 respectively.",
    ], scanned=True)
    print("Created 3 synthetic sample PDFs in samples/.")
