#!/usr/bin/env python3
"""
Train a RandomForestClassifier on UNSW-NB15 to detect network intrusions.

Usage:
    python ml/train.py
    python ml/train.py --sample 50000
    python ml/train.py --data data/UNSW-NB15.csv --output api/ml/model.pkl

The trained model is saved to api/ml/model.pkl by default so it is included
in the Docker build context (./api) and deployed to Cloud Run.

Dataset: https://research.unsw.edu.au/projects/unsw-nb15-dataset
  → Download UNSW-NB15_1.csv through UNSW-NB15_4.csv and concatenate,
    or use the combined CSV (UNSW-NB15.csv) placed in data/.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# UNSW-NB15 column definitions (no header row in the raw CSV)
# ---------------------------------------------------------------------------
ALL_COLUMNS = [
    "srcip", "sport", "dstip", "dsport", "proto", "state", "dur",
    "sbytes", "dbytes", "sttl", "dttl", "sloss", "dloss", "service",
    "Sload", "Dload", "Spkts", "Dpkts", "swin", "dwin", "stcpb",
    "dtcpb", "smeansz", "dmeansz", "trans_depth", "res_bdy_len",
    "Sjit", "Djit", "Stime", "Ltime", "Sintpkt", "Dintpkt",
    "tcprtt", "synack", "ackdat", "is_sm_ips_ports", "ct_state_ttl",
    "ct_flw_http_mthd", "is_ftp_login", "ct_ftp_cmd",
    "ct_srv_src", "ct_srv_dst", "ct_dst_ltm", "ct_src_ltm",
    "ct_src_dport_ltm", "ct_dst_sport_ltm", "ct_dst_src_ltm",
    "attack_cat", "label",
]

# Numeric features used for training (drops IPs, timestamps, nominal strings)
FEATURE_COLUMNS = [
    "sport", "dsport", "dur", "sbytes", "dbytes", "sttl", "dttl",
    "sloss", "dloss", "Sload", "Dload", "Spkts", "Dpkts",
    "swin", "dwin", "stcpb", "dtcpb", "smeansz", "dmeansz",
    "trans_depth", "res_bdy_len", "Sjit", "Djit", "Sintpkt", "Dintpkt",
    "tcprtt", "synack", "ackdat", "is_sm_ips_ports", "ct_state_ttl",
    "ct_flw_http_mthd", "is_ftp_login", "ct_ftp_cmd",
    "ct_srv_src", "ct_srv_dst", "ct_dst_ltm", "ct_src_ltm",
    "ct_src_dport_ltm", "ct_dst_sport_ltm", "ct_dst_src_ltm",
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train RandomForest threat-detection model on UNSW-NB15",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--data",
        default="data/UNSW-NB15.csv",
        help="Path to UNSW-NB15 CSV file (no header row)",
    )
    parser.add_argument(
        "--output",
        default="api/ml/model.pkl",
        help="Output path for the serialised model (joblib format)",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=100_000,
        help="Number of rows to sample (0 = use full dataset)",
    )
    parser.add_argument(
        "--n-estimators",
        type=int,
        default=100,
        help="Number of trees in the RandomForest",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=12,
        help="Maximum depth of each tree",
    )
    args = parser.parse_args()

    # ── Lazy imports (not available at module level during Docker build cache) ──
    try:
        import joblib
        import numpy as np
        import pandas as pd
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.metrics import classification_report, roc_auc_score
        from sklearn.model_selection import train_test_split
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:
        print(f"Missing dependency: {exc}")
        print("Install with: pip install scikit-learn joblib pandas numpy")
        sys.exit(1)

    data_path = Path(args.data)
    if not data_path.exists():
        print(f"ERROR: Dataset not found at '{data_path}'", file=sys.stderr)
        print(
            "Download from: https://research.unsw.edu.au/projects/unsw-nb15-dataset",
            file=sys.stderr,
        )
        sys.exit(1)

    # ── Load dataset ──────────────────────────────────────────────────────────
    print(f"[1/4] Loading dataset from '{data_path}' ...")
    t0 = time.perf_counter()
    df = pd.read_csv(
        data_path,
        header=None,
        names=ALL_COLUMNS,
        low_memory=False,
    )
    print(f"      Loaded {len(df):,} rows in {time.perf_counter() - t0:.1f}s")

    if args.sample and args.sample < len(df):
        print(f"      Sampling {args.sample:,} rows (stratified by label) ...")
        labels = pd.to_numeric(df["label"], errors="coerce").fillna(0).astype(int)
        _, df = train_test_split(
            df, test_size=args.sample, random_state=42, stratify=labels
        )

    attack_ratio = pd.to_numeric(df["label"], errors="coerce").fillna(0).mean()
    print(f"      Attack ratio: {attack_ratio:.1%} | Shape: {df.shape}")

    # ── Feature engineering ───────────────────────────────────────────────────
    print("[2/4] Preparing features ...")
    X = (
        df[FEATURE_COLUMNS]
        .apply(pd.to_numeric, errors="coerce")
        .fillna(0)
        .values
    )
    y = pd.to_numeric(df["label"], errors="coerce").fillna(0).astype(int).values

    X_train, X_test, y_train, y_test = train_test_split(
        X, y,
        test_size=0.20,
        random_state=42,
        stratify=y,
    )
    print(f"      Train: {len(X_train):,} | Test: {len(X_test):,}")

    # ── Train ─────────────────────────────────────────────────────────────────
    print(
        f"[3/4] Training RandomForest "
        f"(n_estimators={args.n_estimators}, max_depth={args.max_depth}) ..."
    )
    t1 = time.perf_counter()
    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", RandomForestClassifier(
            n_estimators=args.n_estimators,
            max_depth=args.max_depth,
            n_jobs=-1,
            random_state=42,
            class_weight="balanced",  # handles class imbalance automatically
        )),
    ])
    pipeline.fit(X_train, y_train)
    print(f"      Training completed in {time.perf_counter() - t1:.1f}s")

    # ── Evaluate ──────────────────────────────────────────────────────────────
    y_pred = pipeline.predict(X_test)
    y_prob = pipeline.predict_proba(X_test)[:, 1]
    auc = float(roc_auc_score(y_test, y_prob))

    print("\n--- Evaluation on held-out test set (20%) ---")
    print(classification_report(y_test, y_pred, target_names=["Normal", "Attack"]))
    print(f"ROC-AUC: {auc:.4f}")
    print("---------------------------------------------\n")

    # ── Persist ───────────────────────────────────────────────────────────────
    print(f"[4/4] Saving model to '{args.output}' ...")
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    model_artifact = {
        "pipeline": pipeline,
        "feature_columns": FEATURE_COLUMNS,
        "trained_on": int(len(df)),
        "n_estimators": args.n_estimators,
        "max_depth": args.max_depth,
        "roc_auc": auc,
    }
    joblib.dump(model_artifact, output_path, compress=3)

    size_mb = output_path.stat().st_size / 1_048_576
    print(f"      Saved ({size_mb:.1f} MB)")
    print(f"\nDone. ROC-AUC = {auc:.4f}. Model ready at '{output_path}'.")
    print("Next step: commit api/ml/model.pkl to include it in the Docker image.")


if __name__ == "__main__":
    main()
