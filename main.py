from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
import httpx
import random
import string
import asyncio
import os
import time
import json
import hashlib
import re
from typing import Optional, Dict, List
from collections import defaultdict
from datetime import datetime, timezone
from contextlib import asynccontextmanager
import phonenumbers

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from dotenv import load_dotenv

APP_STARTED = time.time()

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env.local"))
APPDIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("PGDATABASE_URL")
if not DATABASE_URL:
    raise SystemExit("ERREUR: DATABASE_URL introuvable. Lancez 'neon link' pour generer .env.local, puis redemarrez.")
if DATABASE_URL.startswith(("postgres://", "postgresql://")):
    DATABASE_URL = DATABASE_URL.replace("?sslmode=prefer", "?sslmode=require", 1)

db_pool = ConnectionPool(
    DATABASE_URL,
    min_size=1,
    max_size=4,
    open=False,
    timeout=15,
    reconnect_timeout=300,
    check=ConnectionPool.check_connection,
    kwargs={"row_factory": dict_row},
)


@asynccontextmanager
async def lifespan(app):
    db_pool.open()
    init_db()
    global generated_numbers
    generated_numbers = load_numbers()
    load_campaigns()
    load_templates()
    load_blacklist_db()
    load_queue()
    asyncio.create_task(check_scheduled_campaigns())
    try:
        yield
    finally:
        db_pool.close()


app = FastAPI(title="WhatsApp Number Generator", version="5.0.0", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")

BRIDGE_URL = os.getenv("WHATSAPP_BRIDGE_URL", "http://127.0.0.1:8755")
SIMULATE_WHATSAPP = os.getenv("SIMULATE_WHATSAPP", "1") == "1"
MAX_REQUESTS_PER_MINUTE = 30

COUNTRY_CODES = {
    "US": {
        "name": "United States", "dial_code": "+1",
        "cities": ["New York", "Los Angeles", "Chicago", "Houston", "Phoenix"],
        "mobile_prefixes": ["201", "202", "212", "310", "312", "415", "617", "646", "702", "718", "773", "818"],
        "city_prefixes": {
            "New York": ["212", "646", "718", "917"],
            "Los Angeles": ["213", "310", "323", "424"],
            "Chicago": ["312", "773", "872"],
            "Houston": ["281", "346", "713", "832"],
            "Phoenix": ["480", "602", "623"],
        },
        "national_length": 10,
    },
    "GB": {
        "name": "United Kingdom", "dial_code": "+44",
        "cities": ["London", "Manchester", "Birmingham", "Glasgow"],
        "mobile_prefixes": ["7400", "7420", "7530", "7540", "7700", "7710", "7720", "7810", "7880", "7910"],
        "national_length": 10,
    },
    "FR": {
        "name": "France", "dial_code": "+33",
        "cities": ["Paris", "Marseille", "Lyon", "Toulouse"],
        "mobile_prefixes": ["6", "7"],
        "national_length": 9,
    },
    "DE": {
        "name": "Germany", "dial_code": "+49",
        "cities": ["Berlin", "Munich", "Hamburg", "Cologne"],
        "mobile_prefixes": ["151", "152", "160", "162", "163", "170", "171", "172", "173", "174", "175", "176"],
        "national_length": 11,
    },
    "IN": {
        "name": "India", "dial_code": "+91",
        "cities": ["Mumbai", "Delhi", "Bangalore", "Chennai"],
        "mobile_prefixes": ["6", "7", "8", "9"],
        "national_length": 10,
    },
    "BR": {
        "name": "Brazil", "dial_code": "+55",
        "cities": ["Sao Paulo", "Rio de Janeiro", "Brasilia", "Salvador"],
        "mobile_prefixes": ["11", "21", "31", "41", "51"],
        "city_prefixes": {
            "Sao Paulo": ["11"],
            "Rio de Janeiro": ["21"],
            "Brasilia": ["61"],
            "Salvador": ["71"],
        },
        "national_length": 11,
    },
    "AU": {
        "name": "Australia", "dial_code": "+61",
        "cities": ["Sydney", "Melbourne", "Brisbane", "Perth"],
        "mobile_prefixes": ["40", "41", "42", "43", "45", "46", "48"],
        "national_length": 9,
    },
    "CA": {
        "name": "Canada", "dial_code": "+1",
        "cities": ["Toronto", "Vancouver", "Montreal", "Calgary"],
        "mobile_prefixes": ["403", "416", "438", "514", "604", "647"],
        "city_prefixes": {
            "Toronto": ["416", "437", "647"],
            "Vancouver": ["236", "604", "672"],
            "Montreal": ["438", "450", "514"],
            "Calgary": ["403", "587", "825"],
        },
        "national_length": 10,
    },
    "JP": {
        "name": "Japan", "dial_code": "+81",
        "cities": ["Tokyo", "Osaka", "Nagoya", "Fukuoka"],
        "mobile_prefixes": ["70", "80", "90"],
        "national_length": 10,
    },
    "KR": {
        "name": "South Korea", "dial_code": "+82",
        "cities": ["Seoul", "Busan", "Incheon", "Daegu"],
        "mobile_prefixes": ["10", "11", "16", "17", "18", "19"],
        "national_length": 10,
    },
    "ES": {
        "name": "Spain", "dial_code": "+34",
        "cities": ["Madrid", "Barcelona", "Valencia", "Seville"],
        "mobile_prefixes": ["6", "7"],
        "national_length": 9,
    },
    "IT": {
        "name": "Italy", "dial_code": "+39",
        "cities": ["Rome", "Milan", "Naples", "Turin"],
        "mobile_prefixes": ["320", "327", "328", "329", "330", "333", "339", "340", "347", "348", "349", "360", "366", "380", "388", "390", "391"],
        "national_length": 10,
    },
    "PA": {
        "name": "Panama", "dial_code": "+507",
        "cities": ["Panama City", "Colon", "David", "La Chorrera"],
        "mobile_prefixes": ["6"],
        "national_length": 8,
    },
    "AT": {
        "name": "Austria", "dial_code": "+43",
        "cities": ["Vienna", "Graz", "Linz", "Salzburg"],
        "mobile_prefixes": ["650", "660", "664", "670", "676", "677", "680", "681", "688", "699"],
        "national_length": 11,
    },
    "BE": {
        "name": "Belgium", "dial_code": "+32",
        "cities": ["Brussels", "Antwerp", "Ghent", "Charleroi"],
        "mobile_prefixes": ["460", "465", "466", "470", "471", "472", "473", "474", "475", "476", "477", "478", "479", "484", "485", "486", "487", "488", "489", "490", "491"],
        "national_length": 9,
    },
    "HR": {
        "name": "Croatia", "dial_code": "+385",
        "cities": ["Zagreb", "Split", "Rijeka", "Osijek"],
        "mobile_prefixes": ["91", "92", "95", "98", "99"],
        "national_length": 9,
    },
    "CY": {
        "name": "Cyprus", "dial_code": "+357",
        "cities": ["Nicosia", "Limassol", "Larnaca", "Paphos"],
        "mobile_prefixes": ["94", "95", "96", "97", "99"],
        "national_length": 8,
    },
    "EE": {
        "name": "Estonia", "dial_code": "+372",
        "cities": ["Tallinn", "Tartu", "Parnu", "Narva"],
        "mobile_prefixes": ["5"],
        "national_length": 8,
    },
    "FI": {
        "name": "Finland", "dial_code": "+358",
        "cities": ["Helsinki", "Espoo", "Tampere", "Oulu"],
        "mobile_prefixes": ["40", "41", "42", "43", "44", "45", "46", "50"],
        "national_length": 9,
    },
    "GR": {
        "name": "Greece", "dial_code": "+30",
        "cities": ["Athens", "Thessaloniki", "Patras", "Heraklion"],
        "mobile_prefixes": ["690", "691", "692", "693", "694", "695", "697", "698", "699"],
        "national_length": 10,
    },
    "IE": {
        "name": "Ireland", "dial_code": "+353",
        "cities": ["Dublin", "Cork", "Galway", "Limerick"],
        "mobile_prefixes": ["83", "85", "86", "87", "88", "89"],
        "national_length": 9,
    },
    "LV": {
        "name": "Latvia", "dial_code": "+371",
        "cities": ["Riga", "Daugavpils", "Liepaja", "Jurmala"],
        "mobile_prefixes": ["2"],
        "national_length": 8,
    },
    "LT": {
        "name": "Lithuania", "dial_code": "+370",
        "cities": ["Vilnius", "Kaunas", "Klaipeda", "Siauliai"],
        "mobile_prefixes": ["60", "61", "62", "63", "64", "65", "67", "68", "69"],
        "national_length": 8,
    },
    "LU": {
        "name": "Luxembourg", "dial_code": "+352",
        "cities": ["Luxembourg", "Esch-sur-Alzette", "Differdange", "Dudelange"],
        "mobile_prefixes": ["6", "7", "8"],
        "national_length": 9,
    },
    "MT": {
        "name": "Malta", "dial_code": "+356",
        "cities": ["Valletta", "Birkirkara", "Mosta", "Sliema"],
        "mobile_prefixes": ["77", "79", "96", "98", "99"],
        "national_length": 8,
    },
    "NL": {
        "name": "Netherlands", "dial_code": "+31",
        "cities": ["Amsterdam", "Rotterdam", "The Hague", "Utrecht"],
        "mobile_prefixes": ["6"],
        "national_length": 9,
    },
    "PT": {
        "name": "Portugal", "dial_code": "+351",
        "cities": ["Lisbon", "Porto", "Braga", "Coimbra"],
        "mobile_prefixes": ["81", "82", "83", "91", "92", "93", "96"],
        "national_length": 9,
    },
    "SK": {
        "name": "Slovakia", "dial_code": "+421",
        "cities": ["Bratislava", "Kosice", "Presov", "Nitra"],
        "mobile_prefixes": ["90", "91", "92", "94", "95", "99"],
        "national_length": 9,
    },
    "SI": {
        "name": "Slovenia", "dial_code": "+386",
        "cities": ["Ljubljana", "Maribor", "Celje", "Kranj"],
        "mobile_prefixes": ["30", "31", "40", "41", "51", "64", "68", "69", "70", "71", "72"],
        "national_length": 8,
    },
}

generated_numbers: Dict[str, dict] = {}
sequential_counters: Dict[str, int] = defaultdict(int)
request_log: Dict[str, List[float]] = {}
message_templates: Dict[str, dict] = {}
blacklist_store: Dict[str, dict] = {}
campaign_logs_store: Dict[str, dict] = {}
message_queue_store: Dict[str, dict] = {}


# ------------------------- Database -------------------------

def table_columns(conn, table: str) -> set:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
        (table,),
    ).fetchall()
    return {r["column_name"] for r in rows}


