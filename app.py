import base64
import concurrent.futures
import difflib
import io
import importlib
import json
import os
import re
import sqlite3
import time
from datetime import date, datetime, timedelta

import pandas as pd
import pypdf
import streamlit as st
from google import genai
from google.genai import types
from openai import OpenAI
from PIL import Image

from customer_master import (
    apply_customer_master_lookup,
    build_customer_lookup,
    load_customer_master,
)
from excel_export import build_excel_workbook, excel_export_filename
from freight_master import (
    apply_freight_lookup,
    build_freight_lookup,
    normalize_loading_point,
    short_origin,
)

# Streamlit Cloud can hot-reload this entrypoint while retaining an older
# imported module in the worker process. Reload the local history module before
# importing its API so app.py and invoice_history.py cannot get out of sync.
import invoice_history

importlib.reload(invoice_history)

from invoice_history import (
    filter_unprocessed_uploads,
    get_processed_invoice,
    init_invoice_history_database,
    log_gemini_usage,
    search_processed_invoices,
    store_new_invoice_records,
    store_processed_invoice,
    store_processed_uploads,
)
from billing_statement import (
    SUMMARY_COLUMNS,
    billing_statement_filename,
    build_billing_statement,
    build_billing_statement_workbook,
)

try:
    streamlit_api_key = st.secrets.get("GOOGLE_API_KEY", "")
    streamlit_openai_api_key = st.secrets.get("OPENAI_API_KEY", "")
except st.errors.StreamlitSecretNotFoundError:
    streamlit_api_key = ""
    streamlit_openai_api_key = ""

API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GENAI_API_KEY") or streamlit_api_key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or streamlit_openai_api_key
OPENAI_MODEL = "gpt-5.6"
OPENAI_MAX_WORKERS = 4
MODEL_FALLBACKS = [
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
]
MAX_RETRIES = 2
INITIAL_BACKOFF_SECONDS = 4
GEMINI_TOTAL_TIMEOUT_SECONDS = 60
DATABASE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "billing_history.db")

