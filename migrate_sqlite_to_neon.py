"""One-time migration: copy existing SQLite data into Neon (PostgreSQL)."""
import os
import sqlite3
import json
import time

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE, ".env.local"))
DATABASE_URL = os.getenv("DATABASE_URL")
SQLITE_PATH = os.path.join(BASE, "whatsapp_generator.db")

if not DATABASE_URL:
    raise SystemExit("DATABASE_URL introuvable.")
if not os.path.exists(SQLITE_PATH):
    raise SystemExit("Aucun whatsapp_generator.db a migrer.")

src = sqlite3.connect(SQLITE_PATH)
src.row_factory = sqlite3.Row
dst = psycopg.connect(DATABASE_URL)
dst.autocommit = True


def table_count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def upsert_numbers():
    rows = src.execute("SELECT * FROM numbers").fetchall()
    if not rows:
        return 0
    cur = dst.cursor()
    for r in rows:
            cur.execute(
                """INSERT INTO numbers
                   (id, number, country_code, city, pattern, status, whatsapp_exists,
                    test_message, tested_at, last_message, message_status, message_sent_at,
                    whatsapp_message_id, sent_real, created_at, campaign_id, tags, quality_score)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (id) DO UPDATE SET number=EXCLUDED.number""",
                (r["id"], r["number"], r["country_code"], r["city"], r["pattern"],
                 r["status"], r["whatsapp_exists"], r["test_message"], r["tested_at"],
                 r["last_message"], r["message_status"], r["message_sent_at"],
                 r["whatsapp_message_id"], r["sent_real"], r["created_at"],
                 r["campaign_id"], r["tags"], r["quality_score"]),
            )
    return len(rows)


def upsert_campaigns():
    rows = src.execute("SELECT * FROM campaigns").fetchall()
    if not rows:
        return 0
    cur = dst.cursor()
    for r in rows:
            cur.execute(
                """INSERT INTO campaigns
                   (id, name, country_code, city, plan_count, message, send_after_test,
                    delay_ms, status, generated, tested, exists_count, not_exists_count,
                    sent, failed, created_at, started_at, finished_at, scheduled_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name""",
                (r["id"], r["name"], r["country_code"], r["city"], r["plan_count"],
                 r["message"], r["send_after_test"], r["delay_ms"], r["status"],
                 r["generated"], r["tested"], r["exists_count"], r["not_exists_count"],
                 r["sent"], r["failed"], r["created_at"], r["started_at"],
                 r["finished_at"], r["scheduled_at"]),
            )
    return len(rows)


def upsert_templates():
    rows = src.execute("SELECT * FROM message_templates").fetchall()
    if not rows:
        return 0
    cur = dst.cursor()
    for r in rows:
            cur.execute(
                """INSERT INTO message_templates
                   (id, name, content, category, variables, created_at, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name""",
                (r["id"], r["name"], r["content"], r["category"], r["variables"],
                 r["created_at"], r["updated_at"]),
            )
    return len(rows)


def upsert_blacklist():
    rows = src.execute("SELECT * FROM blacklist").fetchall()
    if not rows:
        return 0
    cur = dst.cursor()
    for r in rows:
            cur.execute(
                """INSERT INTO blacklist (id, number, reason, added_at, added_by)
                   VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT (number) DO UPDATE SET reason=EXCLUDED.reason""",
                (r["id"], r["number"], r["reason"], r["added_at"], r["added_by"]),
            )
    return len(rows)


def upsert_campaign_logs():
    rows = src.execute("SELECT * FROM campaign_logs").fetchall()
    if not rows:
        return 0
    cur = dst.cursor()
    for r in rows:
            cur.execute(
                """INSERT INTO campaign_logs (campaign_id, action, number, details, timestamp)
                   VALUES (%s,%s,%s,%s,%s)""",
                (r["campaign_id"], r["action"], r["number"], r["details"], r["timestamp"]),
            )
    return len(rows)


def upsert_queue():
    rows = src.execute("SELECT * FROM message_queue").fetchall()
    if not rows:
        return 0
    cur = dst.cursor()
    for r in rows:
            cur.execute(
                """INSERT INTO message_queue
                   (id, number, message, campaign_id, priority, status, attempts,
                    max_attempts, last_error, created_at, scheduled_at, sent_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (id) DO UPDATE SET number=EXCLUDED.number""",
                (r["id"], r["number"], r["message"], r["campaign_id"], r["priority"],
                 r["status"], r["attempts"], r["max_attempts"], r["last_error"],
                 r["created_at"], r["scheduled_at"], r["sent_at"]),
            )
    return len(rows)


tables = {
    "numbers": upsert_numbers,
    "campaigns": upsert_campaigns,
    "message_templates": upsert_templates,
    "blacklist": upsert_blacklist,
    "campaign_logs": upsert_campaign_logs,
    "message_queue": upsert_queue,
}

for name, fn in tables.items():
    before = table_count(dst, name)
    n = fn()
    after = table_count(dst, name)
    print(f"{name}: +{n} (avant={before}, apres={after})")

src.close()
dst.close()
print("Migration terminee.")