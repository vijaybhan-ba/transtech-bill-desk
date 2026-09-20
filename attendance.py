"""Attendance store and location logic for the Transtech workforce.

Design notes
------------
* Attendance is stored per employee per calendar day (one row per day).
* ``Present`` / ``Outside`` attendance require a live photo plus GPS
  coordinates. ``Leave`` and ``Holiday`` are recorded without either.
* Sundays are treated as holidays automatically. Nothing is written to the
  database for a Sunday until an employee actually opens the Mark page; the
  holiday rule is applied on the fly when a date is viewed.
* Recognising a place ("Virar", "Andheri Office", "Ambadi") happens with the
  browser GPS coordinates: nearest known site wins, otherwise OpenStreetMap
  Nominatim reverse geocoding is used as a fallback.
"""

import functools
import io
import json
import math
import os
import sqlite3
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

DEFAULT_DATABASE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "attendance.db",
)

IST = ZoneInfo("Asia/Kolkata")
TIME_FORMAT = "%I:%M %p"

PRESENT = "Present"
OUTSIDE = "Outside"
LEAVE = "Leave"
HOLIDAY = "Holiday"
STATUS_OPTIONS = (PRESENT, OUTSIDE, LEAVE, HOLIDAY)

OFFICE_RADIUS_KM = 2.0
KNOWN_RADIUS_KM = 2.5

GEOCODER_USER_AGENT = "TranstechBillDesk/1.0 (attendance)"
GEOCODER_URL = "https://nominatim.openstreetmap.org/reverse"
GEOCODER_TIMEOUT_SECONDS = 8

DEFAULT_EMPLOYEES = (
    ("Vijay", "Andheri Office, Mumbai", 19.1197, 72.8468, "Virar (Home), Palghar", 19.4566, 72.8116),
    ("Anshuman", "Andheri Office, Mumbai", 19.1197, 72.8468, "", None, None),
    ("Nikhat", "Andheri Office, Mumbai", 19.1197, 72.8468, "", None, None),
    ("Shyam", "Andheri Office, Mumbai", 19.1197, 72.8468, "", None, None),
    ("Ajit", "Andheri Office, Mumbai", 19.1197, 72.8468, "", None, None),
    ("Manish", "Andheri Office, Mumbai", 19.1197, 72.8468, "", None, None),
    ("Nitish", "Andheri Office, Mumbai", 19.1197, 72.8468, "", None, None),
)

DEFAULT_KNOWN_LOCATIONS = (
    ("Andheri Office", 19.1197, 72.8468),
)


# --------------------------------------------------------------------------
# Dates and holidays
# --------------------------------------------------------------------------
def today_ist():
    """Return the current calendar date in the Asia/Kolkata time zone."""
    return datetime.now(IST).date()


def now_ist():
    """Return the current wall-clock time in the Asia/Kolkata time zone."""
    return datetime.now(IST)


def is_holiday(day):
    """Sundays are automatic holidays."""
    return day.weekday() == 6


def next_working_day(day):
    """Return the first non-Sunday date on or after ``day``."""
    while is_holiday(day):
        day += timedelta(days=1)
    return day


# --------------------------------------------------------------------------
# Distance and place recognition
# --------------------------------------------------------------------------
def haversine_km(lat1, lng1, lat2, lng2):
    """Great-circle distance in kilometres between two WGS84 points."""
    if lat1 is None or lng1 is None or lat2 is None or lng2 is None:
        return float("inf")
    radius_km = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    )
    return 2 * radius_km * math.asin(math.sqrt(a))


def nearest_known_location(latitude, longitude, known_locations, radius_km=KNOWN_RADIUS_KM):
    """Return the closest configured site within ``radius_km`` or None."""
    best = None
    best_distance = float("inf")
    for location in known_locations:
        distance = haversine_km(
            latitude,
            longitude,
            location.get("lat"),
            location.get("lng"),
        )
        if distance <= radius_km and distance < best_distance:
            best = location
            best_distance = distance
    return best


