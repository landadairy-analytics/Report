import io
import pandas as pd
import streamlit as st

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

        # Αντί για min/max γενικά, θα βρούμε πόσα χτυπήματα υπάρχουν
        # και ποια είναι η πρώτη/τελευταία ώρα ανά μέρα
        daily_summary = (
            df_valid.groupby(["Name", "Date"])["DateTime"]
            .agg(First_Hit="min", Last_Hit="max", Hit_Count="count")
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
            elif hits >= 2:
                # Κανονικά χτυπήματα (Άφιξη = First, Αποχώρηση = Last)
                arr = row["First_Hit"]
                dep = row["Last_Hit"]
                hours = (dep - arr).total_seconds() / 3600
                if hours < 0:
                    hours = 0.0
                overtime = max(0, hours - 10)
                return arr, dep, hours, overtime, ""
            else:
                return pd.NaT, pd.NaT, 0.0, 0.0, ""

        res = daily_summary.apply(calculate_hours_and_notes, axis=1)
        daily_summary["Arrival"] = [r[0] for r in res]
        daily_summary["Departure"] = [r[1] for r in res]
        daily_summary["Hours_Decimal"] = [r[2] for r in res]
        daily_summary["Overtime_Decimal"] = [r[3] for r in res]
        daily_summary["Παρατηρήσεις"] = [r[4] for r in res]

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

        daily_summary_clean = daily_summary.drop(
            columns=[
                "First_Hit",
                "Last_Hit",
                "Hours_Decimal",
                "Overtime_Decimal",
                "Is_Weekend",
                "Hit_Count",
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
                "Departure": "Ώρα Aποχώρησης",
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
</style>
</head>
<body>
    <h1>Αναφορά Ωρών Εργασίας & Υπερωριών</h1>
    <h2>Μηνιαίο Σύνολο Ανά Εργαζόμενο</h2>
    __MONTHLY_TABLE__
    <h2>Αναλυτική Ημερήσια Καταγραφή</h2>
    __DAILY_TABLE__
</body>
</html>"""

        html_content = html_template.replace(
            "__MONTHLY_TABLE__",
            monthly_summary_clean.to_html(index=False, classes="table"),
        )
        html_content = html_content.replace(
            "__DAILY_TABLE__",
            daily_summary_clean.to_html(index=False, classes="table"),
        )

        st.success("Το αρχείο επεξεργάστηκε επιτυχώς!")

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
