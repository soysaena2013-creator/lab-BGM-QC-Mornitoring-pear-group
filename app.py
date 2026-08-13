import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from io import BytesIO

# ReportLab Imports for PDF Generation
import urllib.request
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="BGM QC Peer Group Dashboard",
    page_icon="🩸",
    layout="wide"
)

st.title("🩸 Blood Glucose Monitor (BGM) Inter-lab Peer Group Dashboard")
st.markdown("ระบบประมวลผล QC และเปรียบเทียบ performance ระหว่างเครื่องตรวจน้ำตาลเจาะปลายนิ้ว (Peer Group Analysis)")

# --- DEFAULT GOOGLE SHEETS LINK ---
DEFAULT_SHEETS_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTQeFkTVumXOf3h3Luo3VOBwBrZzlrPRTRTMplSM2U-76i6papYP8qtyekfIFCsi1EX7lUo7fBF13b-/pub?gid=728378443&single=true&output=csv"

# --- SIDEBAR CONFIG ---
st.sidebar.header("⚙️ การเชื่อมต่อข้อมูล")
sheets_url = st.sidebar.text_input(
    "Google Sheets CSV Link:",
    value=DEFAULT_SHEETS_URL
)

# --- DATA LOADING & CLEANING ---
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
col_dept = 'แผนก/หน่วยงาน/หมู่บ้าน'
col_lot_qc = 'Lot no. ของสารควบคุมคุณภาพ(QC)'
col_l1 = 'ผลการตรวจ สารควบคุมคุณภาพ(QC) level 1'
col_l2 = 'ผลการตรวจ สารควบคุมคุณภาพ(QC) level 2'
col_timestamp = 'ประทับเวลา'
col_date = 'วันที่รายงานผล'

# Clean Numeric Data
df_raw[col_l1] = pd.to_numeric(df_raw[col_l1], errors='coerce')
df_raw[col_l2] = pd.to_numeric(df_raw[col_l2], errors='coerce')

# Process Date & YearMonth
if col_date in df_raw.columns:
    df_raw['Parsed_Date'] = pd.to_datetime(df_raw[col_date], errors='coerce')
else:
    df_raw['Parsed_Date'] = pd.to_datetime(df_raw[col_timestamp], errors='coerce')

df_raw['YearMonth'] = df_raw['Parsed_Date'].dt.strftime('%Y-%m')
df_raw['YearMonth'] = df_raw['YearMonth'].fillna('Unspecified')

# Dynamic Extract SN Function (ดึงค่า SN จากคอลัมน์ของแผนกที่เลือก)
def extract_sn(row):
    dept = str(row[col_dept])
    for col in row.index:
        if 'Serial number (SN)' in col and dept in col:
            val = row[col]
            if pd.notna(val) and str(val).strip() != '':
                return str(val).strip()
    for col in row.index:
        if 'Serial number (SN)' in col:
            val = row[col]
            if pd.notna(val) and str(val).strip() != '':
                return str(val).strip()
    return 'N/A'

df_raw['Machine_SN'] = df_raw.apply(extract_sn, axis=1)

# --- SIDEBAR FILTERS ---
st.sidebar.header("🔍 ตัวกรองการวิเคราะห์")

# 1. Monthly Filter
available_months = sorted([str(m) for m in df_raw['YearMonth'].unique() if str(m) != 'nan'], reverse=True)
selected_month = st.sidebar.selectbox("เลือกเดือน:", ["ทั้งหมด"] + available_months)

# 2. Department Filter (ใช้เพื่อซ่อน/แสดงผล ไม่นำไปใช้ในการคำนวณค่า Peer)
available_depts = sorted([str(d) for d in df_raw[col_dept].dropna().unique().tolist()])
selected_dept = st.sidebar.selectbox("เลือกแผนก/หน่วยงาน (เพื่อแสดงผล):", ["ทั้งหมด"] + available_depts)

# 3. Lot QC Filter
available_lots = [str(x) for x in df_raw[col_lot_qc].dropna().unique().tolist()]
selected_lot = st.sidebar.selectbox("เลือก Lot no. ของ QC:", available_lots if available_lots else ["ไม่มีข้อมูล"])

# 4. Level QC Filter
selected_level = st.sidebar.radio("เลือกระดับ QC:", ["Level 1", "Level 2"])


# ==============================================================================
# --- STEP 1: คำนวณ PEER GROUP STATS จากภาพรวมทั้งหมด (ไม่กรองแผนก) ---
# ==============================================================================
df_peer_base = df_raw.copy()

if selected_month != "ทั้งหมด":
    df_peer_base = df_peer_base[df_peer_base['YearMonth'] == selected_month]

if available_lots:
    df_peer_base = df_peer_base[df_peer_base[col_lot_qc].astype(str) == str(selected_lot)]

