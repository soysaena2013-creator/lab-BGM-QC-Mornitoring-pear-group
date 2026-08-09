import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="BGM QC Peer Group Dashboard",
    page_icon="🩸",
    layout="wide"
)

st.title("🩸 Blood Glucose Monitor (BGM) Inter-lab Peer Group Dashboard")
st.markdown("ระบบประมวลผล QC และเปรียบเทียบ performance ระหว่างเครื่องตรวจน้ำตาลเจาะปลายนิ้ว (Peer Group Analysis)")

# --- DEFAULT GOOGLE SHEETS LINK ---
DEFAULT_SHEETS_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vR9es9a9qTs-HRBHsV_uZsFcZczKhRmKpiQVPV8djZANufaYV2EvUg1cO6Q26vwp877AN0ZH9HHhBYr/pub?gid=1644746857&single=true&output=csv"

# --- SIDEBAR CONFIG ---
st.sidebar.header("⚙️ การเชื่อมต่อข้อมูล")
sheets_url = st.sidebar.text_input(
    "Google Sheets CSV Link:",
    value=DEFAULT_SHEETS_URL
)

# --- DATA LOADING ---
@st.cache_data(ttl=30)
def load_data(url):
    df = pd.read_csv(url)
    return df

try:
    df_raw = load_data(sheets_url)
    st.sidebar.success("✅ เชื่อมต่อ Google Sheets สำเร็จ!")
except Exception as e:
    st.error(f"ไม่สามารถโหลดข้อมูลได้ กรุณาตรวจสอบลิงก์: {e}")
    st.stop()

# --- COLUMN DEFINITIONS ---
col_sn = 'Serial number (SN) ของเครื่องตรวจ'
col_dept = 'แผนก/หน่วยงาน/หมู่บ้าน'
col_lot_qc = 'Lot no. ของสารควบคุมคุณภาพ(QC)'
col_l1 = 'ผลการตรวจ สารควบคุมคุณภาพ(QC) level 1'
col_l2 = 'ผลการตรวจ สารควบคุมคุณภาพ(QC) level 2'

# Clean Numeric Data
df_raw[col_l1] = pd.to_numeric(df_raw[col_l1], errors='coerce')
df_raw[col_l2] = pd.to_numeric(df_raw[col_l2], errors='coerce')

# --- SIDEBAR FILTERS ---
st.sidebar.header("🔍 ตัวกรองการวิเคราะห์")
available_lots = [str(x) for x in df_raw[col_lot_qc].dropna().unique().tolist()]

selected_lot = st.sidebar.selectbox(
    "เลือก Lot no. ของ QC:", 
    available_lots if available_lots else ["ไม่มีข้อมูล"]
)

selected_level = st.sidebar.radio("เลือกระดับ QC:", ["Level 1", "Level 2"])

# Filter Dataset
df_filtered = df_raw[df_raw[col_lot_qc].astype(str) == str(selected_lot)]
val_col = col_l1 if selected_level == "Level 1" else col_l2

# --- CALCULATION ENGINE ---
machine_stats = df_filtered.groupby([col_sn, col_dept]).agg(
    Lab_Mean=(val_col, 'mean'),
    Lab_SD=(val_col, 'std'),
    N_Count=(val_col, 'count')
).reset_index()

machine_stats['Lab_SD'] = machine_stats['Lab_SD'].fillna(0)
machine_stats['Lab_CV'] = np.where(machine_stats['Lab_Mean'] > 0, (machine_stats['Lab_SD'] / machine_stats['Lab_Mean']) * 100, 0)

peer_mean = machine_stats['Lab_Mean'].mean() if len(machine_stats) > 0 else 0
peer_sd = machine_stats['Lab_Mean'].std() if len(machine_stats) > 1 else 0
peer_cv = (peer_sd / peer_mean * 100) if peer_mean > 0 else 0
peer_n = len(machine_stats)

machine_stats['Peer_Mean'] = peer_mean
machine_stats['Peer_SD'] = peer_sd
machine_stats['SDI'] = np.where(peer_sd > 0, (machine_stats['Lab_Mean'] - peer_mean) / peer_sd, 0)
machine_stats['Percent_Bias'] = np.where(peer_mean > 0, ((machine_stats['Lab_Mean'] - peer_mean) / peer_mean) * 100, 0)
machine_stats['CVI'] = np.where(peer_cv > 0, machine_stats['Lab_CV'] / peer_cv, 0)

