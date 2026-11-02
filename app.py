import io
import pandas as pd
import streamlit as st

# Ρυθμίσεις σελίδας Streamlit
st.set_page_config(
    page_title="Αναφορά Ωρών Εργασίας & Υπερωριών", page_icon="⏱️", layout="wide"
)

st.title("📊 Σύστημα Υπολογισμού Ωρών & Υπερωριών Εργαζομένων")
st.write(
    "Ανεβάστε το αρχείο CSV με τα χτυπήματα της κάρτας για να δημιουργηθεί"
    " αυτόματα το HTML report."
)

# Κουμπί μεταφόρτωσης αρχείου (Drag & Drop ή επιλογή)
uploaded_file = st.file_uploader("Επιλέξτε αρχείο CSV", type=["csv", "txt"])

if uploaded_file is not None:
  try:
    # 2. Ανάγνωση του CSV
    df = pd.read_csv(uploaded_file, sep="\t", encoding="utf-16", engine="python")

    # Καθαρισμός κενών από τα ονόματα των στηλών
    df.columns = df.columns.str.strip()

    # 3. Μετατροπή της στήλης DateTime
    df["DateTime"] = pd.to_datetime(
        df["DateTime"].astype(str).str.strip(),
        format="%Y/%m/%d %H:%M:%S",
        errors="coerce",
    )

    # 4. Δημιουργία στήλης μόνο με την ημερομηνία
    df["Date"] = df["DateTime"].dt.date

    # Καθαρισμός κενών από τη στήλη 'Name'
    df["Name"] = df["Name"].astype(str).str.strip()

    # 5. Υπολογισμός Ελάχιστης (Άφιξη) και Μέγιστης (Αποχώρηση) ώρας ανά ημέρα
    daily_summary = (
        df.groupby(["Name", "Date"])["DateTime"]
        .agg(Arrival="min", Departure="max")
        .reset_index()
    )

    # Προσθήκη στήλης με την ημέρα της εβδομάδας (στα Ελληνικά)
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

    # Ειδικές στήλες-δείκτες για Σάββατο και Κυριακή (1 αν είναι, 0 αλλιώς)
    daily_summary["Is_Saturday"] = (
        pd.to_datetime(daily_summary["Date"]).dt.dayofweek == 5
    ).astype(int)
    daily_summary["Is_Sunday"] = (
        pd.to_datetime(daily_summary["Date"]).dt.dayofweek == 6
    ).astype(int)

    # 6. Υπολογισμός ωρών εργασίας (σε δεκαδική μορφή)
    daily_summary["Hours_Decimal"] = (
        daily_summary["Departure"] - daily_summary["Arrival"]
    ).dt.total_seconds() / 3600

    # 7. Υπολογισμός Υπερωρίας (πάνω από 10 ώρες)
    daily_summary["Overtime_Decimal"] = daily_summary["Hours_Decimal"].apply(
        lambda x: max(0, x - 10)
    )

    # Βοηθητική συνάρτηση μετατροπής σε "X ώρες Y λεπτά"
    def format_hours_minutes(decimal_hours):
      if pd.isna(decimal_hours) or decimal_hours <= 0:
        return "0 ώρες 0 λεπτά"
      hours = int(decimal_hours)
      minutes = int(round((decimal_hours - hours) * 60))
      if minutes == 60:
        hours += 1
        minutes = 0
      return f"{hours} ώρες {minutes} λεπτά"

    # 8. Δημιουργία αθροιστικού πίνακα ανά άτομο (συμπεριλαμβανομένων Σαββάτων & Κυριακών)
    monthly_summary = (
        daily_summary.groupby("Name")
        .agg(
            Hours_Decimal=("Hours_Decimal", "sum"),
            Overtime_Decimal=("Overtime_Decimal", "sum"),
            Saturday_Count=("Is_Saturday", "sum"),
            Sunday_Count=("Is_Sunday", "sum"),
        )
        .reset_index()
    )

    # Εφαρμογή της μορφοποίησης ωρών
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

    # Αφαίρεση βοηθητικών στηλών και μετονομασία
    daily_summary_clean = daily_summary.drop(
        columns=[
            "Hours_Decimal",
            "Overtime_Decimal",
            "Is_Saturday",
            "Is_Sunday",
        ]
    )
    monthly_summary_clean = monthly_summary.drop(
        columns=["Hours_Decimal", "Overtime_Decimal"]
    )

    # -------------------------------------------------------------
    # ΜΕΤΟΝΟΜΑΣΙΑ ΣΤΗΛΩΝ ΣΕ ΕΛΛΗΝΙΚΑ
    # -------------------------------------------------------------
    monthly_summary_clean = monthly_summary_clean.rename(
        columns={
            "Name": "Όνομα Εργαζομένου",
            "Total_Hours": "Συνολικές Ώρες",
            "Total_Overtime": "Συνολικές Ώρες Υπερωρίας",
            "Saturday_Count": "Ημέρες Σάββατο",
            "Sunday_Count": "Ημέρες Κυριακή",
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

    # 9. Δημιουργία του HTML περιεχομένου
    html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
        <meta charset="utf-8">
        <title>Αναφορά Ωρών Εργασίας & Υπερωριών</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 30px; background-color: #f9f9f9; color: #333; }}
            h1, h2 {{ color: #2c3e50; border-bottom: 2px solid #34495e; padding-bottom: 8px; }}
            table {{ width: 100%; border-collapse: collapse; margin-bottom: 40px; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
            th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #ddd; }}
            th {{ background-color: #2c3e50; color: white; }}
            tr:hover {{ background-color: #f1f1f1; }}
        </style>
        </head>
        <body>
            <h1>Αναφορά Ωρών Εργασίας & Υπερωριών</h1>
            
            <h2>Μηνιαίο Σύνολο Ανά Εργαζόμενο</h2>
            {monthly_summary_clean.to_html(index=False, classes='table')}
            
            <h2>Αναλυτική Ημερήσια Καταγραφή</h2>
            {daily_summary_clean.to_html(index=False, classes='table')}
        </body>
        </html>
        """

    st.success(
        "Το αρχείο επεξεργάστηκε επιτυχώς και το HTML report είναι έτοιμο!"
    )

    # Εμφάνιση προεπισκόπησης στην οθόνη
    st.subheader("📋 Μηνιαίο Σύνολο ανά Εργαζόμενο")
    st.dataframe(monthly_summary_clean, use_container_width=True)

    st.subheader("📅 Αναλυτική Ημερήσια Καταγραφή")
    st.dataframe(daily_summary_clean, use_container_width=True)

    # 10. Κουμπί λήψης του αρχείου HTML για τον χρήστη
    st.download_button(
        label="📥 Λήψη HTML Report",
        data=html_content,
        file_name="Work_and_Overtime_Summary.html",
        mime="text/html",
    )

  except Exception as e:
    st.error(
        f"Προέκυψε κάποιο σφάλμα κατά την επεξεργασία του αρχείου: {e}"
    )
