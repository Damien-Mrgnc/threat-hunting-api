"""
ML-based network threat detection endpoint.

Loads a pre-trained RandomForest model (api/ml/model.pkl) and classifies
incoming network events as normal (0) or attack (1).

Train the model first: python ml/train.py
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.auth import get_current_active_analyst
from core.observability import ML_DETECT_TOTAL

router = APIRouter(prefix="/detect", tags=["Threat Detection (ML)"])

# Model is loaded once on first request (lazy load)
_MODEL_PATH = Path(os.getenv("ML_MODEL_PATH", "ml/model.pkl"))
_model_data: Optional[dict] = None

# Feature order must match exactly the order used during training (ml/train.py)
_FEATURE_ORDER = [
    "sport", "dsport", "dur", "sbytes", "dbytes", "sttl", "dttl",
    "sloss", "dloss", "Sload", "Dload", "Spkts", "Dpkts",
    "swin", "dwin", "stcpb", "dtcpb", "smeansz", "dmeansz",
    "trans_depth", "res_bdy_len", "Sjit", "Djit", "Sintpkt", "Dintpkt",
    "tcprtt", "synack", "ackdat", "is_sm_ips_ports", "ct_state_ttl",
    "ct_flw_http_mthd", "is_ftp_login", "ct_ftp_cmd",
    "ct_srv_src", "ct_srv_dst", "ct_dst_ltm", "ct_src_ltm",
    "ct_src_dport_ltm", "ct_dst_sport_ltm", "ct_dst_src_ltm",
]


def _load_model() -> Optional[dict]:
    global _model_data
    if _model_data is None and _MODEL_PATH.exists():
        try:
            import joblib
            _model_data = joblib.load(_MODEL_PATH)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to load ML model: {exc}")
    return _model_data


def _model_or_503() -> dict:
    data = _load_model()
    if data is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "ML model not available. "
                "Generate it with: python ml/train.py "
                "(requires data/UNSW-NB15.csv)"
            ),
        )
    return data


# ─────────────────────────────────────────────────────────────────────────────
# Request / Response schemas
# ─────────────────────────────────────────────────────────────────────────────

class EventFeatures(BaseModel):
    """
    Numeric features extracted from a network flow record (UNSW-NB15 format).
    All fields default to 0 — only provide the fields you have available.
    """
    sport: float = Field(0, description="Source port number")
    dsport: float = Field(0, description="Destination port number")
    dur: float = Field(0, description="Flow duration (seconds)")
    sbytes: float = Field(0, description="Source → destination bytes")
    dbytes: float = Field(0, description="Destination → source bytes")
    sttl: float = Field(0, description="Source time-to-live value")
    dttl: float = Field(0, description="Destination time-to-live value")
    sloss: float = Field(0, description="Source packets retransmitted or dropped")
    dloss: float = Field(0, description="Destination packets retransmitted or dropped")
    Sload: float = Field(0, description="Source bits per second")
    Dload: float = Field(0, description="Destination bits per second")
    Spkts: float = Field(0, description="Source to destination packet count")
    Dpkts: float = Field(0, description="Destination to source packet count")
    swin: float = Field(0, description="Source TCP window advertisement value")
    dwin: float = Field(0, description="Destination TCP window advertisement value")
    stcpb: float = Field(0, description="Source TCP base sequence number")
    dtcpb: float = Field(0, description="Destination TCP base sequence number")
    smeansz: float = Field(0, description="Mean source packet size (bytes)")
    dmeansz: float = Field(0, description="Mean destination packet size (bytes)")
    trans_depth: float = Field(0, description="HTTP pipelining depth")
    res_bdy_len: float = Field(0, description="HTTP response body size (bytes)")
    Sjit: float = Field(0, description="Source jitter (ms)")
    Djit: float = Field(0, description="Destination jitter (ms)")
    Sintpkt: float = Field(0, description="Source inter-packet arrival time (ms)")
    Dintpkt: float = Field(0, description="Destination inter-packet arrival time (ms)")
    tcprtt: float = Field(0, description="TCP connection setup round-trip time")
    synack: float = Field(0, description="Time between SYN and SYN-ACK packets")
    ackdat: float = Field(0, description="Time between SYN-ACK and ACK packets")
    is_sm_ips_ports: float = Field(0, description="1 if source and destination IPs/ports are equal")
    ct_state_ttl: float = Field(0, description="Connection count by state and TTL range")
    ct_flw_http_mthd: float = Field(0, description="HTTP GET/POST flow count")
    is_ftp_login: float = Field(0, description="1 if FTP session authenticated with user/pass")
    ct_ftp_cmd: float = Field(0, description="FTP command flow count")
    ct_srv_src: float = Field(0, description="Connections with same service + source IP (100-conn window)")
    ct_srv_dst: float = Field(0, description="Connections with same service + dest IP (100-conn window)")
    ct_dst_ltm: float = Field(0, description="Connections to same destination (100-conn window)")
    ct_src_ltm: float = Field(0, description="Connections from same source (100-conn window)")
    ct_src_dport_ltm: float = Field(0, description="Connections from same source + dest port (100-conn window)")
    ct_dst_sport_ltm: float = Field(0, description="Connections to same dest + source port (100-conn window)")
    ct_dst_src_ltm: float = Field(0, description="Connections between same source and dest (100-conn window)")

    model_config = {"json_schema_extra": {
        "examples": [{
            "sport": 1390, "dsport": 53, "dur": 0.001055,
            "sbytes": 132, "dbytes": 164, "sttl": 31, "dttl": 29,
            "sloss": 0, "dloss": 0, "Sload": 500473.9, "Dload": 621800.9,
            "Spkts": 2, "Dpkts": 2, "swin": 0, "dwin": 0,
            "stcpb": 0, "dtcpb": 0, "smeansz": 66, "dmeansz": 82,
            "trans_depth": 0, "res_bdy_len": 0, "Sjit": 0.0, "Djit": 0.0,
            "Sintpkt": 0.017, "Dintpkt": 0.013, "tcprtt": 0.0,
            "synack": 0.0, "ackdat": 0.0, "is_sm_ips_ports": 0,
            "ct_state_ttl": 0, "ct_flw_http_mthd": 0, "is_ftp_login": 0,
            "ct_ftp_cmd": 0, "ct_srv_src": 3, "ct_srv_dst": 7,
            "ct_dst_ltm": 1, "ct_src_ltm": 3, "ct_src_dport_ltm": 1,
            "ct_dst_sport_ltm": 1, "ct_dst_src_ltm": 1,
        }]
    }}


class DetectionResult(BaseModel):
    label: int = Field(description="Binary prediction: 0 = Normal, 1 = Attack")
    is_attack: bool = Field(description="True if the event is classified as an attack")
    confidence: float = Field(description="Model confidence in the predicted class [0.0 – 1.0]")
    model_roc_auc: float = Field(description="Model ROC-AUC score on held-out test set (training quality indicator)")


class ModelInfo(BaseModel):
    feature_count: int
    features: list[str]
    trained_on_samples: Optional[int]
    n_estimators: Optional[int]
    max_depth: Optional[int]
    roc_auc: Optional[float]
    dataset: str
    model_path: str


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=DetectionResult,
    summary="Classify a network event as normal or attack",
    description=(
        "Submits a network flow record to the RandomForest classifier trained on UNSW-NB15. "
        "Returns a binary prediction (0=normal, 1=attack) with confidence score. "
        "All feature fields are optional and default to 0."
    ),
)
def classify_event(
    features: EventFeatures,
    _: dict = Depends(get_current_active_analyst),
) -> DetectionResult:
    import numpy as np

    model_data = _model_or_503()
    pipeline = model_data["pipeline"]

    feature_vector = [[getattr(features, col) for col in _FEATURE_ORDER]]
    X = np.array(feature_vector, dtype=float)

    label = int(pipeline.predict(X)[0])
    confidence = float(pipeline.predict_proba(X)[0][label])

    ML_DETECT_TOTAL.labels(label=str(label)).inc()

    return DetectionResult(
        label=label,
        is_attack=bool(label),
        confidence=round(confidence, 4),
        model_roc_auc=round(model_data.get("roc_auc", 0.0), 4),
    )


@router.get(
    "/model/info",
    response_model=ModelInfo,
    summary="Get ML model metadata",
)
def model_info(_: dict = Depends(get_current_active_analyst)) -> ModelInfo:
    model_data = _model_or_503()
    return ModelInfo(
        feature_count=len(model_data["feature_columns"]),
        features=model_data["feature_columns"],
        trained_on_samples=model_data.get("trained_on"),
        n_estimators=model_data.get("n_estimators"),
        max_depth=model_data.get("max_depth"),
        roc_auc=model_data.get("roc_auc"),
        dataset="UNSW-NB15 (700K network events, 9 attack categories)",
        model_path=str(_MODEL_PATH),
    )