def eval_status(sdi):
    abs_sdi = abs(sdi)
    if abs_sdi <= 1.0:
        return '🟢 Pass (Good)'
    elif abs_sdi <= 2.0:
        return '🟡 Warning (Acceptable)'
    else:
        return '🔴 Action Required'

machine_stats['Status'] = machine_stats['SDI'].apply(eval_status)

# --- METRICS DISPLAY ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("จำนวนเครื่องในกลุ่ม (Peer N)", f"{peer_n} เครื่อง")
col2.metric(f"Peer Mean ({selected_level})", f"{peer_mean:.2f} mg/dL")
col3.metric("Peer SD", f"{peer_sd:.2f}")
col4.metric("Peer %CV", f"{peer_cv:.2f}%")

st.divider()

# --- SDI CHART ---
st.subheader(f"📊 กราฟแท่ง SDI (Z-Score) - สารควบคุม {selected_level} (Lot: {selected_lot})")

if peer_n > 0:
    fig = go.Figure()
    colors = machine_stats['SDI'].apply(lambda x: '#2ca02c' if abs(x) <= 1.0 else ('#ff7f0e' if abs(x) <= 2.0 else '#d62728'))
    x_labels = machine_stats[col_sn].astype(str) + " (" + machine_stats[col_dept].astype(str) + ")"
    
    fig.add_trace(go.Bar(
        x=x_labels,
        y=machine_stats['SDI'],
        marker_color=colors,
        text=machine_stats['SDI'].round(2),
        textposition='outside'
    ))
    
    fig.add_hline(y=0, line_dash="solid", line_color="black")
    fig.add_hline(y=1.0, line_dash="dot", line_color="orange", annotation_text="+1.0 SDI Limit")
    fig.add_hline(y=-1.0, line_dash="dot", line_color="orange", annotation_text="-1.0 SDI Limit")
    fig.add_hline(y=2.0, line_dash="dash", line_color="red", annotation_text="+2.0 SDI Limit")
    fig.add_hline(y=-2.0, line_dash="dash", line_color="red", annotation_text="-2.0 SDI Limit")
    
    y_max = max(3.0, abs(machine_stats['SDI']).max() + 0.5) if len(machine_stats) > 0 else 3.0
    fig.update_layout(
        xaxis_title="เครื่องตรวจ (SN) และ แผนก/หน่วยงาน",
        yaxis_title="Standard Deviation Index (SDI)",
        yaxis=dict(range=[-y_max, y_max]),
        height=480
    )
    st.plotly_chart(fig, use_container_width=True)

# --- TABLE DISPLAY ---
st.subheader("📋 ตารางสรุปผล Peer Group รายเครื่อง")

rename_dict = {
    col_sn: 'Serial Number (SN)',
    col_dept: 'แผนก/หน่วยงาน',
    'Lab_Mean': 'ค่าเฉลี่ยเครื่อง (Mean)',
    'Lab_SD': 'ค่า SD เครื่อง',
    'Lab_CV': '%CV เครื่อง',
    'Peer_Mean': 'Peer Mean',
    'Peer_SD': 'Peer SD',
    'SDI': 'SDI (Z-Score)',
    'Percent_Bias': '%Bias',
    'CVI': 'CVI',
    'Status': 'ผลการประเมิน'
}

df_display = machine_stats[list(rename_dict.keys())].rename(columns=rename_dict)

st.dataframe(
    df_display.style.format({
        'ค่าเฉลี่ยเครื่อง (Mean)': '{:.2f}',
        'ค่า SD เครื่อง': '{:.2f}',
        '%CV เครื่อง': '{:.2f}%',
        'Peer Mean': '{:.2f}',
        'Peer SD': '{:.2f}',
        'SDI (Z-Score)': '{:+.2f}',
        '%Bias': '{:+.2f}%',
        'CVI': '{:.2f}'
    }),
    use_container_width=True
)

# Download CSV
csv_data = df_display.to_csv(index=False).encode('utf-8-sig')
st.download_button(
    label="📥 ดาวน์โหลดรายงานสรุปเป็น CSV",
    data=csv_data,
    file_name=f'BGM_Peer_Group_Report_{selected_level}_Lot_{selected_lot}.csv',
    mime='text/csv'
)