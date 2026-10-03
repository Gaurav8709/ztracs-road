import os
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any
from enum import Enum

class InspectionStatus(str, Enum):
    CREATED = "CREATED"
    UPLOADED = "UPLOADED"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    AI_ANALYSIS = "AI_ANALYSIS"
    GEO_REFERENCING = "GEO_REFERENCING"
    AGGREGATION = "AGGREGATION"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class DefectClass(str, Enum):
    POTHOLE = "pothole"
    CRACK = "crack"
    MARKING_DAMAGE = "marking"
    RUTTING = "rutting"
    RAVELING = "raveling"

class SeverityLevel(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class MaintenancePriority(str, Enum):
    P1 = "P1" # Immediate inspection/intervention
    P2 = "P2" # Planned intervention
    P3 = "P3" # Monitor / scheduled maintenance
    P4 = "P4" # Routine monitoring

# Section 34: Frozen API Contract with CV Team
class CVDetectionPayload(BaseModel):
    detection_id: str
    frame_id: int
    timestamp: float
    defect_class: str = Field(alias="class")
    confidence: float
    bbox: List[float]  # [x1, y1, x2, y2] — exactly 4 numbers
    severity: str      # must be in {low, medium, high, critical}
    latitude: float
    longitude: float
    evidence_uri: Optional[str] = None
    road_segment_id: Optional[str] = None
    model_version: Optional[str] = "RoadDefect-v1.0"

    class Config:
        populate_by_name = True

    @field_validator("latitude")
    @classmethod
    def validate_latitude(cls, v: float) -> float:
        if v < -90.0 or v > 90.0:
            raise ValueError(f"Invalid latitude {v}: must be between -90 and 90")
        return v

    @field_validator("longitude")
    @classmethod
    def validate_longitude(cls, v: float) -> float:
        if v < -180.0 or v > 180.0:
            raise ValueError(f"Invalid longitude {v}: must be between -180 and 180")
        return v

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if v < 0.0 or v > 1.0:
            raise ValueError(f"Invalid confidence {v}: must be between 0.0 and 1.0")
        return v

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, v: List[float]) -> List[float]:
        if len(v) != 4:
            raise ValueError(f"bbox must contain exactly 4 numbers [x1, y1, x2, y2], got {len(v)}")
        return v

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        allowed = {"low", "medium", "high", "critical"}
        if v.lower() not in allowed:
            raise ValueError(f"severity '{v}' is not valid. Must be one of: {sorted(allowed)}")
        return v.lower()

    @field_validator("defect_class")
    @classmethod
    def validate_class(cls, v: str) -> str:
        valid_classes = {"pothole", "crack", "marking", "rutting", "raveling"}
        if v.lower() not in valid_classes:
            raise ValueError(f"Unknown defect class '{v}'. Valid classes are: {', '.join(sorted(valid_classes))}")
        return v.lower()

    @field_validator("evidence_uri")
    @classmethod
    def validate_evidence_uri(cls, v: Optional[str]) -> Optional[str]:
        """D19: evidence_uri must be a relative path only under evidence folder — no http(s)://, file://, or .. traversal."""
        if v is None:
            return v
        if "://" in v:
            raise ValueError(f"evidence_uri must be a relative path, not an absolute URI: {v!r}")
        # Strip legacy prefix if present to normalize into relative path under evidence folder
        clean = v
        for pfx in ("/static/media/evidence/", "static/media/evidence/"):
            if clean.startswith(pfx):
                clean = clean[len(pfx):]
        if ".." in clean or clean.startswith("/") or clean.startswith("\\"):
            raise ValueError(f"evidence_uri must not contain .. or escape evidence folder: {v!r}")
        return clean

class InspectionCreate(BaseModel):
    name: str = "NH-48 Road Survey — September 2026"
    road_id: str = "RD-NH48"
    road_name: str = "NH-48 Corridor (Mumbai–Pune Expressway)"
    source_type: str = "Vehicle Camera"
    model_version: str = "RoadDefect-v1.0"
    processing_mode: str = "Batch"
    inspection_date: Optional[str] = "2026-09-30"
    location: Optional[str] = "NH-48 Km 0.0 - 10.0"
    video_filename: Optional[str] = "demo_road.mp4"
    rtsp_url: Optional[str] = None


class InspectionResponse(BaseModel):
    id: str
    name: str
    road_id: str
    road_name: str
    source_type: str
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    status: InspectionStatus
    model_version: str
    video_url: str
    total_frames: int
    processed_frames: int
    defect_count: int
    progress_percent: int
    current_stage: str
    error_message: Optional[str] = None
    inspection_date: Optional[str] = None
    location: Optional[str] = None
    processing_mode: Optional[str] = "Batch"
    duration_seconds: Optional[float] = 0.0
    fps: Optional[float] = 0.0
    is_mock: Optional[bool] = True

