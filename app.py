import io
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

# Αν 2 εγγραφές της ίδιας μέρας απέχουν λιγότερο από αυτό (σε λεπτά),
# θεωρούνται ύποπτες (π.χ. διπλό χτύπημα) και δεν υπολογίζονται.
MIN_GAP_MINUTES = 30

st.set_page_config(
    page_title="Αναφορά Ωρών Εργασίας & Υπερωριών", page_icon="⏱️", layout="wide"
)

st.title("📊 Σύστημα Υπολογισμού Ωρών & Υπερωριών Εργαζομένων")
st.write(
    "Ανεβάστε το αρχείο CSV με τα χτυπήματα της κάρτας για να δημιουργηθεί"
    " αυτόματα το HTML report."
)

uploaded_file = st.file_uploader("Επιλέξτε αρχείο CSV", type=["csv", "txt"])

if uploaded_file is not None:
    try:
        uploaded_file.seek(0)
        df = pd.read_csv(uploaded_file, sep="\t", encoding="utf-16", engine="python")
        df.columns = df.columns.str.strip()

        df["DateTime"] = pd.to_datetime(
            df["DateTime"].astype(str).str.strip(),
            format="%Y/%m/%d %H:%M:%S",
            errors="coerce",
        )
        df["Name"] = df["Name"].astype(str).str.strip()

        def adjust_night_shift_date(row):
            dt = row["DateTime"]
            if pd.isna(dt):
                return pd.NaT
            if dt.hour < 2:
                return (dt - pd.Timedelta(days=1)).date()
            else:
                return dt.date()

        df["Date"] = df.apply(adjust_night_shift_date, axis=1)

        df_valid = df.dropna(subset=["DateTime", "Date"]).copy()

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
        daily_summary["Day_Name"] = (
            pd.to_datetime(daily_summary["Date"]).dt.dayofweek.map(days_map)
        )
        daily_summary["Is_Weekend"] = (
            pd.to_datetime(daily_summary["Date"]).dt.dayofweek.isin([5, 6])
        ).astype(int)
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
        daily_summary.loc[too_close, "Issue_Reason"] = (
            "2 εγγραφές με πολύ μικρή διαφορά ("
            + daily_summary.loc[too_close, "Gap_Min"].map(lambda g: str(round(g, 1)))
            + " λεπτά)"
        )

        def calculate_hours_and_notes(row):
            hits = row["Hit_Count"]
            if hits == 1:
                # 1 χτύπημα: Υπολογίζουμε 10ωρο και βάζουμε παρατήρηση
                return (
                    row["First_Hit"],
                    pd.NaT,
                    10.0,
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
                hours = (dep - arr).total_seconds() / 3600
                overtime = max(0, hours - 10)
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

        def make_review(ds):
            """Πίνακας με τις ημέρες που χρειάζονται έλεγχο (Has_Issue ή Is_Single)."""
            r = ds[(ds["Has_Issue"] == 1) | (ds["Is_Single"] == 1)].copy()
            r["Τι έγινε"] = [
                (
                    "Δεν υπολογίστηκε: " + x["Issue_Reason"]
                    if x["Has_Issue"] == 1
                    else "Υπολογίστηκαν 10 ώρες (εκτίμηση, 1 μόνο χτύπημα)"
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
                " ίδια ημέρα εργασίας."
            )
            review_input["Πραγματική Άφιξη"] = ""
            review_input["Πραγματική Αποχώρηση"] = ""
            editor_key = (
                "review_editor_"
                + str(getattr(uploaded_file, "name", ""))
                + "_"
                + str(getattr(uploaded_file, "size", 0))
            )
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
                },
            )

            for idx, erow in edited.iterrows():
                arr_txt = str(erow["Πραγματική Άφιξη"] or "").strip()
                dep_txt = str(erow["Πραγματική Αποχώρηση"] or "").strip()
                if arr_txt in ("", "None") and dep_txt in ("", "None"):
                    continue
                who = str(erow["Όνομα Εργαζομένου"]) + " " + str(erow["Ημερομηνία"])
                if arr_txt in ("", "None") or dep_txt in ("", "None"):
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
                    if dep_t.hour < 2:
                        dep_dt = dep_dt + timedelta(days=1)  # μετά τα μεσάνυχτα
                    else:
                        manual_messages.append(
                            who + ": η αποχώρηση είναι πριν ή ίδια με την άφιξη."
                        )
                        continue
                hours = (dep_dt - arr_dt).total_seconds() / 3600
                daily_summary.at[idx, "Arrival"] = pd.Timestamp(arr_dt)
                daily_summary.at[idx, "Departure"] = pd.Timestamp(dep_dt)
                daily_summary.at[idx, "Hours_Decimal"] = hours
                daily_summary.at[idx, "Overtime_Decimal"] = max(0.0, hours - 10)
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

        def format_hours_minutes(decimal_hours):
            if pd.isna(decimal_hours) or decimal_hours <= 0:
                return "0 ώρες 0 λεπτά"
            hours = int(decimal_hours)
            minutes = int(round((decimal_hours - hours) * 60))
            if minutes == 60:
                hours += 1
                minutes = 0
            return str(hours) + " ώρες " + str(minutes) + " λεπτά"

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
                "Άφιξη (χειροκίνητη)": [t.strftime("%H:%M") for t in manual_rows["Arrival"]],
                "Αποχώρηση (χειροκίνητη)": [
                    t.strftime("%H:%M") for t in manual_rows["Departure"]
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
    <p>Κόκκινο = δεν υπολογίστηκε, απαιτείται έλεγχος. Κίτρινο = εκτίμηση 10 ωρών (1 μόνο χτύπημα). Μπλε = ώρες που καταχωρήθηκαν χειροκίνητα.</p>
    __DAILY_TABLE__
</body>
</html>"""

        issue_msg = (
            str(n_issues) + " ημέρες ΔΕΝ υπολογίστηκαν (πάνω από 2 εγγραφές ή 2 εγγραφές"
            " πολύ κοντά μεταξύ τους) και δεν μπήκαν στα σύνολα."
        )
        single_msg = (
            str(n_single) + " ημέρες έχουν 1 μόνο χτύπημα και υπολογίστηκαν ως 10 ώρες"
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

        html_content = html_template.replace("__REVIEW__", review_html)
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

        st.download_button(
            label="Λήψη HTML Report",
            data=html_content,
            file_name="Work_and_Overtime_Summary.html",
            mime="text/html",
        )

    except Exception as e:
        st.error("Προέκυψε σφάλμα κατά την επεξεργασία: " + str(e))