@functools.lru_cache(maxsize=256)
def _reverse_geocode_cached(latitude_key, longitude_key):
    try:
        query = urllib.parse.urlencode(
            {
                "lat": latitude_key,
                "lon": longitude_key,
                "format": "jsonv2",
                "zoom": 16,
                "addressdetails": 1,
            }
        )
        request = urllib.request.Request(
            f"{GEOCODER_URL}?{query}",
            headers={"User-Agent": GEOCODER_USER_AGENT},
        )
        with urllib.request.urlopen(
            request, timeout=GEOCODER_TIMEOUT_SECONDS
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
        address = payload.get("address") or {}
        return _compose_place_label(address) or payload.get("display_name", "")
    except (OSError, ValueError, KeyError):
        return ""


def reverse_geocode(latitude, longitude):
    """Return a human friendly place name for a coordinate pair."""
    if latitude is None or longitude is None:
        return ""
    try:
        return _reverse_geocode_cached(round(float(latitude), 6), round(float(longitude), 6))
    except (TypeError, ValueError):
        return ""


_LOCALITY_KEYS = (
    "neighbourhood",
    "suburb",
    "city_district",
    "town",
    "village",
    "municipality",
    "hamlet",
    "county",
    "district",
    "state_district",
)


def _compose_place_label(address):
    components = [address.get(key) for key in _LOCALITY_KEYS]
    locality = next((part for part in components if part), "")
    state = address.get("state", "")
    parts = [part for part in (locality, address.get("state_district") or
                               address.get("district"), state) if part]
    return ", ".join(dict.fromkeys(parts))[:80]


def format_coordinates(latitude, longitude):
    if latitude is None or longitude is None:
        return ""
    return f"{float(latitude):.5f}, {float(longitude):.5f}"


def classify_touchpoint(
    latitude,
    longitude,
    office_latitude,
    office_longitude,
    known_locations=(),
    office_radius_km=OFFICE_RADIUS_KM,
    known_radius_km=KNOWN_RADIUS_KM,
):
    """Suggest a status and place label for a GPS fix.

    Returns ``(status, location_label)``. Inside the office radius it
    suggests ``Present``; anywhere else it suggests ``Outside`` and names the
    nearest known site, falling back to OpenStreetMap or raw coordinates.
    """
    office_distance = haversine_km(
        latitude, longitude, office_latitude, office_longitude
    )
    if office_distance <= office_radius_km:
        return PRESENT, "Andheri Office"

    nearest = nearest_known_location(
        latitude, longitude, known_locations, radius_km=known_radius_km
    )
    place = reverse_geocode(latitude, longitude) or format_coordinates(
        latitude, longitude
    )
    if nearest is not None:
        return OUTSIDE, f"{nearest.get('name')} - {place}"
    return OUTSIDE, place


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------
def init_attendance_database(database_path=DEFAULT_DATABASE_PATH):
    """Create tables when needed, without touching existing rows."""
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                office_label TEXT,
                office_lat REAL,
                office_lng REAL,
                home_label TEXT,
                home_lat REAL,
                home_lng REAL,
                active INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS known_locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                lat REAL,
                lng REAL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_name TEXT NOT NULL,
                attendance_date TEXT NOT NULL,
                status TEXT NOT NULL,
                time_in TEXT,
                time_out TEXT,
                location_label TEXT,
                latitude REAL,
                longitude REAL,
                accuracy REAL,
                photo BLOB,
                note TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (employee_name, attendance_date)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(attendance_date)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_attendance_employee ON attendance(employee_name)"
        )


def seed_default_data(database_path=DEFAULT_DATABASE_PATH):
    """Insert the standard team and sites only when the store is empty."""
    with sqlite3.connect(database_path) as connection:
        employee_count = connection.execute(
            "SELECT COUNT(*) FROM employees"
        ).fetchone()[0]
        if employee_count == 0:
            connection.executemany(
                """
                INSERT INTO employees (
                    name, office_label, office_lat, office_lng,
                    home_label, home_lat, home_lng
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                DEFAULT_EMPLOYEES,
            )
        location_count = connection.execute(
            "SELECT COUNT(*) FROM known_locations"
        ).fetchone()[0]
        if location_count == 0:
            connection.executemany(
                "INSERT INTO known_locations (name, lat, lng) VALUES (?, ?, ?)",
                DEFAULT_KNOWN_LOCATIONS,
            )


def _employee_row_to_dict(row):
    values = dict(row)
    for key in ("office_lat", "office_lng", "home_lat", "home_lng"):
        values[key] = _sqlite_number(values.get(key))
    return values


def _sqlite_number(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def list_employees(database_path=DEFAULT_DATABASE_PATH, active_only=True):
    query = "SELECT * FROM employees"
    if active_only:
        query += " WHERE active = 1"
    query += " ORDER BY name"
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(query).fetchall()
    return [_employee_row_to_dict(row) for row in rows]


def get_employee(name, database_path=DEFAULT_DATABASE_PATH):
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM employees WHERE name = ?", (name,)
        ).fetchone()
    return _employee_row_to_dict(row) if row is not None else None


def upsert_employee(
    name,
    office_label,
    office_lat,
    office_lng,
    home_label="",
    home_lat=None,
    home_lng=None,
    database_path=DEFAULT_DATABASE_PATH,
):
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO employees (
                name, office_label, office_lat, office_lng, home_label,
                home_lat, home_lng
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                office_label = excluded.office_label,
                office_lat = excluded.office_lat,
                office_lng = excluded.office_lng,
                home_label = excluded.home_label,
                home_lat = excluded.home_lat,
                home_lng = excluded.home_lng,
                active = 1
            """,
            (name, office_label, office_lat, office_lng, home_label,
             home_lat, home_lng),
        )


