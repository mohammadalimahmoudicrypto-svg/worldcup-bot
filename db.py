import os
import sqlite3
from contextlib import contextmanager
from typing import Optional

_DATABASE_URL = os.getenv("DATABASE_URL", "")
_USE_PG = "postgres" in _DATABASE_URL

if _USE_PG:
    import psycopg2
    import psycopg2.extras

_DB_FILE = os.getenv("DB_PATH", "worldcup.db")


# ── Unified cursor wrapper ────────────────────────────────────────────────────

class _Cur:
    """Makes SQLite and psycopg2 cursors behave identically."""

    def __init__(self, raw, use_pg: bool):
        self._raw = raw
        self._use_pg = use_pg

    def execute(self, sql: str, params=()):
        if self._use_pg:
            sql = sql.replace("?", "%s")
            self._raw.execute(sql, params or None)
        else:
            self._raw.execute(sql, params)
        return self  # allow chaining

    def fetchone(self):
        row = self._raw.fetchone()
        return dict(row) if row else None

    def fetchall(self):
        return [dict(r) for r in (self._raw.fetchall() or [])]

    @property
    def rowcount(self):
        return self._raw.rowcount

    @property
    def lastrowid(self):
        return getattr(self._raw, "lastrowid", None)


@contextmanager
def _conn():
    if _USE_PG:
        url = _DATABASE_URL.replace("postgres://", "postgresql://", 1)
        conn = psycopg2.connect(url)
        raw = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur = _Cur(raw, use_pg=True)
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            raw.close()
            conn.close()
    else:
        conn = sqlite3.connect(_DB_FILE)
        conn.row_factory = sqlite3.Row
        raw = conn.cursor()
        cur = _Cur(raw, use_pg=False)
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA_PG = """
    CREATE TABLE IF NOT EXISTS users (
        id            SERIAL PRIMARY KEY,
        telegram_id   BIGINT UNIQUE NOT NULL,
        username      TEXT,
        display_name  TEXT NOT NULL,
        bonus_points  INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS matches (
        id            SERIAL PRIMARY KEY,
        api_match_id  INTEGER,
        home_team     TEXT NOT NULL,
        away_team     TEXT NOT NULL,
        kickoff_utc   TEXT NOT NULL,
        home_score    INTEGER,
        away_score    INTEGER,
        is_finished   INTEGER DEFAULT 0,
        is_locked     INTEGER DEFAULT 0
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_matches_api_id
        ON matches(api_match_id) WHERE api_match_id IS NOT NULL;
    CREATE TABLE IF NOT EXISTS predictions (
        id          SERIAL PRIMARY KEY,
        user_id     INTEGER NOT NULL REFERENCES users(id),
        match_id    INTEGER NOT NULL REFERENCES matches(id),
        home_score  INTEGER NOT NULL,
        away_score  INTEGER NOT NULL,
        points      INTEGER,
        UNIQUE(user_id, match_id)
    );
"""

_SCHEMA_SQLITE = """
    CREATE TABLE IF NOT EXISTS users (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id   INTEGER UNIQUE NOT NULL,
        username      TEXT,
        display_name  TEXT NOT NULL,
        bonus_points  INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS matches (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        api_match_id  INTEGER,
        home_team     TEXT NOT NULL,
        away_team     TEXT NOT NULL,
        kickoff_utc   TEXT NOT NULL,
        home_score    INTEGER,
        away_score    INTEGER,
        is_finished   INTEGER DEFAULT 0,
        is_locked     INTEGER DEFAULT 0
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_matches_api_id
        ON matches(api_match_id) WHERE api_match_id IS NOT NULL;
    CREATE TABLE IF NOT EXISTS predictions (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER NOT NULL REFERENCES users(id),
        match_id    INTEGER NOT NULL REFERENCES matches(id),
        home_score  INTEGER NOT NULL,
        away_score  INTEGER NOT NULL,
        points      INTEGER,
        UNIQUE(user_id, match_id)
    );
"""


def init_db():
    schema = _SCHEMA_PG if _USE_PG else _SCHEMA_SQLITE
    with _conn() as c:
        for stmt in schema.split(";"):
            stmt = stmt.strip()
            if stmt:
                c.execute(stmt)

    # Migration: add api_match_id if missing (handles existing DBs)
    with _conn() as c:
        if _USE_PG:
            c.execute("""
                ALTER TABLE matches ADD COLUMN IF NOT EXISTS api_match_id INTEGER
            """)
            c.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_matches_api_id
                ON matches(api_match_id) WHERE api_match_id IS NOT NULL
            """)
        else:
            try:
                c.execute("ALTER TABLE matches ADD COLUMN api_match_id INTEGER")
                c.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_matches_api_id
                    ON matches(api_match_id) WHERE api_match_id IS NOT NULL
                """)
            except Exception:
                pass  # column already exists


