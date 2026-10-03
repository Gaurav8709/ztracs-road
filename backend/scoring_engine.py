"""
Z-TRACS Road Intelligence - Scoring, Risk, and Priority Engine
Sections 22, 23, 24 of Technical Specification
"""
from typing import Dict, Any, List
from backend.models import MaintenancePriority, ScoringConfig

default_config = ScoringConfig()
SCORING_CONFIG = default_config

def calculate_segment_condition(
    length_km: float,
    defects: List[Dict[str, Any]],
    config: ScoringConfig = default_config
) -> Dict[str, Any]:
    """
    Computes Condition Score (0 - 100), where 100 is pristine road surface and 0 is heavily compromised.
    Condition Score = 100 - (Defect Density Impact + Severity Penalty + Type Penalty)
    """
    if length_km <= 0:
        length_km = 1.0

    potholes = [d for d in defects if d.get("defect_type") == "pothole" or d.get("class") == "pothole" or d.get("type") == "pothole"]
    cracks = [d for d in defects if d.get("defect_type") == "crack" or d.get("class") == "crack" or d.get("type") == "crack"]
    markings = [d for d in defects if d.get("defect_type") == "marking" or d.get("class") == "marking" or d.get("type") == "marking"]
    others = [d for d in defects if d not in potholes and d not in cracks and d not in markings]

    critical = [d for d in defects if (d.get("severity") or d.get("sev")) == "critical"]
    high = [d for d in defects if (d.get("severity") or d.get("sev")) == "high"]
    medium = [d for d in defects if (d.get("severity") or d.get("sev")) == "medium"]
    low = [d for d in defects if (d.get("severity") or d.get("sev")) == "low"]

    # Defect Density (defects per km)
    density = len(defects) / length_km

    # Defect type weighted score
    type_score = (
        len(potholes) * config.pothole_weight * config.pothole_base_mult +
        len(cracks) * config.crack_weight * config.crack_base_mult +
        len(markings) * config.marking_weight * config.marking_base_mult +
        len(others) * config.other_base_mult
    )

    # Severity weighted multiplier
    sev_penalty = (
        len(critical) * config.critical_severity_weight * config.critical_base_mult +
        len(high) * config.high_severity_weight * config.high_base_mult +
        len(medium) * config.medium_severity_weight * config.medium_base_mult +
        len(low) * config.low_severity_weight * config.low_base_mult
    )

    total_deduction = (
        type_score * config.type_score_weight +
        sev_penalty * config.sev_penalty_weight +
        density * config.density_penalty_weight
    )
    condition_score = max(5.0, min(100.0, 100.0 - total_deduction))

    # Determine status color
    if condition_score >= 80.0:
        status_color = "GREEN"
    elif condition_score >= 60.0:
        status_color = "YELLOW"
    elif condition_score >= 50.0:
        status_color = "ORANGE"
    else:
        status_color = "RED"

    return {
        "condition_score": round(condition_score, 1),
        "status_color": status_color,
        "defect_density": round(density, 2),
        "counts": {
            "total": len(defects),
            "potholes": len(potholes),
            "cracks": len(cracks),
            "markings": len(markings),
            "critical": len(critical),
            "high": len(high),
            "medium": len(medium),
            "low": len(low)
        }
    }

def calculate_segment_risk(
    condition_score: float,
    traffic_exposure: float, # 0.0 to 1.0 (AADT normalizer)
    road_importance: float,  # 0.0 to 1.0 (National Highway vs Rural)
    has_critical_defects: bool,
    config: ScoringConfig = default_config
) -> Dict[str, Any]:
    """
    Computes Operational Risk Score (0 - 100) per Section 23.
    Note: Physical condition is separated from operational risk!
    A road with moderate physical defect can carry extreme risk if on a heavy freight highway corridor.
    """
    # Inverse condition represents physical deterioration (0 = perfect, 100 = collapsed)
    physical_deterioration = 100.0 - condition_score

    # Multipliers
    traffic_factor = 0.5 + (traffic_exposure * config.traffic_scale * config.traffic_multiplier)
    importance_factor = 0.5 + (road_importance * config.importance_scale * config.importance_multiplier)

    base_risk = physical_deterioration * config.deterioration_factor * (traffic_factor + importance_factor) / 2.0
    
    # Extra danger bonus for unaddressed critical defects (e.g. pothole in fast lane)
    if has_critical_defects:
        base_risk += config.critical_defect_risk_penalty

    risk_score = max(5.0, min(99.0, base_risk))

    # Priority mapping (unified configuration)
    if risk_score >= config.p1_threshold or has_critical_defects:
        priority = MaintenancePriority.P1
        priority_label = "P1 — Immediate inspection/intervention"
    elif risk_score >= config.p2_threshold:
        priority = MaintenancePriority.P2
        priority_label = "P2 — Planned intervention"
    elif risk_score >= config.p3_threshold:
        priority = MaintenancePriority.P3
        priority_label = "P3 — Monitor / scheduled maintenance"
    else:
        priority = MaintenancePriority.P4
        priority_label = "P4 — Routine monitoring"

    return {
        "risk_score": round(risk_score, 1),
        "priority": priority,
        "priority_label": priority_label
    }


def get_scoring_config() -> ScoringConfig:
    return SCORING_CONFIG


def update_scoring_config(new_weights: Dict[str, Any]) -> ScoringConfig:
    global SCORING_CONFIG
    data = SCORING_CONFIG.dict() if hasattr(SCORING_CONFIG, "dict") else SCORING_CONFIG.model_dump()
    for k, v in new_weights.items():
        if k in data and isinstance(v, (int, float)):
            data[k] = float(v)
    SCORING_CONFIG = ScoringConfig(**data)
    return SCORING_CONFIG