val_col = col_l1 if selected_level == "Level 1" else col_l2

# ดึงเฉพาะแถวที่มีค่า QC ถูกต้องจาก "ทุกแผนก"
df_valid_peer_qc = df_peer_base.dropna(subset=[val_col])

# ค่าสถิติ Peer Group สากล (Overall Peer Statistics)
peer_n = len(df_valid_peer_qc)
peer_mean = df_valid_peer_qc[val_col].mean() if peer_n > 0 else 0
peer_sd = df_valid_peer_qc[val_col].std() if peer_n > 1 else 0
peer_cv = (peer_sd / peer_mean * 100) if peer_mean > 0 else 0


# ==============================================================================
# --- STEP 2: คำนวณค่าของแต่ละเครื่อง และเทียบกับ PEER GROUP สากล ---
# ==============================================================================
machine_stats = df_valid_peer_qc.groupby(['Machine_SN', col_dept]).agg(
    Lab_Mean=(val_col, 'mean'),
    Lab_SD=(val_col, 'std'),
    N_Count=(val_col, 'count')
).reset_index()

machine_stats['Lab_SD'] = machine_stats['Lab_SD'].fillna(0)
machine_stats['Lab_CV'] = np.where(machine_stats['Lab_Mean'] > 0, (machine_stats['Lab_SD'] / machine_stats['Lab_Mean']) * 100, 0)

# นำค่า Peer Group สากล (จาก Step 1) มาใช้กับทุกเครื่อง
machine_stats['Peer_Mean'] = peer_mean
machine_stats['Peer_SD'] = peer_sd
machine_stats['SDI'] = np.where(peer_sd > 0, (machine_stats['Lab_Mean'] - peer_mean) / peer_sd, 0)
machine_stats['Percent_Bias'] = np.where(peer_mean > 0, ((machine_stats['Lab_Mean'] - peer_mean) / peer_mean) * 100, 0)
machine_stats['CVI'] = np.where(peer_cv > 0, machine_stats['Lab_CV'] / peer_cv, 0)

def eval_status(sdi):
    abs_sdi = abs(sdi)
    if abs_sdi <= 2.0:
        return '🟢 Acceptable'
    elif abs_sdi <= 3.0:
        return '🟡 Warning'
    else:
        return '🔴 Unacceptable (Action signal)'

machine_stats['Status'] = machine_stats['SDI'].apply(eval_status)


# ==============================================================================
# --- STEP 3: กรองแผนกเฉพาะเพื่อการแสดงผล (DISPLAY ONLY) ---
# ==============================================================================
if selected_dept != "ทั้งหมด":
    machine_stats_display = machine_stats[machine_stats[col_dept].astype(str) == selected_dept].copy()
else:
    machine_stats_display = machine_stats.copy()


# --- METRICS DISPLAY (แสดงค่า Peer Group ภาพรวมเสมอ ไม่เปลี่ยนตามการเลือกแผนก) ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("จำนวนข้อมูล Peer ภาพรวม (Total N)", f"{peer_n} รายการ ({len(machine_stats)} เครื่อง)")
col2.metric(f"Peer Mean ภาพรวม ({selected_level})", f"{peer_mean:.2f} mg/dL")
col3.metric("Peer SD ภาพรวม", f"{peer_sd:.2f}")
col4.metric("Peer %CV ภาพรวม", f"{peer_cv:.2f}%")

st.divider()

# --- SDI CHART ---
st.subheader(f"📊 กราฟแท่ง SDI (Z-Score) - {selected_level} | เดือน: {selected_month} | แสดงผล: {selected_dept}")

if len(machine_stats_display) > 0:
    fig = go.Figure()
    colors_list = machine_stats_display['SDI'].apply(
        lambda x: '#2ca02c' if abs(x) <= 2.0 else ('#ff7f0e' if abs(x) <= 3.0 else '#d62728')
    )
    x_labels = machine_stats_display['Machine_SN'].astype(str) + " (" + machine_stats_display[col_dept].astype(str) + ")"
    
    fig.add_trace(go.Bar(
        x=x_labels,
        y=machine_stats_display['SDI'],
        marker_color=colors_list,
        text=machine_stats_display['SDI'].round(2),
        textposition='outside'
    ))
    
    fig.add_hline(y=0, line_dash="solid", line_color="black")
    fig.add_hline(y=2.0, line_dash="dot", line_color="orange", annotation_text="+2.0 SDI (Warning Limit)")
    fig.add_hline(y=-2.0, line_dash="dot", line_color="orange", annotation_text="-2.0 SDI (Warning Limit)")
    fig.add_hline(y=3.0, line_dash="dash", line_color="red", annotation_text="+3.0 SDI (Unacceptable Limit)")
    fig.add_hline(y=-3.0, line_dash="dash", line_color="red", annotation_text="-3.0 SDI (Unacceptable Limit)")
    
    y_max = max(3.5, abs(machine_stats_display['SDI']).max() + 0.5) if len(machine_stats_display) > 0 else 3.5
    fig.update_layout(
        xaxis_title="เครื่องตรวจ (SN / PIN) และ แผนก/หน่วยงาน",
        yaxis_title="Standard Deviation Index (SDI)",
        yaxis=dict(range=[-y_max, y_max]),
        height=450
    )
    st.plotly_chart(fig, use_container_width=True)