def init_db():
    with db_pool.connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS numbers (
                id TEXT PRIMARY KEY,
                number TEXT NOT NULL,
                country_code TEXT NOT NULL,
                city TEXT,
                pattern TEXT,
                status TEXT DEFAULT 'pending',
                whatsapp_exists INTEGER,
                test_message TEXT,
                tested_at DOUBLE PRECISION,
                last_message TEXT,
                message_status TEXT,
                message_sent_at DOUBLE PRECISION,
                whatsapp_message_id TEXT,
                sent_real INTEGER DEFAULT 0,
                created_at DOUBLE PRECISION NOT NULL,
                campaign_id TEXT,
                tags TEXT DEFAULT '[]',
                quality_score DOUBLE PRECISION DEFAULT 0
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_numbers_country ON numbers(country_code)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_numbers_status ON numbers(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_numbers_number ON numbers(number)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS campaigns (
                id TEXT PRIMARY KEY,
                name TEXT,
                country_code TEXT,
                city TEXT,
                plan_count INTEGER,
                message TEXT,
                send_after_test INTEGER DEFAULT 0,
                delay_ms INTEGER DEFAULT 0,
                status TEXT DEFAULT 'created',
                generated INTEGER DEFAULT 0,
                tested INTEGER DEFAULT 0,
                exists_count INTEGER DEFAULT 0,
                not_exists_count INTEGER DEFAULT 0,
                sent INTEGER DEFAULT 0,
                failed INTEGER DEFAULT 0,
                created_at DOUBLE PRECISION,
                started_at DOUBLE PRECISION,
                finished_at DOUBLE PRECISION,
                scheduled_at DOUBLE PRECISION
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS message_templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                variables TEXT DEFAULT '[]',
                created_at DOUBLE PRECISION NOT NULL,
                updated_at DOUBLE PRECISION NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS blacklist (
                id TEXT PRIMARY KEY,
                number TEXT NOT NULL UNIQUE,
                reason TEXT,
                added_at DOUBLE PRECISION NOT NULL,
                added_by TEXT DEFAULT 'user'
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_blacklist_number ON blacklist(number)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS campaign_logs (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                action TEXT NOT NULL,
                number TEXT,
                details TEXT,
                timestamp DOUBLE PRECISION NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_campaign ON campaign_logs(campaign_id)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS message_queue (
                id TEXT PRIMARY KEY,
                number TEXT NOT NULL,
                message TEXT NOT NULL,
                campaign_id TEXT,
                priority INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                attempts INTEGER DEFAULT 0,
                max_attempts INTEGER DEFAULT 3,
                last_error TEXT,
                created_at DOUBLE PRECISION NOT NULL,
                scheduled_at DOUBLE PRECISION,
                sent_at DOUBLE PRECISION
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_queue_status ON message_queue(status)")

        existing_nums = table_columns(conn, "numbers")
        for col, coltype in [
            ("whatsapp_message_id", "TEXT"),
            ("sent_real", "INTEGER DEFAULT 0"),
            ("campaign_id", "TEXT"),
            ("tags", "TEXT DEFAULT '[]'"),
            ("quality_score", "DOUBLE PRECISION DEFAULT 0"),
        ]:
            if col not in existing_nums:
                conn.execute(f"ALTER TABLE numbers ADD COLUMN {col} {coltype}")

        existing_camp = table_columns(conn, "campaigns")
        if "scheduled_at" not in existing_camp:
            conn.execute("ALTER TABLE campaigns ADD COLUMN scheduled_at DOUBLE PRECISION")
        if "not_exists_count" not in existing_camp:
            conn.execute("ALTER TABLE campaigns ADD COLUMN not_exists_count INTEGER DEFAULT 0")

        conn.commit()


def load_numbers() -> Dict[str, dict]:
    with db_pool.connection() as conn:
        rows = conn.execute("SELECT * FROM numbers").fetchall()
    result = {}
    for row in rows:
        data = dict(row)
        num_id = data.pop("id")
        if data.get("whatsapp_exists") is not None:
            data["whatsapp_exists"] = bool(data["whatsapp_exists"])
        tags_raw = data.pop("tags", "[]")
        try:
            data["tags"] = json.loads(tags_raw) if tags_raw else []
        except Exception:
            data["tags"] = []
        result[num_id] = data
    return result


def save_number(num_id: str, data: dict):
    tags_json = json.dumps(data.get("tags", []))
    with db_pool.connection() as conn:
        conn.execute(
            """INSERT INTO numbers
               (id, number, country_code, city, pattern, status, whatsapp_exists,
                test_message, tested_at, last_message, message_status, message_sent_at,
                whatsapp_message_id, sent_real, created_at, campaign_id, tags, quality_score)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (id) DO UPDATE SET
                 number=EXCLUDED.number, country_code=EXCLUDED.country_code,
                 city=EXCLUDED.city, pattern=EXCLUDED.pattern, status=EXCLUDED.status,
                 whatsapp_exists=EXCLUDED.whatsapp_exists, test_message=EXCLUDED.test_message,
                 tested_at=EXCLUDED.tested_at, last_message=EXCLUDED.last_message,
                 message_status=EXCLUDED.message_status,
                 message_sent_at=EXCLUDED.message_sent_at,
                 whatsapp_message_id=EXCLUDED.whatsapp_message_id,
                 sent_real=EXCLUDED.sent_real, created_at=EXCLUDED.created_at,
                 campaign_id=EXCLUDED.campaign_id, tags=EXCLUDED.tags,
                 quality_score=EXCLUDED.quality_score""",
            (
                num_id, data.get("number"), data.get("country_code"), data.get("city"),
                data.get("pattern"), data.get("status", "pending"),
                1 if data.get("whatsapp_exists") else 0,
                data.get("test_message"), data.get("tested_at"), data.get("last_message"),
                data.get("message_status"), data.get("message_sent_at"),
                data.get("whatsapp_message_id"), 1 if data.get("sent_real") else 0,
                data.get("created_at", time.time()), data.get("campaign_id"),
                tags_json, data.get("quality_score", 0),
            ),
        )
        conn.commit()


# ------------------------- Campaign storage -------------------------

campaigns: Dict[str, dict] = {}
campaign_runners: Dict[str, bool] = {}


def save_campaign(camp: dict):
    with db_pool.connection() as conn:
        conn.execute(
            """INSERT INTO campaigns
               (id, name, country_code, city, plan_count, message, send_after_test,
                delay_ms, status, generated, tested, exists_count, not_exists_count, sent, failed,
                created_at, started_at, finished_at, scheduled_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (id) DO UPDATE SET
                 name=EXCLUDED.name, country_code=EXCLUDED.country_code,
                 city=EXCLUDED.city, plan_count=EXCLUDED.plan_count,
                 message=EXCLUDED.message, send_after_test=EXCLUDED.send_after_test,
                 delay_ms=EXCLUDED.delay_ms, status=EXCLUDED.status,
                 generated=EXCLUDED.generated, tested=EXCLUDED.tested,
                 exists_count=EXCLUDED.exists_count, not_exists_count=EXCLUDED.not_exists_count,
                 sent=EXCLUDED.sent, failed=EXCLUDED.failed,
                 created_at=EXCLUDED.created_at, started_at=EXCLUDED.started_at,
                 finished_at=EXCLUDED.finished_at, scheduled_at=EXCLUDED.scheduled_at""",
            (
                camp["id"], camp.get("name"), camp.get("country_code"), camp.get("city"),
                camp.get("plan_count"), camp.get("message"),
                1 if camp.get("send_after_test") else 0,
                camp.get("delay_ms", 0), camp.get("status", "created"),
                camp.get("generated", 0), camp.get("tested", 0),
                camp.get("exists_count", 0), camp.get("not_exists_count", 0),
                camp.get("sent", 0), camp.get("failed", 0),
                camp.get("created_at"), camp.get("started_at"), camp.get("finished_at"),
                camp.get("scheduled_at"),
            ),
        )
        conn.commit()


def load_campaigns():
    with db_pool.connection() as conn:
        rows = conn.execute("SELECT * FROM campaigns ORDER BY created_at DESC").fetchall()
    for row in rows:
        camp = dict(row)
        camp["send_after_test"] = bool(camp["send_after_test"])
        camp.setdefault("not_exists_count", 0)
        campaigns[camp["id"]] = camp


# ------------------------- Message Templates -------------------------

def load_templates():
    with db_pool.connection() as conn:
        rows = conn.execute("SELECT * FROM message_templates ORDER BY created_at DESC").fetchall()
    for row in rows:
        t = dict(row)
        try:
            t["variables"] = json.loads(t.get("variables", "[]"))
        except Exception:
            t["variables"] = []
        message_templates[t["id"]] = t


def save_template(template: dict):
    with db_pool.connection() as conn:
        conn.execute(
            """INSERT INTO message_templates
               (id, name, content, category, variables, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (id) DO UPDATE SET
                 name=EXCLUDED.name, content=EXCLUDED.content,
                 category=EXCLUDED.category, variables=EXCLUDED.variables,
                 created_at=EXCLUDED.created_at, updated_at=EXCLUDED.updated_at""",
            (
                template["id"], template["name"], template["content"],
                template.get("category", "general"),
                json.dumps(template.get("variables", [])),
                template["created_at"], template["updated_at"],
            ),
        )
        conn.commit()


def delete_template(template_id: str):
    with db_pool.connection() as conn:
        conn.execute("DELETE FROM message_templates WHERE id = %s", (template_id,))
        conn.commit()
    message_templates.pop(template_id, None)


def apply_template(content: str, variables: dict) -> str:
    result = content
    for key, value in variables.items():
        result = result.replace("{" + key + "}", str(value))
    return result


# ------------------------- Blacklist -------------------------

def load_blacklist_db():
    with db_pool.connection() as conn:
        rows = conn.execute("SELECT * FROM blacklist ORDER BY added_at DESC").fetchall()
    for row in rows:
        b = dict(row)
        blacklist_store[b["number"]] = b


def save_blacklist_entry(entry: dict):
    with db_pool.connection() as conn:
        conn.execute(
            """INSERT INTO blacklist (id, number, reason, added_at, added_by)
               VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (number) DO UPDATE SET
                 reason=EXCLUDED.reason, added_at=EXCLUDED.added_at, added_by=EXCLUDED.added_by""",
            (entry["id"], entry["number"], entry.get("reason"), entry["added_at"], entry.get("added_by", "user")),
        )
        conn.commit()


def is_blacklisted(phone_number: str) -> bool:
    return phone_number in blacklist_store


# ------------------------- Campaign Logs -------------------------

def add_campaign_log(campaign_id: str, action: str, number: str = None, details: str = None):
    ts = time.time()
    with db_pool.connection() as conn:
        conn.execute(
            "INSERT INTO campaign_logs (campaign_id, action, number, details, timestamp) VALUES (%s,%s,%s,%s,%s)",
            (campaign_id, action, number, details, ts),
        )
        conn.commit()
    return {"campaign_id": campaign_id, "action": action, "number": number, "details": details, "timestamp": ts}


def get_campaign_logs(campaign_id: str, limit: int = 100) -> list:
    with db_pool.connection() as conn:
        rows = conn.execute(
            "SELECT * FROM campaign_logs WHERE campaign_id = %s ORDER BY timestamp DESC LIMIT %s",
            (campaign_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


# ------------------------- Message Queue -------------------------

def enqueue_message(number: str, message: str, campaign_id: str = None, priority: int = 0, scheduled_at: float = None):
    msg_id = f"MSG_{int(time.time() * 1000)}_{random.randint(100, 999)}"
    entry = {
        "id": msg_id, "number": number, "message": message, "campaign_id": campaign_id,
        "priority": priority, "status": "pending", "attempts": 0, "max_attempts": 3,
        "last_error": None, "created_at": time.time(), "scheduled_at": scheduled_at, "sent_at": None,
    }
    message_queue_store[msg_id] = entry
    with db_pool.connection() as conn:
        conn.execute(
            """INSERT INTO message_queue
               (id, number, message, campaign_id, priority, status, attempts, max_attempts,
                last_error, created_at, scheduled_at, sent_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (msg_id, number, message, campaign_id, priority, "pending", 0, 3, None, time.time(), scheduled_at, None),
        )
        conn.commit()
    return msg_id


def load_queue():
    with db_pool.connection() as conn:
        rows = conn.execute("SELECT * FROM message_queue").fetchall()
    for row in rows:
        message_queue_store[row["id"]] = dict(row)


async def process_queue():
    pending = [m for m in message_queue_store.values() if m["status"] == "pending"]
    pending.sort(key=lambda m: (m.get("scheduled_at") or 0, -m.get("priority", 0)))
    now = time.time()
    for entry in pending:
        if entry.get("scheduled_at") and entry["scheduled_at"] > now:
            continue
        ok, result = await send_message_via_bridge(entry["number"], entry["message"])
        with db_pool.connection() as conn:
            if ok:
                entry["status"] = "sent"
                entry["sent_at"] = time.time()
                conn.execute(
                    "UPDATE message_queue SET status=%s, sent_at=%s, last_error=NULL WHERE id=%s",
                    ("sent", entry["sent_at"], entry["id"]),
                )
            else:
                entry["attempts"] += 1
                entry["last_error"] = result
                if entry["attempts"] >= entry.get("max_attempts", 3):
                    entry["status"] = "failed"
                    conn.execute(
                        "UPDATE message_queue SET status=%s, attempts=%s, last_error=%s WHERE id=%s",
                        ("failed", entry["attempts"], result, entry["id"]),
                    )
                else:
                    conn.execute(
                        "UPDATE message_queue SET attempts=%s, last_error=%s WHERE id=%s",
                        (entry["attempts"], result, entry["id"]),
                    )
            conn.commit()


def get_queue_status() -> dict:
    pending = sum(1 for m in message_queue_store.values() if m["status"] == "pending")
    sent = sum(1 for m in message_queue_store.values() if m["status"] == "sent")
    failed = sum(1 for m in message_queue_store.values() if m["status"] == "failed")
    return {"pending": pending, "sent": sent, "failed": failed, "total": pending + sent + failed}


# ------------------------- Utility -------------------------

def compute_quality_score(whatsapp_exists: bool, is_valid: bool, has_area_code: bool) -> float:
    score = 0.0
    if is_valid:
        score += 40.0
    if whatsapp_exists:
        score += 40.0
    if has_area_code:
        score += 20.0
    return round(score, 1)


def parse_import_number(raw: str) -> Optional[str]:
    digits = ''.join(ch for ch in raw if ch.isdigit())
    if not digits:
        return None
    if len(digits) <= 9 or len(digits) > 15:
        return None
    try:
        pn = phonenumbers.parse('+' + digits, None)
        if phonenumbers.is_valid_number(pn):
            return phonenumbers.format_number(pn, phonenumbers.PhoneNumberFormat.E164)
        pn2 = phonenumbers.parse(digits, "FR")
        if phonenumbers.is_valid_number(pn2):
            return phonenumbers.format_number(pn2, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        return None
    return None


# ------------------------- Utilities -------------------------

def rate_limit(ip: str):
    now = time.time()
    window = now - 60
    timestamps = [t for t in request_log.get(ip, []) if t > window]
    if len(timestamps) >= MAX_REQUESTS_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Trop de requetes. Veuillez patienter une minute.")
    timestamps.append(now)
    request_log[ip] = timestamps


def generate_realistic_number(country_code: str, city: str = None, pattern: str = "random") -> str:
    country = COUNTRY_CODES[country_code]
    dial_code = country["dial_code"]
    target_len = country["national_length"]

    prefixes = country["mobile_prefixes"]
    if city and country.get("city_prefixes") and city in country["city_prefixes"]:
        prefixes = country["city_prefixes"][city]

    best = None
    for attempt in range(40):
        prefix = random.choice(prefixes)
        remaining = target_len - len(prefix)
        if remaining <= 0:
            continue

        if pattern == "sequential":
            sequential_counters[country_code] += 1
            suffix = str(sequential_counters[country_code]).zfill(remaining)[-remaining:]
        else:
            suffix = ''.join(random.choices(string.digits, k=remaining))

        full_number = f"{dial_code}{prefix}{suffix}"
        try:
            parsed = phonenumbers.parse(full_number, None)
            if phonenumbers.is_valid_number(parsed):
                return full_number
            if best is None and phonenumbers.is_possible_number(parsed):
                best = full_number
        except Exception:
            continue

    return best or f"{dial_code}{prefix}{suffix}"


async def get_bridge_status() -> dict:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{BRIDGE_URL}/status")
            if response.status_code == 200:
                status = response.json()
                status["reachable"] = True
                return status
    except Exception:
        pass
    return {"reachable": False, "connected": False, "hasQr": False, "error": "Bridge non accessible"}


async def test_whatsapp_exists(phone_number: str, bridge_only: bool = False) -> tuple:
    digits = phone_number.replace("+", "").replace(" ", "")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(f"{BRIDGE_URL}/check", json={"phone": digits})
        if response.status_code == 409:
            return False, "Bridge WhatsApp non connecte - scannez le QR code."
        if response.status_code == 200:
            data = response.json()
            if data.get("exists"):
                return True, f"Numero verifie via WhatsApp (ID: {data.get('wa_id')})"
            return False, "Ce numero n'est pas sur WhatsApp (verification reelle via Baileys)."
        return False, f"Erreur bridge: {response.text[:100]}"
    except Exception:
        pass

    if not bridge_only:
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                response = await client.get(f"https://wa.me/{digits}")
            if response.status_code == 200:
                text = response.text[:2000].lower()
                if "invalid" in text or "not found" in text or "incorrect" in text:
                    return False, "Aucun compte WhatsApp trouve pour ce numero (reponse wa.me)."
                if "whatsapp" in text and "chat" in text:
                    return True, "Ce numero a une page WhatsApp valide (reponse wa.me)."
        except Exception:
            pass

    if SIMULATE_WHATSAPP:
        return _simulateWhatsAppCheck(phone_number)

    return False, "Verification non concluante - connectez le bridge Baileys."


async def send_message_via_bridge(phone_number: str, message: str) -> tuple:
    digits = phone_number.replace("+", "").replace(" ", "")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(f"{BRIDGE_URL}/send", json={"phone": digits, "message": message})
        if response.status_code == 200:
            data = response.json()
            return True, (data.get("id") or "sent")
        if response.status_code == 409:
            return False, "Bridge non connecte"
        return False, f"Erreur bridge: {response.text[:100]}"
    except Exception as e:
        return False, f"Bridge inaccessible: {str(e)}"


def _simulateWhatsAppCheck(phone_number: str) -> tuple:
    hash_val = int(hashlib.md5(phone_number.encode()).hexdigest(), 16)
    exists = (hash_val % 100) < 15
    if exists:
        return True, "[Demo] Numero existant simule sur WhatsApp."
    else:
        return False, "[Demo] Numero inexistant simule sur WhatsApp."


def format_e164(num: str) -> str:
    try:
        pn = phonenumbers.parse(num, None)
        return phonenumbers.format_number(pn, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    except Exception:
        return num


# ------------------------- Models -------------------------

class GenerateNumberRequest(BaseModel):
    country_code: str = Field(..., description="ISO country code (e.g., US, GB, FR)")
    city: Optional[str] = Field(None, description="Specific city")
    pattern: Optional[str] = Field(None, description="Number pattern (random or sequential)")


class GenerateBatchRequest(BaseModel):
    country_code: str = Field(..., description="ISO country code (e.g., US, GB, FR)")
    city: Optional[str] = Field(None, description="Specific city")
    count: int = Field(5, ge=1, le=1000, description="Number of numbers to generate")
    pattern: Optional[str] = Field(None, description="Number pattern (random or sequential)")


class CampaignCreate(BaseModel):
    name: str = Field(..., max_length=120)
    country_code: str
    city: Optional[str] = None
    count: int = Field(10, ge=1, le=10000)
    message: Optional[str] = None
    template_id: Optional[str] = None
    send_after_test: bool = False
    delay_ms: int = Field(0, ge=0, le=60000, description="Delay between sends (anti-ban)")
    scheduled_at: Optional[float] = Field(None, description="Unix timestamp to start the campaign")


class BulkImportRequest(BaseModel):
    numbers: List[str] = Field(..., description="Raw phone numbers (E.164 or national)")
    auto_test: bool = Field(False, description="Test each imported number against WhatsApp")


class TemplateCreate(BaseModel):
    name: str = Field(..., max_length=120)
    content: str = Field(..., min_length=1, max_length=2000)
    category: str = Field("general", max_length=50)


class BlacklistAddRequest(BaseModel):
    numbers: List[str] = Field(..., description="Phone numbers to blacklist")
    reason: Optional[str] = Field(None, max_length=200)


class NumberTagRequest(BaseModel):
    tags: List[str] = Field(..., description="Tags to add/remove")
    action: str = Field("add", description="'add' or 'remove'")


async def run_campaign_bg(campaign_id: str):
    camp = campaigns.get(campaign_id)
    if not camp:
        return
    if camp["country_code"] not in COUNTRY_CODES:
        camp["status"] = "error"
        save_campaign(camp)
        return

    campaign_runners[campaign_id] = True
    camp["status"] = "running"
    camp["started_at"] = time.time()
    save_campaign(camp)
    add_campaign_log(campaign_id, "started", details=f"Campagne lancee: {camp.get('name', 'Sans nom')}")

    country_code = camp["country_code"]
    country = COUNTRY_CODES[country_code]
    selected_city = camp["city"] if camp["city"] in country["cities"] else country["cities"][0]
    delay = max(0, camp.get("delay_ms", 0)) / 1000.0

    try:
        for _ in range(camp["plan_count"]):
            if not campaign_runners.get(campaign_id):
                camp["status"] = "stopped"
                add_campaign_log(campaign_id, "stopped", details="Campagne arretee par l'utilisateur")
                break

            num = generate_realistic_number(country_code, selected_city, "random")
            camp["generated"] += 1

            if is_blacklisted(num):
                add_campaign_log(campaign_id, "skipped_blacklist", number=num, details="Numero en liste noire")
                camp["failed"] += 1
                save_campaign(camp)
                continue

            existing_nums = [n.get("number") for n in generated_numbers.values() if n.get("sent_real")]
            if num in existing_nums:
                add_campaign_log(campaign_id, "skipped_duplicate", number=num, details="Deja envoye")
                camp["failed"] += 1
                save_campaign(camp)
                continue

            exists, msg = await test_whatsapp_exists(num, bridge_only=True)
            camp["tested"] += 1

            num_id = f"{country_code}_{selected_city}_{num.replace(country['dial_code'], '')}"
            is_valid = phonenumbers.is_valid_number(phonenumbers.parse(num, None)) if num.startswith("+") else False
            has_area = bool(country.get("city_prefixes") and selected_city in country.get("city_prefixes", {}))
            quality = compute_quality_score(exists, is_valid, has_area)

            data = {
                "number": num,
                "formatted": format_e164(num),
                "country_code": country_code,
                "city": selected_city,
                "dial_code": country["dial_code"],
                "pattern": "random",
                "status": "tested" if exists else "not_exists",
                "whatsapp_exists": exists,
                "test_message": msg,
                "tested_at": time.time(),
                "created_at": time.time(),
                "campaign_id": campaign_id,
                "quality_score": quality,
                "tags": [],
            }
            generated_numbers[num_id] = data
            save_number(num_id, data)

            if exists:
                camp["exists_count"] += 1
                add_campaign_log(campaign_id, "whatsapp_found", number=num, details=msg)
                if camp.get("send_after_test") and camp.get("message"):
                    msg_text = apply_template(camp["message"], {
                        "numero": num, "pays": country["name"], "ville": selected_city,
                    })
                    ok, res = await send_message_via_bridge(num, msg_text)
                    if ok:
                        camp["sent"] += 1
                        data["last_message"] = msg_text
                        data["message_status"] = "campaign_sent"
                        data["message_sent_at"] = time.time()
                        data["sent_real"] = True
                        add_campaign_log(campaign_id, "message_sent", number=num, details=f"Envoye: {msg_text[:100]}")
                    else:
                        camp["failed"] += 1
                        data["message_status"] = "campaign_send_failed"
                        data["last_message"] = f"Echec envoi: {res}"
                        add_campaign_log(campaign_id, "message_failed", number=num, details=res)
                    save_number(num_id, data)
                    if delay:
                        await asyncio.sleep(delay)
            else:
                camp["not_exists_count"] = camp.get("not_exists_count", 0) + 1

            save_campaign(camp)
            await asyncio.sleep(0)

        if camp["status"] != "stopped":
            camp["status"] = "done"
            add_campaign_log(campaign_id, "completed", details=f"Terminee: {camp['sent']} envoyes, {camp['exists_count']} existants")
    except Exception as e:
        camp["status"] = "error"
        camp["error"] = str(e)
        add_campaign_log(campaign_id, "error", details=str(e))
    finally:
        campaign_runners.pop(campaign_id, None)
        camp["finished_at"] = time.time()
        save_campaign(camp)


# ------------------------- Scheduled campaigns -------------------------

async def check_scheduled_campaigns():
    while True:
        now = time.time()
        for cid, camp in list(campaigns.items()):
            if camp.get("status") in ("created", "scheduled") and camp.get("scheduled_at") and camp["scheduled_at"] <= now:
                asyncio.create_task(run_campaign_bg(cid))
        await asyncio.sleep(10)


# ------------------------- Routes -------------------------


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {
        "country_codes": COUNTRY_CODES
    })


@app.get("/api/cities")
async def get_cities(country: str):
    if country not in COUNTRY_CODES:
        raise HTTPException(status_code=400, detail="Invalid country code")
    return {"country_code": country, "cities": COUNTRY_CODES[country]["cities"]}


@app.post("/api/generate-number")
async def generate_number(request: GenerateNumberRequest, req: Request):
    rate_limit(req.client.host if req.client else "unknown")
    if request.country_code not in COUNTRY_CODES:
        raise HTTPException(status_code=400, detail="Invalid country code")

    country = COUNTRY_CODES[request.country_code]
    selected_city = request.city if request.city in country["cities"] else country["cities"][0]
    pattern = request.pattern or "random"
    full_number = generate_realistic_number(request.country_code, selected_city, pattern)

    formatted = full_number
    try:
        parsed = phonenumbers.parse(full_number, None)
        formatted = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    except Exception:
        pass

    is_valid = phonenumbers.is_valid_number(phonenumbers.parse(full_number, None)) if full_number.startswith("+") else False
    has_area = bool(country.get("city_prefixes") and selected_city in country.get("city_prefixes", {}))

    number_suffix = full_number.replace(country["dial_code"], "")
    number_id = f"{request.country_code}_{selected_city}_{number_suffix}"
    data = {
        "number": full_number,
        "formatted": formatted,
        "country_code": request.country_code,
        "city": selected_city,
        "dial_code": country["dial_code"],
        "pattern": pattern,
        "status": "pending",
        "created_at": time.time(),
        "quality_score": compute_quality_score(False, is_valid, has_area),
        "tags": [],
    }
    generated_numbers[number_id] = data
    save_number(number_id, data)

    return {
        "success": True, "number": full_number, "formatted": formatted,
        "city": selected_city, "country": country["name"],
        "dial_code": country["dial_code"], "number_id": number_id,
        "quality_score": data["quality_score"],
    }


@app.post("/api/test-whatsapp/{number_id}")
async def test_whatsapp(number_id: str):
    if number_id not in generated_numbers:
        raise HTTPException(status_code=404, detail="Number not found")

    number_data = generated_numbers[number_id]
    full_number = number_data["number"]

    exists, message = await test_whatsapp_exists(full_number)

    is_valid = phonenumbers.is_valid_number(phonenumbers.parse(full_number, None)) if full_number.startswith("+") else False
    cc = number_data.get("country_code", "")
    country = COUNTRY_CODES.get(cc, {})
    city = number_data.get("city", "")
    has_area = bool(country.get("city_prefixes") and city in country.get("city_prefixes", {}))
    quality = compute_quality_score(exists, is_valid, has_area)

    number_data["status"] = "tested" if exists else "not_exists"
    number_data["whatsapp_exists"] = exists
    number_data["test_message"] = message
    number_data["tested_at"] = time.time()
    number_data["quality_score"] = quality
    save_number(number_id, number_data)

    return {
        "number": full_number, "exists": exists, "message": message,
        "tested_at": number_data["tested_at"], "quality_score": quality,
    }


@app.post("/api/send-message/{number_id}")
async def send_message(number_id: str, request: Request):
    if number_id not in generated_numbers:
        raise HTTPException(status_code=404, detail="Number not found")

    number_data = generated_numbers[number_id]
    full_number = number_data["number"]

    try:
        body = await request.json()
        message_text = body.get("message", "Test de numero WhatsApp")
    except Exception:
        form_data = await request.form()
        message_text = form_data.get("message", "Test de numero WhatsApp")

    if is_blacklisted(full_number):
        raise HTTPException(status_code=403, detail="Ce numero est en liste noire.")

    sent_real = False
    whatsapp_message_id = None
    exists = number_data.get("whatsapp_exists", False)
    if exists:
        ok, result = await send_message_via_bridge(full_number, message_text)
        if ok:
            sent_real = True
            whatsapp_message_id = result
            result_message = f"Message reellement envoye via WhatsApp\n\nMessage: {message_text}"
            status = "exists_message_sent"
        else:
            result_message = f"Numero existant, envoi non realise ({result})\n\nMessage: {message_text}"
            status = "exists_message_simulated"
    else:
        result_message = f"Ce numero n'existe pas sur WhatsApp\n\nMessage: {message_text}"
        status = "not_exists_message_sent"

    number_data["last_message"] = result_message
    number_data["message_status"] = status
    number_data["message_sent_at"] = time.time()
    number_data["whatsapp_message_id"] = whatsapp_message_id
    number_data["sent_real"] = sent_real
    save_number(number_id, number_data)

    return {
        "success": True, "number": full_number, "message_sent": result_message,
        "status": status, "number_exists": exists, "sent_real": sent_real,
        "whatsapp_message_id": whatsapp_message_id,
    }


@app.get("/api/wa/status")
async def wa_status():
    status = await get_bridge_status()
    if status.get("hasQr"):
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{BRIDGE_URL}/qr")
                if response.status_code == 200:
                    status["qr"] = response.json().get("qr")
        except Exception:
            pass
    return status


@app.get("/api/numbers")
async def list_numbers(status: Optional[str] = None, country: Optional[str] = None, search: Optional[str] = None, tag: Optional[str] = None):
    items = list(generated_numbers.values())
    if status and status != "all":
        items = [n for n in items if n.get("status") == status]
    if country and country != "all":
        items = [n for n in items if n.get("country_code") == country]
    if search:
        q = search.strip().lower()
        items = [n for n in items if q in n.get("number", "").lower() or q in n.get("country_code", "").lower() or q in (n.get("city") or "").lower()]
    if tag:
        items = [n for n in items if tag in n.get("tags", [])]

    items.sort(key=lambda n: n.get("created_at", 0), reverse=True)
    by_status = defaultdict(int)
    for n in items:
        by_status[n.get("status", "pending")] += 1

    total_all = len(generated_numbers)
    return {
        "total": total_all, "count": len(items), "by_status": dict(by_status), "numbers": items,
    }


@app.post("/api/generate-batch")
async def generate_batch(request: GenerateBatchRequest, req: Request):
    rate_limit(req.client.host if req.client else "unknown")
    if request.country_code not in COUNTRY_CODES:
        raise HTTPException(status_code=400, detail="Invalid country code")

    country = COUNTRY_CODES[request.country_code]
    selected_city = request.city if request.city in country["cities"] else country["cities"][0]
    pattern = request.pattern or "random"

    created = []
    for _ in range(request.count):
        num = generate_realistic_number(request.country_code, selected_city, pattern)
        num_id = f"{request.country_code}_{selected_city}_{num.replace(country['dial_code'], '')}"
        if num_id in generated_numbers:
            continue
        is_valid = phonenumbers.is_valid_number(phonenumbers.parse(num, None)) if num.startswith("+") else False
        has_area = bool(country.get("city_prefixes") and selected_city in country.get("city_prefixes", {}))
        data = {
            "number": num, "formatted": format_e164(num),
            "country_code": request.country_code, "city": selected_city,
            "dial_code": country["dial_code"], "pattern": pattern,
            "status": "pending", "created_at": time.time(),
            "quality_score": compute_quality_score(False, is_valid, has_area),
            "tags": [],
        }
        generated_numbers[num_id] = data
        save_number(num_id, data)
        created.append(data)

    return {
        "success": True, "count": len(created),
        "country_code": request.country_code, "country": country["name"],
        "city": selected_city,
        "numbers": [{"number": d["number"], "formatted": d["formatted"], "number_id": f"{request.country_code}_{selected_city}_{d['number'].replace(country['dial_code'], '')}", "quality_score": d.get("quality_score", 0)} for d in created],
    }


@app.post("/api/import")
async def import_numbers(request: BulkImportRequest):
    imported = []
    skipped = []
    errors = []
    blacklisted_count = 0
    for raw in request.numbers:
        raw = str(raw).strip()
        e164 = parse_import_number(raw)
        if not e164:
            errors.append(raw)
            continue
        if is_blacklisted(e164):
            blacklisted_count += 1
            continue
        try:
            pn = phonenumbers.parse(e164, None)
            region = phonenumbers.region_code_for_number(pn) or "UNK"
            num_id = f"IMP_{e164.replace('+', '')}"
            if num_id in generated_numbers:
                skipped.append(e164)
                continue
            data = {
                "number": e164,
                "formatted": phonenumbers.format_number(pn, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
                "country_code": region, "city": None,
                "dial_code": "+" + str(pn.country_code),
                "pattern": "import", "status": "pending", "created_at": time.time(),
                "quality_score": 0, "tags": [],
            }
            generated_numbers[num_id] = data
            save_number(num_id, data)
            imported.append(data)
        except Exception:
            errors.append(raw)

    if request.auto_test and imported:
        asyncio.create_task(_auto_test_numbers([d["number"] for d in imported]))

    return {
        "success": True, "imported": len(imported), "skipped": len(skipped),
        "invalid": len(errors), "blacklisted": blacklisted_count,
        "auto_test": request.auto_test, "invalid_numbers": errors[:20],
    }


async def _auto_test_numbers(numbers: List[str]):
    for num in numbers:
        exists, msg = await test_whatsapp_exists(num, bridge_only=True)
        num_id = f"IMP_{num.replace('+', '')}"
        data = generated_numbers.get(num_id)
        if not data:
            continue
        data["status"] = "tested" if exists else "not_exists"
        data["whatsapp_exists"] = exists
        data["test_message"] = msg
        data["tested_at"] = time.time()
        save_number(num_id, data)
        await asyncio.sleep(0)


@app.get("/api/export")
async def export_numbers(format: str = "csv", status: Optional[str] = None, search: Optional[str] = None):
    items = list(generated_numbers.values())
    if status and status != "all":
        items = [n for n in items if n.get("status") == status]
    if search:
        q = search.strip().lower()
        items = [n for n in items if q in n.get("number", "").lower()]

    if format == "json":
        payload = json.dumps(items, ensure_ascii=False, default=str)
        return Response(content=payload, media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="whatsapp_numbers.json"'})

    import csv
    import io
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "number", "formatted", "country", "city", "status", "whatsapp_exists",
                     "test_message", "tested_at", "message_status", "message_sent_at", "campaign_id", "quality_score", "tags"])
    for n in items:
        writer.writerow([
            n.get("id", ""), n.get("number", ""), n.get("formatted", ""),
            n.get("country_code", ""), n.get("city", "") or "",
            n.get("status", ""), "yes" if n.get("whatsapp_exists") else "no",
            (n.get("test_message") or "").replace("\n", " "),
            n.get("tested_at") or "", n.get("message_status") or "",
            n.get("message_sent_at") or "", n.get("campaign_id") or "",
            n.get("quality_score", 0), ",".join(n.get("tags", [])),
        ])
    csv_data = buf.getvalue()
    return Response(content=csv_data, media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="whatsapp_numbers.csv"'})


# ------------------------- Campaigns routes -------------------------

@app.get("/api/campaigns")
async def list_campaigns():
    items = list(campaigns.values())
    items.sort(key=lambda c: c.get("created_at", 0), reverse=True)
    return {"campaigns": items}


@app.post("/api/campaigns")
async def create_campaign(request: CampaignCreate):
    if request.country_code not in COUNTRY_CODES:
        raise HTTPException(status_code=400, detail="Invalid country code")
    country = COUNTRY_CODES[request.country_code]
    city = request.city if request.city in country["cities"] else country["cities"][0]

    msg = request.message
    if request.template_id and request.template_id in message_templates:
        msg = message_templates[request.template_id]["content"]

    campaign_id = f"CAMP_{int(time.time() * 1000)}_{random.randint(100, 999)}"
    camp = {
        "id": campaign_id, "name": request.name,
        "country_code": request.country_code, "city": city,
        "plan_count": request.count, "message": msg,
        "send_after_test": request.send_after_test, "delay_ms": request.delay_ms,
        "status": "scheduled" if request.scheduled_at else "created",
        "generated": 0, "tested": 0, "exists_count": 0, "not_exists_count": 0,
        "sent": 0, "failed": 0,
        "created_at": time.time(), "scheduled_at": request.scheduled_at,
    }
    campaigns[campaign_id] = camp
    save_campaign(camp)
    add_campaign_log(campaign_id, "created", details=f"Campagne creee: {request.name}")
    return {"success": True, "campaign": camp}


@app.post("/api/campaigns/{campaign_id}/start")
async def start_campaign(campaign_id: str):
    if campaign_id not in campaigns:
        raise HTTPException(status_code=404, detail="Campaign not found")
    camp = campaigns[campaign_id]
    if campaign_runners.get(campaign_id) or camp["status"] in ("running", "done"):
        raise HTTPException(status_code=400, detail=f"Campagne deja {camp['status']}")
    asyncio.create_task(run_campaign_bg(campaign_id))
    return {"success": True, "status": "starting"}


@app.post("/api/campaigns/{campaign_id}/stop")
async def stop_campaign(campaign_id: str):
    if campaign_id not in campaigns:
        raise HTTPException(status_code=404, detail="Campaign not found")
    campaign_runners[campaign_id] = False
    return {"success": True, "status": campaigns[campaign_id]["status"]}


@app.delete("/api/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: str):
    if campaign_id not in campaigns:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign_runners.get(campaign_id):
        raise HTTPException(status_code=400, detail="Arretez la campagne avant de la supprimer")
    camp = campaigns.pop(campaign_id)
    with db_pool.connection() as conn:
        conn.execute("DELETE FROM campaigns WHERE id = %s", (campaign_id,))
        conn.execute("DELETE FROM campaign_logs WHERE campaign_id = %s", (campaign_id,))
        conn.commit()
    return {"success": True, "deleted": camp["id"]}


@app.get("/api/campaigns/{campaign_id}/logs")
async def campaign_logs_route(campaign_id: str, limit: int = 50):
    if campaign_id not in campaigns:
        raise HTTPException(status_code=404, detail="Campaign not found")
    logs = get_campaign_logs(campaign_id, limit)
    return {"logs": logs, "count": len(logs)}


# ------------------------- Message Templates routes -------------------------

@app.get("/api/templates")
async def list_templates():
    items = list(message_templates.values())
    items.sort(key=lambda t: t.get("created_at", 0), reverse=True)
    return {"templates": items}


@app.post("/api/templates")
async def create_template(request: TemplateCreate):
    template_id = f"TPL_{int(time.time() * 1000)}_{random.randint(100, 999)}"
    variables = re.findall(r"\{(\w+)\}", request.content)
    now = time.time()
    template = {
        "id": template_id, "name": request.name, "content": request.content,
        "category": request.category, "variables": variables,
        "created_at": now, "updated_at": now,
    }
    message_templates[template_id] = template
    save_template(template)
    return {"success": True, "template": template}


@app.put("/api/templates/{template_id}")
async def update_template(template_id: str, request: TemplateCreate):
    if template_id not in message_templates:
        raise HTTPException(status_code=404, detail="Template not found")
    variables = re.findall(r"\{(\w+)\}", request.content)
    template = message_templates[template_id]
    template["name"] = request.name
    template["content"] = request.content
    template["category"] = request.category
    template["variables"] = variables
    template["updated_at"] = time.time()
    save_template(template)
    return {"success": True, "template": template}


@app.delete("/api/templates/{template_id}")
async def delete_template_route(template_id: str):
    if template_id not in message_templates:
        raise HTTPException(status_code=404, detail="Template not found")
    delete_template(template_id)
    return {"success": True, "deleted": template_id}


@app.post("/api/templates/{template_id}/preview")
async def preview_template(template_id: str, request: Request):
    if template_id not in message_templates:
        raise HTTPException(status_code=404, detail="Template not found")
    body = await request.json()
    variables = body.get("variables", {})
    template = message_templates[template_id]
    preview = apply_template(template["content"], variables)
    return {"preview": preview}


# ------------------------- Blacklist routes -------------------------

@app.get("/api/blacklist")
async def list_blacklist():
    items = list(blacklist_store.values())
    items.sort(key=lambda b: b.get("added_at", 0), reverse=True)
    return {"blacklist": items, "count": len(items)}


@app.post("/api/blacklist")
async def add_to_blacklist(request: BlacklistAddRequest):
    added = 0
    skipped = 0
    for raw in request.numbers:
        raw = str(raw).strip()
        digits = ''.join(ch for ch in raw if ch.isdigit())
        if len(digits) < 7:
            skipped += 1
            continue
        e164 = parse_import_number(raw) or f"+{digits}"
        if e164 in blacklist_store:
            skipped += 1
            continue
        entry_id = f"BLK_{int(time.time() * 1000)}_{random.randint(100, 999)}"
        entry = {
            "id": entry_id, "number": e164, "reason": request.reason,
            "added_at": time.time(), "added_by": "user",
        }
        blacklist_store[e164] = entry
        save_blacklist_entry(entry)
        added += 1
    return {"success": True, "added": added, "skipped": skipped}


@app.delete("/api/blacklist/{entry_id}")
async def remove_from_blacklist(entry_id: str):
    to_remove = None
    for num, entry in blacklist_store.items():
        if entry["id"] == entry_id:
            to_remove = num
            break
    if not to_remove:
        raise HTTPException(status_code=404, detail="Blacklist entry not found")
    blacklist_store.pop(to_remove)
    with db_pool.connection() as conn:
        conn.execute("DELETE FROM blacklist WHERE id = %s", (entry_id,))
        conn.commit()
    return {"success": True, "removed": to_remove}


# ------------------------- Number Tags routes -------------------------

@app.post("/api/numbers/{number_id}/tags")
async def update_number_tags(number_id: str, request: NumberTagRequest):
    if number_id not in generated_numbers:
        raise HTTPException(status_code=404, detail="Number not found")
    data = generated_numbers[number_id]
    tags = data.get("tags", [])
    if request.action == "add":
        for tag in request.tags:
            if tag not in tags:
                tags.append(tag)
    elif request.action == "remove":
        tags = [t for t in tags if t not in request.tags]
    data["tags"] = tags
    save_number(number_id, data)
    return {"success": True, "tags": tags}


# ------------------------- Queue routes -------------------------

@app.get("/api/queue")
async def get_queue():
    items = list(message_queue_store.values())
    items.sort(key=lambda m: m.get("created_at", 0), reverse=True)
    return {"queue": items[:100], "status": get_queue_status()}


@app.post("/api/queue/process")
async def process_queue_route():
    await process_queue()
    return {"success": True, "status": get_queue_status()}


# ------------------------- Stats routes -------------------------

@app.get("/api/stats")
async def get_stats():
    total = len(generated_numbers)
    tested = sum(1 for n in generated_numbers.values() if n.get("status") in ("tested", "not_exists"))
    exists = sum(1 for n in generated_numbers.values() if n.get("whatsapp_exists"))
    sent = sum(1 for n in generated_numbers.values() if n.get("sent_real"))

    now = time.time()
    day_ago = now - 86400
    week_ago = now - 604800
    today_total = sum(1 for n in generated_numbers.values() if n.get("created_at", 0) >= day_ago)
    today_exists = sum(1 for n in generated_numbers.values() if n.get("whatsapp_exists") and n.get("tested_at", 0) >= day_ago)
    week_total = sum(1 for n in generated_numbers.values() if n.get("created_at", 0) >= week_ago)

    avg_quality = 0
    quality_scores = [n.get("quality_score", 0) for n in generated_numbers.values() if n.get("quality_score", 0) > 0]
    if quality_scores:
        avg_quality = round(sum(quality_scores) / len(quality_scores), 1)

    by_country = {}
    for n in generated_numbers.values():
        code = n["country_code"]
        c = by_country.setdefault(code, {"country": COUNTRY_CODES.get(code, {}).get("name", code), "total": 0, "tested": 0, "exists": 0, "sent": 0})
        c["total"] += 1
        if n.get("status") in ("tested", "not_exists"):
            c["tested"] += 1
        if n.get("whatsapp_exists"):
            c["exists"] += 1
        if n.get("sent_real"):
            c["sent"] += 1

    by_status = defaultdict(int)
    for n in generated_numbers.values():
        by_status[n.get("status", "pending")] += 1

    by_city = defaultdict(lambda: {"total": 0, "exists": 0})
    for n in generated_numbers.values():
        city = n.get("city") or "Inconnu"
        by_city[city]["total"] += 1
        if n.get("whatsapp_exists"):
            by_city[city]["exists"] += 1

    top_cities = sorted(by_city.items(), key=lambda x: x[1]["total"], reverse=True)[:10]

    active_campaigns = sum(1 for c in campaigns.values() if c.get("status") == "running")

    return {
        "total": total, "tested": tested, "exists": exists, "sent": sent,
        "today_total": today_total, "today_exists": today_exists,
        "week_total": week_total,
        "success_rate": round((exists / tested * 100), 1) if tested else 0,
        "avg_quality_score": avg_quality,
        "by_status": dict(by_status), "by_country": by_country,
        "top_cities": [{"city": c, **d} for c, d in top_cities],
        "active_campaigns": active_campaigns,
        "templates_count": len(message_templates),
        "blacklist_count": len(blacklist_store),
        "queue_status": get_queue_status(),
        "uptime": round(time.time() - APP_STARTED, 1),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
