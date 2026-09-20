"""Smoke tests for the multipage Navigations app and the Attendance page."""

import pytest
from streamlit.testing.v1 import AppTest

RUN_TIMEOUT = 60


@pytest.fixture(autouse=True)
def isolated_attendance_database(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "ATTENDANCE_DATABASE", str(tmp_path / "attendance-test.db")
    )
    yield


def test_app_navigates_to_billing_desk_by_default():
    app = AppTest.from_file("app.py")
    app.run(timeout=RUN_TIMEOUT)
    assert not app.exception
    assert any("Billing Dashboard" in str(markdown.value)
               for markdown in app.markdown)


def test_attendance_page_renders_without_error():
    app = AppTest.from_file("pages/attendance.py")
    app.run(timeout=RUN_TIMEOUT)
    assert not app.exception
    assert any("Mark" in str(markdown.value)
               for markdown in app.markdown)
    assert app.selectbox[0].value == "Ajit"
    assert app.date_input[0].value is not None
    assert app.radio[0].value == "Present"


def test_attendance_page_can_mark_leave():
    app = AppTest.from_file("pages/attendance.py")
    app.run(timeout=RUN_TIMEOUT)
    assert not app.exception

    app.radio[0].set_value("Leave")
    app.run(timeout=RUN_TIMEOUT)
    assert not app.exception

    button = next(b for b in app.button if b.label == "Submit Attendance")
    assert not button.disabled
    button.click()
    app.run(timeout=RUN_TIMEOUT)
    assert not app.exception
    assert any(
        "Attendance recorded" in str(info.value)
        for info in list(app.info) + list(app.success)
    )