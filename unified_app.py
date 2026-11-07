"""Isolated three-report preview; source teammate application stays untouched."""
import os
import sys
from pathlib import Path
import streamlit as st

ROOT=Path(__file__).resolve().parent
MANAGEMENT=ROOT/'management_snapshot'
os.environ.setdefault('SLP_DB',str(ROOT/'slp.duckdb'))
os.environ.setdefault('SLP_DATA',str(ROOT/'data'))
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(MANAGEMENT))
from slp_navigation import create_pages

st.set_page_config(page_title='SLP 통합 리포트',page_icon='🏭',layout='wide')
management_page=MANAGEMENT/'pages/1_생산_일간_리포트.py'
st.navigation([st.Page(management_page,title='경영 리포트',icon='📊',default=True),*create_pages()]).run()
