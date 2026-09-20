from datetime import date

import pytest

import attendance as att


@pytest.fixture
def database(tmp_path):
    database_path = tmp_path / "attendance-test.db"
    att.init_attendance_database(database_path)
    att.seed_default_data(database_path)
    return database_path


def test_sunday_is_holiday_but_weekdays_are_not():
    assert att.is_holiday(date(2026, 9, 20))
    assert not att.is_holiday(date(2026, 9, 21))


def test_next_working_day_skips_sunday():
    assert att.next_working_day(date(2026, 9, 18)) == date(2026, 9, 18)
    assert att.next_working_day(date(2026, 9, 20)) == date(2026, 9, 21)


def test_haversine_office_to_virar_is_reasonable():
    distance = att.haversine_km(19.1197, 72.8468, 19.4566, 72.8116)
    assert 25 < distance < 45


def test_seed_creates_team_and_office(database):
    assert [e["name"] for e in att.list_employees(database)] == [
        "Ajit", "Anshuman", "Manish", "Nikhat", "Nitish", "Shyam", "Vijay",
    ]
    assert att.get_employee("Vijay", database)["office_lat"] == pytest.approx(19.1197)


def test_upsert_employee_updates_and_keeps_single_row(database):
    att.upsert_employee(
        "Vijay", "Andheri Office", 19.1197, 72.8468,
        "Virar (Home)", 19.4566, 72.8116, database_path=database,
    )
    employees = [e for e in att.list_employees(database) if e["name"] == "Vijay"]
    assert len(employees) == 1
    assert employees[0]["home_lat"] == pytest.approx(19.4566)


def test_classify_present_inside_office_radius():
    status, label = att.classify_touchpoint(
        19.1200, 72.8470, 19.1197, 72.8468, []
    )
    assert status == att.PRESENT
    assert label == "Andheri Office"


def test_classify_outside_with_known_site(database):
    sites = [{"name": "Ambadi", "lat": 19.0, "lng": 73.0}]
    status, label = att.classify_touchpoint(
        19.0, 73.0, 19.1197, 72.8468, sites
    )
    assert status == att.OUTSIDE
    assert label.startswith("Ambadi")


def test_classify_outside_without_known_site_falls_back_to_coordinates():
    status, label = att.classify_touchpoint(
        19.4566, 72.8116, 19.1197, 72.8468, []
    )
    assert status == att.OUTSIDE
    assert label


def test_nearest_known_location_returns_none_when_far_away():
    sites = [{"name": "Ambadi", "lat": 19.0, "lng": 73.0}]
    assert att.nearest_known_location(19.4566, 72.8116, sites) is None


def test_mark_and_read_back_attendance(database):
    today = date(2026, 9, 21)
    record = att.mark_attendance(
        "Vijay",
        today,
        att.OUTSIDE,
        location_label="Virar - Virar, Palghar, Maharashtra",
        latitude=19.4566,
        longitude=72.8116,
        photo_bytes=b"\x89PNG\r\n\r\n",
        note="Working from home",
        database_path=database,
    )
    assert record["status"] == att.OUTSIDE
    assert record["location_label"].startswith("Virar")
    assert record["note"] == "Working from home"

    records = att.list_attendance(database, employee_name="Vijay",
                                  year_month="2026-09")
    assert len(records) == 1
    assert records[0]["attendance_date"] == today
    assert records[0]["photo"] == b"\x89PNG\r\n\r\n"


def test_resubmitting_same_day_updates_in_place(database):
    today = date(2026, 9, 21)
    att.mark_attendance("Vijay", today, att.PRESENT,
                        location_label="Andheri Office",
                        latitude=19.1197, longitude=72.8468,
                        database_path=database)
    second = att.mark_attendance(
        "Vijay", today, att.OUTSIDE,
        location_label="Virar - Virar",
        latitude=19.4566, longitude=72.8116,
        database_path=database,
    )
    assert second["status"] == att.OUTSIDE
    assert second["time_in"] is not None
    assert second["time_out"] is not None

    records = att.list_attendance(database, year_month="2026-09")
    assert len(records) == 1


def test_leave_does_not_require_location(database):
    record = att.mark_attendance("Nikhat", date(2026, 9, 22), att.LEAVE,
                                 database_path=database)
    assert record["status"] == att.LEAVE
    assert record["latitude"] is None


def test_sunday_holiday_visible_in_render_month():
    days = att.render_month(9, 2026)
    holiday_days = {day for day, is_holiday in days if is_holiday}
    assert 6 in {day.day for day in holiday_days}
    assert date(2026, 9, 13) in holiday_days
    assert date(2026, 9, 20) in holiday_days
    assert date(2026, 9, 27) in holiday_days
    assert date(2026, 9, 21) not in holiday_days


def test_attendance_summary_counts_statuses(database):
    att.mark_attendance("Vijay", date(2026, 9, 21), att.PRESENT,
                        database_path=database)
    att.mark_attendance("Ajit", date(2026, 9, 21), att.LEAVE,
                        database_path=database)
    records = att.list_attendance(database, year_month="2026-09")
    summary = att.attendance_summary(records)
    assert summary == {att.PRESENT: 1, att.OUTSIDE: 0, att.LEAVE: 1,
                       att.HOLIDAY: 0}