class DetectionItem(BaseModel):
    id: str
    detection_id: str
    inspection_id: str
    frame_id: int
    timestamp: float # in seconds e.g. 204.0 (03:24)
    timestamp_formatted: str
    defect_type: str
    confidence: float
    severity: SeverityLevel
    bbox: List[float]
    latitude: float
    longitude: float
    road_segment_id: str
    evidence_orig_url: str
    evidence_anno_url: str
    model_version: str

class RoadSegment(BaseModel):
    id: str
    road_id: str
    segment_name: str
    geometry: List[List[float]] # [[lat, lng], [lat, lng], ...]
    length_km: float
    road_class: str
    traffic_exposure: float # 0.0 to 1.0
    road_importance: float # 0.0 to 1.0
    condition_score: float # 0 to 100
    risk_score: float # 0 to 100
    priority: MaintenancePriority
    status_color: str # GREEN, YELLOW, ORANGE, RED
    defect_count: int
    pothole_count: int
    crack_count: int
    marking_count: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int

class AnalyticsOverview(BaseModel):
    inspected_distance_km: float
    total_defects: int
    critical_defects: int
    high_risk_segments: int
    average_condition_score: float
    average_risk_score: float
    defect_distribution: Dict[str, int]
    defect_distribution_pct: Dict[str, float]
    severity_distribution: Dict[str, int]
    defects_per_km: List[Dict[str, Any]]
    segment_condition_summary: List[Dict[str, Any]]

class AssetItem(BaseModel):
    id: str
    road_id: str
    segment_id: str
    asset_type: str
    asset_name: str
    latitude: float
    longitude: float
    condition_score: float = 85.0
    status: str = "OPERATIONAL"
    last_inspected: Optional[str] = None
    created_at: str

class AlertItem(BaseModel):
    id: str
    inspection_id: str
    segment_id: str
    defect_id: str
    defect_type: str
    severity: str
    message: str
    timestamp: str
    latitude: float
    longitude: float
    evidence_url: str
    is_read: bool = False

class ScoringConfig(BaseModel):
    # Weights & Multipliers (env-overridable)
    pothole_weight: float = Field(default_factory=lambda: float(os.getenv("SCORING_POTHOLE_WEIGHT", "1.5")))
    crack_weight: float = Field(default_factory=lambda: float(os.getenv("SCORING_CRACK_WEIGHT", "1.0")))
    marking_weight: float = Field(default_factory=lambda: float(os.getenv("SCORING_MARKING_WEIGHT", "0.6")))
    critical_severity_weight: float = Field(default_factory=lambda: float(os.getenv("SCORING_CRITICAL_SEVERITY_WEIGHT", "2.0")))
    high_severity_weight: float = Field(default_factory=lambda: float(os.getenv("SCORING_HIGH_SEVERITY_WEIGHT", "1.4")))
    medium_severity_weight: float = Field(default_factory=lambda: float(os.getenv("SCORING_MEDIUM_SEVERITY_WEIGHT", "0.8")))
    low_severity_weight: float = Field(default_factory=lambda: float(os.getenv("SCORING_LOW_SEVERITY_WEIGHT", "0.4")))
    traffic_multiplier: float = Field(default_factory=lambda: float(os.getenv("SCORING_TRAFFIC_MULTIPLIER", "1.2")))
    importance_multiplier: float = Field(default_factory=lambda: float(os.getenv("SCORING_IMPORTANCE_MULTIPLIER", "1.1")))

    # Base formula constants (previously hardcoded in scoring_engine.py, now env-overridable)
    pothole_base_mult: float = Field(default_factory=lambda: float(os.getenv("SCORING_POTHOLE_BASE_MULT", "3.5")))
    crack_base_mult: float = Field(default_factory=lambda: float(os.getenv("SCORING_CRACK_BASE_MULT", "2.2")))
    marking_base_mult: float = Field(default_factory=lambda: float(os.getenv("SCORING_MARKING_BASE_MULT", "1.5")))
    other_base_mult: float = Field(default_factory=lambda: float(os.getenv("SCORING_OTHER_BASE_MULT", "1.5")))
    critical_base_mult: float = Field(default_factory=lambda: float(os.getenv("SCORING_CRITICAL_BASE_MULT", "8.0")))
    high_base_mult: float = Field(default_factory=lambda: float(os.getenv("SCORING_HIGH_BASE_MULT", "4.5")))
    medium_base_mult: float = Field(default_factory=lambda: float(os.getenv("SCORING_MEDIUM_BASE_MULT", "2.0")))
    low_base_mult: float = Field(default_factory=lambda: float(os.getenv("SCORING_LOW_BASE_MULT", "0.8")))
    type_score_weight: float = Field(default_factory=lambda: float(os.getenv("SCORING_TYPE_SCORE_WEIGHT", "0.25")))
    sev_penalty_weight: float = Field(default_factory=lambda: float(os.getenv("SCORING_SEV_PENALTY_WEIGHT", "0.26")))
    density_penalty_weight: float = Field(default_factory=lambda: float(os.getenv("SCORING_DENSITY_PENALTY_WEIGHT", "1.05")))
    traffic_scale: float = Field(default_factory=lambda: float(os.getenv("SCORING_TRAFFIC_SCALE", "0.7")))
    importance_scale: float = Field(default_factory=lambda: float(os.getenv("SCORING_IMPORTANCE_SCALE", "0.70")))
    deterioration_factor: float = Field(default_factory=lambda: float(os.getenv("SCORING_DETERIORATION_FACTOR", "0.98")))
    critical_defect_risk_penalty: float = Field(default_factory=lambda: float(os.getenv("SCORING_CRITICAL_DEFECT_RISK_PENALTY", "18.0")))

    # Unified Priority & Risk Thresholds
    p1_threshold: float = Field(default_factory=lambda: float(os.getenv("SCORING_P1_THRESHOLD", "75.0")))
    p2_threshold: float = Field(default_factory=lambda: float(os.getenv("SCORING_P2_THRESHOLD", "50.0")))
    p3_threshold: float = Field(default_factory=lambda: float(os.getenv("SCORING_P3_THRESHOLD", "25.0")))
    high_risk_threshold: float = Field(default_factory=lambda: float(os.getenv("SCORING_HIGH_RISK_THRESHOLD", "60.0")))


