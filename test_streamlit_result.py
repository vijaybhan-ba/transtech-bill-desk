import pandas as pd
from app import apply_case_jar_logic

# Simulated Gemini output from a complex invoice with mixed case and jar rows
raw_records = [
    {"Date": "03-May-26", "Invoice No.": "MUMCIN270012371", "Vehicle No.": "MH-04 LE 8405", "From": "Godown no 14, Kothari Compound", "Customer Name": "PAURAS ENTERPRISES", "To": "HOUSE 321", "Vehicle Type": "9MT", "Case": 100, "Jar": 0},
    {"Date": "03-May-26", "Invoice No.": "MUMCIN270012371", "Vehicle No.": "MH-04 LE 8405", "From": "Godown no 14, Kothari Compound", "Customer Name": "PAURAS ENTERPRISES", "To": "HOUSE 321", "Vehicle Type": "9MT", "Case": 48, "Jar": 0},
    {"Date": "03-May-26", "Invoice No.": "MUMCIN270012371", "Vehicle No.": "MH-04 LE 8405", "From": "Godown no 14, Kothari Compound", "Customer Name": "PAURAS ENTERPRISES", "To": "HOUSE 321", "Vehicle Type": "9MT", "Case": 3, "Jar": 0},
    {"Date": "03-May-26", "Invoice No.": "MUMCIN270012371", "Vehicle No.": "MH-04 LE 8405", "From": "Godown no 14, Kothari Compound", "Customer Name": "PAURAS ENTERPRISES", "To": "HOUSE 321", "Vehicle Type": "9MT", "Case": 0, "Jar": 280},
    {"Date": "03-May-26", "Invoice No.": "MUMCIN270012371", "Vehicle No.": "MH-04 LE 8405", "From": "Godown no 14, Kothari Compound", "Customer Name": "PAURAS ENTERPRISES", "To": "HOUSE 321", "Vehicle Type": "9MT", "Case": 0, "Jar": 40},
    {"Date": "03-May-26", "Invoice No.": "MUMCIN270012371", "Vehicle No.": "MH-04 LE 8405", "From": "Godown no 14, Kothari Compound", "Customer Name": "PAURAS ENTERPRISES", "To": "HOUSE 321", "Vehicle Type": "9MT", "Case": 0, "Jar": 108},
    {"Date": "03-May-26", "Invoice No.": "MUMCIN270012371", "Vehicle No.": "MH-04 LE 8405", "From": "Godown no 14, Kothari Compound", "Customer Name": "PAURAS ENTERPRISES", "To": "HOUSE 321", "Vehicle Type": "9MT", "Case": 0, "Jar": 6},
    {"Date": "03-May-26", "Invoice No.": "MUMCIN270012371", "Vehicle No.": "MH-04 LE 8405", "From": "Godown no 14, Kothari Compound", "Customer Name": "PAURAS ENTERPRISES", "To": "HOUSE 321", "Vehicle Type": "9MT", "Case": 0, "Jar": 20},
]

# Transform and aggregate using the same logic as app.py

# Build DataFrame from extracted records
records = [apply_case_jar_logic(r) for r in raw_records]
df = pd.DataFrame(records)
for col in ("Case", "Jar"):
    if col not in df.columns:
        df[col] = 0.0
    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

def _parse_date(val):
    if pd.isna(val):
        return pd.NaT
    for fmt in ("%d-%b-%y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return pd.to_datetime(val, format=fmt)
        except Exception:
            continue
    return pd.to_datetime(val, errors="coerce")

df["_parsed_date"] = df.get("Date", "").apply(_parse_date)

# Normalize invoice numbers
# Use an uppercase, whitespace-free key for duplicate detection

df["invoice_key"] = df["Invoice No."].astype(str).str.upper().str.replace(r"\s+", "", regex=True)

has_invoice = df["invoice_key"].astype(str) != ""
df_with_invoice = df[has_invoice].copy()

agg = (
    df_with_invoice.groupby("invoice_key", dropna=False)
    .agg(
        {
            "Invoice No.": "first",
            "_parsed_date": "min",
            "Vehicle No.": "first",
            "From": "first",
            "Customer Name": "first",
            "To": "first",
            "Vehicle Type": "first",
            "Case": "sum",
            "Jar": "sum",
        }
    )
    .reset_index(drop=True)
)

agg["_parsed_date"] = pd.to_datetime(agg["_parsed_date"], errors="coerce")
agg = agg.sort_values("_parsed_date", na_position="last").reset_index(drop=True)
agg["Date"] = agg["_parsed_date"].dt.strftime("%d-%b-%y").fillna("")
agg.insert(0, "Sr No.", range(1, len(agg) + 1))

print(agg.to_string(index=False))
