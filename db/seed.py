import argparse
import csv
import os
import random
from datetime import datetime, timedelta, timezone

import psycopg


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--data", required=True, help="Path to UNSW-NB15 data CSV (NO header)")
    p.add_argument("--features", required=True, help="Path to UNSW-NB15_features.csv (has column names)")
    p.add_argument("--dsn", required=True, help="PostgreSQL DSN (psycopg)")
    p.add_argument("--limit", type=int, default=0, help="0 = no limit")
    p.add_argument("--days", type=int, default=30, help="Generate ts in last N days (if no timestamp)")
    return p.parse_args()


def to_int(x):
    try:
        if x is None or x == "":
            return None
        return int(float(x))
    except:
        return None


def load_feature_names(features_csv_path: str) -> list[str]:
    """
    UNSW-NB15_features.csv has format: No.,Name,Type,Description
    We need the Name column (index 1).
    Note: UNSW-NB15_features.csv is often in latin-1 encoding.
    """
    names = []
    with open(features_csv_path, newline="", encoding="latin-1") as f:
        reader = csv.reader(f)
        header = next(reader, None)  # skip header row (No.,Name,Type,Description)
        for row in reader:
            if not row or len(row) < 2:
                continue
            name = row[1].strip()  # Get Name column (index 1)
            if name:
                names.append(name)
    if not names:
        raise SystemExit("No feature names found in features file.")
    print(f"Loaded {len(names)} feature names")
    return names


def main():
    args = parse_args()
    feature_names = load_feature_names(args.features)

    now = datetime.now(timezone.utc)
    inserted = 0

    with psycopg.connect(args.dsn) as conn:
        with conn.cursor() as cur:
            with open(args.data, newline="", encoding="utf-8-sig") as f:
                reader = csv.reader(f)

                for row in reader:
                    # Some rows might be empty/broken
                    if not row:
                        continue

                    # Data row length should match number of features (often 49)
                    if len(row) != len(feature_names):
                        raise SystemExit(
                            f"Row has {len(row)} columns but features has {len(feature_names)}. "
                            "Check separators/format."
                        )

                    rec = dict(zip(feature_names, row))

                    # Map required fields (names in UNSW often: srcip, dstip, proto, service, sbytes, attack_cat, Label)
                    srcip = rec.get("srcip")
                    dstip = rec.get("dstip")
                    proto = rec.get("proto")
                    service = rec.get("service")
                    sbytes = to_int(rec.get("sbytes"))
                    attack_cat = rec.get("attack_cat")
                    label = rec.get("Label")  # Note: uppercase L in UNSW dataset

                    # Generate a timestamp in last N days (baseline-friendly)
                    ts = now - timedelta(seconds=random.randint(0, args.days * 24 * 3600))

                    cur.execute(
                        """
                        INSERT INTO network_events (ts, srcip, dstip, proto, service, sbytes, attack_cat, label)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (ts, srcip, dstip, proto, service, sbytes, attack_cat, label),
                    )

                    inserted += 1
                    if args.limit and inserted >= args.limit:
                        break

        conn.commit()

    print(f"Inserted {inserted} rows into network_events")


if __name__ == "__main__":
    main()
