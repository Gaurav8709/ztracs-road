from reportlab.graphics.shapes import Drawing, Rect, Circle, String
"""
Z-TRACS Road Intelligence - PDF Report Generator
Implements Section 26 ("Inspection Report") & Section 27 ("AI Auditability")
"""
import os
from datetime import datetime
from xml.sax.saxutils import escape as xml_escape  # E22: sanitize user data for ReportLab Paragraph()
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage, HRFlowable
)
from backend.database import get_connection

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS_DIR = os.getenv("REPORTS_DIR", os.path.join(PROJECT_ROOT, "static", "reports"))
try:
    os.makedirs(REPORTS_DIR, exist_ok=True)
except OSError:
    pass


def create_static_gis_map(segments, detections, width=540, height=75) -> Drawing:
    d = Drawing(width, height)
    # Background panel
    d.add(Rect(0, 0, width, height, rx=5, ry=5, fillColor=colors.HexColor("#0F172A"), strokeColor=colors.HexColor("#1E293B"), strokeWidth=1))
    
    # Title & Legend
    d.add(String(12, height - 16, "Corridor segment overview (schematic)", fontSize=8, fontName="Helvetica-Bold", fillColor=colors.HexColor("#E2E8F0")))
    d.add(Circle(width - 150, height - 13, 3, fillColor=colors.HexColor("#22C55E"), strokeColor=None))
    d.add(String(width - 143, height - 16, "Good", fontSize=7, fontName="Helvetica", fillColor=colors.HexColor("#94A3B8")))
    d.add(Circle(width - 115, height - 13, 3, fillColor=colors.HexColor("#EAB308"), strokeColor=None))
    d.add(String(width - 108, height - 16, "Fair", fontSize=7, fontName="Helvetica", fillColor=colors.HexColor("#94A3B8")))
    d.add(Circle(width - 85, height - 13, 3, fillColor=colors.HexColor("#EA580C"), strokeColor=None))
    d.add(String(width - 78, height - 16, "High Risk", fontSize=7, fontName="Helvetica", fillColor=colors.HexColor("#94A3B8")))
    d.add(Circle(width - 35, height - 13, 3, fillColor=colors.HexColor("#DC2626"), strokeColor=None))
    d.add(String(width - 28, height - 16, "Crit", fontSize=7, fontName="Helvetica", fillColor=colors.HexColor("#94A3B8")))

    if not segments:
        d.add(String(width / 2, 30, "No corridor segments recorded for this road (0.0 KM)", textAnchor="middle", fontSize=8, fontName="Helvetica-Oblique", fillColor=colors.HexColor("#64748B")))
        return d

    margin_x = 15
    track_w = width - 2 * margin_x
    n_segs = len(segments)
    seg_w = track_w / max(n_segs, 1)
    track_y = 32
    track_h = 10

    color_map = {
        "GREEN": colors.HexColor("#22C55E"),
        "YELLOW": colors.HexColor("#EAB308"),
        "ORANGE": colors.HexColor("#EA580C"),
        "RED": colors.HexColor("#DC2626"),
    }

    for i, s in enumerate(segments):
        sx = margin_x + i * seg_w
        scol = color_map.get(str(s.get("status_color", "GREEN")).upper(), colors.HexColor("#22C55E"))
        d.add(Rect(sx + 1, track_y, max(seg_w - 2, 1), track_h, rx=2, ry=2, fillColor=scol, strokeColor=None))
        s_label = str(s.get("id", f"S{i+1}"))
        d.add(String(sx + seg_w / 2, track_y - 11, s_label, textAnchor="middle", fontSize=6.5, fontName="Helvetica-Bold", fillColor=colors.HexColor("#94A3B8")))

    for det in detections:
        seg_id = det.get("road_segment_id")
        seg_idx = next((i for i, s in enumerate(segments) if s["id"] == seg_id), None)
        if seg_idx is not None:
            pin_x = margin_x + seg_idx * seg_w + (seg_w * 0.5)
            sev = str(det.get("severity", "medium")).lower()
            pin_col = colors.HexColor("#DC2626") if sev == "critical" else (colors.HexColor("#EA580C") if sev == "high" else colors.HexColor("#EAB308"))
            d.add(Circle(pin_x, track_y + track_h + 8, 3.5, fillColor=pin_col, strokeColor=colors.white, strokeWidth=0.8))

    return d

