"""Attendance page for the Transtech Bill Desk app.

Captures a live webcam photo plus automatic GPS location, recognises the
place (e.g. "Virar – Vijay's Home"), and records Present / Outside /
Leave / Holiday attendance. Sundays are auto-holidays.
"""

import io
import os

import pandas as pd
import streamlit as st
from streamlit_geolocation import streamlit_geolocation

import attendance as att

ATTENDANCE_DB = os.getenv("ATTENDANCE_DATABASE") or att.DEFAULT_DATABASE_PATH

PAGE_CSS = """
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

    .title-kicker {
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.18em;
        color: #1565C0;
        text-transform: uppercase;
        margin-bottom: 0.35rem;
    }

    .premium-title {
        margin: 0;
        font-size: 2.6rem;
        line-height: 1.05;
        font-weight: 800;
        color: #111111;
        letter-spacing: -0.03em;
    }

    .premium-title span {
        color: #1565C0;
    }

    .title-subtext {
        margin-top: 0.4rem;
        font-size: 0.9rem;
        color: #777777;
    }

    .stat-card {
        background: #FFFFFF;
        border: 1px solid rgba(17, 17, 17, 0.08);
        border-radius: 16px;
        padding: 0.9rem 1rem;
        box-shadow: 0 10px 28px rgba(17, 17, 17, 0.08);
    }

    .stat-card h4 {
        margin: 0 0 0.3rem 0;
        color: #111111;
        font-size: 0.95rem;
        font-weight: 700;
    }

    .stat-card p {
        margin: 0;
        color: #111111;
        font-size: 1.7rem;
        font-weight: 800;
    }

    .location-badge {
        display: inline-block;
        margin: 0.2rem 0;
        padding: 0.4rem 0.8rem;
        border-radius: 999px;
        background: rgba(21, 101, 192, 0.1);
        color: #0D47A1;
        font-size: 0.95rem;
        font-weight: 700;
    }

    [data-testid="stDataFrame"] {
        border: 1px solid rgba(17, 17, 17, 0.10);
        border-radius: 16px;
        overflow: hidden;
        box-shadow: 0 10px 28px rgba(17, 17, 17, 0.08);
        background: #FFFFFF;
    }

    div[data-testid="stButton"] > button,
    button[kind="primary"] {
        background: #1565C0 !important;
        color: #FFFFFF !important;
        border: 1px solid #1565C0 !important;
        border-radius: 12px;
        font-weight: 700;
        padding: 0.75rem 1.15rem;
        box-shadow: 0 10px 24px rgba(21, 101, 192, 0.18);
    }

    div[data-testid="stButton"] > button:hover,
    button[kind="primary"]:hover {
        background: #0D47A1 !important;
        border-color: #0D47A1 !important;
    }
</style>
"""


def _photo_io(photo_bytes):
    if not photo_bytes:
        return None
    try:
        return io.BytesIO(photo_bytes)
    except TypeError:
        return None


def render_stats(records):
    summary = att.attendance_summary(records)
    columns = st.columns(4)
    for column, (status, count) in zip(columns, summary.items()):
        with column:
            st.markdown(
                f'<div class="stat-card"><h4>{status}</h4>'
                f'<p>{count}</p></div>',
                unsafe_allow_html=True,
            )
    return summary


def render_location_preview(latitude, longitude, employee):
    if latitude is None or longitude is None:
        st.info("Click **Get Location** below to capture your GPS position.")
        return None

    known_locations = []
    for site in att.list_known_locations(ATTENDANCE_DB):
        known_locations.append(
            {"name": site["name"], "lat": site["lat"], "lng": site["lng"]}
        )
    if employee.get("home_lat"):
        known_locations.append(
            {
                "name": employee.get("home_label") or "Home",
                "lat": employee["home_lat"],
                "lng": employee["home_lng"],
            }
        )
    suggested_status, location_label = att.classify_touchpoint(
        latitude,
        longitude,
        employee.get("office_lat"),
        employee.get("office_lng"),
        known_locations,
    )
    st.markdown(
        f'<div class="location-badge">You are near: {location_label}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"Location: {location_label} | "
        f"Coordinates {att.format_coordinates(latitude, longitude)}"
    )
    st.map(pd.DataFrame(
        [{"lat": float(latitude), "lon": float(longitude)}]
    ), height=200, use_container_width=True)
    return suggested_status, location_label


