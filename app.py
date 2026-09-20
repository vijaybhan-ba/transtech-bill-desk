"""Transtech Operations home.

Entry point for the multipage Streamlit app. Groups the two tools under one
sidebar navigation:
- Billing Desk (invoice extraction, Excel and billing statement export)
- Attendance (live photo + GPS attendance marking)
"""

import streamlit as st

billing_page = st.Page(
    "pages/billing_desk.py",
    title="Billing Desk",
    url_path="billing",
    default=True,
)
attendance_page = st.Page(
    "pages/attendance.py",
    title="Attendance",
    url_path="attendance",
)

navigator = st.navigation([billing_page, attendance_page])

st.set_page_config(
    page_title="Transtech Operations",
    page_icon="",
    layout="wide",
)

navigator.run()