PREMIUM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

    html, body, [data-testid="stAppViewContainer"] {
        background-color: #F8F9FA;
        color: #111111;
        font-family: 'Inter', 'Helvetica Neue', sans-serif;
    }

    .main .block-container {
        max-width: 1180px;
        padding-top: 2rem;
        padding-bottom: 2rem;
    }

    .premium-title-wrap {
        margin-bottom: 1.2rem;
    }

    .title-kicker {
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.18em;
        color: #D32F2F;
        text-transform: uppercase;
        margin-bottom: 0.35rem;
    }

    .premium-title {
        margin: 0;
        font-size: 3rem;
        line-height: 1.05;
        font-weight: 800;
        color: #111111;
        letter-spacing: -0.03em;
    }

    .premium-title span {
        color: #D32F2F;
    }

    .onboarding-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 1rem;
        margin: 1.4rem 0 1.8rem;
    }

    .onboarding-card {
        background: #FFFFFF;
        border: 1px solid rgba(17, 17, 17, 0.08);
        border-radius: 18px;
        padding: 1rem 1.05rem;
        box-shadow: 0 10px 28px rgba(17, 17, 17, 0.08);
    }

    .onboarding-step {
        display: inline-block;
        margin-bottom: 0.65rem;
        padding: 0.28rem 0.55rem;
        border-radius: 999px;
        background: rgba(211, 47, 47, 0.1);
        color: #D32F2F;
        font-size: 0.82rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }

    .onboarding-card h4 {
        margin: 0 0 0.4rem 0;
        color: #111111;
        font-size: 1.05rem;
        font-weight: 700;
    }

    .onboarding-card p {
        margin: 0;
        color: #111111;
        font-size: 0.95rem;
        line-height: 1.55;
    }

    [data-testid="stFileUploader"] section {
        background: #FFFFFF;
        border: 1px solid rgba(17, 17, 17, 0.12);
        border-radius: 16px;
        box-shadow: 0 8px 24px rgba(17, 17, 17, 0.08);
        transition: border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease;
    }

    [data-testid="stFileUploader"] section:hover {
        border-color: #D32F2F;
        box-shadow: 0 12px 30px rgba(211, 47, 47, 0.14);
        transform: translateY(-1px);
    }

    [data-testid="stFileUploader"] button,
    [data-testid="stBaseButton-secondary"] button,
    div[data-testid="stButton"] > button,
    button[kind="primary"] {
        background: #D32F2F !important;
        color: #FFFFFF !important;
        border: 1px solid #D32F2F !important;
        border-radius: 12px;
        font-weight: 700;
        letter-spacing: 0.01em;
        padding: 0.75rem 1.15rem;
        box-shadow: 0 10px 24px rgba(211, 47, 47, 0.18);
        transition: all 180ms ease;
    }

    [data-testid="stFileUploader"] button:hover,
    [data-testid="stBaseButton-secondary"] button:hover,
    div[data-testid="stButton"] > button:hover,
    button[kind="primary"]:hover {
        background: #B71C1C !important;
        border-color: #B71C1C !important;
        box-shadow: 0 14px 30px rgba(183, 28, 28, 0.3);
        transform: translateY(-1px);
    }

    [data-testid="stFileUploader"] div[data-testid="stFileUploaderFileLink"] {
        color: #111111 !important;
        background: #FFFFFF !important;
        border: 1px solid rgba(17, 17, 17, 0.12);
        border-radius: 10px;
        padding: 0.25rem 0.5rem;
    }

    [data-testid="stFileUploader"] div[data-testid="stFileUploaderFileLink"] span,
    [data-testid="stFileUploader"] div[data-testid="stFileUploaderFileLink"] p,
    [data-testid="stFileUploader"] div[data-testid="stFileUploaderFileLink"] * {
        color: #111111 !important;
    }

    [data-testid="stFileUploader"] [data-testid="stWidgetLabel"],
    [data-testid="stFileUploader"] .st-emotion-cache-1h9usn1,
    [data-testid="stFileUploader"] .st-emotion-cache-17rjhe1,
    [data-testid="stFileUploader"] .st-emotion-cache-1xsdgfe,
    [data-testid="stFileUploader"] .st-emotion-cache-1v0mbdj,
    [data-testid="stFileUploader"] .st-emotion-cache-1ya1qef,
    [data-testid="stFileUploader"] p,
    [data-testid="stFileUploader"] span,
    [data-testid="stFileUploader"] div {
        color: #111111 !important;
    }

    [data-testid="stFileUploader"] button,
    [data-testid="stFileUploader"] button * {
        color: #FFFFFF !important;
    }

    [data-testid="stDataFrame"],
    [data-testid="stDataEditor"] {
        border: 1px solid rgba(17, 17, 17, 0.10);
        border-radius: 16px;
        overflow: hidden;
        box-shadow: 0 10px 28px rgba(17, 17, 17, 0.08);
        background: #FFFFFF;
    }

    [data-testid="stDataFrame"] > div,
    [data-testid="stDataEditor"] > div {
        border-radius: 16px;
    }

    [data-testid="stDataFrame"] table,
    [data-testid="stDataEditor"] table,
    [data-testid="stDataFrame"] th,
    [data-testid="stDataEditor"] th,
    [data-testid="stDataFrame"] td,
    [data-testid="stDataEditor"] td {
        background: #f7f8fa !important;
        color: #111111 !important;
        border-color: rgba(17, 17, 17, 0.08) !important;
    }

    [data-testid="stDataFrame"] th {
        background: #e8eaed !important;
        color: #111111 !important;
    }

    [data-testid="stDataFrame"] tr:nth-child(odd) td,
    [data-testid="stDataEditor"] tr:nth-child(odd) td {
        background: #f7f8fa !important;
    }

    [data-testid="stDataFrame"] tr:nth-child(even) td,
    [data-testid="stDataEditor"] tr:nth-child(even) td {
        background: #ffffff !important;
    }

    div[data-testid="stDownloadButton"] > button,
    [data-testid="stDownloadButton"] button {
        background: #2E7D32 !important;
        color: #FFFFFF !important;
        border: 1px solid #2E7D32 !important;
        border-radius: 8px !important;
    }

    div[data-testid="stDownloadButton"] > button *,
    [data-testid="stDownloadButton"] button * {
        color: #FFFFFF !important;
    }

    .section-label {
        margin: 0.9rem 0 0.5rem;
        color: #111111;
        font-size: 1.08rem;
        font-weight: 700;
        letter-spacing: 0.01em;
    }

    .upload-status {
        margin: 0 0 1.35rem 0;
        padding: 0.85rem 1rem;
        background: #1B5E20;
        border: 1px solid #2E7D32;
        border-left: 4px solid #2E7D32;
        border-radius: 12px;
        color: #FFFFFF;
        font-weight: 700;
        box-shadow: 0 8px 22px rgba(17, 17, 17, 0.08);
    }

    div[data-testid="stNotification"] {
        background: #1B5E20;
        border: 1px solid #2E7D32;
        border-left: 4px solid #2E7D32;
        border-radius: 12px;
        box-shadow: 0 8px 22px rgba(17, 17, 17, 0.08);
    }

    div[data-testid="stNotification"] * {
        color: #FFFFFF !important;
    }

    div[data-testid="stDialog"] button[kind="tertiary"] {
        background: transparent !important;
        color: #D32F2F !important;
        border: 0 !important;
        box-shadow: none !important;
        padding: 0.25rem 0 !important;
        white-space: nowrap;
    }

    div[data-testid="stDialog"] button[kind="tertiary"]:hover {
        background: transparent !important;
        color: #B71C1C !important;
        border: 0 !important;
        box-shadow: none !important;
        transform: none;
        text-decoration: underline;
    }
</style>
"""

COLUMNS = [
    "Date",
    "Invoice No.",
    "Vehicle No.",
    "From",
    "Customer Code",
    "Customer Name",
    "To",
    "Vehicle Type",
    "Case",
    "Jar",
    "Freight Charge",
    "Lookup Status",
]

MIME_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "pdf": "application/pdf",
}

SYSTEM_INSTRUCTION = """
You are auditing a combined batch of logistics delivery sheets for Ubiquity Transtech.
Scan all attached documents together and extract every single distinct trip row you find across all files.

