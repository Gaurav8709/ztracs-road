"""
Z-TRACS Road Intelligence - Golden Demo Seed Dataset
Implements Section 38 ("Demo Mode") & Section 17 ("Map Interaction Example RD-014")
"""
import os
import shutil
import json
from backend.database import get_connection

def seed_demo_data(force: bool = False):
    # Ensure static/media directories exist and demo assets are copied
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    demo_assets_dir = os.path.join(project_root, "demo_assets")
    video_target_dir = os.path.join(project_root, "static", "media", "video")
    evidence_target_dir = os.path.join(project_root, "static", "media", "evidence")
    demo_001_evidence_dir = os.path.join(evidence_target_dir, "DEMO-001")

    os.makedirs(video_target_dir, exist_ok=True)
    os.makedirs(demo_001_evidence_dir, exist_ok=True)

    if os.path.exists(demo_assets_dir):
        src_video = os.path.join(demo_assets_dir, "video", "demo_road.mp4")
        dst_video = os.path.join(video_target_dir, "demo_road.mp4")
        if os.path.exists(src_video) and not os.path.exists(dst_video):
            shutil.copy2(src_video, dst_video)

        src_ev_demo = os.path.join(demo_assets_dir, "evidence", "DEMO-001")
        if os.path.exists(src_ev_demo):
            for f in os.listdir(src_ev_demo):
                src_f = os.path.join(src_ev_demo, f)
                dst_f = os.path.join(demo_001_evidence_dir, f)
                if os.path.isfile(src_f) and not os.path.exists(dst_f):
                    shutil.copy2(src_f, dst_f)

        src_ev_root = os.path.join(demo_assets_dir, "evidence")
        if os.path.exists(src_ev_root):
            for f in os.listdir(src_ev_root):
                src_f = os.path.join(src_ev_root, f)
                dst_f = os.path.join(evidence_target_dir, f)
                if os.path.isfile(src_f) and not os.path.exists(dst_f):
                    shutil.copy2(src_f, dst_f)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as cnt FROM inspections WHERE id = 'DEMO-001'")
    row = cursor.fetchone()
    if row and row["cnt"] > 0 and not force:
        conn.close()
        return

    # Clear existing if force
    if force:
        cursor.execute("DELETE FROM segment_metrics WHERE inspection_id = 'DEMO-001'")
        cursor.execute("DELETE FROM alerts WHERE inspection_id = 'DEMO-001'")
        cursor.execute("DELETE FROM detections WHERE inspection_id = 'DEMO-001'")
        cursor.execute("DELETE FROM inspections WHERE id = 'DEMO-001'")
        cursor.execute("DELETE FROM segment_metrics")
        cursor.execute("DELETE FROM alerts")
        cursor.execute("DELETE FROM detections")
        cursor.execute("DELETE FROM inspections WHERE id = 'DEMO-001'")
        conn.commit()

    # 1. Seed Demo Road Segments (10 segments along NH-48 Corridor, ~10 KM total)
    # Coordinates along Mumbai-Pune expressway / NH-48 stretch
    base_lat = 18.9950
    base_lng = 73.1150
    segments_data = [
        {"id": "RD-001", "name": "NH-48 Km 0.0 - 1.0 (Panvel Tollway Entry)", "traffic": 0.90, "imp": 0.95, "len": 1.0, "road_class": "Expressway"},
        {"id": "RD-002", "name": "NH-48 Km 1.0 - 2.0 (Kalamboli Flyover)", "traffic": 0.88, "imp": 0.90, "len": 1.0, "road_class": "Expressway"},
        {"id": "RD-003", "name": "NH-48 Km 2.0 - 3.0 (Khanda Colony Overpass)", "traffic": 0.82, "imp": 0.85, "len": 1.0, "road_class": "Expressway"},
        {"id": "RD-004", "name": "NH-48 Km 3.0 - 4.0 (Palaspe Junction Connector)", "traffic": 0.85, "imp": 0.90, "len": 1.0, "road_class": "Expressway"},
        {"id": "RD-005", "name": "NH-48 Km 4.0 - 5.0 (Somatne Viaduct Approach)", "traffic": 0.78, "imp": 0.85, "len": 1.0, "road_class": "Expressway"},
        {"id": "RD-006", "name": "NH-48 Km 5.0 - 6.0 (Akurdi Expressway Cut)", "traffic": 0.80, "imp": 0.85, "len": 1.0, "road_class": "Expressway"},
        {"id": "RD-007", "name": "NH-48 Km 6.0 - 7.0 (Talegaon Toll Plaza Zone)", "traffic": 0.92, "imp": 0.90, "len": 1.0, "road_class": "Expressway"},
        {"id": "RD-008", "name": "NH-48 Km 7.0 - 8.0 (Dehu Road Bypass Section)", "traffic": 0.86, "imp": 0.90, "len": 1.0, "road_class": "Expressway"},
        {"id": "RD-009", "name": "NH-48 Km 8.0 - 9.0 (Ravet Flyover Descent)", "traffic": 0.80, "imp": 0.85, "len": 1.0, "road_class": "Expressway"},
        {"id": "RD-014", "name": "NH-48 Km 9.0 - 10.0 (Wakad Fast Corridor RD-014)", "traffic": 0.95, "imp": 0.98, "len": 1.0, "road_class": "Expressway"},
    ]

    # Pre-defined detections per segment to match Section 17 & 21
    # Section 17 specifically asks for RD-014: Total Defects: 17 (Potholes: 8, Cracks: 6, Marking: 3; Crit: 2, High: 5, Med: 7, Low: 3)
    raw_detections = []
    
    # Generate coordinates for polyline along highway corridor
    for i, seg in enumerate(segments_data):
        seg_id = seg["id"]
        # Polyline points for segment
        p1 = [round(base_lat + i * 0.0075, 5), round(base_lng + i * 0.0065, 5)]
        p2 = [round(base_lat + (i + 0.5) * 0.0075 + 0.0005, 5), round(base_lng + (i + 0.5) * 0.0065 - 0.0003, 5)]
        p3 = [round(base_lat + (i + 1) * 0.0075, 5), round(base_lng + (i + 1) * 0.0065, 5)]
        geom = [p1, p2, p3]

        geojson_geom = json.dumps({"type": "LineString", "coordinates": [[pt[1], pt[0]] for pt in geom]})
        cursor.execute("""
        INSERT INTO road_segments (
            id, road_id, segment_name, geometry_json, geom, length_km, road_class,
            traffic_exposure, road_importance, condition_score, risk_score, priority, status_color
        ) VALUES (%s, %s, %s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            road_id = EXCLUDED.road_id,
            segment_name = EXCLUDED.segment_name,
            geometry_json = EXCLUDED.geometry_json,
            geom = EXCLUDED.geom,
            length_km = EXCLUDED.length_km,
            road_class = EXCLUDED.road_class,
            traffic_exposure = EXCLUDED.traffic_exposure,
            road_importance = EXCLUDED.road_importance,
            condition_score = EXCLUDED.condition_score,
            risk_score = EXCLUDED.risk_score,
            priority = EXCLUDED.priority,
            status_color = EXCLUDED.status_color
        """, (
            seg_id, "RD-NH48", seg["name"], json.dumps(geom), geojson_geom,
            seg["len"], seg["road_class"], seg["traffic"], seg["imp"],
            85.0, 20.0, "P3", "GREEN"
        ))

    # Flagship detections
    # RD-014 (Section 17 flagship segment)
    rd014_defects = [
        {"id": "DEF-POT-00124", "type": "pothole", "sev": "critical", "conf": 0.942, "ts": 204.0, "lat": 19.0682, "lng": 73.1785, "frame": 6120, "orig": "defect_00124_orig.jpg", "anno": "defect_00124_anno.jpg", "bbox": [0.32, 0.45, 0.68, 0.76]},
        {"id": "DEF-POT-00125", "type": "pothole", "sev": "critical", "conf": 0.925, "ts": 210.5, "lat": 19.0691, "lng": 73.1792, "frame": 6315, "orig": "defect_00124_orig.jpg", "anno": "defect_00124_anno.jpg", "bbox": [0.28, 0.42, 0.60, 0.72]},
        {"id": "DEF-POT-00126", "type": "pothole", "sev": "high", "conf": 0.910, "ts": 214.0, "lat": 19.0698, "lng": 73.1798, "frame": 6420, "orig": "defect_00124_orig.jpg", "anno": "defect_00124_anno.jpg", "bbox": [0.35, 0.48, 0.65, 0.75]},
        {"id": "DEF-POT-00127", "type": "pothole", "sev": "high", "conf": 0.895, "ts": 218.2, "lat": 19.0704, "lng": 73.1802, "frame": 6546, "orig": "defect_00124_orig.jpg", "anno": "defect_00124_anno.jpg", "bbox": [0.30, 0.44, 0.62, 0.73]},
        {"id": "DEF-POT-00128", "type": "pothole", "sev": "high", "conf": 0.880, "ts": 222.0, "lat": 19.0710, "lng": 73.1808, "frame": 6660, "orig": "defect_00124_orig.jpg", "anno": "defect_00124_anno.jpg", "bbox": [0.31, 0.46, 0.63, 0.74]},
        {"id": "DEF-POT-00129", "type": "pothole", "sev": "medium", "conf": 0.870, "ts": 225.0, "lat": 19.0714, "lng": 73.1812, "frame": 6750, "orig": "defect_00124_orig.jpg", "anno": "defect_00124_anno.jpg", "bbox": [0.33, 0.47, 0.61, 0.72]},
        {"id": "DEF-POT-00130", "type": "pothole", "sev": "medium", "conf": 0.865, "ts": 228.0, "lat": 19.0719, "lng": 73.1817, "frame": 6840, "orig": "defect_00124_orig.jpg", "anno": "defect_00124_anno.jpg", "bbox": [0.34, 0.49, 0.60, 0.71]},
        {"id": "DEF-POT-00131", "type": "pothole", "sev": "low", "conf": 0.830, "ts": 232.0, "lat": 19.0725, "lng": 73.1822, "frame": 6960, "orig": "defect_00124_orig.jpg", "anno": "defect_00124_anno.jpg", "bbox": [0.36, 0.50, 0.58, 0.70]},
        {"id": "DEF-CRK-00132", "type": "crack", "sev": "high", "conf": 0.930, "ts": 236.0, "lat": 19.0730, "lng": 73.1828, "frame": 7080, "orig": "defect_00089_orig.jpg", "anno": "defect_00089_anno.jpg", "bbox": [0.24, 0.35, 0.72, 0.82]},
        {"id": "DEF-CRK-00133", "type": "crack", "sev": "high", "conf": 0.915, "ts": 239.5, "lat": 19.0735, "lng": 73.1832, "frame": 7185, "orig": "defect_00089_orig.jpg", "anno": "defect_00089_anno.jpg", "bbox": [0.22, 0.36, 0.70, 0.80]},
        {"id": "DEF-CRK-00134", "type": "crack", "sev": "medium", "conf": 0.890, "ts": 242.0, "lat": 19.0740, "lng": 73.1837, "frame": 7260, "orig": "defect_00089_orig.jpg", "anno": "defect_00089_anno.jpg", "bbox": [0.25, 0.37, 0.68, 0.78]},
        {"id": "DEF-CRK-00135", "type": "crack", "sev": "medium", "conf": 0.875, "ts": 245.0, "lat": 19.0745, "lng": 73.1841, "frame": 7350, "orig": "defect_00089_orig.jpg", "anno": "defect_00089_anno.jpg", "bbox": [0.26, 0.38, 0.65, 0.76]},
        {"id": "DEF-CRK-00136", "type": "crack", "sev": "medium", "conf": 0.860, "ts": 248.0, "lat": 19.0750, "lng": 73.1846, "frame": 7440, "orig": "defect_00089_orig.jpg", "anno": "defect_00089_anno.jpg", "bbox": [0.27, 0.39, 0.63, 0.75]},
        {"id": "DEF-CRK-00137", "type": "crack", "sev": "low", "conf": 0.820, "ts": 251.0, "lat": 19.0755, "lng": 73.1850, "frame": 7530, "orig": "defect_00089_orig.jpg", "anno": "defect_00089_anno.jpg", "bbox": [0.28, 0.40, 0.60, 0.74]},
        {"id": "DEF-MRK-00138", "type": "marking", "sev": "medium", "conf": 0.880, "ts": 255.0, "lat": 19.0760, "lng": 73.1855, "frame": 7650, "orig": "defect_00042_orig.jpg", "anno": "defect_00042_anno.jpg", "bbox": [0.26, 0.38, 0.52, 0.84]},
        {"id": "DEF-MRK-00139", "type": "marking", "sev": "medium", "conf": 0.865, "ts": 258.0, "lat": 19.0765, "lng": 73.1860, "frame": 7740, "orig": "defect_00042_orig.jpg", "anno": "defect_00042_anno.jpg", "bbox": [0.25, 0.37, 0.51, 0.82]},
        {"id": "DEF-MRK-00140", "type": "marking", "sev": "low", "conf": 0.810, "ts": 262.0, "lat": 19.0770, "lng": 73.1865, "frame": 7860, "orig": "defect_00042_orig.jpg", "anno": "defect_00042_anno.jpg", "bbox": [0.27, 0.39, 0.50, 0.80]}
    ]

    for d in rd014_defects:
        d["segment_id"] = "RD-014"
        raw_detections.append(d)

    # RD-008 defects (Severe alligator cracks - High Risk ORANGE)
    rd008_defects = [
        {"id": "DEF-CRK-00089", "segment_id": "RD-008", "type": "crack", "sev": "high", "conf": 0.918, "ts": 88.0, "lat": 19.0482, "lng": 73.1610, "frame": 2640, "orig": "defect_00089_orig.jpg", "anno": "defect_00089_anno.jpg", "bbox": [0.24, 0.35, 0.72, 0.82]},
        {"id": "DEF-CRK-00090", "segment_id": "RD-008", "type": "crack", "sev": "high", "conf": 0.892, "ts": 94.0, "lat": 19.0495, "lng": 73.1622, "frame": 2820, "orig": "defect_00089_orig.jpg", "anno": "defect_00089_anno.jpg", "bbox": [0.26, 0.37, 0.68, 0.80]},
        {"id": "DEF-POT-00091", "segment_id": "RD-008", "type": "pothole", "sev": "medium", "conf": 0.854, "ts": 99.5, "lat": 19.0505, "lng": 73.1630, "frame": 2985, "orig": "defect_00124_orig.jpg", "anno": "defect_00124_anno.jpg", "bbox": [0.32, 0.45, 0.68, 0.76]}
    ]
    raw_detections.extend(rd008_defects)

    # RD-003 defects (Marking wear - Monitor YELLOW)
    rd003_defects = [
        {"id": "DEF-MRK-00042", "segment_id": "RD-003", "type": "marking", "sev": "medium", "conf": 0.885, "ts": 42.0, "lat": 19.0110, "lng": 73.1285, "frame": 1260, "orig": "defect_00042_orig.jpg", "anno": "defect_00042_anno.jpg", "bbox": [0.26, 0.38, 0.52, 0.84]},
        {"id": "DEF-MRK-00043", "segment_id": "RD-003", "type": "marking", "sev": "low", "conf": 0.820, "ts": 48.0, "lat": 19.0125, "lng": 73.1300, "frame": 1440, "orig": "defect_00042_orig.jpg", "anno": "defect_00042_anno.jpg", "bbox": [0.28, 0.40, 0.50, 0.82]}
    ]
    raw_detections.extend(rd003_defects)

    # RD-004 defects (Palaspe Junction Connector - ORANGE)
    rd004_defects = [
        {"id": "DEF-POT-00051", "segment_id": "RD-004", "type": "pothole", "sev": "high", "conf": 0.902, "ts": 55.0, "lat": 19.0185, "lng": 73.1352, "frame": 1650, "orig": "defect_00124_orig.jpg", "anno": "defect_00124_anno.jpg", "bbox": [0.32, 0.45, 0.68, 0.76]},
        {"id": "DEF-CRK-00052", "segment_id": "RD-004", "type": "crack", "sev": "medium", "conf": 0.871, "ts": 61.0, "lat": 19.0200, "lng": 73.1368, "frame": 1830, "orig": "defect_00089_orig.jpg", "anno": "defect_00089_anno.jpg", "bbox": [0.24, 0.35, 0.72, 0.82]}
    ]
    raw_detections.extend(rd004_defects)

    # 4. Insert Demo Inspection Record (Section 38 & 20)
    cursor.execute("""
    INSERT INTO inspections (
        id, name, road_id, road_name, source_type, created_at, started_at, completed_at,
        status, model_version, video_url, total_frames, processed_frames, defect_count,
        progress_percent, current_stage, error_message, is_mock
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (id) DO UPDATE SET
        name = EXCLUDED.name,
        road_id = EXCLUDED.road_id,
        road_name = EXCLUDED.road_name,
        source_type = EXCLUDED.source_type,
        created_at = EXCLUDED.created_at,
        started_at = EXCLUDED.started_at,
        completed_at = EXCLUDED.completed_at,
        status = EXCLUDED.status,
        model_version = EXCLUDED.model_version,
        video_url = EXCLUDED.video_url,
        total_frames = EXCLUDED.total_frames,
        processed_frames = EXCLUDED.processed_frames,
        defect_count = EXCLUDED.defect_count,
        progress_percent = EXCLUDED.progress_percent,
        current_stage = EXCLUDED.current_stage,
        error_message = EXCLUDED.error_message,
        is_mock = EXCLUDED.is_mock
    """, (
        "DEMO-001",
        "NH-48 Golden Corridor Survey — Demo Road (10 KM)",
        "RD-NH48",
        "NH-48 Corridor (Mumbai–Pune Expressway section)",
        "Vehicle Camera",
        "2026-09-29 14:00:00",
        "2026-09-29 14:02:10",
        "2026-09-29 14:08:45",
        "COMPLETED",
        "RoadDefect-v1.0",
        "demo_road.mp4",
        13200,
        13200,
        len(raw_detections),
        100,
        "Completed & Geo-Referenced",
        None,
        1
    ))

    # 2. Insert Detections
    for det in raw_detections:
        cursor.execute("""
        INSERT INTO detections (
            id, detection_id, inspection_id, frame_id, timestamp, defect_type,
            confidence, severity, bbox_json, latitude, longitude, geom,
            road_segment_id, evidence_orig_url, evidence_anno_url, model_version, is_mock, gps_source
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            detection_id = EXCLUDED.detection_id,
            inspection_id = EXCLUDED.inspection_id,
            frame_id = EXCLUDED.frame_id,
            timestamp = EXCLUDED.timestamp,
            defect_type = EXCLUDED.defect_type,
            confidence = EXCLUDED.confidence,
            severity = EXCLUDED.severity,
            bbox_json = EXCLUDED.bbox_json,
            latitude = EXCLUDED.latitude,
            longitude = EXCLUDED.longitude,
            geom = EXCLUDED.geom,
            road_segment_id = EXCLUDED.road_segment_id,
            evidence_orig_url = EXCLUDED.evidence_orig_url,
            evidence_anno_url = EXCLUDED.evidence_anno_url,
            model_version = EXCLUDED.model_version,
            is_mock = EXCLUDED.is_mock,
            gps_source = EXCLUDED.gps_source
        """, (
            det["id"], det["id"], "DEMO-001", det["frame"], det["ts"], det["type"],
            det["conf"], det["sev"], json.dumps(det["bbox"]), det["lat"], det["lng"],
            det["lng"], det["lat"],
            det["segment_id"], det["orig"], det["anno"], "RoadDefect-v1.0", 1, "EXIF_OR_SYNTHETIC"
        ))

    # 3. Compute Segment Metrics & Update Segments using Scoring Engine
    from backend.scoring_engine import calculate_segment_condition, calculate_segment_risk
    for seg in segments_data:
        seg_id = seg["id"]
        seg_defects = [d for d in raw_detections if d["segment_id"] == seg_id]
        
        # In Section 17 & 21, RD-014 computes to 48/100 condition and 83/100 risk directly from engine
        # PoC weights, calibrated so the demo segment matches the spec example, not an engineering standard.
        if seg_id == "RD-014":
            has_crit = any((d.get("severity") or d.get("sev")) == "critical" for d in seg_defects)
            cond_res = calculate_segment_condition(seg.get("length_km", 1.0), seg_defects)
            risk_res = calculate_segment_risk(cond_res["condition_score"], 0.95, 0.98, has_crit)
            cond_score = cond_res["condition_score"]
            risk_score = risk_res["risk_score"]
            status_color = cond_res["status_color"]
            priority = risk_res["priority"].value if hasattr(risk_res["priority"], "value") else str(risk_res["priority"])
        elif seg_id in ["RD-004", "RD-008"]:
            cond_score = 54.0 if seg_id == "RD-004" else 58.0
            risk_score = 68.0 if seg_id == "RD-004" else 72.0
            status_color = "ORANGE"
            priority = "P2"
        elif seg_id in ["RD-003", "RD-007"]:
            cond_score = 71.0
            risk_score = 42.0
            status_color = "YELLOW"
            priority = "P3"
        else:
            cond_score = 92.0
            risk_score = 15.0
            status_color = "GREEN"
            priority = "P4"

        cursor.execute("""
        UPDATE road_segments SET
            condition_score = %s, risk_score = %s, priority = %s, status_color = %s
        WHERE id = %s
        """, (cond_score, risk_score, priority, status_color, seg_id))

        pothole_cnt = len([d for d in seg_defects if d["type"] == "pothole"])
        crack_cnt = len([d for d in seg_defects if d["type"] == "crack"])
        marking_cnt = len([d for d in seg_defects if d["type"] == "marking"])
        crit_cnt = len([d for d in seg_defects if d["sev"] == "critical"])
        high_cnt = len([d for d in seg_defects if d["sev"] == "high"])
        med_cnt = len([d for d in seg_defects if d["sev"] == "medium"])
        low_cnt = len([d for d in seg_defects if d["sev"] == "low"])

        cursor.execute("""
        INSERT INTO segment_metrics (
            segment_id, inspection_id, defect_count, pothole_count, crack_count, marking_count,
            critical_count, high_count, medium_count, low_count, defect_density, condition_score, risk_score
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (inspection_id, segment_id) DO UPDATE SET
            defect_count = EXCLUDED.defect_count,
            pothole_count = EXCLUDED.pothole_count,
            crack_count = EXCLUDED.crack_count,
            marking_count = EXCLUDED.marking_count,
            critical_count = EXCLUDED.critical_count,
            high_count = EXCLUDED.high_count,
            medium_count = EXCLUDED.medium_count,
            low_count = EXCLUDED.low_count,
            defect_density = EXCLUDED.defect_density,
            condition_score = EXCLUDED.condition_score,
            risk_score = EXCLUDED.risk_score
        """, (
            seg_id, "DEMO-001", len(seg_defects), pothole_cnt, crack_cnt, marking_cnt,
            crit_cnt, high_cnt, med_cnt, low_cnt, len(seg_defects) / seg["len"],
            cond_score, risk_score
        ))



    # 5. Insert Critical Alert per Section 25
    cursor.execute("""
    INSERT INTO alerts (
        id, inspection_id, segment_id, defect_id, defect_type, severity,
        message, timestamp, latitude, longitude, evidence_url, is_read
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (id) DO UPDATE SET
        inspection_id = EXCLUDED.inspection_id,
        segment_id = EXCLUDED.segment_id,
        defect_id = EXCLUDED.defect_id,
        defect_type = EXCLUDED.defect_type,
        severity = EXCLUDED.severity,
        message = EXCLUDED.message,
        timestamp = EXCLUDED.timestamp,
        latitude = EXCLUDED.latitude,
        longitude = EXCLUDED.longitude,
        evidence_url = EXCLUDED.evidence_url,
        is_read = EXCLUDED.is_read
    """, (
        "ALT-001",
        "DEMO-001",
        "RD-014",
        "DEF-POT-00124",
        "Pothole",
        "Critical",
        "CRITICAL DEFECT DETECTED on RD-014: Pothole with depth > 60mm in center travel lane. Immediate P1 intervention assessment required.",
        "2026-09-29 14:05:32",
        19.0682,
        73.1785,
        "defect_00124_anno.jpg",
        0
    ))

    # Seed Highway Infrastructure Assets
    cursor.execute("SELECT COUNT(*) as count FROM assets")
    asset_count = cursor.fetchone()["count"]
    if asset_count == 0 or force:
        demo_assets = [
            ("AST-BRG-01", "NH-48", "RD-001", "bridge", "Panvel Tollway Overpass Flyover", 19.0601, 73.1650, 88.0, "OPERATIONAL", "2026-09-29"),
            ("AST-SGN-01", "NH-48", "RD-002", "signboard", "Electronic Variable Message Sign (VMS-02)", 19.0620, 73.1685, 92.0, "OPERATIONAL", "2026-09-29"),
            ("AST-GRD-01", "NH-48", "RD-004", "guardrail", "Median High-Tension W-Beam Guardrail", 19.0650, 73.1720, 78.0, "OPERATIONAL", "2026-09-29"),
            ("AST-CUL-01", "NH-48", "RD-014", "culvert", "Cross-Drainage Reinforced Concrete Culvert Box", 19.0682, 73.1785, 62.0, "MAINTENANCE_REQUIRED", "2026-09-29"),
            ("AST-LGT-01", "NH-48", "RD-006", "lighting", "High-Mast Solar LED Illumination Tower", 19.0710, 73.1850, 95.0, "OPERATIONAL", "2026-09-29"),
        ]
        for aid, rid, sid, atype, aname, lat, lon, cscore, astatus, l_insp in demo_assets:
            cursor.execute("""
                INSERT INTO assets (id, road_id, segment_id, asset_type, asset_name, latitude, longitude, condition_score, status, last_inspected, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '2026-09-29 14:00:00')
                ON CONFLICT (id) DO UPDATE SET
                    road_id = EXCLUDED.road_id,
                    segment_id = EXCLUDED.segment_id,
                    asset_type = EXCLUDED.asset_type,
                    asset_name = EXCLUDED.asset_name,
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude,
                    condition_score = EXCLUDED.condition_score,
                    status = EXCLUDED.status,
                    last_inspected = EXCLUDED.last_inspected
            """, (aid, rid, sid, atype, aname, lat, lon, cscore, astatus, l_insp))

    conn.commit()
    conn.close()
    print("Seeded Demo Inspection DEMO-001 successfully!")

if __name__ == "__main__":
    seed_demo_data(force=True)
