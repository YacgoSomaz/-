import aiosqlite
from config import DB_PATH

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS comments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id    TEXT,
    user_name  TEXT,
    content    TEXT,
    ts         INTEGER  -- unix timestamp ms
);

CREATE TABLE IF NOT EXISTS transcripts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id    TEXT,
    text       TEXT,
    start_sec  INTEGER,  -- chunk 起始秒（相对于直播开始）
    created_at INTEGER
);
"""

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_CREATE_SQL)
        await db.commit()

async def save_comment(room_id: str, user_name: str, content: str, ts: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO comments (room_id, user_name, content, ts) VALUES (?,?,?,?)",
            (room_id, user_name, content, ts),
        )
        await db.commit()

async def save_transcript(room_id: str, text: str, start_sec: int, created_at: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO transcripts (room_id, text, start_sec, created_at) VALUES (?,?,?,?)",
            (room_id, text, start_sec, created_at),
        )
        await db.commit()