def _resolve_fix():
    """Return (latitude, longitude, accuracy) from browser GPS or manual entry."""
    fix = streamlit_geolocation()
    if isinstance(fix, dict) and fix.get("latitude") is not None:
        return (
            fix.get("latitude"),
            fix.get("longitude"),
            fix.get("accuracy"),
        )
    manual_lat = st.text_input("Latitude (manual)", value="", key="manual_lat")
    manual_lng = st.text_input("Longitude (manual)", value="", key="manual_lng")
    if manual_lat and manual_lng:
        try:
            return float(manual_lat), float(manual_lng), None
        except ValueError:
            st.error("Manual coordinates must be numbers.")
    return None, None, None


def render_mark_attendance():
    st.markdown(
        """
        <div class="title-kicker">Attendance</div>
        <h1 class="premium-title">Mark <span>Attendance</span></h1>
        <div class="title-subtext">Live photo + automatic GPS location. Sundays are
        holidays automatically.</div>
        """,
        unsafe_allow_html=True,
    )

    employees = att.list_employees(ATTENDANCE_DB)
    employee_names = [employee["name"] for employee in employees]
    if not employee_names:
        st.error("No employees configured. Add employees in the Settings tab.")
        return

    employee_name = st.selectbox("Employee", employee_names,
                                 key="mark_employee")
    employee = att.get_employee(employee_name, ATTENDANCE_DB)
    selected_day = st.date_input("Date", value=att.today_ist(),
                                 key="mark_date")

    if att.is_holiday(selected_day):
        st.info(f"{selected_day.strftime('%A, %d %b %Y')} is a **holiday** "
                "and will be recorded automatically.")

    existing = att.get_attendance_record(employee_name, selected_day,
                                         ATTENDANCE_DB)
    if existing:
        st.success(
            f"Already recorded: {existing['status']} at "
            f"{existing['location_label'] or 'n/a'} "
            f"(in {existing['time_in']}, out {existing['time_out'] or '-'}). "
            "Submitting again will update today's record."
        )

    default_status = att.PRESENT
    if existing:
        default_status = existing["status"]
    elif att.is_holiday(selected_day):
        default_status = att.HOLIDAY

    status = st.radio(
        "Attendance status",
        options=att.STATUS_OPTIONS,
        index=att.STATUS_OPTIONS.index(default_status),
        format_func=lambda option: {
            att.PRESENT: "Present - in office",
            att.OUTSIDE: "Outside attendance - work from home / site",
            att.LEAVE: "Leave",
            att.HOLIDAY: "Holiday",
        }[option],
        key="mark_status",
    )

    needs_photo_location = status in (att.PRESENT, att.OUTSIDE)
    photo_bytes = None
    latitude = longitude = None
    accuracy = None

    if needs_photo_location:
        left, right = st.columns(2)
        with left:
            photo = st.camera_input(
                "Take a live photo",
                key="attendance_photo",
                help="This photo is stored with your attendance record.",
            )
        with right:
            st.markdown("### Your location")
            latitude, longitude, accuracy = _resolve_fix()
            st.caption("GPS is captured automatically by the Get Location "
                       "button. Enter coordinates manually only if GPS is "
                       "unavailable.")

        if photo is not None:
            photo_bytes = photo.getvalue()
            st.image(photo_bytes, caption="Photo to be stored", width=220)

        if latitude is not None and longitude is not None:
            st.session_state["last_fix_status"] = render_location_preview(
                latitude, longitude, employee
            )
        else:
            st.info("Click **Get Location** to capture your position.")

    note = st.text_area("Note (optional)", value="", key="mark_note",
                        height=70,
                        placeholder="e.g. Working from home, Mumbai site visit...")

    can_submit = status in (att.LEAVE, att.HOLIDAY) or (
        needs_photo_location and photo_bytes is not None
        and latitude is not None and longitude is not None
    )

    if st.button("Submit Attendance", type="primary",
                 disabled=not can_submit, key="submit_attendance"):
        location_label = ""
        if status in (att.LEAVE, att.HOLIDAY):
            location_label = status
        else:
            suggestion = st.session_state.get("last_fix_status")
            if suggestion:
                _, location_label = suggestion

        record = att.mark_attendance(
            employee_name=employee_name,
            attendance_date=selected_day,
            status=status,
            location_label=location_label,
            latitude=latitude,
            longitude=longitude,
            accuracy=accuracy,
            photo_bytes=photo_bytes,
            note=note,
            database_path=ATTENDANCE_DB,
        )
        st.success(
            f"Attendance recorded for {employee_name} "
            f"({selected_day.strftime('%d %b %Y')}): **{record['status']}**"
            + (f" at {location_label}" if location_label else "")
        )


