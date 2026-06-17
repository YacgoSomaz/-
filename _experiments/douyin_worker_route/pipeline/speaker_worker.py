"""Low-priority incremental speaker labeling for sealed, transcribed audio."""

from __future__ import annotations

import argparse
import csv
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

import imageio_ffmpeg
import numpy as np
import sherpa_onnx

from . import config

SAMPLE_RATE = 16000
EMBED_SAMPLE_SEC = 5
EMBED_SAMPLE_POINTS = (0.2, 0.5, 0.8)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS speaker_labels (
    room_id TEXT NOT NULL,
    file_name TEXT NOT NULL,
    speaker_label TEXT NOT NULL,
    similarity REAL,
    change_status TEXT,
    embedding BLOB,
    source TEXT NOT NULL,
    error TEXT,
    segment_ts INTEGER,
    analyzed_ts INTEGER NOT NULL,
    PRIMARY KEY(room_id, file_name)
);
CREATE INDEX IF NOT EXISTS idx_speaker_labels_room_time
    ON speaker_labels(room_id, analyzed_ts);
CREATE TABLE IF NOT EXISTS speaker_profiles (
    room_id TEXT NOT NULL,
    speaker_label TEXT NOT NULL,
    centroid BLOB NOT NULL,
    sample_count INTEGER NOT NULL,
    updated_ts INTEGER NOT NULL,
    PRIMARY KEY(room_id, speaker_label)
);
"""


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(config.SPEAKER_DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    columns = {row["name"] for row in con.execute("PRAGMA table_info(speaker_labels)")}
    if "segment_ts" not in columns:
        con.execute("ALTER TABLE speaker_labels ADD COLUMN segment_ts INTEGER")
    con.commit()
    return con


def _room_from_path(value: str) -> str:
    parts = Path(value.replace("\\", "/")).parts
    try:
        return parts[parts.index("audio") + 1]
    except (ValueError, IndexError):
        return ""


def _normalize(vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    if norm <= 0:
        raise ValueError("zero-norm speaker embedding")
    return vector / norm


def _audio_path(value: str) -> Path:
    """Support both legacy `room/file.mp3` and new `audio/room/file.mp3` paths."""
    relative = Path(value.replace("\\", "/"))
    if relative.parts and relative.parts[0].lower() == "audio":
        return config.ROUTE_DIR / relative
    return config.AUDIO_DIR / relative


def _make_extractor() -> sherpa_onnx.SpeakerEmbeddingExtractor:
    if not config.SPEAKER_MODEL.exists():
        raise FileNotFoundError(f"speaker model missing: {config.SPEAKER_MODEL}")
    cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=str(config.SPEAKER_MODEL), num_threads=1, provider="cpu"
    )
    return sherpa_onnx.SpeakerEmbeddingExtractor(cfg)


def _decode(path: Path) -> np.ndarray:
    proc = subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-v", "error", "-i", str(path), "-vn", "-ac", "1",
            "-ar", str(SAMPLE_RATE), "-f", "f32le", "pipe:1",
        ],
        capture_output=True,
        timeout=90, creationflags=_NO_WINDOW,
    )
    if proc.returncode != 0:
        error = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(error[-400:] or f"ffmpeg rc={proc.returncode}")
    samples = np.frombuffer(proc.stdout, dtype="<f4").copy()
    if len(samples) < SAMPLE_RATE * 3:
        raise RuntimeError(f"audio too short: {len(samples) / SAMPLE_RATE:.2f}s")
    return samples


def _embedding(
    extractor: sherpa_onnx.SpeakerEmbeddingExtractor, samples: np.ndarray
) -> np.ndarray:
    sample_len = EMBED_SAMPLE_SEC * SAMPLE_RATE
    if len(samples) > sample_len * len(EMBED_SAMPLE_POINTS):
        pieces = []
        for point in EMBED_SAMPLE_POINTS:
            center = int(len(samples) * point)
            start = max(0, min(center - sample_len // 2, len(samples) - sample_len))
            pieces.append(samples[start:start + sample_len])
        samples = np.concatenate(pieces)
    stream = extractor.create_stream()
    stream.accept_waveform(SAMPLE_RATE, samples)
    stream.input_finished()
    if not extractor.is_ready(stream):
        raise RuntimeError("speaker extractor not ready")
    return _normalize(np.asarray(extractor.compute(stream), dtype=np.float32))


def _seed_existing(con: sqlite3.Connection) -> None:
    """Import the validated historical labels and embeddings once."""
    if not config.SPEAKER_LABELS_CSV.exists() or not config.SPEAKER_ANALYSIS_DB.exists():
        return
    feature_con = sqlite3.connect(f"file:{config.SPEAKER_ANALYSIS_DB}?mode=ro", uri=True)
    try:
        features = {
            (row[0], row[1]): (row[2], row[3])
            for row in feature_con.execute(
                "SELECT file_name, file_path, embedding, capture_ts FROM audio_features "
                "WHERE embedding IS NOT NULL"
            )
        }
    finally:
        feature_con.close()

    grouped: dict[tuple[str, str], list[np.ndarray]] = {}
    with config.SPEAKER_LABELS_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            label = (row.get("speaker_label") or "").strip()
            if not label.startswith("speaker_") or label == "speaker_uncertain":
                continue
            room_id = _room_from_path(row.get("file_path", ""))
            file_name = Path(row.get("file_name", "")).name
            feature = features.get((file_name, row.get("file_path", "")))
            if not room_id or not file_name or feature is None:
                continue
            blob, segment_ts = feature
            embedding = _normalize(np.frombuffer(blob, dtype=np.float32).copy())
            con.execute(
                "INSERT OR IGNORE INTO speaker_labels "
                "(room_id,file_name,speaker_label,similarity,change_status,embedding,"
                "source,error,segment_ts,analyzed_ts) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    room_id, file_name, label, None, row.get("change_status", ""),
                    embedding.tobytes(), "historical_seed", None, segment_ts, int(time.time()),
                ),
            )
            grouped.setdefault((room_id, label), []).append(embedding)
    for (room_id, label), vectors in grouped.items():
        centroid = _normalize(np.mean(np.vstack(vectors), axis=0))
        con.execute(
            "INSERT OR IGNORE INTO speaker_profiles "
            "(room_id,speaker_label,centroid,sample_count,updated_ts) VALUES(?,?,?,?,?)",
            (room_id, label, centroid.tobytes(), len(vectors), int(time.time())),
        )
    if config.DB_PATH.exists():
        transcript_con = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
        try:
            for room_id, mp3_name, segment_ts in transcript_con.execute(
                "SELECT room_id,mp3_name,segment_ts FROM transcripts"
            ):
                con.execute(
                    "UPDATE speaker_labels SET segment_ts=COALESCE(segment_ts,?) "
                    "WHERE room_id=? AND file_name=?",
                    (segment_ts, room_id, Path(mp3_name.replace("\\", "/")).name),
                )
        finally:
            transcript_con.close()
    con.commit()


def _pending_transcripts(limit: int) -> list[sqlite3.Row]:
    if not config.DB_PATH.exists():
        return []
    con = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    labels = _connect()
    try:
        labeled = {
            (row[0], row[1])
            for row in labels.execute("SELECT room_id,file_name FROM speaker_labels")
        }
        cutoff = int(time.time()) - config.SPEAKER_DELAY_SEC
        rows = con.execute(
            "SELECT id,room_id,mp3_name,segment_ts,created_ts,segment_id "
            "FROM transcripts WHERE created_ts <= ? ORDER BY segment_ts,id",
            (cutoff,),
        ).fetchall()
        out = []
        for row in rows:
            file_name = Path((row["mp3_name"] or "").replace("\\", "/")).name
            if (row["room_id"], file_name) in labeled:
                continue
            path = _audio_path(row["mp3_name"])
            if not path.exists() or path.stat().st_size <= 0:
                continue
            if time.time() - path.stat().st_mtime < config.SPEAKER_DELAY_SEC:
                continue
            if row["segment_id"] is not None:
                sealed = con.execute(
                    "SELECT 1 FROM recording_timeline WHERE id=? "
                    "AND kind IN ('segment','short') AND transcribed_ts IS NOT NULL",
                    (row["segment_id"],),
                ).fetchone()
                if not sealed:
                    continue
            out.append(row)
            if len(out) >= limit:
                break
        return out
    finally:
        labels.close()
        con.close()


def _profiles(con: sqlite3.Connection, room_id: str) -> dict[str, tuple[np.ndarray, int]]:
    return {
        row["speaker_label"]: (
            _normalize(np.frombuffer(row["centroid"], dtype=np.float32).copy()),
            int(row["sample_count"]),
        )
        for row in con.execute(
            "SELECT speaker_label,centroid,sample_count FROM speaker_profiles WHERE room_id=?",
            (room_id,),
        )
    }


def _next_label(con: sqlite3.Connection, room_id: str) -> str:
    labels = [
        row[0] for row in con.execute(
            "SELECT speaker_label FROM speaker_profiles WHERE room_id=?", (room_id,)
        )
    ]
    used = {label.removeprefix("speaker_") for label in labels}
    for code in range(ord("A"), ord("Z") + 1):
        if chr(code) not in used:
            return f"speaker_{chr(code)}"
    return f"speaker_{len(labels) + 1}"


def _merge_similar_profiles(
    con: sqlite3.Connection,
    room_id: str,
    threshold: float | None = None,
) -> list[tuple[str, str]]:
    """Merge duplicate speaker identities while keeping stable label names."""
    threshold = threshold if threshold is not None else config.SPEAKER_MERGE_THRESHOLD
    merges: list[tuple[str, str]] = []
    while True:
        profiles = _profiles(con, room_id)
        best_pair: tuple[str, str] | None = None
        best_similarity = threshold
        labels = sorted(profiles)
        for index, left in enumerate(labels):
            for right in labels[index + 1:]:
                similarity = float(np.dot(profiles[left][0], profiles[right][0]))
                if similarity >= best_similarity:
                    best_pair = (left, right)
                    best_similarity = similarity
        if best_pair is None:
            break

        keep, merged = best_pair
        keep_centroid, keep_count = profiles[keep]
        merged_centroid, merged_count = profiles[merged]
        centroid = _normalize(
            (keep_centroid * keep_count + merged_centroid * merged_count)
            / (keep_count + merged_count)
        )
        now = int(time.time())
        con.execute(
            "UPDATE speaker_labels SET speaker_label=?,change_status='' "
            "WHERE room_id=? AND speaker_label=?",
            (keep, room_id, merged),
        )
        con.execute(
            "UPDATE speaker_profiles SET centroid=?,sample_count=?,updated_ts=? "
            "WHERE room_id=? AND speaker_label=?",
            (
                centroid.tobytes(), keep_count + merged_count, now,
                room_id, keep,
            ),
        )
        con.execute(
            "DELETE FROM speaker_profiles WHERE room_id=? AND speaker_label=?",
            (room_id, merged),
        )
        merges.append((merged, keep))
    return merges


def _confirm_changes(con: sqlite3.Connection, room_id: str) -> None:
    rows = con.execute(
        "SELECT file_name,speaker_label,embedding FROM speaker_labels "
        "WHERE room_id=? AND embedding IS NOT NULL ORDER BY segment_ts,file_name",
        (room_id,),
    ).fetchall()
    if len(rows) < config.SPEAKER_NEW_CONFIRM_SEGMENTS:
        return
    latest = rows[-config.SPEAKER_NEW_CONFIRM_SEGMENTS:]
    labels = {row["speaker_label"] for row in latest}
    if labels == {"speaker_uncertain"}:
        vectors = [
            _normalize(np.frombuffer(row["embedding"], dtype=np.float32).copy())
            for row in latest
        ]
        similarities = [
            float(np.dot(vectors[i], vectors[j]))
            for i in range(len(vectors)) for j in range(i)
        ]
        if similarities and min(similarities) >= config.SPEAKER_MATCH_THRESHOLD:
            label = _next_label(con, room_id)
            centroid = _normalize(np.mean(np.vstack(vectors), axis=0))
            for index, row in enumerate(latest):
                change = "change_confirmed_start" if index == 0 else (
                    "change_confirmed" if index == len(latest) - 1 else "change_candidate"
                )
                con.execute(
                    "UPDATE speaker_labels SET speaker_label=?,change_status=? "
                    "WHERE room_id=? AND file_name=?",
                    (label, change, room_id, row["file_name"]),
                )
            con.execute(
                "INSERT OR REPLACE INTO speaker_profiles VALUES(?,?,?,?,?)",
                (room_id, label, centroid.tobytes(), len(vectors), int(time.time())),
            )

    confirmed = [row for row in rows if row["speaker_label"] != "speaker_uncertain"]
    if len(confirmed) < config.SPEAKER_NEW_CONFIRM_SEGMENTS + 1:
        return
    tail = confirmed[-config.SPEAKER_NEW_CONFIRM_SEGMENTS:]
    tail_labels = {row["speaker_label"] for row in tail}
    previous = confirmed[-config.SPEAKER_NEW_CONFIRM_SEGMENTS - 1]["speaker_label"]
    if len(tail_labels) == 1 and next(iter(tail_labels)) != previous:
        con.execute(
            "UPDATE speaker_labels SET change_status='change_confirmed_start' "
            "WHERE room_id=? AND file_name=? AND change_status=''",
            (room_id, tail[0]["file_name"]),
        )


def process_once(limit: int | None = None) -> int:
    limit = limit or config.SPEAKER_BATCH_SIZE
    con = _connect()
    _seed_existing(con)
    room_ids = [
        row[0] for row in con.execute(
            "SELECT DISTINCT room_id FROM speaker_profiles ORDER BY room_id"
        )
    ]
    for room_id in room_ids:
        _merge_similar_profiles(con, room_id)
    con.commit()
    con.close()
    pending = _pending_transcripts(limit)
    if not pending:
        return 0
    extractor = _make_extractor()
    con = _connect()
    done = 0
    try:
        for row in pending:
            room_id = row["room_id"]
            file_name = Path(row["mp3_name"].replace("\\", "/")).name
            path = _audio_path(row["mp3_name"])
            try:
                embedding = _embedding(extractor, _decode(path))
                profiles = _profiles(con, room_id)
                best_label = "speaker_uncertain"
                best_similarity = None
                if profiles:
                    scored = {
                        label: float(np.dot(embedding, centroid))
                        for label, (centroid, _) in profiles.items()
                    }
                    best_label = max(scored, key=scored.get)
                    best_similarity = scored[best_label]
                    if best_similarity < config.SPEAKER_MATCH_THRESHOLD:
                        best_label = "speaker_uncertain"
                con.execute(
                    "INSERT OR REPLACE INTO speaker_labels "
                    "(room_id,file_name,speaker_label,similarity,change_status,embedding,"
                    "source,error,segment_ts,analyzed_ts) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        room_id, file_name, best_label, best_similarity, "",
                        embedding.tobytes(), "incremental", None,
                        int(row["segment_ts"]), int(time.time()),
                    ),
                )
                if (
                    best_label != "speaker_uncertain"
                    and best_similarity is not None
                    and best_similarity >= config.SPEAKER_PROFILE_UPDATE_THRESHOLD
                ):
                    centroid, count = profiles[best_label]
                    updated = _normalize((centroid * count + embedding) / (count + 1))
                    con.execute(
                        "UPDATE speaker_profiles SET centroid=?,sample_count=?,updated_ts=? "
                        "WHERE room_id=? AND speaker_label=?",
                        (updated.tobytes(), count + 1, int(time.time()), room_id, best_label),
                    )
                _confirm_changes(con, room_id)
                _merge_similar_profiles(con, room_id)
            except Exception as exc:  # noqa: BLE001
                con.execute(
                    "INSERT OR REPLACE INTO speaker_labels "
                    "(room_id,file_name,speaker_label,similarity,change_status,embedding,"
                    "source,error,segment_ts,analyzed_ts) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        room_id, file_name, "speaker_uncertain", None, "",
                        None, "incremental_error", repr(exc)[:500],
                        int(row["segment_ts"]), int(time.time()),
                    ),
                )
            con.commit()
            done += 1
        return done
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.once:
        print(f"speaker labeled: {process_once(args.limit)}")
        return 0
    while True:
        print(f"speaker labeled: {process_once(args.limit)}", flush=True)
        time.sleep(config.SPEAKER_POLL_SEC)


if __name__ == "__main__":
    raise SystemExit(main())