def generate_inspection_pdf(inspection_id: str) -> str:
    pdf_filename = f"inspection_{inspection_id}_report.pdf"
    pdf_path = os.path.join(REPORTS_DIR, pdf_filename)

    conn = get_connection()
    cursor = conn.cursor()

    # Fetch inspection details
    cursor.execute("SELECT * FROM inspections WHERE id = %s", (inspection_id,))
    insp = cursor.fetchone()
    if not insp:
        conn.close()
        raise ValueError(f"Inspection {inspection_id} not found")

    # Fetch detections
    cursor.execute("SELECT * FROM detections WHERE inspection_id = %s ORDER BY timestamp ASC", (inspection_id,))
    detections = cursor.fetchall()

    # Fetch segments for this road
    insp_road_id = dict(insp).get("road_id")
    det_seg_ids = list(set([d["road_segment_id"] for d in detections if d.get("road_segment_id")]))
    if insp_road_id:
        cursor.execute("SELECT * FROM road_segments WHERE road_id = %s ORDER BY id ASC", (insp_road_id,))
        segments = cursor.fetchall()
        if not segments and det_seg_ids:
            cursor.execute("SELECT * FROM road_segments WHERE id = ANY(%s) ORDER BY id ASC", (det_seg_ids,))
            segments = cursor.fetchall()
    elif det_seg_ids:
        cursor.execute("SELECT * FROM road_segments WHERE id = ANY(%s) ORDER BY id ASC", (det_seg_ids,))
        segments = cursor.fetchall()
    else:
        segments = []
    conn.close()

    # Document setup
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
        pageCompression=0
    )

    styles = getSampleStyleSheet()
    
    # Custom Palette
    c_primary = colors.HexColor("#0F172A")    # Deep slate
    c_accent = colors.HexColor("#0284C7")     # Sky blue
    c_high = colors.HexColor("#EA580C")       # Orange
    c_text_dark = colors.HexColor("#1E293B")
    c_border = colors.HexColor("#CBD5E1")
    c_bg_light = colors.HexColor("#F8FAFC")

    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=c_primary
    )

    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=14,
        textColor=c_accent
    )

    heading2_style = ParagraphStyle(
        'Heading2',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=c_primary,
        spaceBefore=10,
        spaceAfter=6
    )

    body_style = ParagraphStyle(
        'Body',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=c_text_dark
    )


    story = []

    # 1. Header Banner
    story.append(Paragraph("Z-TRACS ROAD INTELLIGENCE", subtitle_style))
    story.append(Paragraph("PoC Inspection Report", title_style))
    story.append(Paragraph(f"Theme 02 — AI for Roads, Bridges & Tunnels | Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", body_style))
    story.append(Spacer(1, 4))
    poc_note_style = ParagraphStyle(
        'PoCNote',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#64748B")
    )
    story.append(Paragraph("<b>PoC Advisory:</b> Scores and priorities are PoC workflow categories, not engineering standards. Detections generated via Mock CV Service.", poc_note_style))
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=2, color=c_accent, spaceBefore=2, spaceAfter=12))

    # 2. Executive Summary Cards Table
    critical_cnt = sum(1 for d in detections if d["severity"] == "critical")

    avg_condition = round(sum(s["condition_score"] for s in segments) / max(len(segments), 1), 1) if segments else 0.0
    high_risk_segs = sum(1 for s in segments if s["risk_score"] >= 60.0) if segments else 0

    # Dynamic survey distance calculation from road segments
    survey_dist_km = sum(float(s["length_km"]) for s in segments) if segments else 0.0

    summary_data = [
        [
            Paragraph("<b>Corridor / Road:</b>", body_style),
            Paragraph(xml_escape(str(insp['road_name'])), body_style),
            Paragraph("<b>Inspection ID:</b>", body_style),
            Paragraph(xml_escape(str(insp['id'])), body_style),
        ],
        [
            Paragraph("<b>Survey Distance:</b>", body_style),
            Paragraph(f"{survey_dist_km:.1f} KM", body_style),
            Paragraph("<b>AI Model:</b>", body_style),
            Paragraph(xml_escape(str(insp['model_version'])) + " (Mock CV)", body_style),
        ],
        [
            Paragraph("<b>Total Defects Detected:</b>", body_style),
            Paragraph(f"<b>{len(detections)}</b>", body_style),
            Paragraph("<b>Critical Defects (P1):</b>", body_style),
            Paragraph(f"<font color='#DC2626'><b>{critical_cnt}</b></font>", body_style),
        ],
        [
            Paragraph("<b>Average Road Health:</b>", body_style),
            Paragraph(f"<b>{avg_condition}/100</b>", body_style),
            Paragraph("<b>High-Risk Segments:</b>", body_style),
            Paragraph(f"<b>{high_risk_segs} of {len(segments)}</b>", body_style),
        ]
    ]

    summary_table = Table(summary_data, colWidths=[120, 150, 120, 150])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), c_bg_light),
        ('BOX', (0, 0), (-1, -1), 1, c_border),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, c_border),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 10))

    # Static GIS Map Representation / Corridor Overview
    if not segments:
        story.append(Paragraph("<i>No GIS corridor geometry or segments available for this inspection.</i>", body_style))
    else:
        story.append(create_static_gis_map(segments, detections, width=540, height=75))
    story.append(Spacer(1, 12))

    # 3. Defect & Severity Breakdown
    story.append(Paragraph("1. Defect & Severity Distribution", heading2_style))
    classes_present = sorted(list(set(str(d.get("defect_type", "Unknown")).title() for d in detections)))

    breakdown_data = [
        [
            Paragraph("<b>Defect Class</b>", body_style),
            Paragraph("<b>Total Count</b>", body_style),
            Paragraph("<b>Critical (P1)</b>", body_style),
            Paragraph("<b>High (P2)</b>", body_style),
            Paragraph("<b>Medium (P3)</b>", body_style),
            Paragraph("<b>Low (P4)</b>", body_style)
        ]
    ]

    if not classes_present:
        breakdown_data.append([
            Paragraph("<i>No defects detected</i>", body_style),
            Paragraph("0", body_style),
            Paragraph("0", body_style),
            Paragraph("0", body_style),
            Paragraph("0", body_style),
            Paragraph("0", body_style)
        ])
    else:
        for cls in classes_present:
            cls_dets = [d for d in detections if str(d.get("defect_type", "")).title() == cls]
            tot_cnt = len(cls_dets)
            c_crit = sum(1 for d in cls_dets if str(d.get("severity", "")).lower() == "critical")
            c_high = sum(1 for d in cls_dets if str(d.get("severity", "")).lower() == "high")
            c_med = sum(1 for d in cls_dets if str(d.get("severity", "")).lower() == "medium")
            c_low = sum(1 for d in cls_dets if str(d.get("severity", "")).lower() == "low")

            crit_str = f"<font color='#DC2626'><b>{c_crit}</b></font>" if c_crit > 0 else "0"
            high_str = f"<font color='#EA580C'><b>{c_high}</b></font>" if c_high > 0 else "0"
            med_str = f"<font color='#CA8A04'><b>{c_med}</b></font>" if c_med > 0 else "0"
            low_str = str(c_low)

            breakdown_data.append([
                Paragraph(xml_escape(cls), body_style),
                Paragraph(f"<b>{tot_cnt}</b>", body_style),
                Paragraph(crit_str, body_style),
                Paragraph(high_str, body_style),
                Paragraph(med_str, body_style),
                Paragraph(low_str, body_style)
            ])

    bd_table = Table(breakdown_data, colWidths=[150, 75, 80, 75, 80, 80])
    bd_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
        ('GRID', (0, 0), (-1, -1), 0.5, c_border),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(bd_table)
    story.append(Spacer(1, 14))

    # 4. Road Segment Condition & Risk Analysis (Section 17 & 21)
    story.append(Paragraph("2. Road Segment Condition & Risk Ranking", heading2_style))
    if not segments:
        story.append(Paragraph("No segments recorded for this road (0.0 KM).", body_style))
        story.append(Spacer(1, 14))
    else:
        seg_table_data = [
            [
                Paragraph("<b>Segment ID</b>", body_style),
                Paragraph("<b>Segment Name / Corridor Section</b>", body_style),
                Paragraph("<b>Condition Score</b>", body_style),
                Paragraph("<b>Risk Score</b>", body_style),
                Paragraph("<b>Priority</b>", body_style),
                Paragraph("<b>Status</b>", body_style)
            ]
        ]

        for s in segments:
            col = "#16A34A" if s["status_color"] == "GREEN" else ("#CA8A04" if s["status_color"] == "YELLOW" else ("#EA580C" if s["status_color"] == "ORANGE" else "#DC2626"))
            seg_table_data.append([
                Paragraph(f"<b>{xml_escape(str(s['id']))}</b>", body_style),
                Paragraph(xml_escape(str(s['segment_name'])[:35]), body_style),
                Paragraph(f"{s['condition_score']}/100", body_style),
                Paragraph(f"<b>{s['risk_score']}/100</b>", body_style),
                Paragraph(f"<b>{s['priority']}</b>", body_style),
                Paragraph(f"<font color='{col}'><b>{s['status_color']}</b></font>", body_style)
            ])

        seg_table = Table(seg_table_data, colWidths=[65, 200, 75, 65, 65, 70])
        seg_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
            ('GRID', (0, 0), (-1, -1), 0.5, c_border),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(seg_table)
        story.append(Spacer(1, 14))

    # 5. High-Risk Corridor Segments & Priority Interventions
    story.append(Paragraph("3. High-Risk Corridor Segments & Recommended Interventions", heading2_style))
    high_risk_list = [s for s in segments if float(s.get("risk_score", 0.0) or 0.0) >= 60.0 or str(s.get("priority", "")).upper() in ("P1", "P2")]
    if not high_risk_list:
        story.append(Paragraph("<i>No high-risk segments identified in this survey corridor (all segments meet baseline pavement criteria).</i>", body_style))
        story.append(Spacer(1, 10))
    else:
        hr_data = [
            [
                Paragraph("<b>Segment</b>", body_style),
                Paragraph("<b>Location / Section</b>", body_style),
                Paragraph("<b>Risk Score</b>", body_style),
                Paragraph("<b>Priority</b>", body_style),
                Paragraph("<b>Recommended Intervention (PoC Advisory)</b>", body_style),
            ]
        ]
        for hr_s in high_risk_list:
            p_val = str(hr_s.get("priority", "P2")).upper()
            action_desc = "Recommended P1 safety inspection and surface patching assessment" if p_val == "P1" else "Recommended P2 asphalt resurfacing and joint maintenance review"
            p_col = "#DC2626" if p_val == "P1" else "#EA580C"
            hr_data.append([
                Paragraph(f"<b>{xml_escape(str(hr_s['id']))}</b>", body_style),
                Paragraph(xml_escape(str(hr_s['segment_name'])[:30]), body_style),
                Paragraph(f"<b>{hr_s['risk_score']}/100</b>", body_style),
                Paragraph(f"<font color='{p_col}'><b>{p_val}</b></font>", body_style),
                Paragraph(action_desc, body_style),
            ])
        hr_table = Table(hr_data, colWidths=[65, 145, 65, 55, 210])
        hr_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#FEE2E2")),
            ('GRID', (0, 0), (-1, -1), 0.5, c_border),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(hr_table)
        story.append(Spacer(1, 12))

    # 6. Flagship AI Defect Evidence (Section 18 & 27) - Up to 3 Evidence Images
    story.append(Paragraph("4. Flagship Defect Evidence & AI Auditability", heading2_style))
    story.append(Paragraph("Every detection is traceable to frame ID, video timestamp, model version, and geocoordinates per Section 27.", body_style))
    story.append(Spacer(1, 6))

    if not detections:
        story.append(Paragraph("<b>No detections recorded.</b>", body_style))
    else:
        sev_weights = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        sorted_dets = sorted(
            detections,
            key=lambda d: (
                sev_weights.get(str(d.get("severity", "")).lower(), 0),
                float(d.get("confidence", 0.0) or 0.0)
            ),
            reverse=True
        )
        top_dets = sorted_dets[:3]

        for idx, top_det in enumerate(top_dets):
            det_id_val = top_det.get("detection_id") or top_det.get("id") or "N/A"
            det_type_val = str(top_det.get("defect_type", "Defect")).title()
            sev_val = str(top_det.get("severity", "MEDIUM")).upper()
            sev_color = "#DC2626" if sev_val == "CRITICAL" else ("#EA580C" if sev_val == "HIGH" else "#CA8A04")
            p_tier = "P1" if sev_val == "CRITICAL" else ("P2" if sev_val == "HIGH" else "P3")
            model_ver_val = top_det.get("model_version") or insp.get("model_version") or "RoadDefect-v1.0"
            
            conf_num = float(top_det.get("confidence", 0.0) or 0.0)
            conf_str = f"{conf_num * 100:.1f}%" if conf_num <= 1.0 else f"{conf_num:.1f}%"
            
            lat_val = float(top_det.get("latitude", 0.0) or 0.0)
            lng_val = float(top_det.get("longitude", 0.0) or 0.0)
            coord_str = f"{lat_val:.5f} N, {lng_val:.5f} E"

            seg_id_val = top_det.get("road_segment_id") or "N/A"
            seg_match = next((s for s in segments if s["id"] == seg_id_val), None)
            seg_str = f"{seg_id_val} ({seg_match['segment_name'][:25]})" if seg_match else str(seg_id_val)

            ts_sec = float(top_det.get("timestamp", 0.0) or 0.0)
            m = int(ts_sec // 60)
            s = int(ts_sec % 60)
            frame_val = top_det.get("frame_id", "N/A")
            ts_str = f"{m:02d}:{s:02d} (Frame {frame_val})"

            if sev_val == "CRITICAL":
                action_str = "P1 — Immediate intervention assessment & deployment"
            elif sev_val == "HIGH":
                action_str = "P2 — Planned resurfacing & asphalt repair"
            elif sev_val == "MEDIUM":
                action_str = "P3 — Scheduled repainting / maintenance"
            else:
                action_str = "P4 — Routine monitoring in next survey cycle"

            # Locate evidence image on disk
            img_rel = str(top_det.get("evidence_anno_url") or top_det.get("evidence_orig_url") or "")
            for prefix in ("/static/media/evidence/", "static/media/evidence/", "/api/media/evidence/"):
                if img_rel.startswith(prefix):
                    img_rel = img_rel[len(prefix):]
            img_rel = img_rel.lstrip("/")

            evidence_env_dir = os.getenv("EVIDENCE_DIR", os.path.join(PROJECT_ROOT, "static", "media", "evidence"))
            candidate_paths = [
                os.path.join(evidence_env_dir, img_rel),
                os.path.join(evidence_env_dir, inspection_id, img_rel),
                os.path.join(evidence_env_dir, os.path.basename(img_rel)),
                os.path.join(PROJECT_ROOT, "static", "media", "evidence", img_rel),
                os.path.join(PROJECT_ROOT, "static", "media", "evidence", inspection_id, img_rel),
                os.path.join(PROJECT_ROOT, "static", "media", "evidence", os.path.basename(img_rel)),
                os.path.join(PROJECT_ROOT, "demo_assets", "evidence", img_rel),
                os.path.join(PROJECT_ROOT, "demo_assets", "evidence", "DEMO-001", os.path.basename(img_rel)),
                os.path.join(PROJECT_ROOT, "demo_assets", "evidence", os.path.basename(img_rel)),
            ]
            img_path = next((p for p in candidate_paths if os.path.exists(p) and os.path.isfile(p)), None)

            if img_path:
                try:
                    rl_img = RLImage(img_path, width=270, height=152)
                except Exception:
                    rl_img = Paragraph("<i>[Evidence image rendering unavailable]</i>", body_style)
            else:
                rl_img = Paragraph("<i>[Evidence image pending upload/sync]</i>", body_style)

            label_prefix = f"Priority Detection {idx + 1}" if len(top_dets) > 1 else "Flagship Detection"
            ev_desc = [
                Paragraph(f"<b>{label_prefix}: {xml_escape(str(det_id_val))}</b>", body_style),
                Paragraph(f"<b>Defect Class:</b> {xml_escape(det_type_val)}", body_style),
                Paragraph(f"<b>Severity:</b> <font color='{sev_color}'><b>{sev_val} ({p_tier})</b></font>", body_style),
                Paragraph(f"<b>Model Version:</b> {xml_escape(str(model_ver_val))}", body_style),
                Paragraph(f"<b>Inference Confidence:</b> {conf_str}", body_style),
                Paragraph(f"<b>Coordinates:</b> {coord_str}", body_style),
                Paragraph(f"<b>Segment:</b> {xml_escape(seg_str)}", body_style),
                Paragraph(f"<b>Video Timestamp:</b> {ts_str}", body_style),
                Paragraph(f"<b>Action:</b> {action_str}", body_style),
            ]
            ev_table = Table([[rl_img, ev_desc]], colWidths=[280, 260])
            ev_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('BACKGROUND', (0, 0), (-1, -1), c_bg_light),
                ('BOX', (0, 0), (-1, -1), 1, c_border),
                ('TOPPADDING', (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                ('LEFTPADDING', (0, 0), (-1, -1), 5),
                ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ]))
            story.append(ev_table)
            story.append(Spacer(1, 8))

    story.append(Spacer(1, 16))
    
    # Sign-off block with blank signature lines
    sign_data = [
        [
            Paragraph("<b>Inspected By:</b><br/><br/>___________________________<br/>Inspector signature", body_style),
            Paragraph("<b>Date:</b><br/><br/>___________________________<br/>Date", body_style),
            Paragraph("<b>Authority:</b><br/><br/>Rodic InfraAI Challenge 2026", body_style)
        ]
    ]
    sign_table = Table(sign_data, colWidths=[180, 180, 180])
    sign_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.5, c_border),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#F1F5F9")),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(sign_table)

    doc.build(story)
    try:
        from backend.s3_client import is_s3_enabled, upload_file
        if is_s3_enabled():
            upload_file(pdf_path, f"reports/{pdf_filename}", "application/pdf")
    except Exception as exc:
        print(f"[Reports] S3 upload error: {exc}")
    return pdf_path

if __name__ == "__main__":
    path = generate_inspection_pdf("DEMO-001")
    print("Generated PDF at:", path)
