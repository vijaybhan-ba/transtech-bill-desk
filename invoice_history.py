import hashlib
import os
import sqlite3
from datetime import datetime


DEFAULT_DATABASE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "billing_history.db",
)

HISTORY_COLUMNS = (
    "invoice_date",
    "invoice_number",
    "vehicle_number",
    "origin",
    "customer_code",
    "customer_name",
    "destination",
    "vehicle_type",
    "cases",
    "jars",
    "freight_charge",
    "lookup_status",
)


def init_invoice_history_database(database_path=DEFAULT_DATABASE_PATH):
    """Create the detailed, append-only processed invoice store."""
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_invoice_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                processed_timestamp TEXT NOT NULL,
                invoice_date TEXT,
                invoice_number TEXT,
                vehicle_number TEXT,
                origin TEXT,
                customer_code TEXT,
                customer_name TEXT,
                destination TEXT,
                vehicle_type TEXT,
                cases NUMERIC,
                jars NUMERIC,
                freight_charge NUMERIC,
                lookup_status TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_upload_history (
                file_hash TEXT PRIMARY KEY,
                filename TEXT,
                processed_timestamp TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS gemini_usage_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                processed_timestamp TEXT NOT NULL,
                model_requested TEXT NOT NULL,
                model_version TEXT,
                file_count INTEGER NOT NULL,
                prompt_tokens INTEGER,
                output_tokens INTEGER,
                thoughts_tokens INTEGER,
                total_tokens INTEGER
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_processed_invoice_number
            ON processed_invoice_history(invoice_number)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_processed_customer_name
            ON processed_invoice_history(customer_name)
            """
        )


def upload_digest(uploaded_file):
    """Return a stable fingerprint without trusting the uploaded filename."""
    return hashlib.sha256(uploaded_file.getvalue()).hexdigest()


def filter_unprocessed_uploads(uploaded_files, database_path=DEFAULT_DATABASE_PATH):
    """Split uploads into new files and exact byte-for-byte repeats."""
    new_files = []
    duplicate_files = []
    seen_in_batch = set()
    with sqlite3.connect(database_path) as connection:
        for uploaded_file in uploaded_files:
            file_hash = upload_digest(uploaded_file)
            already_processed = connection.execute(
                "SELECT 1 FROM processed_upload_history WHERE file_hash = ?",
                (file_hash,),
            ).fetchone()
            if already_processed is not None or file_hash in seen_in_batch:
                duplicate_files.append(uploaded_file)
                continue
            seen_in_batch.add(file_hash)
            new_files.append(uploaded_file)
    return new_files, duplicate_files


def store_processed_uploads(uploaded_files, database_path=DEFAULT_DATABASE_PATH):
    """Remember uploads only after Gemini returned a parseable result."""
    processed_timestamp = datetime.now().isoformat(timespec="seconds")
    with sqlite3.connect(database_path) as connection:
        connection.executemany(
            """
            INSERT OR IGNORE INTO processed_upload_history
                (file_hash, filename, processed_timestamp)
            VALUES (?, ?, ?)
            """,
            [
                (upload_digest(uploaded_file), uploaded_file.name, processed_timestamp)
                for uploaded_file in uploaded_files
            ],
        )


def log_gemini_usage(
    model_requested,
    model_version,
    file_count,
    usage_metadata,
    database_path=DEFAULT_DATABASE_PATH,
):
    """Persist API token accounting without storing invoice contents."""
    def usage_value(name):
        value = getattr(usage_metadata, name, None) if usage_metadata else None
        return int(value) if value is not None else None

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO gemini_usage_history (
                processed_timestamp, model_requested, model_version, file_count,
                prompt_tokens, output_tokens, thoughts_tokens, total_tokens
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(timespec="seconds"),
                model_requested,
                model_version or "",
                file_count,
                usage_value("prompt_token_count"),
                usage_value("candidates_token_count"),
                usage_value("thoughts_token_count"),
                usage_value("total_token_count"),
            ),
        )


def _sqlite_value(value):
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    return value


def _invoice_number_from_record(record):
    value = record.get("Invoice No.", record.get("Invoice No", ""))
    return str(value or "").strip()


def find_processed_invoice_by_number(
    invoice_number,
    database_path=DEFAULT_DATABASE_PATH,
):
    """Return the most recent history event for an exact invoice number."""
    normalized_invoice_number = str(invoice_number or "").strip()
    if not normalized_invoice_number:
        return None

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT
                id,
                processed_timestamp,
                invoice_number,
                customer_name
            FROM processed_invoice_history
            WHERE invoice_number = ?
            ORDER BY processed_timestamp DESC, id DESC
            LIMIT 1
            """,
            (normalized_invoice_number,),
        ).fetchone()
    return dict(row) if row is not None else None


