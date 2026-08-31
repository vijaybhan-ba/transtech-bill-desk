import pandas as pd

# Sample records simulating parsed Gemini output across multiple rows for same invoice
records = [
    {"Date": "01-May-26", "Invoice No.": "INV-001", "Vehicle No.": "MH04LE", "From": "A", "Customer Name": "Cust1", "To": "B", "Vehicle Type": "9MT", "Case": 100, "Jar": 0},
    {"Date": "01-May-26", "Invoice No.": "INV-001", "Vehicle No.": "MH04LE", "From": "A", "Customer Name": "Cust1", "To": "B", "Vehicle Type": "9MT", "Case": 48, "Jar": 0},
    {"Date": "01-May-26", "Invoice No.": "INV-001", "Vehicle No.": "MH04LE", "From": "A", "Customer Name": "Cust1", "To": "B", "Vehicle Type": "9MT", "Case": 3, "Jar": 0},
    {"Date": "01-May-26", "Invoice No.": "INV-001", "Vehicle No.": "MH04LE", "From": "A", "Customer Name": "Cust1", "To": "B", "Vehicle Type": "9MT", "Case": 0, "Jar": 280},
    {"Date": "01-May-26", "Invoice No.": "INV-001", "Vehicle No.": "MH04LE", "From": "A", "Customer Name": "Cust1", "To": "B", "Vehicle Type": "9MT", "Case": 0, "Jar": 40},
    {"Date": "01-May-26", "Invoice No.": "INV-001", "Vehicle No.": "MH04LE", "From": "A", "Customer Name": "Cust1", "To": "B", "Vehicle Type": "9MT", "Case": 0, "Jar": 108},
    {"Date": "01-May-26", "Invoice No.": "INV-001", "Vehicle No.": "MH04LE", "From": "A", "Customer Name": "Cust1", "To": "B", "Vehicle Type": "9MT", "Case": 0, "Jar": 6},
    {"Date": "01-May-26", "Invoice No.": "INV-001", "Vehicle No.": "MH04LE", "From": "A", "Customer Name": "Cust1", "To": "B", "Vehicle Type": "9MT", "Case": 0, "Jar": 20},
    # Another invoice earlier date
    {"Date": "30-Apr-26", "Invoice No.": "INV-000", "Vehicle No.": "MH01AB", "From": "X", "Customer Name": "Cust0", "To": "Y", "Vehicle Type": "9MT", "Case": 10, "Jar": 5},
    # Blank invoice row should be preserved
    {"Date": "02-May-26", "Invoice No.": "", "Vehicle No.": "MH02CD", "From": "Z", "Customer Name": "Cust2", "To": "W", "Vehicle Type": "9MT", "Case": 2, "Jar": 1},
]

# Processing logic copied from app.py
COLUMNS = ["Sr No.", "Date", "Invoice No.", "Vehicle No.", "From", "Customer Name", "To", "Vehicle Type", "Case", "Jar"]

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

# Normalize Invoice No.
df["Invoice No."] = df.get("Invoice No.", "")
has_invoice = df["Invoice No."].astype(str).str.strip() != ""
df_with_invoice = df[has_invoice].copy()
df_blank_invoice = df[~has_invoice].copy()

if not df_with_invoice.empty:
    agg = (
        df_with_invoice.groupby("Invoice No.", dropna=False)
        .agg(
            {
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
        .reset_index()
    )
else:
    agg = pd.DataFrame(columns=["Invoice No.", "_parsed_date", "Vehicle No.", "From", "Customer Name", "To", "Vehicle Type", "Case", "Jar"]) 

if not df_blank_invoice.empty:
    for c in ["_parsed_date", "Vehicle No.", "From", "Customer Name", "To", "Vehicle Type", "Case", "Jar"]:
        if c not in df_blank_invoice.columns:
            df_blank_invoice[c] = pd.NA
    df_blank_invoice["Case"] = df_blank_invoice["Case"].astype(float)
    df_blank_invoice["Jar"] = df_blank_invoice["Jar"].astype(float)
    blank_agg = df_blank_invoice[["Invoice No.", "_parsed_date", "Vehicle No.", "From", "Customer Name", "To", "Vehicle Type", "Case", "Jar"]].copy()
    agg = pd.concat([agg, blank_agg], ignore_index=True, sort=False)

agg["_parsed_date"] = pd.to_datetime(agg["_parsed_date"], errors="coerce")
agg = agg.sort_values("_parsed_date", na_position="last").reset_index(drop=True)
agg["Date"] = agg["_parsed_date"].dt.strftime("%d-%b-%y").fillna("")


def _maybe_int(x):
    try:
        if pd.isna(x):
            return 0
        f = float(x)
        return int(f) if f == int(f) else f
    except Exception:
        return x

agg["Case"] = agg["Case"].apply(_maybe_int)
agg["Jar"] = agg["Jar"].apply(_maybe_int)

agg.insert(0, "Sr No.", range(1, len(agg) + 1))

final_cols = [c for c in COLUMNS if c in agg.columns]
final = agg[final_cols]

print(final.to_string(index=False))