# ── Users ─────────────────────────────────────────────────────────────────────

def upsert_user(telegram_id: int, username: Optional[str], display_name: str):
    with _conn() as c:
        c.execute("""
            INSERT INTO users (telegram_id, username, display_name)
            VALUES (?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username     = excluded.username,
                display_name = excluded.display_name
        """, (telegram_id, username, display_name))


def get_user(telegram_id: int):
    with _conn() as c:
        return c.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()


def set_bonus_points(identifier: str, points: int) -> bool:
    with _conn() as c:
        if identifier.startswith("@"):
            c.execute(
                "UPDATE users SET bonus_points = ? WHERE username = ?",
                (points, identifier[1:])
            )
        else:
            c.execute(
                "UPDATE users SET bonus_points = ? WHERE display_name = ?",
                (points, identifier)
            )
        return c.rowcount > 0


def get_rankings():
    with _conn() as c:
        return c.execute("""
            SELECT
                u.display_name,
                u.bonus_points,
                COALESCE(SUM(p.points), 0)                       AS earned_points,
                u.bonus_points + COALESCE(SUM(p.points), 0)     AS total_points
            FROM users u
            LEFT JOIN predictions p ON p.user_id = u.id AND p.points IS NOT NULL
            GROUP BY u.id, u.display_name, u.bonus_points
            ORDER BY total_points DESC
        """).fetchall()


def get_bot_rankings():
    with _conn() as c:
        return c.execute("""
            SELECT
                u.display_name,
                COALESCE(SUM(p.points), 0) AS earned_points
            FROM users u
            LEFT JOIN predictions p ON p.user_id = u.id AND p.points IS NOT NULL
            GROUP BY u.id, u.display_name
            ORDER BY earned_points DESC
        """).fetchall()


def get_avg_rankings():
    with _conn() as c:
        return c.execute("""
            SELECT
                u.display_name,
                COALESCE(SUM(p.points), 0)                             AS earned_points,
                COUNT(CASE WHEN p.points IS NOT NULL THEN 1 END)       AS graded,
                CASE
                    WHEN COUNT(CASE WHEN p.points IS NOT NULL THEN 1 END) > 0
                    THEN CAST(COALESCE(SUM(p.points), 0) AS REAL)
                         / COUNT(CASE WHEN p.points IS NOT NULL THEN 1 END)
                    ELSE 0
                END AS avg_points
            FROM users u
            LEFT JOIN predictions p ON p.user_id = u.id
            GROUP BY u.id, u.display_name
            ORDER BY avg_points DESC
        """).fetchall()


def get_olympic_rankings():
    with _conn() as c:
        return c.execute("""
            SELECT
                u.display_name,
                COALESCE(SUM(CASE WHEN p.points = 10 THEN 1 ELSE 0 END), 0) AS exact,
                COALESCE(SUM(CASE WHEN p.points = 7  THEN 1 ELSE 0 END), 0) AS correct_gd,
                COALESCE(SUM(CASE WHEN p.points = 5  THEN 1 ELSE 0 END), 0) AS correct_outcome
            FROM users u
            LEFT JOIN predictions p ON p.user_id = u.id AND p.points IS NOT NULL
            GROUP BY u.id, u.display_name
            ORDER BY exact DESC, correct_gd DESC, correct_outcome DESC
        """).fetchall()


def list_users():
    with _conn() as c:
        return c.execute("SELECT * FROM users ORDER BY display_name").fetchall()


def get_user_stats(user_id: int):
    with _conn() as c:
        return c.execute("""
            SELECT
                SUM(CASE WHEN points IS NOT NULL THEN 1 ELSE 0 END) AS graded,
                SUM(CASE WHEN points = 10 THEN 1 ELSE 0 END)        AS exact,
                SUM(CASE WHEN points = 7  THEN 1 ELSE 0 END)        AS correct_gd,
                SUM(CASE WHEN points = 5  THEN 1 ELSE 0 END)        AS correct_outcome,
                SUM(CASE WHEN points = 0  THEN 1 ELSE 0 END)        AS miss,
                COALESCE(SUM(points), 0)                             AS earned_points
            FROM predictions
            WHERE user_id = ?
        """, (user_id,)).fetchone()


# ── Matches ───────────────────────────────────────────────────────────────────

