"""Portable local downloads: readable HTML and exact-valued JSON/CSV ZIP."""
from datetime import datetime, date
from zoneinfo import ZoneInfo
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
import html
import json
import math
import re
from numbers import Real
import pandas as pd
import streamlit as st
import table_display as TD
from number_format import number, text


def clean(value):
    if isinstance(value, pd.DataFrame):
        return clean(value.to_dict('records'))
    if isinstance(value, pd.Series):
        return clean(value.to_dict())
    if isinstance(value, dict):
        return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value, (tuple,list)):
        return [clean(v) for v in value]
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value,(datetime,date,pd.Timestamp)):
        return value.isoformat()
    if isinstance(value,Real):
        if not math.isfinite(value):
            return None
        return value.item() if hasattr(value,'item') else value
    return value if isinstance(value,(str,bool,int,float)) else str(value)


def build(title, metadata, tables, paragraphs, alarm=None):
    meta = {'생성시각':datetime.now(ZoneInfo('Asia/Seoul')).isoformat(), **metadata}
    payload = clean({'제목':title,'분석조건':meta,'설명':paragraphs,'표':tables,'모의알림':alarm or {}})
    raw_json = json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)
    chunks = ['<!doctype html><html lang="ko"><meta charset="utf-8">',
              '<title>'+html.escape(title)+'</title>',
              '<style>body{font:15px sans-serif;margin:32px;line-height:1.7;color:#172033}table{border-collapse:collapse;display:block;overflow:auto;max-width:100%;font-size:13px}th,td{border:1px solid #ccd4df;padding:6px 10px;text-align:left}th{background:#edf2f7}h2{margin-top:32px}@media print{body{margin:8px}table{display:table;font-size:10px}tr{break-inside:avoid}}</style>',
              '<h1>'+html.escape(title)+'</h1>']
    for key,value in meta.items():
        chunks.append('<p><b>'+html.escape(key)+'</b>: '+html.escape('—' if clean(value) is None else str(clean(value)))+'</p>')
    for name,frame in tables.items():
        if not isinstance(frame,pd.DataFrame):
            continue
        chunks.append('<h2>'+html.escape(name)+'</h2>')
        if frame.empty:
            chunks.append('<p>해당 데이터 없음 / 보류</p>');continue
        if name == '판정표':
            shown = TD.judgment(frame)
        elif name == '생산정보':
            shown = TD.physical(frame)
        elif name == '배럴':
            from lot_analysis import BARREL_TOL
            column_pairs = [('실측', '설정')] + [(col, col[:-3] + ' 설정') for col in frame if col.endswith(' 실측')]
            shown = TD.pairs(frame, column_pairs, tolerance=BARREL_TOL)
        elif name == '공정조건' and metadata.get('LOT'):
            shown = TD.process(frame, metadata['LOT'], metadata.get('비교 LOT') or [])
        elif name in ('계량', '믹서', 'Grade'):
            shown = TD.pairs(frame, [('실측', '기준'), ('측정', '설정')] + [(v,v+'_기준') for v in ('RPM','전류','진공')])
            change_cols = [c for c in frame if c in ('차이율','배치최대차이율') or str(c).endswith(' 변화%')]
            if change_cols:
                shown = shown.map(lambda value: TD.direction(value,0), subset=change_cols)
        else:
            shown = frame.style
        shown = TD.pretty(shown)
        # Escape both cell content and labels in the standalone document.
        for col in shown.data.columns:
            shown.format({col: lambda value, c=col: html.escape(text(value) if c in ('데이터','관측·비교 결과','MI (규격)','IZOD (규격)') else number(value))}, subset=[col], na_rep='—')
        shown.format_index(escape='html', axis=0).format_index(escape='html', axis=1)
        chunks.append(shown.hide(axis='index').to_html())
    chunks.append('<h2>모의 알림 이력</h2><pre>'+html.escape(json.dumps(clean(alarm or {}),ensure_ascii=False,indent=2))+'</pre>')
    for heading,body in paragraphs.items():
        chunks += ['<h2>'+html.escape(heading)+'</h2>','<p>'+html.escape(str(body)).replace('\n','<br>')+'</p>']
    chunks.append('</html>')
    document = '\n'.join(chunks)
    out = BytesIO()
    with ZipFile(out,'w',ZIP_DEFLATED) as bundle:
        bundle.writestr('report.html',document)
        bundle.writestr('report.json',raw_json)
        for idx,(name,frame) in enumerate(tables.items(),1):
            if isinstance(frame,pd.DataFrame):
                safe = re.sub(r'[^\w가-힣-]','_',name)
                bundle.writestr(f'{idx:02d}_{safe}.csv',frame.to_csv(index=False).encode('utf-8-sig'))
    return document,out.getvalue()


def render_download(title, metadata, tables, paragraphs, context, alarm=None):
    st.subheader('리포트 다운로드')
    document,bundle = build(title,metadata,tables,paragraphs,alarm)
    stem = re.sub(r'[^\w가-힣-]','_',title)
    left,right = st.columns(2)
    left.download_button('리포트 HTML 다운로드',document,file_name=stem+'.html',mime='text/html',key=context+'html')
    right.download_button('전체 자료 ZIP 다운로드',bundle,file_name=stem+'.zip',mime='application/zip',key=context+'zip')
    st.caption('HTML은 브라우저에서 열어 인쇄·PDF 저장할 수 있습니다. ZIP에는 리포트와 분석조건·원래 계산값 JSON, 표별 CSV가 포함됩니다. 화면의 가독성 표시와 별도로 원래 수치는 보존합니다.')