def render_records():
    st.markdown(
        """
        <div class="title-kicker">Attendance</div>
        <h1 class="premium-title">Records & <span>Map</span></h1>
        """,
        unsafe_allow_html=True,
    )

    employees = att.list_employees(ATTENDANCE_DB)
    names = ["All"] + [employee["name"] for employee in employees]
    query_employee = st.selectbox("Employee", names, key="records_employee")
    query_month = st.date_input(
        "Month", value=att.today_ist(), key="records_month"
    )
    year_month = query_month.strftime("%Y-%m")

    if query_employee == "All":
        records = att.list_attendance(ATTENDANCE_DB, year_month=year_month)
    else:
        records = att.list_attendance(
            ATTENDANCE_DB, employee_name=query_employee,
            year_month=year_month,
        )
    records = [
        record for record in records
        if record["attendance_date"] is not None
    ]

    render_stats(records)
    st.divider()

    if not records:
        st.caption("No attendance recorded for this month yet.")
        return

    table_rows = []
    for record in records:
        table_rows.append(
            {
                "Date": record["attendance_date"].strftime("%d %b %Y"),
                "Employee": record["employee_name"],
                "Status": record["status"],
                "Location": record["location_label"] or "",
                "Time In": record["time_in"] or "",
                "Time Out": record["time_out"] or "",
                "Note": record["note"] or "",
                "Photo": "Yes" if record.get("photo") else "No",
            }
        )
    st.subheader("Daily records")
    st.dataframe(pd.DataFrame(table_rows), hide_index=True,
                 use_container_width=True, height=320)

    located = [
        record for record in records
        if record.get("latitude") is not None and record.get("longitude") is not None
    ]
    if located:
        st.subheader("Marked locations")
        st.map(
            pd.DataFrame([
                {
                    "lat": record["latitude"],
                    "lon": record["longitude"],
                    "label": record["employee_name"] + " - "
                             + (record["location_label"] or ""),
                }
                for record in located
            ]),
            height=320,
            use_container_width=True,
            zoom=10,
        )
        with st.expander("View attendance photos"):
            for record in located:
                image = _photo_io(record.get("photo"))
                employee_line = (
                    f"**{record['employee_name']}** - "
                    f"{record['attendance_date'].strftime('%d %b %Y')} "
                    f"- {record['status']} - "
                    f"{record['location_label'] or ''}"
                )
                st.markdown(employee_line)
                if image is None:
                    st.caption("No photo stored for this record.")
                else:
                    st.image(image, width=260)
                st.divider()


def render_monthly_report():
    st.markdown(
        """
        <div class="title-kicker">Attendance</div>
        <h1 class="premium-title">Monthly <span>Report</span></h1>
        """,
        unsafe_allow_html=True,
    )

    employees = att.list_employees(ATTENDANCE_DB)
    names = ["All"] + [employee["name"] for employee in employees]
    report_employee = st.selectbox("Employee", names, key="report_employee")
    report_month = st.date_input("Month", value=att.today_ist(),
                                 key="report_month")
    year_month = report_month.strftime("%Y-%m")

    if report_employee == "All":
        records = att.list_attendance(ATTENDANCE_DB, year_month=year_month)
    else:
        records = att.list_attendance(
            ATTENDANCE_DB, employee_name=report_employee,
            year_month=year_month,
        )
    render_stats(records)
    st.divider()

    lookup = {}
    for record in records:
        if record["attendance_date"] is None:
            continue
        lookup[(record["attendance_date"], record["employee_name"])] = record

    matrix = []
    day_rows = att.render_month(report_month.month, report_month.year)
    if report_employee == "All":
        covered_names = employees
    else:
        covered_names = [employee for employee in employees
                         if employee["name"] == report_employee]
    for day, is_holiday in day_rows:
        row = {"Date": day.strftime("%a %d")}
        for employee in covered_names:
            record = lookup.get((day, employee["name"]))
            if record is not None:
                row[employee["name"]] = record["status"]
            elif is_holiday:
                row[employee["name"]] = att.HOLIDAY
            else:
                row[employee["name"]] = ""
        matrix.append(row)

    report_frame = pd.DataFrame(matrix)
    if report_employee == "All":
        display_columns = ["Date"] + [employee["name"] for employee in employees]
        report_frame = report_frame[display_columns]
    st.subheader("Day-by-day status")
    st.dataframe(report_frame, hide_index=True, use_container_width=True,
                 height=420)
    st.caption("Short statuses: Present, Outside, Leave, Holiday. "
               "Blank empty cells are unrecorded working days. "
               "Sunday cells are assumed Holiday automatically.")

    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
        report_frame.to_excel(writer, index=False, sheet_name="Attendance")
        summary_row = {"Date": "Summary"}
        for employee in covered_names:
            employee_records = [
                record for record in records
                if record["employee_name"] == employee["name"]
            ]
            counts = att.attendance_summary(employee_records)
            summary_row[employee["name"]] = (
                f"P {counts[att.PRESENT]} O {counts[att.OUTSIDE]} "
                f"L {counts[att.LEAVE]} H {counts[att.HOLIDAY]}"
            )
        summary_frame = pd.DataFrame([summary_row])
        summary_frame.to_excel(writer, index=False,
                               sheet_name="Summary")
    st.download_button(
        "Download monthly report (Excel)",
        data=excel_buffer.getvalue(),
        mime=("application/vnd.openxmlformats-officedocument"
              ".spreadsheetml.sheet"),
        file_name=f"attendance_report_{year_month}.xlsx",
    )