Return ONLY a single valid JSON list of objects. Each object represents one invoice trip row and must contain exactly these keys:
- "Date" (format: DD-MMM-YY, e.g. 25-May-26)
- "Invoice No."
- "Vehicle No."
- "From"
- "Loading Point"
- "Customer Code"
- "Customer Name"
- "To"
- "Vehicle Type"
- "Case"
- "Jar"
- "items" (an array of product-line objects)

Rules:
- Treat all attached documents as one consolidated batch and aggregate the final result across the whole upload.
- Extract the "Shipped To" section in this exact order: Customer Code, Customer Name, address lines, then administrative fields.
- "Loading Point": extract the invoice origin from the "Shipped From" section only. Normalize it to exactly one of Thane, Vasai, Andheri, Vidya Vihar, Bhiwandi, Kandivali, PRPL, Wada, Mahul, Khopoli, or Kamshet. Use null when it cannot be determined.
- "Customer Code": extract only the value after "Customer Code :" (or "Customer Code:") in the "Shipped To" section. Do not use any other identifier.
- "Customer Name": extract ONLY the first text line immediately after Customer Code. It must be exactly one business/company name and must not contain any address text.
- "To": begin immediately AFTER the Customer Name. Concatenate every subsequent physical-address line, in order, into one value. Stop before the first administrative field: State Code, GSTIN, PAN, Phone, Email, FSSAI, Payment Terms, or any tax identifier.
- "To" must contain delivery-address text only. Never include Customer Name, Customer Code, GSTIN, or any administrative field or value.
- Example: for "Customer Code : MUMCO02703" followed by "SANTKRIPA DUGDHALAYA(KALYAN-E)", then "GODAVARI BLDG SHOP NO 4 LOKGRAM", "KALYAN CITY NETIVALI KALYAN EAST", "THANE 421306", and then "State Code : MH": Customer Name is "SANTKRIPA DUGDHALAYA(KALYAN-E)" and To is "GODAVARI BLDG SHOP NO 4 LOKGRAM, KALYAN CITY, NETIVALI, KALYAN EAST, THANE 421306".
- Extract EVERY product line exactly as printed on the invoice into "items". Each item must contain exactly "description" (the complete printed product description) and "qty" (the printed quantity).
- Keep every product row separate. Never combine rows, total quantities, or classify any item as Case or Jar.
- Always include "Case" and "Jar" with a value of 0. Do not calculate their totals; their values will be calculated from "items" after extraction.
- Vehicle Type should default to "9MT" when it is not clearly visible.
- Do not include any markdown fences, commentary, or notes. Return raw JSON only.
""".strip()


def file_to_part(uploaded_file):
    file_bytes = uploaded_file.getvalue()
    extension = uploaded_file.name.rsplit(".", 1)[-1].lower()
    mime_type = MIME_TYPES[extension]

    if extension in {"png", "jpg", "jpeg"}:
        Image.open(io.BytesIO(file_bytes))
    elif extension == "pdf":
        pypdf.PdfReader(io.BytesIO(file_bytes))

    return types.Part.from_bytes(data=file_bytes, mime_type=mime_type)


def extract_json_text(raw_text):
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def is_jar_item(description):
    normalized = str(description).upper()
    return bool(re.search(r"(?<!\d)20[\s.\-]*LTR", normalized))


def parse_item_quantity(item):
    quantity = item.get("quantity") if item.get("quantity") is not None else item.get("qty")
    if quantity is None:
        return 0.0

    if isinstance(quantity, (int, float)):
        return float(quantity)

    if isinstance(quantity, str):
        cleaned = quantity.replace(",", "")
        match = re.search(r"[-+]?\d*\.?\d+", cleaned)
        if match:
            try:
                return float(match.group())
            except ValueError:
                return 0.0
    return 0.0


def apply_case_jar_logic(record):
    case_qty = 0.0
    jar_qty = 0.0

    items = record.get("items", [])
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue

            description = str(item.get("description", ""))
            quantity = parse_item_quantity(item)

            if is_jar_item(description):
                jar_qty += quantity
            else:
                case_qty += quantity

    case_value = 0
    jar_value = 0
    if case_qty:
        case_value = int(case_qty) if case_qty == int(case_qty) else case_qty
    if jar_qty:
        jar_value = int(jar_qty) if jar_qty == int(jar_qty) else jar_qty

    record["Case"] = case_value
    record["Jar"] = jar_value
    record.pop("items", None)

    customer_code = record.get("Customer Code", "")
    if customer_code is None:
        customer_code = ""
    else:
        customer_code = str(customer_code).strip().upper().replace(" ", "")

    loading_point = normalize_loading_point(record.get("Loading Point"))

    return {
        "Date": record.get("Date", ""),
        "Invoice No.": record.get("Invoice No.", record.get("Invoice No", "")),
        "Vehicle No.": record.get("Vehicle No.", record.get("Vehicle No", "")),
        "From": short_origin(record.get("From", ""), loading_point),
        "Loading Point": loading_point,
        "Customer Code": customer_code,
        "Customer Name": record.get("Customer Name", ""),
        "To": record.get("To", ""),
        "Vehicle Type": record.get("Vehicle Type", "") or "9MT",
        "Case": case_value,
        "Jar": jar_value,
    }


def parse_gemini_response(raw_text):
    payload = json.loads(extract_json_text(raw_text))
    if isinstance(payload, dict):
        payload = payload.get("trips") or payload.get("records") or payload.get("data") or [payload]
    if not isinstance(payload, list):
        raise ValueError("Gemini response must be a JSON array of trip records.")

    processed_records = []
    for record in payload:
        if not isinstance(record, dict):
            continue

        items = record.get("items", [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    print(
                        f'description="{item.get("description", "")}" '
                        f'qty={item.get("qty", item.get("quantity", ""))}'
                    )
        processed_record = apply_case_jar_logic(record)
        print(
            "DEBUG recalculated quantities after apply_case_jar_logic "
            f"(invoice={processed_record.get('Invoice No.', '')}): "
            f"Case={processed_record.get('Case', 0)}, Jar={processed_record.get('Jar', 0)}"
        )
        processed_records.append(processed_record)

    return processed_records


def build_batch_content_parts(uploaded_files):
    content_parts = []
    for uploaded_file in uploaded_files:
        content_parts.append(
            types.Part.from_text(text=f"Document: {uploaded_file.name}")
        )
        content_parts.append(file_to_part(uploaded_file))
    return content_parts


def build_openai_content(uploaded_files):
    content = [
        {
            "type": "input_text",
            "text": "Extract every distinct invoice trip row from all attached documents.",
        }
    ]
    for uploaded_file in uploaded_files:
        file_bytes = uploaded_file.getvalue()
        extension = uploaded_file.name.rsplit(".", 1)[-1].lower()
        mime_type = MIME_TYPES[extension]
        encoded = base64.b64encode(file_bytes).decode("ascii")
        content.append({"type": "input_text", "text": f"Document: {uploaded_file.name}"})
        if extension == "pdf":
            content.append(
                {
                    "type": "input_file",
                    "filename": uploaded_file.name,
                    "file_data": f"data:{mime_type};base64,{encoded}",
                }
            )
        else:
            content.append(
                {
                    "type": "input_image",
                    "image_url": f"data:{mime_type};base64,{encoded}",
                    "detail": "original",
                }
            )
    return content


OPENAI_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "records": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "Date": {"type": "string"},
                    "Invoice No.": {"type": "string"},
                    "Vehicle No.": {"type": "string"},
                    "From": {"type": "string"},
                    "Loading Point": {"type": ["string", "null"]},
                    "Customer Code": {"type": "string"},
                    "Customer Name": {"type": "string"},
                    "To": {"type": "string"},
                    "Vehicle Type": {"type": "string"},
                    "Case": {"type": "number"},
                    "Jar": {"type": "number"},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "description": {"type": "string"},
                                "qty": {"type": ["number", "string"]},
                            },
                            "required": ["description", "qty"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": [
                    "Date", "Invoice No.", "Vehicle No.", "From", "Loading Point",
                    "Customer Code", "Customer Name", "To", "Vehicle Type", "Case",
                    "Jar", "items",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["records"],
    "additionalProperties": False,
}


def analyze_bills_with_openai(uploaded_files):
    if not OPENAI_API_KEY:
        raise ValueError(
            "Gemini produced no result and OPENAI_API_KEY is not configured."
        )

    def analyze_one_file(uploaded_file):
        openai_instruction = f"""
{SYSTEM_INSTRUCTION}

