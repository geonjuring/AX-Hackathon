"""Standalone entry; shared navigation can import the page renderers."""
import streamlit as st
st.set_page_config(page_title="SLP 분석 에이전트", page_icon="🏭", layout="wide")
from slp.ui.lot_page import lot_page
from slp.ui.equipment_page import equip_page
with st.sidebar:
    st.header("🏭 SLP 분석 에이전트")
    menu = st.radio("메뉴", ["LOT 이상 분석", "설비 이상 분석"], label_visibility="collapsed")
    mode = st.radio("분석 모드", ["이력 분석", "과거 사례 재생"], key="analysis_mode")
    st.divider()
if menu == "LOT 이상 분석":
    lot_page(mode)
else:
    equip_page(mode)
