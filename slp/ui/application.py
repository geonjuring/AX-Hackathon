"""Stable three-report Streamlit navigation."""
from pathlib import Path
import streamlit as st
from slp.ui.navigation import create_pages


def main():
    st.set_page_config(page_title='SLP 통합 리포트', page_icon='🏭', layout='wide')
    management_page = Path(__file__).with_name('management_page.py')
    st.navigation([
        st.Page(management_page, title='경영 리포트', icon='📊', default=True),
        *create_pages(),
    ]).run()