OpenAI fallback accuracy rules:
- This request contains exactly one uploaded document named {uploaded_file.name!r}.
- Inspect the original-resolution document carefully and transcribe identifiers character by character.
- Do not guess obscured digits or silently substitute similar-looking characters.
- Pay special attention to Invoice No., Customer Code, Customer Name, Vehicle No., and every item quantity.
- Customer Code normally begins with MUMC. Preserve every following digit exactly as printed.
- Extract every visible product row. A 20 LTR product is a Jar; all other product rows are Cases.
- Still return Case and Jar as 0 because the application calculates them from the extracted items.
- Return one record when the document contains one invoice. Return multiple records only when the
  document visibly contains multiple distinct invoices.
""".strip()
        last_error = None
        for _ in range(2):
            try:
                response = OpenAI(
                    api_key=OPENAI_API_KEY,
                    timeout=180.0,
                ).responses.create(
                    model=OPENAI_MODEL,
                    instructions=openai_instruction,
                    input=[
                        {
                            "role": "user",
                            "content": build_openai_content([uploaded_file]),
                        }
                    ],
                    reasoning={"effort": "high"},
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "invoice_trip_rows",
                            "strict": True,
                            "schema": OPENAI_RESPONSE_SCHEMA,
                        }
                    },
                    store=False,
                )
                records = parse_gemini_response(response.output_text)
                if records:
                    return records
                last_error = ValueError(
                    f"OpenAI returned no invoice for {uploaded_file.name}."
                )
            except Exception as error:
                last_error = error

        raise ValueError(
            f"OpenAI could not extract a usable invoice from {uploaded_file.name}: "
            f"{last_error}"
        )

    worker_count = min(OPENAI_MAX_WORKERS, len(uploaded_files))
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        per_file_records = list(executor.map(analyze_one_file, uploaded_files))

    records = [record for file_records in per_file_records for record in file_records]
    records = repair_openai_customer_identifiers(records)
    if not records:
        raise ValueError("OpenAI also returned no invoice records for this batch.")
    return records


def _identifier_distance(left, right):
    previous = list(range(len(right) + 1))
    for left_index, left_character in enumerate(left, 1):
        current = [left_index]
        for right_index, right_character in enumerate(right, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_character != right_character),
                )
            )
        previous = current
    return previous[-1]


def _normalized_customer_name(value):
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def repair_openai_customer_identifiers(records):
    """Repair only high-confidence OCR slips using the authoritative customer master."""
    customer_lookup = build_customer_lookup(load_customer_master())
    names_to_codes = {}
    for code, customer in customer_lookup.items():
        normalized_name = _normalized_customer_name(customer.get("Customer Name"))
        if normalized_name:
            names_to_codes.setdefault(normalized_name, []).append(code)

    repaired_records = []
    for record in records:
        repaired_record = record.copy()
        extracted_code = str(repaired_record.get("Customer Code", "") or "").strip().upper()
        extracted_code = re.sub(r"\s+", "", extracted_code)
        if extracted_code in customer_lookup:
            repaired_records.append(repaired_record)
            continue

        extracted_name = _normalized_customer_name(
            repaired_record.get("Customer Name", "")
        )
        exact_name_codes = names_to_codes.get(extracted_name, [])
        if len(exact_name_codes) == 1:
            repaired_record["Customer Code"] = exact_name_codes[0]
            repaired_records.append(repaired_record)
            continue

        nearby_codes = [
            code
            for code in customer_lookup
            if _identifier_distance(extracted_code, code) <= 1
        ]
        if len(nearby_codes) == 1:
            repaired_record["Customer Code"] = nearby_codes[0]
            repaired_records.append(repaired_record)
            continue

        if extracted_name and nearby_codes:
            scored_codes = sorted(
                (
                    difflib.SequenceMatcher(
                        None,
                        extracted_name,
                        _normalized_customer_name(
                            customer_lookup[code].get("Customer Name")
                        ),
                    ).ratio(),
                    code,
                )
                for code in nearby_codes
            )
            best_score, best_code = scored_codes[-1]
            next_score = scored_codes[-2][0] if len(scored_codes) > 1 else 0
            if best_score >= 0.88 and best_score - next_score >= 0.08:
                repaired_record["Customer Code"] = best_code

        repaired_records.append(repaired_record)

    return repaired_records


def is_retryable_error(error):
    error_text = f"{type(error).__name__}: {error}".lower()
    retry_tokens = [
        "503",
        "service unavailable",
        "temporarily unavailable",
        "overloaded",
        "429",
        "resource exhausted",
        "too many requests",
        "rate limit",
        "502",
        "504",
        "500",
        "backend error",
    ]
    return any(token in error_text for token in retry_tokens)


def analyze_bills(uploaded_files):
    if not API_KEY:
        raise ValueError(
            "Missing API key. Set GOOGLE_API_KEY in the environment or add it to Streamlit secrets."
        )

    gemini_started_at = time.monotonic()
    gemini_deadline = gemini_started_at + GEMINI_TOTAL_TIMEOUT_SECONDS
    client = genai.Client(api_key=API_KEY)
    content_parts = build_batch_content_parts(uploaded_files)

    last_error = None
    for model_name in MODEL_FALLBACKS:
        for attempt in range(1, MAX_RETRIES + 1):
            remaining_seconds = gemini_deadline - time.monotonic()
            if remaining_seconds <= 0:
                last_error = TimeoutError(
                    f"Gemini exceeded the {GEMINI_TOTAL_TIMEOUT_SECONDS}-second limit."
                )
                break
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=content_parts,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        http_options=types.HttpOptions(
                            timeout=max(1, int(remaining_seconds * 1000)),
                            retry_options=types.HttpRetryOptions(attempts=1),
                        ),
                    ),
                )
                if time.monotonic() >= gemini_deadline:
                    last_error = TimeoutError(
                        f"Gemini exceeded the {GEMINI_TOTAL_TIMEOUT_SECONDS}-second limit."
                    )
                    break
                print("DEBUG raw Gemini response before parse_gemini_response:")
                print(response.text)
            except Exception as e:
                last_error = e
                error_text = str(e).lower()

                if "not_found" in error_text or "not found" in error_text:
                    st.warning(f"Model {model_name} unavailable; switching to next available model.")
                    break

                if not is_retryable_error(e):
                    st.warning(
                        f"Gemini could not produce a result on {model_name}; "
                        "trying the next available model."
                    )
                    break

                if attempt < MAX_RETRIES:
                    remaining_seconds = gemini_deadline - time.monotonic()
                    if remaining_seconds <= 0:
                        break
                    st.warning(
                        f"Google servers busy on {model_name}; retrying in 4 seconds... ({attempt}/{MAX_RETRIES})"
                    )
                    time.sleep(min(INITIAL_BACKOFF_SECONDS, remaining_seconds))
                    continue

                st.warning(f"Exhausted retries for {model_name}; trying the next available model.")
                break

            log_gemini_usage(
                model_name,
                getattr(response, "model_version", ""),
                len(uploaded_files),
                getattr(response, "usage_metadata", None),
                DATABASE_PATH,
            )
            try:
                records = parse_gemini_response(response.text)
            except (json.JSONDecodeError, TypeError, ValueError) as error:
                last_error = error
                st.warning(
                    f"Gemini returned no usable result on {model_name}; trying the next model."
                )
                break
            if records:
                return records
            last_error = ValueError(f"Gemini model {model_name} returned zero records.")
            st.warning(f"Gemini returned no records on {model_name}; trying the next model.")
            break

        if time.monotonic() >= gemini_deadline:
            break

    if OPENAI_API_KEY:
        if isinstance(last_error, TimeoutError):
            st.warning(
                "Gemini did not finish within 1 minute. Switching this batch to OpenAI."
            )
        else:
            st.warning(
                "Gemini could not produce a result with any available model. "
                "Switching this batch to OpenAI."
            )
        return analyze_bills_with_openai(uploaded_files)

    if last_error is not None:
        raise last_error

    return []


def init_database():
    """Create the lightweight invoice-processing history store when needed."""
    with sqlite3.connect(DATABASE_PATH) as connection:
        existing_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(billing_history)").fetchall()
        }
        if existing_columns and "id" not in existing_columns:
            connection.execute(
                "ALTER TABLE billing_history RENAME TO billing_history_legacy"
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS billing_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_no TEXT NOT NULL,
                processed_timestamp TEXT NOT NULL
            )
            """
        )
        if existing_columns and "id" not in existing_columns:
            connection.execute(
                """
                INSERT INTO billing_history (invoice_no, processed_timestamp)
                SELECT invoice_no, processed_timestamp
                FROM billing_history_legacy
                """
            )
            connection.execute("DROP TABLE billing_history_legacy")