def list_known_locations(database_path=DEFAULT_DATABASE_PATH):
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT id, name, lat, lng FROM known_locations ORDER BY name"
        ).fetchall()
    return [dict(row) for row in rows]


def upsert_known_location(name, lat, lng, database_path=DEFAULT_DATABASE_PATH):
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO known_locations (name, lat, lng) VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET lat = excluded.lat, lng = excluded.lng
            """,
            (name, lat, lng),
        )


def delete_known_location(name, database_path=DEFAULT_DATABASE_PATH):
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "DELETE FROM known_locations WHERE name = ?", (name,)
        )


def get_attendance_record(
    employee_name, attendance_date, database_path=DEFAULT_DATABASE_PATH
):
    """Return one employee/day row or None when nothing was recorded."""
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT * FROM attendance
            WHERE employee_name = ? AND attendance_date = ?
            """,
            (employee_name, attendance_date.isoformat()),
        ).fetchone()
    if row is None:
        return None
    record = dict(row)
    record["attendance_date"] = attendance_date
    return record


def mark_attendance(
    employee_name,
    attendance_date,
    status,
    location_label="",
    latitude=None,
    longitude=None,
    accuracy=None,
    photo_bytes=None,
    note="",
    database_path=DEFAULT_DATABASE_PATH,
    captured_at=None,
):
    """Create or update the daily attendance row for one employee.

    ``time_in`` records the first capture of the day and ``time_out`` the
    latest submission, so an employee who moves from the office to home ends
    up with both touch points preserved.
    """
    attendance_date = attendance_date or today_ist()
    if isinstance(attendance_date, str):
        attendance_date = date.fromisoformat(attendance_date)
    if isinstance(status, str):
        status = status.strip().title()
    status = status if status in STATUS_OPTIONS else LEAVE

    captured_at = captured_at or now_ist()
    stamp = captured_at.strftime(TIME_FORMAT)

    existing = get_attendance_record(
        employee_name, attendance_date, database_path=database_path
    )
    time_in = (existing or {}).get("time_in") or stamp
    time_out = stamp if existing is not None else None

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO attendance (
                employee_name, attendance_date, status, time_in, time_out,
                location_label, latitude, longitude, accuracy, photo, note,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(employee_name, attendance_date) DO UPDATE SET
                status = excluded.status,
                time_out = excluded.time_out,
                location_label = excluded.location_label,
                latitude = excluded.latitude,
                longitude = excluded.longitude,
                accuracy = excluded.accuracy,
                photo = excluded.photo,
                note = excluded.note,
                updated_at = excluded.updated_at
            """,
            (
                employee_name,
                attendance_date.isoformat(),
                status,
                time_in,
                time_out,
                location_label or "",
                latitude,
                longitude,
                accuracy,
                photo_bytes,
                note or "",
                captured_at.isoformat(timespec="seconds"),
                captured_at.isoformat(timespec="seconds"),
            ),
        )
    return get_attendance_record(
        employee_name, attendance_date, database_path=database_path
    )


def list_attendance(
    database_path=DEFAULT_DATABASE_PATH,
    employee_name=None,
    start_date=None,
    end_date=None,
    year_month=None,
):
    """Return attendance rows filtered by employee and/or a month range."""
    if employee_name == "All":
        employee_name = None
    clauses = []
    parameters = []
    if employee_name:
        clauses.append("employee_name = ?")
        parameters.append(employee_name)
    if start_date and end_date:
        clauses.append("attendance_date BETWEEN ? AND ?")
        parameters.extend((start_date.isoformat(), end_date.isoformat()))
    elif year_month:
        clauses.append("attendance_date LIKE ?")
        parameters.append(f"{year_month}-%")

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = (
        "SELECT * FROM attendance "
        f"{where} ORDER BY attendance_date DESC, employee_name"
    )
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(query, parameters).fetchall()
    records = [dict(row) for row in rows]
    for record in records:
        try:
            record["attendance_date"] = date.fromisoformat(
                record["attendance_date"]
            )
        except (TypeError, ValueError):
            record["attendance_date"] = None
    return records


def attendance_summary(records):
    """Count statuses across a list of attendance records."""
    counts = {status: 0 for status in STATUS_OPTIONS}
    for record in records:
        counts[record.get("status", "")] = counts.get(record.get("status"), 0) + 1
    return counts


def render_month(month, year):
    """Return a calendar matrix for one month.

    Each cell is ``(date, is_holiday)``; Sunday cells are marked as holiday.
    """
    first = date(year, month, 1)
    last = date(year, month + 1, 1) - timedelta(days=1)
    return [(day, is_holiday(day)) for day in _dates_between(first, last)]


def _dates_between(start, end):
    for offset in range((end - start).days + 1):
        yield start + timedelta(days=offset)


def photo_io(record):
    """Return a file-like object for the stored photo bytes or None."""
    photo = record.get("photo")
    if not photo:
        return None
    return io.BytesIO(photo)