# --- TABLE DISPLAY ---
st.subheader("📋 ตารางสรุปผล Peer Group รายเครื่อง")

rename_dict = {
    'Machine_SN': 'Serial Number / PIN',
    col_dept: 'แผนก/หน่วยงาน',
    'Lab_Mean': 'ค่าเฉลี่ยเครื่อง (Mean)',
    'Lab_SD': 'ค่า SD เครื่อง',
    'Lab_CV': '%CV เครื่อง',
    'Peer_Mean': 'Peer Mean (ภาพรวม)',
    'Peer_SD': 'Peer SD (ภาพรวม)',
    'SDI': 'SDI (Z-Score)',
    'Percent_Bias': '%Bias',
    'CVI': 'CVI',
    'Status': 'ผลการประเมิน'
}

df_display = machine_stats_display[list(rename_dict.keys())].rename(columns=rename_dict)

st.dataframe(
    df_display.style.format({
        'ค่าเฉลี่ยเครื่อง (Mean)': '{:.2f}',
        'ค่า SD เครื่อง': '{:.2f}',
        '%CV เครื่อง': '{:.2f}%',
        'Peer Mean (ภาพรวม)': '{:.2f}',
        'Peer SD (ภาพรวม)': '{:.2f}',
        'SDI (Z-Score)': '{:+.2f}',
        '%Bias': '{:+.2f}%',
        'CVI': '{:.2f}'
    }),
    use_container_width=True
)


# --- HELPER FUNCTION: DOWNLOAD & REGISTER THAI FONT FOR PDF ---
@st.cache_resource
def register_thai_font():
    try:
        font_url = "https://github.com/google/fonts/raw/main/ofl/sarabun/Sarabun-Regular.ttf"
        font_bold_url = "https://github.com/google/fonts/raw/main/ofl/sarabun/Sarabun-Bold.ttf"
        
        font_data = urllib.request.urlopen(font_url).read()
        font_bold_data = urllib.request.urlopen(font_bold_url).read()
        
        font_buffer = BytesIO(font_data)
        font_bold_buffer = BytesIO(font_bold_data)
        
        pdfmetrics.registerFont(TTFont('THSarabun', font_buffer))
        pdfmetrics.registerFont(TTFont('THSarabun-Bold', font_bold_buffer))
        return 'THSarabun', 'THSarabun-Bold'
    except Exception:
        return 'Helvetica', 'Helvetica-Bold'


