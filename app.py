import io
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
                Issue_Days=("Has_Issue", "sum"),
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
        issues = daily_summary[daily_summary["Has_Issue"] == 1][
            ["Name", "Date", "Hit_Count", "All_Times", "Issue_Reason"]
        ]

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
                "Issue_Days": "Ημέρες με Πρόβλημα",
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
    .warning { background: #fdecea; border-left: 5px solid #c0392b; padding: 10px 15px; margin-bottom: 20px; }
</style>
</head>
<body>
    <h1>Αναφορά Ωρών Εργασίας & Υπερωριών</h1>
    __WARNING__
    <h2>Μηνιαίο Σύνολο Ανά Εργαζόμενο</h2>
    __MONTHLY_TABLE__
    <h2>Αναλυτική Ημερήσια Καταγραφή</h2>
    __DAILY_TABLE__
</body>
</html>"""

        if len(issues) > 0:
            warning_html = (
                '<div class="warning"><b>Προσοχή:</b> ' + str(len(issues))
                + " ημέρες έχουν ύποπτες εγγραφές (πάνω από 2 εγγραφές ή 2 εγγραφές"
                " πολύ κοντά μεταξύ τους) και δεν υπολογίστηκαν."
                " Δείτε τις παρατηρήσεις στην ημερήσια καταγραφή.</div>"
            )
        else:
            warning_html = ""

        html_content = html_template.replace("__WARNING__", warning_html)
        html_content = html_content.replace(
            "__MONTHLY_TABLE__",
            monthly_summary_clean.to_html(index=False, classes="table"),
        )
        html_content = html_content.replace(
            "__DAILY_TABLE__",
            daily_summary_clean.to_html(index=False, classes="table"),
        )

        st.success("Το αρχείο επεξεργάστηκε επιτυχώς!")

        if len(issues) > 0:
            st.warning(
                "⚠️ Βρέθηκαν " + str(len(issues)) + " ημέρες με ύποπτες εγγραφές "
                "(πάνω από 2 εγγραφές ή 2 εγγραφές πολύ κοντά μεταξύ τους). "
                "Δεν υπολογίστηκαν ώρες για αυτές και δεν μπήκαν στα σύνολα."
            )
            st.dataframe(
                issues.rename(
                    columns={
                        "Name": "Όνομα Εργαζομένου",
                        "Date": "Ημερομηνία",
                        "Hit_Count": "Αριθμός Εγγραφών",
                        "All_Times": "Ώρες Εγγραφών",
                        "Issue_Reason": "Λόγος",
                    }
                ),
                use_container_width=True,
            )

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
