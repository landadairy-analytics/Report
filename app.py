import hashlib
import io
import os
from datetime import datetime, timedelta
from xml.sax.saxutils import escape

import pandas as pd
import streamlit as st


class InputError(Exception):
    """Πρόβλημα στο αρχείο εισόδου, με μήνυμα κατανοητό για τον χρήστη."""

# ---- Κανόνες υπολογισμού (αλλάζουν μόνο εδώ) ----
# Κανονικό ωράριο σε ώρες: ό,τι το ξεπερνά μετράει υπερωρία, και τόσες ώρες
# μπαίνουν (ως εκτίμηση) όταν υπάρχει μόνο 1 χτύπημα στη μέρα.
STANDARD_HOURS = 10
# Χτυπήματα πριν από αυτή την ώρα (π.χ. 00:30) ανήκουν στην προηγούμενη ημέρα εργασίας.
NIGHT_CUTOFF_HOUR = 2
# Αν 2 εγγραφές της ίδιας μέρας απέχουν λιγότερο από αυτό (σε λεπτά),
# θεωρούνται ύποπτες (π.χ. διπλό χτύπημα) και δεν υπολογίζονται.
MIN_GAP_MINUTES = 30


# ----------------------------------------------------------------------
# PDF για εκτύπωση (χρειάζεται: pip install reportlab, και μια γραμματοσειρά
# με ελληνικούς χαρακτήρες)
# ----------------------------------------------------------------------
def find_greek_font():
    """Ψάχνει μια γραμματοσειρά TTF με ελληνικά. Επιστρέφει (κανονική, έντονη)."""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        base_dir = os.getcwd()
    win = os.environ.get("WINDIR", "C:\\Windows")
    pairs = [
        # δίπλα στο app.py, φάκελος fonts (αν θες να βάλεις δική σου γραμματοσειρά)
        (os.path.join(base_dir, "fonts", "DejaVuSans.ttf"),
         os.path.join(base_dir, "fonts", "DejaVuSans-Bold.ttf")),
        (os.path.join(win, "Fonts", "arial.ttf"), os.path.join(win, "Fonts", "arialbd.ttf")),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
        ("/System/Library/Fonts/Supplemental/Arial.ttf",
         "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ]
    try:
        import matplotlib

        ttf = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
        pairs.append(
            (os.path.join(ttf, "DejaVuSans.ttf"), os.path.join(ttf, "DejaVuSans-Bold.ttf"))
        )
    except Exception:
        pass
    for regular, bold in pairs:
        if os.path.exists(regular):
            return regular, (bold if os.path.exists(bold) else regular)
    return None, None


def build_pdf_report(review, manual_table, monthly, daily, n_issues, n_single, period):
    """Δημιουργεί PDF (A4 οριζόντιο) για εκτύπωση και επιστρέφει τα bytes."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        KeepTogether,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    regular, bold = find_greek_font()
    if regular is None:
        raise RuntimeError(
            "δεν βρέθηκε γραμματοσειρά με ελληνικά. Βάλε το DejaVuSans.ttf και το"
            " DejaVuSans-Bold.ttf σε φάκελο «fonts» δίπλα στο app.py"
        )
    pdfmetrics.registerFont(TTFont("GR", regular))
    pdfmetrics.registerFont(TTFont("GR-B", bold))
    pdfmetrics.registerFontFamily("GR", normal="GR", bold="GR-B", italic="GR", boldItalic="GR-B")

    page_w, page_h = landscape(A4)
    margin = 28
    width = page_w - 2 * margin

    st_title = ParagraphStyle("t", fontName="GR-B", fontSize=15, leading=19, spaceAfter=2)
    st_meta = ParagraphStyle("m", fontName="GR", fontSize=8.5, leading=11, textColor=colors.HexColor("#444444"))
    st_h2 = ParagraphStyle("h2", fontName="GR-B", fontSize=11, leading=14, spaceBefore=10, spaceAfter=4)
    st_cell = ParagraphStyle("c", fontName="GR", fontSize=8, leading=10)
    st_head = ParagraphStyle("h", fontName="GR-B", fontSize=8, leading=10)
    st_box = ParagraphStyle("b", fontName="GR", fontSize=8.5, leading=11)

    def make_table(header, rows, fracs, row_bg=None):
        data = [[Paragraph(escape(h), st_head) for h in header]]
        for r in rows:
            data.append([Paragraph(escape(str(c)), st_cell) for c in r])
        t = Table(data, colWidths=[width * f for f in fracs], repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e8eb")),
            ("LINEBELOW", (0, 0), (-1, 0), 1, colors.black),
            ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor("#bbbbbb")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]
        for i, bg in enumerate(row_bg or []):
            if bg:
                style.append(("BACKGROUND", (0, i + 1), (-1, i + 1), colors.HexColor(bg)))
        t.setStyle(TableStyle(style))
        return t

    def box(text, bg, line):
        t = Table([[Paragraph(text, st_box)]], colWidths=[width])
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg)),
                    ("LINEBEFORE", (0, 0), (0, -1), 3, colors.HexColor(line)),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        return t

    story = [
        Paragraph(escape("Αναφορά Ωρών Εργασίας & Υπερωριών"), st_title),
        Paragraph(escape(period), st_meta),
        Spacer(1, 8),
    ]

    # Ημέρες που χρειάζονται έλεγχο
    if len(review) > 0:
        if n_issues > 0:
            story += [
                box(
                    "<b>Προσοχή:</b> " + escape(
                        str(n_issues) + " ημέρες ΔΕΝ υπολογίστηκαν (πάνω από 2 εγγραφές ή 2"
                        " εγγραφές πολύ κοντά μεταξύ τους) και δεν μπήκαν στα σύνολα."
                    ),
                    "#fdecea", "#c0392b",
                ),
                Spacer(1, 4),
            ]
        if n_single > 0:
            story += [
                box(
                    "<b>Σημείωση:</b> " + escape(
                        str(n_single) + " ημέρες έχουν 1 μόνο χτύπημα και υπολογίστηκαν ως"
                        " " + str(STANDARD_HOURS) + " ώρες (εκτίμηση)."
                    ),
                    "#fff8e1", "#f39c12",
                ),
                Spacer(1, 4),
            ]
        story.append(Paragraph("Ημέρες που χρειάζονται έλεγχο", st_h2))
        bg = [
            "#fdecea" if str(x).startswith("Δεν υπολογίστηκε") else "#fff8e1"
            for x in review["Τι έγινε"]
        ]
        story.append(
            make_table(
                list(review.columns),
                review.values.tolist(),
                [0.15, 0.11, 0.10, 0.24, 0.40],
                bg,
            )
        )
    else:
        story.append(box("Δεν βρέθηκαν ημέρες που χρειάζονται έλεγχο.", "#eafaf1", "#27ae60"))

    # Χειροκίνητες διορθώσεις
    if len(manual_table) > 0:
        story += [
            Spacer(1, 6),
            box(
                "<b>Σημείωση:</b> " + escape(
                    str(len(manual_table)) + " ημέρες έχουν ώρες που καταχωρήθηκαν"
                    " χειροκίνητα και δεν προέρχονται από την κάρτα."
                ),
                "#e8f4fd", "#2980b9",
            ),
            Paragraph("Χειροκίνητες διορθώσεις", st_h2),
            make_table(
                list(manual_table.columns),
                manual_table.values.tolist(),
                [0.14, 0.10, 0.09, 0.20, 0.12, 0.14, 0.21],
            ),
        ]

    # Μηνιαίο σύνολο
    story.append(
        KeepTogether(
            [
                Paragraph("Μηνιαίο Σύνολο Ανά Εργαζόμενο", st_h2),
                make_table(
                    list(monthly.columns),
                    monthly.values.tolist(),
                    [0.30, 0.14, 0.28, 0.28],
                ),
            ]
        )
    )

    # Αναλυτική ημερήσια καταγραφή (σε νέα σελίδα)
    def fmt_time(t, base_date):
        if pd.isna(t):
            return ""
        txt = t.strftime("%H:%M")
        if t.date() > base_date:
            txt += " (+1)"
        return txt

    rows, row_bg = [], []
    for _, r in daily.iterrows():
        note = str(r["Παρατηρήσεις"])
        rows.append(
            [
                r["Όνομα Εργαζομένου"],
                str(r["Ημερομηνία"]),
                r["Ημέρα"],
                fmt_time(r["Ώρα Άφιξης"], r["Ημερομηνία"]),
                fmt_time(r["Ώρα Αποχώρησης"], r["Ημερομηνία"]),
                note,
                r["Ώρες Εργασίας"],
                r["Ώρες Υπερωρίας"],
            ]
        )
        if note.startswith("ΠΡΟΣΟΧΗ"):
            row_bg.append("#fdecea")
        elif note.startswith("Χειροκίνητη"):
            row_bg.append("#e8f4fd")
        elif note != "":
            row_bg.append("#fff8e1")
        else:
            row_bg.append(None)

    story += [
        PageBreak(),
        Paragraph("Αναλυτική Ημερήσια Καταγραφή", st_h2),
        Paragraph(
            escape(
                "Κόκκινο = δεν υπολογίστηκε, απαιτείται έλεγχος. Κίτρινο = εκτίμηση " + str(STANDARD_HOURS) + " ωρών"
                " (1 μόνο χτύπημα). Μπλε = ώρες που καταχωρήθηκαν χειροκίνητα."
                " (+1) = την επόμενη ημερολογιακή μέρα."
            ),
            st_meta,
        ),
        Spacer(1, 4),
        make_table(
            [
                "Όνομα Εργαζομένου", "Ημερομηνία", "Ημέρα", "Ώρα Άφιξης",
                "Ώρα Αποχώρησης", "Παρατηρήσεις", "Ώρες Εργασίας", "Ώρες Υπερωρίας",
            ],
            rows,
            [0.12, 0.09, 0.09, 0.09, 0.10, 0.27, 0.12, 0.12],
            row_bg,
        ),
    ]

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("GR", 8)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawRightString(page_w - margin, 14, "Σελίδα " + str(doc_.page))
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin + 6,
        title="Αναφορά Ωρών Εργασίας & Υπερωριών",
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


st.set_page_config(
    page_title="Αναφορά Ωρών Εργασίας & Υπερωριών", page_icon="⏱️", layout="wide"
)

st.title("📊 Σύστημα Υπολογισμού Ωρών & Υπερωριών Εργαζομένων")
st.write(
    "Ανεβάστε το αρχείο CSV με τα χτυπήματα της κάρτας για να δημιουργηθεί"
    " αυτόματα το report (HTML και PDF για εκτύπωση)."
)

uploaded_file = st.file_uploader("Επιλέξτε αρχείο CSV", type=["csv", "txt"])

if uploaded_file is not None:
    try:
        uploaded_file.seek(0)
        df = pd.read_csv(uploaded_file, sep="\t", encoding="utf-16", engine="python")
        df.columns = df.columns.str.strip()

        missing_cols = [c for c in ("Name", "DateTime") if c not in df.columns]
        if missing_cols:
            raise InputError(
                "Στο αρχείο λείπουν οι στήλες: " + ", ".join(missing_cols)
                + ". Στήλες που βρέθηκαν: " + ", ".join(str(c) for c in df.columns)
            )

        df["DateTime"] = pd.to_datetime(
            df["DateTime"].astype(str).str.strip(),
            format="%Y/%m/%d %H:%M:%S",
            errors="coerce",
        )
        df["Name"] = df["Name"].fillna("").astype(str).str.strip()

        # Γραμμές που δεν μπορούν να χρησιμοποιηθούν: ενημερώνουμε, δεν τις χάνουμε σιωπηλά
        bad_time = df["DateTime"].isna()
        no_name = df["Name"] == ""
        if bad_time.sum() > 0:
            st.warning(
                "⚠️ Αγνοήθηκαν " + str(int(bad_time.sum()))
                + " γραμμές με μη αναγνώσιμη ημερομηνία/ώρα."
            )
        if (no_name & ~bad_time).sum() > 0:
            st.warning(
                "⚠️ Αγνοήθηκαν " + str(int((no_name & ~bad_time).sum()))
                + " γραμμές χωρίς όνομα εργαζομένου."
            )
        df_valid = df[~bad_time & ~no_name].copy()
        if df_valid.empty:
            raise InputError("Δεν βρέθηκε καμία έγκυρη εγγραφή στο αρχείο.")

        # Ημέρα εργασίας: τα χτυπήματα πριν τις NIGHT_CUTOFF_HOUR ανήκουν στην προηγούμενη
        df_valid["Date"] = (
            df_valid["DateTime"] - pd.Timedelta(hours=NIGHT_CUTOFF_HOUR)
        ).dt.date

        def list_times(series):
            return ", ".join(t.strftime("%H:%M") for t in sorted(series))

        daily_summary = (
            df_valid.groupby(["Name", "Date"])["DateTime"]
            .agg(
                First_Hit="min",
                Last_Hit="max",
                Hit_Count="count",
                All_Times=list_times,
            )
            .reset_index()
        )

        days_map = {
            0: "Δευτέρα",
            1: "Τρίτη",
            2: "Τετάρτη",
            3: "Πέμπτη",
            4: "Παρασκευή",
            5: "Σάββατο",
            6: "Κυριακή",
        }
        weekday = pd.to_datetime(daily_summary["Date"]).dt.dayofweek
        daily_summary["Day_Name"] = weekday.map(days_map)
        daily_summary["Is_Weekend"] = weekday.isin([5, 6]).astype(int)
        # Διαφορά πρώτης-τελευταίας εγγραφής σε λεπτά
        daily_summary["Gap_Min"] = (
            daily_summary["Last_Hit"] - daily_summary["First_Hit"]
        ).dt.total_seconds() / 60

        # Πρόβλημα που θέλει έλεγχο: 3+ εγγραφές, ή 2 εγγραφές πολύ κοντινές
        too_many = daily_summary["Hit_Count"] > 2
        too_close = (daily_summary["Hit_Count"] == 2) & (
            daily_summary["Gap_Min"] < MIN_GAP_MINUTES
        )
        daily_summary["Has_Issue"] = (too_many | too_close).astype(int)
        daily_summary["Is_Single"] = (daily_summary["Hit_Count"] == 1).astype(int)
        daily_summary["Issue_Reason"] = ""
        daily_summary.loc[too_many, "Issue_Reason"] = "Πάνω από 2 εγγραφές"
        if too_close.any():
            daily_summary.loc[too_close, "Issue_Reason"] = [
                "2 εγγραφές με πολύ μικρή διαφορά (" + str(round(g, 1)) + " λεπτά)"
                for g in daily_summary.loc[too_close, "Gap_Min"]
            ]

        def calculate_hours_and_notes(row):
            hits = row["Hit_Count"]
            if hits == 1:
                # 1 χτύπημα: Υπολογίζουμε το κανονικό ωράριο και βάζουμε παρατήρηση
                return (
                    row["First_Hit"],
                    pd.NaT,
                    float(STANDARD_HOURS),
                    0.0,
                    "Ελλιπές χτύπημα - Ξέχασαν να χτυπήσουν",
                )
            elif hits == 2 and row["Gap_Min"] < MIN_GAP_MINUTES:
                # 2 εγγραφές σχεδόν ταυτόχρονα: ΔΕΝ μαντεύουμε
                return (
                    pd.NaT,
                    pd.NaT,
                    0.0,
                    0.0,
                    "ΠΡΟΣΟΧΗ: 2 εγγραφές με διαφορά μόνο " + str(round(row["Gap_Min"], 1))
                    + " λεπτών (" + row["All_Times"]
                    + ") - Δεν υπολογίστηκε, απαιτείται έλεγχος",
                )
            elif hits == 2:
                arr = row["First_Hit"]
                dep = row["Last_Hit"]
                # Στρογγυλοποίηση σε ολόκληρα λεπτά ΑΝΑ ΗΜΕΡΑ, ώστε τα μηνιαία σύνολα
                # να ισούνται πάντα με το άθροισμα των ημερήσιων γραμμών
                hours = round((dep - arr).total_seconds() / 60) / 60
                overtime = max(0.0, hours - STANDARD_HOURS)
                return arr, dep, hours, overtime, ""
            else:
                # 3+ εγγραφές: ΔΕΝ μαντεύουμε. Καμία ώρα, καμία υπολογισμένη τιμή.
                return (
                    pd.NaT,
                    pd.NaT,
                    0.0,
                    0.0,
                    "ΠΡΟΣΟΧΗ: " + str(hits) + " εγγραφές (" + row["All_Times"]
                    + ") - Δεν υπολογίστηκε, απαιτείται έλεγχος",
                )

        res = daily_summary.apply(calculate_hours_and_notes, axis=1)
        daily_summary["Arrival"] = [r[0] for r in res]
        daily_summary["Departure"] = [r[1] for r in res]
        daily_summary["Hours_Decimal"] = [r[2] for r in res]
        daily_summary["Overtime_Decimal"] = [r[3] for r in res]
        daily_summary["Παρατηρήσεις"] = [r[4] for r in res]
        daily_summary["Is_Manual"] = 0
        daily_summary["Is_Ignored"] = 0

        def make_review(ds):
            """Πίνακας με τις ημέρες που χρειάζονται έλεγχο (Has_Issue ή Is_Single)."""
            r = ds[(ds["Has_Issue"] == 1) | (ds["Is_Single"] == 1)].copy()
            r["Τι έγινε"] = [
                (
                    "Δεν υπολογίστηκε: " + x["Issue_Reason"]
                    if x["Has_Issue"] == 1
                    else "Υπολογίστηκαν " + str(STANDARD_HOURS) + " ώρες (εκτίμηση, 1 μόνο χτύπημα)"
                )
                for _, x in r.iterrows()
            ]
            r = r.sort_values(["Name", "Date"])[
                ["Name", "Date", "Day_Name", "All_Times", "Τι έγινε"]
            ].rename(
                columns={
                    "Name": "Όνομα Εργαζομένου",
                    "Date": "Ημερομηνία",
                    "Day_Name": "Ημέρα",
                    "All_Times": "Ώρες Εγγραφών",
                }
            )
            r["Ημερομηνία"] = r["Ημερομηνία"].astype(str)
            return r

        def cell_text(value):
            """Κείμενο κελιού του editor, κενό αν είναι None/NaN/NA (όταν σβηστεί)."""
            return "" if pd.isna(value) else str(value).strip()

        def parse_time_text(text):
            """Επιστρέφει (ώρα, None) αν είναι σωστό ΩΩ:ΛΛ, αλλιώς (None, μήνυμα)."""
            t = str(text).strip().replace(".", ":")
            try:
                return datetime.strptime(t, "%H:%M"), None
            except ValueError:
                return None, "μη έγκυρη ώρα «" + str(text) + "» (γράψε π.χ. 08:30)"

        # ---- Χειροκίνητη καταχώρηση πραγματικών ωρών για τις ημέρες με παρατηρήσεις
        review_input = make_review(daily_summary)
        manual_messages = []
        manual_count = 0

        if len(review_input) > 0:
            st.subheader("✍️ Ημέρες με παρατηρήσεις - συμπλήρωσε τις πραγματικές ώρες")
            st.caption(
                "Γράψε Ώρα Άφιξης ΚΑΙ Ώρα Αποχώρησης (μορφή ΩΩ:ΛΛ) στις ημέρες που"
                " θέλεις να διορθώσεις. Όσες αφήσεις κενές μένουν όπως υπολογίστηκαν."
                " Αν η αποχώρηση είναι μετά τα μεσάνυχτα (π.χ. 00:30), μετράει στην"
                " ίδια ημέρα εργασίας. Αν μια ημέρα δεν πρέπει να μετρήσει καθόλου"
                " (π.χ. λάθος ημερομηνία), τσέκαρε «Αγνόηση ημέρας» και θα μπει με 0 ώρες"
                " (οι ώρες που έγραψες στην ίδια γραμμή τότε δεν λαμβάνονται υπόψη)."
            )
            review_input["Πραγματική Άφιξη"] = ""
            review_input["Πραγματική Αποχώρηση"] = ""
            review_input["Αγνόηση ημέρας (0 ώρες)"] = False
            try:
                file_id = hashlib.md5(uploaded_file.getvalue()).hexdigest()[:12]
            except Exception:
                file_id = str(getattr(uploaded_file, "name", "")) + str(
                    getattr(uploaded_file, "size", 0)
                )
            editor_key = "review_editor_" + file_id

            def highlight_unresolved(row):
                if str(row["Τι έγινε"]).startswith("Δεν υπολογίστηκε"):
                    style = "background-color: #fdecea; color: #7b1f16"
                else:
                    style = ""
                return [style] * len(row)

            # Το χρώμα εφαρμόζεται στις στήλες που δεν επεξεργάζονται (πρώτες 5)
            try:
                editor_data = review_input.style.apply(highlight_unresolved, axis=1)
            except Exception:
                editor_data = review_input  # αν δεν υποστηρίζεται, χωρίς χρώμα

            edited = st.data_editor(
                editor_data,
                key=editor_key,
                hide_index=True,
                use_container_width=True,
                disabled=[
                    "Όνομα Εργαζομένου",
                    "Ημερομηνία",
                    "Ημέρα",
                    "Ώρες Εγγραφών",
                    "Τι έγινε",
                ],
                column_config={
                    "Πραγματική Άφιξη": st.column_config.TextColumn(
                        "Πραγματική Άφιξη (ΩΩ:ΛΛ)", max_chars=5
                    ),
                    "Πραγματική Αποχώρηση": st.column_config.TextColumn(
                        "Πραγματική Αποχώρηση (ΩΩ:ΛΛ)", max_chars=5
                    ),
                    "Αγνόηση ημέρας (0 ώρες)": st.column_config.CheckboxColumn(
                        "Αγνόηση ημέρας (0 ώρες)",
                        help="Η ημέρα δεν μετράει καθόλου (0 ώρες, χωρίς υπερωρία).",
                        default=False,
                    ),
                },
            )

            for idx, erow in edited.iterrows():
                ignore_flag = erow.get("Αγνόηση ημέρας (0 ώρες)", False)
                if (not pd.isna(ignore_flag)) and bool(ignore_flag):
                    # Η ημέρα δεν μετράει: 0 ώρες, χωρίς ώρες άφιξης/αποχώρησης
                    daily_summary.at[idx, "Arrival"] = pd.NaT
                    daily_summary.at[idx, "Departure"] = pd.NaT
                    daily_summary.at[idx, "Hours_Decimal"] = 0.0
                    daily_summary.at[idx, "Overtime_Decimal"] = 0.0
                    daily_summary.at[idx, "Παρατηρήσεις"] = (
                        "Χειροκίνητη αγνόηση ημέρας - 0 ώρες (αρχικές εγγραφές: "
                        + daily_summary.at[idx, "All_Times"] + ")"
                    )
                    daily_summary.at[idx, "Has_Issue"] = 0
                    daily_summary.at[idx, "Is_Single"] = 0
                    daily_summary.at[idx, "Is_Weekend"] = 0
                    daily_summary.at[idx, "Is_Manual"] = 1
                    daily_summary.at[idx, "Is_Ignored"] = 1
                    manual_count += 1
                    continue
                arr_txt = cell_text(erow["Πραγματική Άφιξη"])
                dep_txt = cell_text(erow["Πραγματική Αποχώρηση"])
                if arr_txt == "" and dep_txt == "":
                    continue
                who = str(erow["Όνομα Εργαζομένου"]) + " " + str(erow["Ημερομηνία"])
                if arr_txt == "" or dep_txt == "":
                    manual_messages.append(who + ": συμπλήρωσε και τις δύο ώρες.")
                    continue
                arr_t, err1 = parse_time_text(arr_txt)
                dep_t, err2 = parse_time_text(dep_txt)
                if err1 or err2:
                    manual_messages.append(who + ": " + (err1 or err2))
                    continue
                base_date = daily_summary.at[idx, "Date"]
                arr_dt = datetime.combine(base_date, arr_t.time())
                dep_dt = datetime.combine(base_date, dep_t.time())
                if dep_dt <= arr_dt:
                    if dep_t.hour < NIGHT_CUTOFF_HOUR:
                        dep_dt = dep_dt + timedelta(days=1)  # μετά τα μεσάνυχτα
                    else:
                        manual_messages.append(
                            who + ": η αποχώρηση είναι πριν ή ίδια με την άφιξη."
                        )
                        continue
                hours = round((dep_dt - arr_dt).total_seconds() / 60) / 60
                daily_summary.at[idx, "Arrival"] = pd.Timestamp(arr_dt)
                daily_summary.at[idx, "Departure"] = pd.Timestamp(dep_dt)
                daily_summary.at[idx, "Hours_Decimal"] = hours
                daily_summary.at[idx, "Overtime_Decimal"] = max(0.0, hours - STANDARD_HOURS)
                daily_summary.at[idx, "Παρατηρήσεις"] = (
                    "Χειροκίνητη καταχώρηση ωρών (αρχικές εγγραφές: "
                    + daily_summary.at[idx, "All_Times"] + ")"
                )
                daily_summary.at[idx, "Has_Issue"] = 0
                daily_summary.at[idx, "Is_Single"] = 0
                daily_summary.at[idx, "Is_Manual"] = 1
                manual_count += 1

            if manual_count > 0:
                st.success(
                    "✅ Καταχωρήθηκαν " + str(manual_count)
                    + " χειροκίνητες διορθώσεις. Τα σύνολα παρακάτω τις περιλαμβάνουν."
                )
            for m in manual_messages:
                st.warning("⚠️ " + m + " (αγνοήθηκε)")

        # Περίοδος δεδομένων: οι ημέρες που αγνοήθηκαν δεν μετράνε
        active_dates = daily_summary.loc[daily_summary["Is_Ignored"] == 0, "Date"]
        if active_dates.empty:
            active_dates = daily_summary["Date"]
        first_date = active_dates.min()
        last_date = active_dates.max()
        if (first_date.year, first_date.month) != (last_date.year, last_date.month):
            st.warning(
                "⚠️ Το αρχείο καλύπτει περισσότερους από έναν μήνες ("
                + first_date.strftime("%d/%m/%Y") + " - " + last_date.strftime("%d/%m/%Y")
                + "). Τα σύνολα ανά εργαζόμενο αθροίζονται για όλο το διάστημα."
            )

        def format_hours_minutes(decimal_hours):
            if pd.isna(decimal_hours) or decimal_hours <= 0:
                return "0 ώρες 0 λεπτά"
            hours, minutes = divmod(int(round(decimal_hours * 60)), 60)
            hours_txt = "1 ώρα" if hours == 1 else str(hours) + " ώρες"
            minutes_txt = "1 λεπτό" if minutes == 1 else str(minutes) + " λεπτά"
            return hours_txt + " " + minutes_txt

        monthly_summary = (
            daily_summary.groupby("Name")
            .agg(
                Hours_Decimal=("Hours_Decimal", "sum"),
                Overtime_Decimal=("Overtime_Decimal", "sum"),
                Weekend_Count=("Is_Weekend", "sum"),
            )
            .reset_index()
        )

        daily_summary["Hours_Worked"] = daily_summary["Hours_Decimal"].apply(
            format_hours_minutes
        )
        daily_summary["Overtime"] = daily_summary["Overtime_Decimal"].apply(
            format_hours_minutes
        )

        monthly_summary["Total_Hours"] = monthly_summary["Hours_Decimal"].apply(
            format_hours_minutes
        )
        monthly_summary["Total_Overtime"] = monthly_summary[
            "Overtime_Decimal"
        ].apply(format_hours_minutes)

        # Ημέρες με πρόβλημα, κρατάμε πριν σβήσουμε τις βοηθητικές στήλες
        n_issues = int(daily_summary["Has_Issue"].sum())
        n_single = int(daily_summary["Is_Single"].sum())

        # Ημέρες που ΑΚΟΜΑ χρειάζονται έλεγχο (μετά τις χειροκίνητες διορθώσεις)
        review = make_review(daily_summary)

        # Χειροκίνητες διορθώσεις, για διαφάνεια στο report
        manual_rows = daily_summary[daily_summary["Is_Manual"] == 1].sort_values(
            ["Name", "Date"]
        )
        manual_table = pd.DataFrame(
            {
                "Όνομα Εργαζομένου": list(manual_rows["Name"]),
                "Ημερομηνία": [str(d) for d in manual_rows["Date"]],
                "Ημέρα": list(manual_rows["Day_Name"]),
                "Αρχικές Εγγραφές": list(manual_rows["All_Times"]),
                "Άφιξη (χειροκίνητη)": [
                    "—" if pd.isna(t) else t.strftime("%H:%M") for t in manual_rows["Arrival"]
                ],
                "Αποχώρηση (χειροκίνητη)": [
                    "—" if pd.isna(t) else t.strftime("%H:%M") for t in manual_rows["Departure"]
                ],
                "Ώρες Εργασίας": list(manual_rows["Hours_Worked"]),
            }
        )

        daily_summary_clean = daily_summary.drop(
            columns=[
                "First_Hit",
                "Last_Hit",
                "Hours_Decimal",
                "Overtime_Decimal",
                "Is_Weekend",
                "Hit_Count",
                "All_Times",
                "Has_Issue",
                "Is_Single",
                "Is_Manual",
                "Is_Ignored",
                "Gap_Min",
                "Issue_Reason",
            ]
        )
        monthly_summary_clean = monthly_summary.drop(
            columns=["Hours_Decimal", "Overtime_Decimal"]
        )

        monthly_summary_clean = monthly_summary_clean.rename(
            columns={
                "Name": "Όνομα Εργαζομένου",
                "Total_Hours": "Συνολικές Ώρες",
                "Total_Overtime": "Συνολικές Ώρες Υπερωρίας",
                "Weekend_Count": "Ημέρες Σ-Κ",
            }
        )

        daily_summary_clean = daily_summary_clean.rename(
            columns={
                "Name": "Όνομα Εργαζομένου",
                "Date": "Ημερομηνία",
                "Day_Name": "Ημέρα",
                "Arrival": "Ώρα Άφιξης",
                "Departure": "Ώρα Αποχώρησης",
                "Hours_Worked": "Ώρες Εργασίας",
                "Overtime": "Ώρες Υπερωρίας",
            }
        )

        html_template = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Αναφορά Ωρών Εργασίας & Υπερωριών</title>
<style>
    body { font-family: Arial, sans-serif; margin: 30px; background-color: #f9f9f9; color: #333; }
    h1, h2 { color: #2c3e50; border-bottom: 2px solid #34495e; padding-bottom: 8px; }
    table { width: 100%; border-collapse: collapse; margin-bottom: 40px; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    th, td { padding: 12px 15px; text-align: left; border-bottom: 1px solid #ddd; }
    th { background-color: #2c3e50; color: white; }
    tr:hover { background-color: #f1f1f1; }
    .warning { background: #fdecea; border-left: 5px solid #c0392b; padding: 10px 15px; margin-bottom: 12px; }
    .info { background: #fff8e1; border-left: 5px solid #f39c12; padding: 10px 15px; margin-bottom: 12px; }
    .manual { background: #e8f4fd; border-left: 5px solid #2980b9; padding: 10px 15px; margin-bottom: 12px; }
    .ok { background: #eafaf1; border-left: 5px solid #27ae60; padding: 10px 15px; margin-bottom: 20px; }
</style>
</head>
<body>
    <h1>Αναφορά Ωρών Εργασίας & Υπερωριών</h1>
    __REVIEW__
    __MANUAL__
    <h2>Μηνιαίο Σύνολο Ανά Εργαζόμενο</h2>
    __MONTHLY_TABLE__
    <h2>Αναλυτική Ημερήσια Καταγραφή</h2>
    <p>Κόκκινο = δεν υπολογίστηκε, απαιτείται έλεγχος. Κίτρινο = εκτίμηση __STD__ ωρών (1 μόνο χτύπημα). Μπλε = ώρες που καταχωρήθηκαν χειροκίνητα.</p>
    __DAILY_TABLE__
</body>
</html>"""

        issue_msg = (
            str(n_issues) + " ημέρες ΔΕΝ υπολογίστηκαν (πάνω από 2 εγγραφές ή 2 εγγραφές"
            " πολύ κοντά μεταξύ τους) και δεν μπήκαν στα σύνολα."
        )
        single_msg = (
            str(n_single) + " ημέρες έχουν 1 μόνο χτύπημα και υπολογίστηκαν ως " + str(STANDARD_HOURS) + " ώρες"
            " (εκτίμηση)."
        )

        # Περίληψη όλων όσων χρειάζονται έλεγχο, στην κορυφή του report
        if len(review) > 0:
            review_html = ""
            if n_issues > 0:
                review_html += '<div class="warning"><b>Προσοχή:</b> ' + issue_msg + "</div>"
            if n_single > 0:
                review_html += '<div class="info"><b>Σημείωση:</b> ' + single_msg + "</div>"
            review_html += (
                "<h2>Ημέρες που χρειάζονται έλεγχο</h2>"
                + review.to_html(index=False, classes="table")
            )
        else:
            review_html = '<div class="ok">Δεν βρέθηκαν ημέρες που χρειάζονται έλεγχο.</div>'

        # Χρωματισμός γραμμών στην ημερήσια καταγραφή
        def highlight_row(row):
            note = str(row["Παρατηρήσεις"])
            if note.startswith("ΠΡΟΣΟΧΗ"):
                color = "background-color: #fdecea"
            elif note.startswith("Χειροκίνητη"):
                color = "background-color: #e8f4fd"
            elif note != "":
                color = "background-color: #fff8e1"
            else:
                color = ""
            return [color] * len(row)

        daily_html = (
            daily_summary_clean.style.apply(highlight_row, axis=1)
            .format(na_rep="")
            .hide(axis="index")
            .set_table_attributes('class="table"')
            .to_html()
        )

        if len(manual_table) > 0:
            manual_html = (
                '<div class="manual"><b>Σημείωση:</b> ' + str(len(manual_table))
                + " ημέρες έχουν ώρες που καταχωρήθηκαν χειροκίνητα και δεν"
                " προέρχονται από την κάρτα.</div>"
                "<h2>Χειροκίνητες διορθώσεις</h2>"
                + manual_table.to_html(index=False, classes="table")
            )
        else:
            manual_html = ""

        html_content = html_template.replace("__STD__", str(STANDARD_HOURS))
        html_content = html_content.replace("__REVIEW__", review_html)
        html_content = html_content.replace("__MANUAL__", manual_html)
        html_content = html_content.replace(
            "__MONTHLY_TABLE__",
            monthly_summary_clean.to_html(index=False, classes="table"),
        )
        html_content = html_content.replace("__DAILY_TABLE__", daily_html)

        st.success("Το αρχείο επεξεργάστηκε επιτυχώς!")

        # Περίληψη όλων όσων χρειάζονται έλεγχο, στην κορυφή της οθόνης
        if len(review) > 0:
            if n_issues > 0:
                st.warning("⚠️ " + issue_msg)
            if n_single > 0:
                st.info("ℹ️ " + single_msg)
            st.subheader("🔎 Ημέρες που χρειάζονται έλεγχο")
            st.dataframe(review, use_container_width=True)
        else:
            st.success("Δεν βρέθηκαν ημέρες που χρειάζονται έλεγχο.")

        st.subheader("📋 Μηνιαίο Σύνολο ανά Εργαζόμενο")
        st.dataframe(monthly_summary_clean, use_container_width=True)

        st.subheader("📅 Αναλυτική Ημερήσια Καταγραφή")
        st.dataframe(daily_summary_clean, use_container_width=True)

        # PDF για εκτύπωση (το HTML παραμένει όπως ήταν)
        pdf_bytes, pdf_error = None, None
        try:
            if len(daily_summary) > 0:
                period = (
                    "Περίοδος: " + first_date.strftime("%d/%m/%Y")
                    + " - " + last_date.strftime("%d/%m/%Y")
                    + " | Δημιουργήθηκε: " + datetime.now().strftime("%d/%m/%Y %H:%M")
                )
            else:
                period = "Δημιουργήθηκε: " + datetime.now().strftime("%d/%m/%Y %H:%M")
            pdf_bytes = build_pdf_report(
                review, manual_table, monthly_summary_clean, daily_summary_clean,
                n_issues, n_single, period,
            )
        except Exception as pdf_exc:
            pdf_error = str(pdf_exc)

        col_html, col_pdf = st.columns(2)
        with col_html:
            st.download_button(
                label="Λήψη HTML Report",
                data=html_content,
                file_name="Work_and_Overtime_Summary.html",
                mime="text/html",
            )
        with col_pdf:
            if pdf_bytes is not None:
                st.download_button(
                    label="🖨️ Λήψη PDF για εκτύπωση",
                    data=pdf_bytes,
                    file_name="Work_and_Overtime_Summary.pdf",
                    mime="application/pdf",
                )
            else:
                st.info(
                    "Το PDF δεν ήταν δυνατό να δημιουργηθεί: " + str(pdf_error)
                    + ". (Χρειάζεται: pip install reportlab)"
                )

    except InputError as e:
        st.error(str(e))
    except Exception as e:
        st.error("Προέκυψε σφάλμα κατά την επεξεργασία: " + str(e))
