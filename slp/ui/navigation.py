"""LOT/equipment pages for a shared Streamlit st.navigation entry."""
import streamlit as st


def render_lot():
    from slp.ui.lot_page import lot_page
    mode=st.sidebar.radio('분석 모드',['이력 분석','과거 사례 재생'],key='slp_lot_analysis_mode')
    lot_page(mode)


def render_equipment():
    from slp.ui.equipment_page import equip_page
    mode=st.sidebar.radio('분석 모드',['이력 분석','과거 사례 재생'],key='slp_equipment_analysis_mode')
    equip_page(mode)


def create_pages():
    return [st.Page(render_lot,title='LOT 이상 분석',url_path='lot-analysis'),
            st.Page(render_equipment,title='설비 이상 분석',url_path='equipment-analysis')]