def log_processed_invoice(invoice_no, database_path=DATABASE_PATH):
    """Record one successful processing event for dashboard reporting."""
    normalized_invoice_no = str(invoice_no or "").strip()
    if not normalized_invoice_no:
        return

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO billing_history (invoice_no, processed_timestamp)
            VALUES (?, ?)
            """,
            (normalized_invoice_no, datetime.now().isoformat(timespec="seconds")),
        )


def _get_processed_count(start_date, end_date):
    with sqlite3.connect(DATABASE_PATH) as connection:
        result = connection.execute(
            """
            SELECT COUNT(*)
            FROM billing_history
            WHERE DATE(processed_timestamp) BETWEEN ? AND ?
            """,
            (start_date.isoformat(), end_date.isoformat()),
        ).fetchone()
    return result[0]


def get_today_count():
    today = date.today()
    return _get_processed_count(today, today)


def get_week_count():
    today = date.today()
    return _get_processed_count(today - timedelta(days=today.weekday()), today)


def get_month_count():
    today = date.today()
    return _get_processed_count(today.replace(day=1), today)


def get_custom_count(start_date, end_date):
    if start_date > end_date:
        return 0
    return _get_processed_count(start_date, end_date)


def format_processed_timestamp(timestamp):
    try:
        return datetime.fromisoformat(timestamp).strftime("%d-%b-%Y %I:%M %p")
    except (TypeError, ValueError):
        return str(timestamp or "")


def format_history_freight_charge(value):
    if value in (None, ""):
        return ""
    try:
        return f"₹ {float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


@st.dialog("Processed Invoice Details")
def show_processed_invoice_dialog(invoice):
    details = (
        ("Date Processed", format_processed_timestamp(invoice["processed_timestamp"])),
        ("Invoice Date", invoice["invoice_date"]),
        ("Invoice Number", invoice["invoice_number"]),
        ("Vehicle Number", invoice["vehicle_number"]),
        ("Customer Code", invoice["customer_code"]),
        ("Customer Name", invoice["customer_name"]),
        ("From", invoice["origin"]),
        ("To", invoice["destination"]),
        ("Vehicle Type", invoice["vehicle_type"]),
        ("Cases", invoice["cases"]),
        ("Jars", invoice["jars"]),
        ("Freight Charge", format_history_freight_charge(invoice["freight_charge"])),
        ("Lookup Status", invoice["lookup_status"]),
    )
    for label, value in details:
        label_column, value_column = st.columns([0.38, 0.62])
        label_column.markdown(f"**{label}**")
        value_column.write("" if value is None else value)

    if st.button("Close", key="close_processed_invoice_dialog"):
        st.session_state["selected_history_invoice_id"] = None
        st.rerun()


def render_processed_invoice_history(database_path):
    search_query = st.text_input(
        "Search invoice history",
        placeholder="Search by invoice number or customer name",
        key="processed_invoice_history_search",
    )
    history_rows = search_processed_invoices(search_query, database_path)

    with st.container(height=360, border=True):
        header_columns = st.columns([1.5, 1.5, 2.2, 1.2, 0.7])
        for column, label in zip(
            header_columns,
            (
                "Date Processed",
                "Invoice Number",
                "Customer Name",
                "Freight Charge",
                "Actions",
            ),
        ):
            column.markdown(f"**{label}**")

        if not history_rows:
            st.caption("No processed invoices found.")

        for row in history_rows:
            columns = st.columns([1.5, 1.5, 2.2, 1.2, 0.7])
            columns[0].write(format_processed_timestamp(row["processed_timestamp"]))
            columns[1].write(row["invoice_number"] or "")
            columns[2].write(row["customer_name"] or "")
            columns[3].write(format_history_freight_charge(row["freight_charge"]))
            if columns[4].button("View", key=f"view_processed_invoice_{row['id']}"):
                st.session_state["selected_history_invoice_id"] = row["id"]

    selected_history_id = st.session_state.get("selected_history_invoice_id")
    if selected_history_id is not None:
        selected_invoice = get_processed_invoice(selected_history_id, database_path)
        if selected_invoice is not None:
            show_processed_invoice_dialog(selected_invoice)


@st.dialog("Duplicate Invoices", width="large")
def show_duplicate_invoice_dialog(database_path):
    duplicates = st.session_state.get("duplicate_invoices", [])

    if duplicates:
        _, reupload_all_column = st.columns([4.8, 1.2])
        if reupload_all_column.button(
            "Re-Upload All",
            key="reupload_all_duplicates",
            type="primary",
        ):
            records = [duplicate["record"] for duplicate in duplicates]
            for record in records:
                store_processed_invoice(record, database_path)
                log_processed_invoice(
                    record.get("Invoice No.", record.get("Invoice No", "")),
                    database_path,
                )

            reuploaded_data = pd.DataFrame(records, columns=COLUMNS)
            current_bill_data = st.session_state.get("bill_data")
            if current_bill_data is None or current_bill_data.empty:
                st.session_state["bill_data"] = reuploaded_data
            else:
                st.session_state["bill_data"] = pd.concat(
                    [current_bill_data, reuploaded_data],
                    ignore_index=True,
                )

            st.session_state["processing_new_count"] = (
                st.session_state.get("processing_new_count", 0) + len(records)
            )
            st.session_state["duplicate_invoices"] = []
            st.session_state["show_duplicate_invoice_details"] = False
            st.rerun()

    header_columns = st.columns([1.5, 2.2, 1.7, 1.2])
    for column, label in zip(
        header_columns,
        (
            "Invoice Number",
            "Customer Name",
            "Previously Processed On",
            "Action",
        ),
    ):
        column.markdown(f"**{label}**")

    for index, duplicate in enumerate(duplicates):
        record = duplicate["record"]
        previous = duplicate["previous"]
        columns = st.columns([1.5, 2.2, 1.7, 1.2])
        columns[0].write(record.get("Invoice No.", record.get("Invoice No", "")))
        columns[1].write(record.get("Customer Name", ""))
        columns[2].write(format_processed_timestamp(previous["processed_timestamp"]))
        if columns[3].button(
            "Re-upload anyway",
            key=f"reupload_duplicate_{index}",
            type="tertiary",
        ):
            store_processed_invoice(record, database_path)
            log_processed_invoice(
                record.get("Invoice No.", record.get("Invoice No", "")),
                database_path,
            )
            current_bill_data = st.session_state.get("bill_data")
            reuploaded_data = pd.DataFrame([record], columns=COLUMNS)
            if current_bill_data is None or current_bill_data.empty:
                st.session_state["bill_data"] = reuploaded_data
            else:
                st.session_state["bill_data"] = pd.concat(
                    [current_bill_data, reuploaded_data],
                    ignore_index=True,
                )
            st.session_state["processing_new_count"] += 1
            del st.session_state["duplicate_invoices"][index]
            st.rerun()

    if not duplicates:
        st.caption("No skipped duplicate invoices remain.")

    if st.button("Close", key="close_duplicate_invoice_dialog"):
        st.session_state["show_duplicate_invoice_details"] = False
        st.rerun()


def render_processing_summary(database_path):
    if "processing_new_count" not in st.session_state:
        return

    duplicate_count = len(st.session_state.get("duplicate_invoices", []))
    st.markdown('<div class="section-label">Processing Complete</div>', unsafe_allow_html=True)
    st.write(f"New invoices processed: {st.session_state['processing_new_count']}")
    st.write(f"Duplicate invoices skipped: {duplicate_count}")

    if duplicate_count and st.button("View Details", key="view_duplicate_invoice_details"):
        st.session_state["show_duplicate_invoice_details"] = True

    if st.session_state.get("show_duplicate_invoice_details", False):
        show_duplicate_invoice_dialog(database_path)


st.set_page_config(
    page_title="Transtech Bill Desk",
    page_icon="",
    layout="wide",
)

st.markdown(PREMIUM_CSS, unsafe_allow_html=True)

st.markdown(
    """
    <div class="premium-title-wrap">
        <div class="title-kicker">Billing Operations Suite</div>
        <h1 class="premium-title">Transtech <span>Bill Desk</span></h1>
    </div>
    """,
    unsafe_allow_html=True,
)

init_database()
init_invoice_history_database(DATABASE_PATH)

st.markdown('<div class="section-label">Billing Dashboard</div>', unsafe_allow_html=True)
today_column, week_column, month_column = st.columns(3)
for column, label, value in (
    (today_column, "Today's Bills", get_today_count()),
    (week_column, "This Week", get_week_count()),
    (month_column, "This Month", get_month_count()),
):
    with column:
        st.markdown(
            f"""
            <div class="onboarding-card">
                <h4>{label}</h4>
                <p>{value:,}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.markdown('<div style="height: 1rem;"></div>', unsafe_allow_html=True)