# ==============================================================================
# CV Team Schema 1.0 Contracts (ai_results.json, processing_status.json, etc.)
# ==============================================================================

class CVBBoxDict(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float

class CVGeometry(BaseModel):
    bbox: Optional[CVBBoxDict] = None

class CVClassification(BaseModel):
    class_name: str
    confidence: float
    severity: str

class CVFrame(BaseModel):
    frame_number: int
    timestamp_seconds: float

class CVLocation(BaseModel):
    latitude: float
    longitude: float
    accuracy_meters: Optional[float] = None
    quality: Optional[str] = None

class CVRoadRef(BaseModel):
    road_id: Optional[str] = None
    segment_id: Optional[str] = None

class CVEvidenceDict(BaseModel):
    original_frame_s3_key: Optional[str] = None
    annotated_frame_s3_key: Optional[str] = None
    crop_s3_key: Optional[str] = None

class CVMeasurementDict(BaseModel):
    estimated_length_m: Optional[float] = None
    estimated_width_m: Optional[float] = None
    estimated_area_m2: Optional[float] = None
    method: Optional[str] = None
    confidence: Optional[float] = None

class CVDetectionItemSchema1(BaseModel):
    detection_id: str
    track_id: Optional[str] = None
    frame: CVFrame
    classification: CVClassification
    geometry: Optional[CVGeometry] = None
    location: CVLocation
    road: Optional[CVRoadRef] = None
    measurement: Optional[CVMeasurementDict] = None
    evidence: Optional[CVEvidenceDict] = None

class CVSegmentMetric(BaseModel):
    segment_id: str
    metrics: Optional[Dict[str, Any]] = None
    condition_features: Optional[Dict[str, Any]] = None

class CVAIResultsPayload(BaseModel):
    schema_version: Optional[str] = "1.0"
    inspection_id: str
    model: Optional[Dict[str, Any]] = None
    video: Optional[Dict[str, Any]] = None
    detections: List[CVDetectionItemSchema1] = []
    segments: Optional[List[CVSegmentMetric]] = []

class CVStatusUpdatePayload(BaseModel):
    inspection_id: str
    status: str
    stage: Optional[str] = "ai_inference"
    progress: Optional[int] = 0
    frames_processed: Optional[int] = 0
    total_frames: Optional[int] = 0
    detections_found: Optional[int] = 0

class CVFailedPayload(BaseModel):
    inspection_id: str
    status: str = "failed"
    stage: Optional[str] = "ai_inference"
    error_code: Optional[str] = "MODEL_LOAD_ERROR"
    error_message: Optional[str] = "Processing failed"
    retryable: Optional[bool] = True