# --- PDF GENERATION FUNCTION ---
def generate_pdf_report(df_report, peer_m, peer_s, peer_c, peer_n_total, month, dept, lot, level):
    font_reg, font_bold = register_thai_font()
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=30,
        leftMargin=30,
        topMargin=30,
        bottomMargin=30
    )
    
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'TitleStyle',
        fontName=font_bold,
        fontSize=18,
        alignment=1,
        spaceAfter=5
    )
    
    subtitle_style = ParagraphStyle(
        'SubTitleStyle',
        fontName=font_reg,
        fontSize=11,
        alignment=0,
        spaceAfter=12
    )
    
    cell_style = ParagraphStyle(
        'CellStyle',
        fontName=font_reg,
        fontSize=9,
        alignment=1,
        leading=11
    )
    
    cell_header_style = ParagraphStyle(
        'HeaderStyle',
        fontName=font_bold,
        fontSize=9,
        alignment=1,
        textColor=colors.whitesmoke,
        leading=11
    )
    
    elements = []
    
    elements.append(Paragraph("<b>INTER-LABORATORY PEER GROUP ANALYSIS REPORT</b>", title_style))
    elements.append(Paragraph("<b>Blood Glucose Monitoring System (BGM QC Monitoring)</b>", ParagraphStyle('Sub', parent=title_style, fontName=font_bold, fontSize=13)))
    
    meta_info = f"""
    <b>Period (Month):</b> {month} &nbsp;&nbsp;|&nbsp;&nbsp; 
    <b>Department Filter:</b> {dept} &nbsp;&nbsp;|&nbsp;&nbsp; 
    <b>QC Control Level:</b> {level} &nbsp;&nbsp;|&nbsp;&nbsp; 
    <b>QC Lot No.:</b> {lot}<br/>
    <b>Overall Peer Group Mean:</b> {peer_m:.2f} mg/dL &nbsp;&nbsp;|&nbsp;&nbsp; 
    <b>Overall Peer Group SD:</b> {peer_s:.2f} &nbsp;&nbsp;|&nbsp;&nbsp; 
    <b>Overall Peer Group %CV:</b> {peer_c:.2f}% &nbsp;&nbsp;|&nbsp;&nbsp; 
    <b>Total Peer QC Runs (N):</b> {peer_n_total}
    """
    elements.append(Paragraph(meta_info, subtitle_style))
    elements.append(Spacer(1, 10))
    
    # Headers
    table_data = [
        [
            Paragraph("SN / PIN", cell_header_style),
            Paragraph("Department", cell_header_style),
            Paragraph("Lab Mean", cell_header_style),
            Paragraph("Lab SD", cell_header_style),
            Paragraph("%CV", cell_header_style),
            Paragraph("Peer Mean", cell_header_style),
            Paragraph("Peer SD", cell_header_style),
            Paragraph("SDI", cell_header_style),
            Paragraph("%Bias", cell_header_style),
            Paragraph("CVI", cell_header_style),
            Paragraph("Status", cell_header_style)
        ]
    ]
    
    # Data Rows
    for _, row in df_report.iterrows():
        table_data.append([
            Paragraph(str(row['Serial Number / PIN']), cell_style),
            Paragraph(str(row['แผนก/หน่วยงาน']), cell_style),
            Paragraph(f"{row['ค่าเฉลี่ยเครื่อง (Mean)']:.2f}", cell_style),
            Paragraph(f"{row['ค่า SD เครื่อง']:.2f}", cell_style),
            Paragraph(f"{row['%CV เครื่อง']:.2f}%", cell_style),
            Paragraph(f"{row['Peer Mean (ภาพรวม)']:.2f}", cell_style),
            Paragraph(f"{row['Peer SD (ภาพรวม)']:.2f}", cell_style),
            Paragraph(f"{row['SDI (Z-Score)'] if not pd.isna(row['SDI (Z-Score)']) else 0:+.2f}", cell_style),
            Paragraph(f"{row['%Bias'] if not pd.isna(row['%Bias']) else 0:+.2f}%", cell_style),
            Paragraph(f"{row['CVI'] if not pd.isna(row['CVI']) else 0:.2f}", cell_style),
            Paragraph(str(row['ผลการประเมิน']).replace('🟢 ', '').replace('🟡 ', '').replace('🔴 ', ''), cell_style)
        ])
    
    col_widths = [130, 95, 55, 50, 45, 55, 50, 45, 50, 40, 110]
    
    t = Table(table_data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1f77b4')),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,0), 5),
        ('TOPPADDING', (0,0), (-1,0), 5),
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#f7f9fa')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
    ]))
    
    elements.append(t)
    elements.append(Spacer(1, 15))
    
    guide_text = "<b>Interpretation Guidelines:</b> Acceptable (|SDI| <= 2.0) | Warning (2.0 < |SDI| <= 3.0) | Unacceptable / Action signal (|SDI| > 3.0)"
    elements.append(Paragraph(guide_text, ParagraphStyle('Guide', fontName=font_reg, fontSize=9)))
    elements.append(Spacer(1, 20))
    
    sig_table = Table([
        ['Reported By: ___________________________', 'Reviewed By: ___________________________'],
        ['Date: ____ / ____ / ________', 'Date: ____ / ____ / ________']
    ], colWidths=[380, 380])
    sig_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,-1), font_reg),
        ('FONTSIZE', (0,0), (-1,-1), 9),
    ]))
    elements.append(sig_table)
    
    doc.build(elements)
    buffer.seek(0)
    return buffer


# --- DOWNLOAD BUTTONS ---
st.divider()
c1, c2 = st.columns(2)

with c1:
    csv_data = df_display.to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        label="📥 ดาวน์โหลดรายงานสรุปเป็น CSV (Excel)",
        data=csv_data,
        file_name=f'BGM_Peer_Report_{selected_month}_{selected_dept}_{selected_level}.csv',
        mime='text/csv',
        use_container_width=True
    )

with c2:
    if not df_display.empty:
        pdf_bytes = generate_pdf_report(
            df_display, peer_mean, peer_sd, peer_cv, peer_n,
            selected_month, selected_dept, selected_lot, selected_level
        )
        st.download_button(
            label="📄 ดาวน์โหลดรายงานสรุปเป็นเอกสาร PDF",
            data=pdf_bytes,
            file_name=f'BGM_Peer_Report_{selected_month}_{selected_dept}_{selected_level}.pdf',
            mime='application/pdf',
            use_container_width=True
        )