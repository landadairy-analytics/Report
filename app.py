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

    # Καθαρισμός κενών από τη στήλη 'Name'
    df["Name"] = df["Name"].astype(str).str.strip()


    # ΔΙΟΡΘΩΣΗ ΓΙΑ ΝΥΧΤΕΡΙΝΕΣ ΒΑΡΔΙΕΣ ΜΕΤΑ ΤΙΣ 12:00 ΕΩΣ 02:00
    def adjust_night_shift_date(row):
      dt = row["DateTime"]
      if pd.isna(dt):
        return pd.NaT
      if dt.hour < 2:
        return (dt - pd.Timedelta(days=1)).date()
      else:
        return dt.date()


    df["Date"] = df.apply(adjust_night_shift_date, axis=1)

    # 5. Έλεγχος χτυπημάτων ανά ημέρα
    counts = df.groupby(["Name", "Date"]).size().reset_index(name="Hit_Count")

    # Υπολογισμός Ελάχιστης και Μέγιστης ώρας
    daily_summary = (
        df.groupby(["Name", "Date"])["DateTime"]
        .agg(Arrival="min", Departure="max")
        .reset_index()
    )

    # Ενσωμάτωση πλήθους χτυπημάτων
    daily_summary = pd.merge(daily_summary, counts, on=["Name", "Date"])

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

    # Δείκτης για Σάββατο (5) ή Κυριακή (6) μαζί
    daily_summary["Is_Weekend"] = (
        pd.to_datetime(daily_summary["Date"]).dt.dayofweek.isin([5, 6])
    ).astype(int)


    # 6. Υπολογισμός ωρών εργασίας & διαχείρισης "ξεχασμένου χτυπήματος"
    def calculate_hours_and_notes(row):
      if row["Hit_Count"] == 1:
        return 10.0, 0.0, "Ελλιπές χτύπημα - Ξέχασαν να χτυπήσουν"
      else:
        hours = (row["Departure"] - row["Arrival"]).total_seconds() / 3600
        if hours < 0:
          hours = 0.0
        overtime = max(0, hours - 10)
        return hours, overtime, ""


    res = daily_summary.apply(calculate_hours_and_notes, axis=1)
    daily_summary["Hours_Decimal"] = [r[0] for r in res]
    daily_summary["Overtime_Decimal"] = [r[1] for r in res]
    daily_summary["Παρατηρήσεις"] = [r[2] for r in res]

    daily_summary.loc[daily_summary["Hit_Count"] == 1, "Arrival"] = pd.NaT
    daily_summary.loc[daily_summary["Hit_Count"] == 1, "Departure"] = pd.NaT


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


    # 8. Δημιουργία αθροιστικού πίνακα ανά άτομο
    monthly_summary = (
        daily_summary.groupby("Name")
        .agg(
            Hours_Decimal=("Hours_Decimal", "sum"),
            Overtime_Decimal=("Overtime_Decimal", "sum"),
            Weekend_Count=("Is_Weekend", "sum"),
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

    # Αφαίρεση βοηθητικών στηλών
    daily_summary_clean = daily_summary.drop(
        columns=[
            "Hours_Decimal",
            "Overtime_Decimal",
            "Is_Weekend",
            "Hit_Count",
        ]
    )
    monthly_summary_clean = monthly_summary.drop(
        columns=["Hours_Decimal", "Overtime_Decimal"]
    )

    # ΜΕΤΟΝΟΜΑΣΙΑ ΣΤΗΛΩΝ ΣΕ ΕΛΛΗΝΙΚΑ
    monthly_summary_clean = monthly_summary_clean.rename(
        columns={
            "Name":