def render_settings():
    st.markdown(
        """
        <div class="title-kicker">Attendance</div>
        <h1 class="premium-title">Settings</h1>
        """,
        unsafe_allow_html=True,
    )

    tab_employees, tab_locations = st.tabs(
        ["Employees", "Known locations"]
    )

    with tab_employees:
        st.markdown("### Team")
        st.caption("Office coordinates are used to distinguish Present "
                   "(in office) from Outside attendance. Add a home coordinate "
                   "so work-from-home is named automatically, e.g. "
                   "'Virar (Home)'.")
        employees_frame = pd.DataFrame(
            [
                {
                    "Name": employee["name"],
                    "Office label": employee["office_label"] or "",
                    "Office lat": employee["office_lat"],
                    "Office lng": employee["office_lng"],
                    "Home label": employee["home_label"] or "",
                    "Home lat": employee["home_lat"],
                    "Home lng": employee["home_lng"],
                }
                for employee in att.list_employees(ATTENDANCE_DB,
                                                   active_only=False)
            ]
        )
        edited = st.data_editor(
            employees_frame,
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            key="settings_employees_editor",
        )
        if st.button("Save employees", key="save_employees"):
            for _, row in edited.iterrows():
                name = str(row.get("Name") or "").strip()
                if not name:
                    continue
                att.upsert_employee(
                    name=name,
                    office_label=str(row.get("Office label") or "").strip()
                    or "Andheri Office, Mumbai",
                    office_lat=_float_or_none(row.get("Office lat")),
                    office_lng=_float_or_none(row.get("Office lng")),
                    home_label=str(row.get("Home label") or "").strip(),
                    home_lat=_float_or_none(row.get("Home lat")),
                    home_lng=_float_or_none(row.get("Home lng")),
                    database_path=ATTENDANCE_DB,
                )
            st.success("Employees saved.")

    with tab_locations:
        st.markdown("### Sites")
        st.caption("Add other work sites, e.g. Ambadi. When someone marks "
                   "attendance near a site it is shown as "
                   "'<site> - <place>'.")
        locations = att.list_known_locations(ATTENDANCE_DB)
        locations_frame = pd.DataFrame(
            [
                {
                    "Name": site["name"],
                    "Lat": site["lat"],
                    "Lng": site["lng"],
                }
                for site in locations
            ]
        )
        locations_edited = st.data_editor(
            locations_frame,
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            key="settings_locations_editor",
        )
        if st.button("Save locations", key="save_locations"):
            saved_names = set()
            for _, row in locations_edited.iterrows():
                name = str(row.get("Name") or "").strip()
                if not name:
                    continue
                att.upsert_known_location(
                    name,
                    _float_or_none(row.get("Lat")),
                    _float_or_none(row.get("Lng")),
                    database_path=ATTENDANCE_DB,
                )
                saved_names.add(name)
            for site in locations:
                if site["name"] not in saved_names:
                    att.delete_known_location(site["name"],
                                              database_path=ATTENDANCE_DB)
            st.success("Known locations saved.")


def _float_or_none(value):
    if value is None or value == "" or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def main():
    st.markdown(PAGE_CSS, unsafe_allow_html=True)

    att.init_attendance_database(ATTENDANCE_DB)
    att.seed_default_data(ATTENDANCE_DB)

    page = st.tabs(
        [
            "Mark Attendance",
            "Records & Map",
            "Monthly Report",
            "Settings",
        ]
    )

    with page[0]:
        render_mark_attendance()
    with page[1]:
        render_records()
    with page[2]:
        render_monthly_report()
    with page[3]:
        render_settings()


main()