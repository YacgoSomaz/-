import asyncio
import argparse
import csv
import json
import sqlite3
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from typing import Any

import websockets


BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = Path(__file__).resolve().parent / "relay_logs"
DB_PATH = BASE_DIR / "dycast_messages.db"
LOG_DIR.mkdir(exist_ok=True)


def log_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d")
    return LOG_DIR / f"dycast_messages_{stamp}.jsonl"


def init_db(db_path: Path) -> None:
    with sqlite3.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS live_rooms (
                room_num TEXT PRIMARY KEY,
                room_id TEXT,
                nickname TEXT,
                title TEXT,
                avatar TEXT,
                cover TEXT,
                status INTEGER,
                first_seen_at TEXT,
                last_seen_at TEXT,
                raw_json TEXT
            );

            CREATE TABLE IF NOT EXISTS live_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                received_at TEXT NOT NULL,
                room_num TEXT,
                room_id TEXT,
                message_id TEXT,
                method TEXT,
                user_id TEXT,
                user_name TEXT,
                content TEXT,
                raw_json TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_live_messages_room_time
                ON live_messages(room_num, received_at);

            CREATE UNIQUE INDEX IF NOT EXISTS idx_live_messages_dedupe
                ON live_messages(room_num, method, message_id)
                WHERE message_id IS NOT NULL;
            """
        )


def upsert_room(db_path: Path, payload: dict[str, Any], received_at: str) -> dict[str, str | None]:
    room_num = str(payload.get("roomNum") or "")
    room_id = str(payload.get("roomId") or "")
    if not room_num and not room_id:
        return {"room_num": None, "room_id": None}

    with sqlite3.connect(db_path) as db:
        db.execute(
            """
            INSERT INTO live_rooms (
                room_num, room_id, nickname, title, avatar, cover, status,
                first_seen_at, last_seen_at, raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(room_num) DO UPDATE SET
                room_id=excluded.room_id,
                nickname=excluded.nickname,
                title=excluded.title,
                avatar=excluded.avatar,
                cover=excluded.cover,
                status=excluded.status,
                last_seen_at=excluded.last_seen_at,
                raw_json=excluded.raw_json
            """,
            (
                room_num or room_id,
                room_id or None,
                payload.get("nickname"),
                payload.get("title"),
                payload.get("avatar"),
                payload.get("cover"),
                payload.get("status"),
                received_at,
                received_at,
                json.dumps(payload, ensure_ascii=False),
            ),
        )

    return {"room_num": room_num or room_id or None, "room_id": room_id or None}


def save_message(
    db_path: Path,
    payload: dict[str, Any],
    received_at: str,
    room_num: str | None,
    room_id: str | None,
) -> None:
    user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
    message_id = payload.get("id")
    method = payload.get("method")
    payload_room_num = payload.get("roomNum") or payload.get("room_num")
    payload_room_id = payload.get("roomId") or payload.get("room_id")

    with sqlite3.connect(db_path) as db:
        db.execute(
            """
            INSERT OR IGNORE INTO live_messages (
                received_at, room_num, room_id, message_id, method,
                user_id, user_name, content, raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                received_at,
                room_num or (str(payload_room_num) if payload_room_num else None),
                room_id or (str(payload_room_id) if payload_room_id else None),
                str(message_id) if message_id is not None else None,
                str(method) if method is not None else None,
                user.get("id"),
                user.get("name"),
                payload.get("content"),
                json.dumps(payload, ensure_ascii=False),
            ),
        )


def write_jsonl(record: dict[str, Any]) -> None:
    with log_path().open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(record, ensure_ascii=False) + "\n")


def is_room_info(payload: Any) -> bool:
    return isinstance(payload, dict) and ("roomNum" in payload or "roomId" in payload) and "method" not in payload


def iter_messages(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and payload.get("method"):
        return [payload]
    return []


def query_messages(query: dict[str, list[str]]) -> list[sqlite3.Row]:
    clauses = []
    params: list[Any] = []
    room = query.get("room", [""])[0]
    method = query.get("method", [""])[0]
    from_time = query.get("from", [""])[0]
    to_time = query.get("to", [""])[0]

    if room:
        clauses.append("room_num = ?")
        params.append(room)
    if method:
        clauses.append("method = ?")
        params.append(method)
    if from_time:
        clauses.append("received_at >= ?")
        params.append(from_time)
    if to_time:
        clauses.append("received_at <= ?")
        params.append(to_time)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT
            received_at, room_num, room_id, message_id, method,
            user_id, user_name, content, raw_json
        FROM live_messages
        {where}
        ORDER BY received_at ASC, id ASC
    """
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        return db.execute(sql, params).fetchall()


def csv_bytes(rows: list[sqlite3.Row]) -> bytes:
    from io import StringIO

    output = StringIO()
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
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row[key] for key in fieldnames})
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def jsonl_bytes(rows: list[sqlite3.Row]) -> bytes:
    lines = [json.dumps(dict(row), ensure_ascii=False) for row in rows]
    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")


class ExportHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            body = json.dumps({"ok": True}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path not in ("/export/messages.csv", "/export/messages.jsonl"):
            self.send_response(404)
            self.end_headers()
            return

        query = parse_qs(parsed.query)
        rows = query_messages(query)
        if parsed.path.endswith(".jsonl"):
            body = jsonl_bytes(rows)
            content_type = "application/x-ndjson; charset=utf-8"
            filename = "dycast_messages.jsonl"
        else:
            body = csv_bytes(rows)
            content_type = "text/csv; charset=utf-8"
            filename = "dycast_messages.csv"

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_export_server(host: str, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), ExportHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


async def collect(websocket):
    room_num: str | None = None
    room_id: str | None = None

    async for message in websocket:
        received_at = datetime.now(timezone.utc).isoformat()
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            payload = {"raw": message}

        record = {
            "received_at": received_at,
            "payload": payload,
        }

        write_jsonl(record)

        if is_room_info(payload):
            room_state = upsert_room(DB_PATH, payload, received_at)
            room_num = room_state["room_num"] or room_num
            room_id = room_state["room_id"] or room_id
        else:
            for item in iter_messages(payload):
                save_message(DB_PATH, item, received_at, room_num, room_id)

        print(json.dumps(record, ensure_ascii=False))
        await websocket.send(json.dumps({"ok": True, "received_at": received_at}, ensure_ascii=False))


async def main(host: str, port: int, export_host: str, export_port: int):
    init_db(DB_PATH)
    export_server = start_export_server(export_host, export_port)
    async with websockets.serve(collect, host, port):
        print(f"dycast collector listening on ws://{host}:{port}")
        print(f"export server listening on http://{export_host}:{export_port}")
        print(f"sqlite database: {DB_PATH}")
        print(f"jsonl logs: {LOG_DIR}")
        try:
            await asyncio.Future()
        finally:
            export_server.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect dycast forwarded messages.")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--export-host", default="localhost")
    parser.add_argument("--export-port", type=int, default=8766)
    args = parser.parse_args()
    asyncio.run(main(args.host, args.port, args.export_host, args.export_port))