def _insert_processed_invoice(connection, record, processed_timestamp):
    values = (
        record.get("Date", ""),
        _invoice_number_from_record(record),
        record.get("Vehicle No.", record.get("Vehicle No", "")),
        record.get("From", ""),
        record.get("Customer Code", ""),
        record.get("Customer Name", ""),
        record.get("To", ""),
        record.get("Vehicle Type", ""),
        record.get("Case", ""),
        record.get("Jar", ""),
        record.get("Freight Charge", ""),
        record.get("Lookup Status", ""),
    )
    cursor = connection.execute(
        """
        INSERT INTO processed_invoice_history (
            processed_timestamp,
            invoice_date,
            invoice_number,
            vehicle_number,
            origin,
            customer_code,
            customer_name,
            destination,
            vehicle_type,
            cases,
            jars,
            freight_charge,
            lookup_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (processed_timestamp, *(_sqlite_value(value) for value in values)),
    )
    return cursor.lastrowid


def store_processed_invoice(
    record,
    database_path=DEFAULT_DATABASE_PATH,
    processed_at=None,
):
    """Append one successfully processed invoice and return its history ID."""
    processed_timestamp = (processed_at or datetime.now()).isoformat(timespec="seconds")

    with sqlite3.connect(database_path) as connection:
        return _insert_processed_invoice(connection, record, processed_timestamp)


def store_processed_invoice_if_new(
    record,
    database_path=DEFAULT_DATABASE_PATH,
    processed_at=None,
):
    """Atomically append an invoice unless its invoice number is already stored.

    Returns ``(history_id, None)`` when inserted, or ``(None, existing_record)``
    when skipped. Records without an invoice number are stored normally because
    they cannot be identified as duplicates.
    """
    processed_timestamp = (processed_at or datetime.now()).isoformat(timespec="seconds")
    invoice_number = _invoice_number_from_record(record)

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN IMMEDIATE")
        existing = None
        if invoice_number:
            existing = connection.execute(
                """
                SELECT
                    id,
                    processed_timestamp,
                    invoice_number,
                    customer_name
                FROM processed_invoice_history
                WHERE invoice_number = ?
                ORDER BY processed_timestamp DESC, id DESC
                LIMIT 1
                """,
                (invoice_number,),
            ).fetchone()

        if existing is not None:
            return None, dict(existing)

        history_id = _insert_processed_invoice(connection, record, processed_timestamp)
        return history_id, None


def store_new_invoice_records(records, database_path=DEFAULT_DATABASE_PATH):
    """Store a batch and separate accepted records from skipped invoice numbers."""
    accepted_records = []
    duplicates_by_invoice = {}

    for record in records:
        history_id, existing = store_processed_invoice_if_new(record, database_path)
        invoice_number = _invoice_number_from_record(record)
        if history_id is None:
            duplicates_by_invoice.setdefault(
                invoice_number,
                {"record": record, "previous": existing},
            )
            continue
        accepted_records.append(record)

    return accepted_records, list(duplicates_by_invoice.values())


def search_processed_invoices(query="", database_path=DEFAULT_DATABASE_PATH):
    """Return history summaries matching an invoice number or customer name."""
    search_term = f"%{str(query or '').strip()}%"
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT
                id,
                processed_timestamp,
                invoice_number,
                customer_name,
                freight_charge
            FROM processed_invoice_history
            WHERE invoice_number LIKE ? COLLATE NOCASE
               OR customer_name LIKE ? COLLATE NOCASE
            ORDER BY processed_timestamp DESC, id DESC
            """,
            (search_term, search_term),
        ).fetchall()
    return [dict(row) for row in rows]


def get_processed_invoice(history_id, database_path=DEFAULT_DATABASE_PATH):
    """Return all stored fields for one processing event."""
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT
                id,
                processed_timestamp,
                invoice_date,
                invoice_number,
                vehicle_number,
                origin,
                customer_code,
                customer_name,
                destination,
                vehicle_type,
                cases,
                jars,
                freight_charge,
                lookup_status
            FROM processed_invoice_history
            WHERE id = ?
            """,
            (history_id,),
        ).fetchone()
    return dict(row) if row is not None else None
