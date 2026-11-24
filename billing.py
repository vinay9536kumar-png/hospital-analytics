"""Builds a printable PDF bill for one hospital visit (uses reportlab)."""
import io
from datetime import date
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

import db


def money(value):
    return f"Rs. {value:,.2f}"


def make_bill_pdf(visit_id, hospital_name, hospital_address="", hospital_phone=""):
    header = db.get_visit_header(visit_id)
    if header is None:
        raise ValueError("Visit not found")
    items = db.get_bill_items(visit_id)
    summary = db.bill_summary(visit_id)

    styles = getSampleStyleSheet()
    title = ParagraphStyle("title", parent=styles["Title"], fontSize=20, spaceAfter=2)
    center = ParagraphStyle("center", parent=styles["Normal"], alignment=1, fontSize=9)
    normal = ParagraphStyle("normal", parent=styles["Normal"], fontSize=10, leading=14)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8,
                           textColor=colors.grey, alignment=1)

    def p(text, style=normal):
        return Paragraph(escape(str(text)), style)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"Bill {visit_id}", author=hospital_name,
    )
    story = [p(hospital_name, title)]
    if hospital_address:
        story.append(p(hospital_address, center))
    if hospital_phone:
        story.append(p(f"Phone: {hospital_phone}", center))
    story += [Spacer(1, 8), p("BILL / INVOICE", ParagraphStyle("h", parent=center, fontSize=12,
                                                fontName="Helvetica-Bold")), Spacer(1, 8)]

    info = [
        [p(f"Bill No: BILL-{visit_id:06d}"), p(f"Date: {date.today().strftime('%d-%m-%Y')}")],
        [p(f"Patient: {header['name']}"), p(f"Patient ID: {header['patient_id']}")],
        [p(f"Age / Gender: {header['age']} / {header['gender']}"),
         p(f"Phone: {header['phone'] or '-'}")],
        [p(f"Visit type: {header['visit_type']}"), p(f"Department: {header['department']}")],
        [p(f"Diagnosis: {header['disease']}"), p(f"Doctor: {header['doctor'] or '-'}")],
        [p(f"Admit / visit date: {header['admit_date']}"),
         p(f"Discharge date: {header['discharge_date'] or 'Not discharged yet'}")],
    ]
    info_table = Table(info, colWidths=[87 * mm, 87 * mm])
    info_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story += [info_table, Spacer(1, 10)]

    rows = [["#", "Category", "Description", "Qty", "Rate", "Amount"]]
    for n, row in enumerate(items.itertuples(), 1):
        rows.append([
            str(n), p(row.category), p(row.description),
            f"{row.quantity:g}", money(row.unit_price), money(row.amount),
        ])
    if items.empty:
        rows.append(["", "", p("No charges added"), "", "", ""])
    table = Table(rows, colWidths=[9 * mm, 30 * mm, 58 * mm, 14 * mm, 30 * mm, 33 * mm],
                  repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4e79")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f6fa")]),
    ]))
    story += [table, Spacer(1, 10)]

    totals = [
        ["Subtotal", money(summary["subtotal"])],
        ["Discount", "- " + money(summary["discount"])],
        ["Total amount", money(summary["total"])],
        [f"Paid ({summary['payment_mode']})", money(summary["paid"])],
        ["Balance due", money(summary["balance"])],
    ]
    totals_table = Table(totals, colWidths=[45 * mm, 40 * mm], hAlign="RIGHT")
    totals_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("FONTNAME", (0, 4), (-1, 4), "Helvetica-Bold"),
        ("LINEABOVE", (0, 2), (-1, 2), 0.8, colors.black),
        ("LINEABOVE", (0, 4), (-1, 4), 0.8, colors.black),
    ]))
    story += [totals_table, Spacer(1, 6), p(f"Payment status: {summary['status']}"),
              Spacer(1, 24), p("This is a computer generated bill.", small)]

    doc.build(story)
    return buffer.getvalue()