def add_match(home: str, away: str, kickoff_utc: str, api_match_id: int = None) -> int:
    with _conn() as c:
        if _USE_PG:
            return c.execute(
                "INSERT INTO matches (home_team, away_team, kickoff_utc, api_match_id) VALUES (?, ?, ?, ?) RETURNING id",
                (home, away, kickoff_utc, api_match_id)
            ).fetchone()["id"]
        else:
            c.execute(
                "INSERT INTO matches (home_team, away_team, kickoff_utc, api_match_id) VALUES (?, ?, ?, ?)",
                (home, away, kickoff_utc, api_match_id)
            )
            return c.lastrowid


def get_match(match_id: int):
    with _conn() as c:
        return c.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()


def get_match_by_api_id(api_match_id: int):
    with _conn() as c:
        return c.execute(
            "SELECT * FROM matches WHERE api_match_id = ?", (api_match_id,)
        ).fetchone()


def get_upcoming_matches():
    with _conn() as c:
        return c.execute(
            "SELECT * FROM matches WHERE is_finished = 0 ORDER BY kickoff_utc ASC"
        ).fetchall()


def get_recent_finished(limit: int = 5):
    with _conn() as c:
        return c.execute(
            "SELECT * FROM matches WHERE is_finished = 1 ORDER BY kickoff_utc DESC LIMIT ?",
            (limit,)
        ).fetchall()


def get_all_matches():
    with _conn() as c:
        return c.execute("SELECT * FROM matches ORDER BY kickoff_utc ASC").fetchall()


def get_pending_locks():
    with _conn() as c:
        return c.execute(
            "SELECT * FROM matches WHERE is_locked = 0 AND is_finished = 0"
        ).fetchall()


def get_synced_unfinished():
    with _conn() as c:
        return c.execute(
            "SELECT * FROM matches WHERE api_match_id IS NOT NULL AND is_finished = 0"
        ).fetchall()


def get_matches_between(from_utc: str, to_utc: str):
    with _conn() as c:
        return c.execute(
            "SELECT * FROM matches WHERE kickoff_utc >= ? AND kickoff_utc < ? ORDER BY kickoff_utc ASC",
            (from_utc, to_utc)
        ).fetchall()


def lock_match(match_id: int):
    with _conn() as c:
        c.execute("UPDATE matches SET is_locked = 1 WHERE id = ?", (match_id,))


def set_result(match_id: int, home_score: int, away_score: int):
    with _conn() as c:
        c.execute("""
            UPDATE matches
            SET home_score = ?, away_score = ?, is_finished = 1, is_locked = 1
            WHERE id = ?
        """, (home_score, away_score, match_id))


def delete_match(match_id: int) -> bool:
    with _conn() as c:
        c.execute(
            "DELETE FROM matches WHERE id = ? AND is_finished = 0", (match_id,)
        )
        return c.rowcount > 0


# ── Predictions ───────────────────────────────────────────────────────────────

def upsert_prediction(user_id: int, match_id: int, home_score: int, away_score: int, pred_winner: int = None):
    with _conn() as c:
        c.execute("""
            INSERT INTO predictions (user_id, match_id, home_score, away_score, pred_winner)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, match_id) DO UPDATE SET
                home_score   = excluded.home_score,
                away_score   = excluded.away_score,
                pred_winner  = excluded.pred_winner,
                points       = NULL
        """, (user_id, match_id, home_score, away_score, pred_winner))


def get_user_predictions(user_id: int):
    with _conn() as c:
        return c.execute("""
            SELECT
                p.*,
                m.home_team, m.away_team, m.kickoff_utc,
                m.home_score AS actual_home, m.away_score AS actual_away,
                m.is_finished, m.is_locked
            FROM predictions p
            JOIN matches m ON m.id = p.match_id
            WHERE p.user_id = ?
            ORDER BY m.kickoff_utc ASC
        """, (user_id,)).fetchall()


def get_match_predictions(match_id: int):
    with _conn() as c:
        return c.execute("""
            SELECT p.*, u.display_name, u.telegram_id
            FROM predictions p
            JOIN users u ON u.id = p.user_id
            WHERE p.match_id = ?
            ORDER BY u.display_name
        """, (match_id,)).fetchall()


def award_points(match_id: int, user_id: int, points: int):
    with _conn() as c:
        c.execute("""
            UPDATE predictions SET points = ?
            WHERE match_id = ? AND user_id = ?
        """, (points, match_id, user_id))
def delete_user(identifier: str) -> bool:
    with _conn() as c:
        if identifier.startswith("@"):
            c.execute("DELETE FROM users WHERE username = ?", (identifier[1:],))
        else:
            c.execute("DELETE FROM users WHERE display_name = ?", (identifier,))
        return c.rowcount > 0