if st.button("Processed Invoice History", key="toggle_processed_invoice_history"):
    st.session_state["show_processed_invoice_history"] = not st.session_state.get(
        "show_processed_invoice_history",
        False,
    )

if st.session_state.get("show_processed_invoice_history", False):
    render_processed_invoice_history(DATABASE_PATH)

st.markdown('<div class="section-label">Custom Report</div>', unsafe_allow_html=True)
from_column, to_column, generate_column = st.columns([1, 1, 0.7])
with from_column:
    start_date = st.date_input("From Date", value=date.today(), key="custom_report_start")
with to_column:
    end_date = st.date_input("To Date", value=date.today(), key="custom_report_end")
with generate_column:
    st.write("")
    generate_report = st.button("Generate", key="generate_custom_report")

if generate_report:
    if start_date > end_date:
        st.error("From Date must be on or before To Date.")
    else:
        st.session_state["custom_report_count"] = get_custom_count(start_date, end_date)

if "custom_report_count" in st.session_state:
    st.markdown(
        f"""
        <div class="onboarding-card">
            <h4>Invoices Processed</h4>
            <p>{st.session_state['custom_report_count']:,}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown('<div class="section-label">Upload Bisleri Bills</div>', unsafe_allow_html=True)

uploaded_files = st.file_uploader(
    "Upload one or more bill images or PDFs",
    type=["png", "jpg", "jpeg", "pdf"],
    accept_multiple_files=True,
)

if uploaded_files:
    file_count = len(uploaded_files)
    st.markdown(
        f"""
        <div class="upload-status">
            {file_count} file{'s' if file_count != 1 else ''} uploaded successfully.
        </div>
        """,
        unsafe_allow_html=True,
    )

files_to_process = []
repeated_files = []
selected_repeated_files = []
if uploaded_files:
    files_to_process, repeated_files = filter_unprocessed_uploads(
        uploaded_files,
        DATABASE_PATH,
    )

if repeated_files:
    st.warning(
        f"Found {len(repeated_files)} identical file(s) that were already processed "
        "or repeated in this upload."
    )
    process_repeated_files = st.checkbox(
        "Process duplicate invoices anyway",
        key="process_duplicate_uploads_anyway",
        help="Selected files will be sent to Gemini again and may use additional credits.",
    )
    if process_repeated_files:
        with st.expander("Select duplicate files to process", expanded=True):
            selected_repeated_indexes = st.multiselect(
                "Duplicate files",
                options=list(range(len(repeated_files))),
                default=list(range(len(repeated_files))),
                format_func=lambda index: repeated_files[index].name,
                key="selected_duplicate_upload_indexes",
            )
            selected_repeated_files = [
                repeated_files[index] for index in selected_repeated_indexes
            ]

files_selected_for_processing = files_to_process + selected_repeated_files

if st.button("Process Bills", disabled=not files_selected_for_processing):
    with st.spinner("AI is analyzing documents..."):
        try:
            skipped_repeated_count = len(repeated_files) - len(selected_repeated_files)
            if skipped_repeated_count:
                st.warning(
                    f"Skipped {skipped_repeated_count} identical file(s) already processed "
                    "or repeated in this upload. No Gemini credits were used for them."
                )

            records = analyze_bills(files_selected_for_processing)
            master_data = load_customer_master()
            customer_lookup = build_customer_lookup(master_data)
            records = apply_customer_master_lookup(records, customer_lookup)
            records = apply_freight_lookup(records, build_freight_lookup(master_data))
            accepted_records, duplicates = store_new_invoice_records(
                records,
                DATABASE_PATH,
            )
            store_processed_uploads(files_selected_for_processing, DATABASE_PATH)
            for accepted_record in accepted_records:
                log_processed_invoice(
                    accepted_record.get(
                        "Invoice No.",
                        accepted_record.get("Invoice No", ""),
                    ),
                    DATABASE_PATH,
                )
            st.session_state["bill_data"] = pd.DataFrame(
                accepted_records,
                columns=COLUMNS,
            )
            st.session_state["processing_new_count"] = len(accepted_records)
            st.session_state["duplicate_invoices"] = duplicates
            st.session_state["show_duplicate_invoice_details"] = False
        except json.JSONDecodeError:
            st.error("Gemini returned invalid JSON. Please try processing again.")
        except Exception as error:
            st.error(f"Failed to process bills: {error}")

render_processing_summary(DATABASE_PATH)

if "bill_data" in st.session_state and not st.session_state["bill_data"].empty:
    st.subheader("Review & Edit Extracted Data")

    edited_df = st.data_editor(
        st.session_state["bill_data"],
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
    )

    st.session_state["bill_data"] = edited_df

    st.download_button(
        label="Download Excel",
        data=build_excel_workbook(edited_df),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        file_name=excel_export_filename(),
    )

    st.subheader("Billing Statement")
    billing_statement = build_billing_statement(edited_df)
    if billing_statement.empty:
        st.caption("No invoice entries are available for the billing statement.")
    else:
        st.dataframe(
            billing_statement[SUMMARY_COLUMNS],
            use_container_width=True,
            hide_index=True,
            height=360,
        )
        st.download_button(
            label="Download Billing Statement",
            data=build_billing_statement_workbook(billing_statement),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            file_name=billing_statement_filename(billing_statement),
        )
