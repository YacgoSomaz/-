import argparse
import csv
import json
import sqlite3
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "dycast_messages.db"
DEFAULT_OUT = BASE_DIR / "exports"


def build_query(args: argparse.Namespace) -> tuple[str, list[Any]]:
    clauses = []
    params: list[Any] = []

    if args.room:
        clauses.append("room_num = ?")
        params.append(args.room)
    if args.method:
        clauses.append("method = ?")
        params.append(args.method)
    if args.from_time:
        clauses.append("received_at >= ?")
        params.append(args.from_time)
    if args.to_time:
        clauses.append("received_at <= ?")
        params.append(args.to_time)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT
            received_at, room_num, room_id, message_id, method,
            user_id, user_name, content, raw_json
        FROM live_messages
        {where}
        ORDER BY received_at ASC, id ASC
    """
    return sql, params


def export_csv(rows: list[sqlite3.Row], out_path: Path) -> None:
    fieldnames = [
        "received_at",
        "room_num",
        "room_id",
        "message_id",
        "method",
        "user_id",
        "user_name",
        "content",
        "raw_json",
    ]
    with out_path.open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in fieldnames})


def export_jsonl(rows: list[sqlite3.Row], out_path: Path) -> None:
    with out_path.open("w", encoding="utf-8") as fp:
        for row in rows:
            fp.write(json.dumps(dict(row), ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export dycast collected messages.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path.")
    parser.add_argument("--room", help="Filter by dycast room number.")
    parser.add_argument("--method", help="Filter by message method, e.g. WebcastChatMessage.")
    parser.add_argument("--from-time", help="Inclusive ISO timestamp, e.g. 2026-06-03T00:00:00+00:00.")
    parser.add_argument("--to-time", help="Inclusive ISO timestamp.")
    parser.add_argument("--format", choices=["csv", "jsonl"], default="csv")
    parser.add_argument("--out", help="Output file path.")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"Database does not exist: {db_path}")

    DEFAULT_OUT.mkdir(exist_ok=True)
    out_path = Path(args.out) if args.out else DEFAULT_OUT / f"dycast_export.{args.format}"

    sql, params = build_query(args)
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(sql, params).fetchall()

    if args.format == "csv":
        export_csv(rows, out_path)
    else:
        export_jsonl(rows, out_path)

    print(f"exported {len(rows)} rows to {out_path}")


if __name__ == "__main__":
    main()
