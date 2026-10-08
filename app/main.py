from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import random
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import jwt
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
import pandas as pd
import httpx
from functools import lru_cache
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

try:
    import mysql.connector
    from mysql.connector import Error as MySQLError
except ImportError:  # MySQL is optional when using SQLite mode
    mysql = None
    MySQLError = Exception
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

BASE = Path(__file__).resolve().parent.parent
load_dotenv(BASE / ".env")

def _configured_path(value: str, default: Path) -> Path:
    raw = (value or "").strip()
    if not raw:
        return default
    p = Path(raw).expanduser()
    return p if p.is_absolute() else BASE / p

# Database configuration. SQLite remains the zero-configuration fallback, while
# local MySQL can be enabled with CIVICCARE_DB_ENGINE=mysql and the MYSQL_* settings.
DB_ENGINE = os.getenv("CIVICCARE_DB_ENGINE", "sqlite").strip().lower()
DB = _configured_path(os.getenv("CIVICCARE_DB_PATH", ""), BASE / "data" / "civiccare.db")
MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "civiccare")
UPLOADS = _configured_path(os.getenv("CIVICCARE_UPLOADS_DIR", ""), BASE / "uploads")
STATIC = BASE / "app" / "static"
DATASET = BASE / "data" / "accident_risk_dataset.csv"
MODEL_SUMMARY = {}
RISK_MODEL = None
DB.parent.mkdir(parents=True, exist_ok=True)
UPLOADS.mkdir(parents=True, exist_ok=True)

JWT_SECRET = os.getenv("CIVICCARE_JWT_SECRET", "civiccare-local-development-secret")
TOMTOM_API_KEY = os.getenv("TOMTOM_API_KEY", "").strip()
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
NOMINATIM_URL = "https://nominatim.openstreetmap.org"
OVERPASS_URL = os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
HTTP_TIMEOUT = float(os.getenv("CIVICCARE_HTTP_TIMEOUT", "8"))
LIVE_CACHE_TTL = int(os.getenv("CIVICCARE_LIVE_CACHE_TTL", "60"))
_live_cache = {}
app = FastAPI(title="CivicCare AI", version="5.8.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOADS), name="uploads")

DEMO_USERS = [
    ("Citizen Demo", "citizen@civiccare.local", "Citizen@123", "citizen", "Citizen"),
    ("Roads Officer", "roads@civiccare.local", "Authority@123", "authority", "Roads"),
    ("Traffic Officer", "traffic@civiccare.local", "Authority@123", "authority", "Traffic"),
    ("Water Officer", "water@civiccare.local", "Authority@123", "authority", "Water"),
    ("Sanitation Officer", "sanitation@civiccare.local", "Authority@123", "authority", "Sanitation"),
    ("Electrical Officer", "electrical@civiccare.local", "Authority@123", "authority", "Electrical"),
    ("Disaster Management Officer", "disaster@civiccare.local", "Authority@123", "authority", "Disaster Management"),
    ("Emergency Officer", "emergency@civiccare.local", "Authority@123", "authority", "Emergency"),
    ("General Services Officer", "general@civiccare.local", "Authority@123", "authority", "General Services"),
    ("Admin", "admin@civiccare.local", "Admin@123", "admin", "Administration"),
]

RULES = {
    "pothole": ("Pothole", "Roads", 0.78), "road": ("Road Damage", "Roads", 0.68),
    "garbage": ("Garbage", "Sanitation", 0.65), "waste": ("Waste", "Sanitation", 0.64),
    "streetlight": ("Streetlight", "Electrical", 0.62), "light": ("Streetlight", "Electrical", 0.58),
    "traffic": ("Traffic", "Traffic", 0.72), "accident": ("Accident", "Traffic", 0.94),
    "flood": ("Flood", "Disaster Management", 0.91), "water": ("Water Supply", "Water", 0.77),
    "drain": ("Drainage", "Disaster Management", 0.82), "landslide": ("Landslide", "Disaster Management", 0.97),
    "fire": ("Fire", "Emergency", 0.99), "fallen tree": ("Fallen Tree", "Disaster Management", 0.88),
    "sewage": ("Sewage", "Water", 0.80), "injury": ("Accident", "Traffic", 0.92),
}
HIGH_RISK_WORDS = {"fire", "accident", "injury", "flood", "landslide", "collapse", "electrical", "exposed wire", "dangerous"}
MEDIUM_RISK_WORDS = {"blocked", "overflow", "leak", "dark", "pothole", "garbage", "sewage", "traffic"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DBRow(dict):
    """Small row adapter so existing SQLite-style dict/index access works on MySQL."""
    def __init__(self, columns, values):
        super().__init__(zip(columns, values))
        self._values = tuple(values)
    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


class MySQLCursorAdapter:
    def __init__(self, cursor):
        self._cursor = cursor
        self.lastrowid = None
    def _adapt(self, sql):
        sql = sql.replace("printf('%02d',hour)", "LPAD(CAST(hour AS CHAR),2,'0')")
        sql = sql.replace("date(?, '-14 day')", "DATE_SUB(?, INTERVAL 14 DAY)")
        sql = sql.replace("INSERT OR REPLACE INTO", "REPLACE INTO")
        return sql.replace('?', '%s')
    def execute(self, sql, params=None):
        self._cursor.execute(self._adapt(sql), params or ())
        self.lastrowid = self._cursor.lastrowid
        return self
    def executemany(self, sql, seq):
        self._cursor.executemany(self._adapt(sql), seq)
        self.lastrowid = self._cursor.lastrowid
        return self
    def executescript(self, script):
        for statement in script.split(';'):
            statement = statement.strip()
            if statement:
                self.execute(statement)
        return self
    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return DBRow(self._cursor.column_names, row)
    def fetchall(self):
        rows = self._cursor.fetchall()
        return [DBRow(self._cursor.column_names, row) for row in rows]
    def close(self):
        self._cursor.close()


class MySQLConnectionAdapter:
    def __init__(self, connection):
        self._connection = connection
    def execute(self, sql, params=None):
        cur = MySQLCursorAdapter(self._connection.cursor())
        cur.execute(sql, params)
        return cur
    def executemany(self, sql, seq):
        cur = MySQLCursorAdapter(self._connection.cursor())
        cur.executemany(sql, seq)
        return cur
    def executescript(self, script):
        cur = MySQLCursorAdapter(self._connection.cursor())
        cur.executescript(script)
        cur.close()
        return self
    def commit(self):
        self._connection.commit()
    def rollback(self):
        self._connection.rollback()
    def close(self):
        self._connection.close()


def _mysql_connection():
    if mysql is None:
        raise RuntimeError("mysql-connector-python is not installed. Run: python -m pip install mysql-connector-python")
    try:
        server = mysql.connector.connect(
            host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER, password=MYSQL_PASSWORD
        )
        cur = server.cursor()
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DATABASE}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        cur.close(); server.close()
        connection = mysql.connector.connect(
            host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER, password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE, buffered=True
        )
        return MySQLConnectionAdapter(connection)
    except Exception as exc:
        raise RuntimeError(
            f"Cannot connect to local MySQL at {MYSQL_HOST}:{MYSQL_PORT} as {MYSQL_USER}. "
            f"Check MySQL is running and MYSQL_HOST/MYSQL_PORT/MYSQL_USER/MYSQL_PASSWORD. Details: {exc}"
        ) from exc


def db():
    if DB_ENGINE == "mysql":
        return _mysql_connection()
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 210000)
    return f"pbkdf2$210000${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters)).hex()
        return hmac.compare_digest(calc, digest)
    except Exception:
        return False



def import_accident_dataset(c):
    """Import the supplied CSV once into the configured database."""
    c.execute("""CREATE TABLE IF NOT EXISTS accident_records(
        accident_id INTEGER PRIMARY KEY, city TEXT NOT NULL, state TEXT NOT NULL,
        latitude DOUBLE NOT NULL, longitude DOUBLE NOT NULL, date TEXT NOT NULL, time TEXT NOT NULL,
        hour INTEGER NOT NULL, day_of_week TEXT NOT NULL, is_weekend INTEGER NOT NULL,
        road_type TEXT NOT NULL, lanes INTEGER NOT NULL, traffic_signal INTEGER NOT NULL,
        weather TEXT NOT NULL, visibility TEXT NOT NULL, temperature DOUBLE NOT NULL,
        traffic_density TEXT NOT NULL, cause TEXT NOT NULL, accident_severity TEXT NOT NULL,
        vehicles_involved INTEGER NOT NULL, casualties INTEGER NOT NULL, is_peak_hour INTEGER NOT NULL,
        festival TEXT, risk_score DOUBLE NOT NULL
    )""")
    count=c.execute("SELECT COUNT(*) FROM accident_records").fetchone()[0]
    if count >= 20000 or not DATASET.exists():
        return count
    df=pd.read_csv(DATASET)
    df=df.where(pd.notna(df), None)
    rows=[]
    cols=['accident_id','city','state','latitude','longitude','date','time','hour','day_of_week','is_weekend','road_type','lanes','traffic_signal','weather','visibility','temperature','traffic_density','cause','accident_severity','vehicles_involved','casualties','is_peak_hour','festival','risk_score']
    for row in df[cols].itertuples(index=False, name=None): rows.append(row)
    c.executemany("REPLACE INTO accident_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)" if DB_ENGINE == "mysql" else "INSERT OR REPLACE INTO accident_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    acc_indexes = [
        "CREATE INDEX idx_acc_city ON accident_records(city)",
        "CREATE INDEX idx_acc_date ON accident_records(date)",
        "CREATE INDEX idx_acc_risk ON accident_records(risk_score)",
        "CREATE INDEX idx_acc_severity ON accident_records(accident_severity)",
    ]
    for statement in acc_indexes:
        try: c.execute(statement)
        except Exception: pass
    return len(rows)


def train_risk_model(c):
    """Train a reproducible local baseline model against the supplied risk_score target."""
    global RISK_MODEL, MODEL_SUMMARY
    rows=c.execute("SELECT city,state,hour,day_of_week,is_weekend,road_type,lanes,traffic_signal,weather,visibility,temperature,traffic_density,cause,accident_severity,vehicles_involved,casualties,is_peak_hour,festival,risk_score FROM accident_records").fetchall()
    if len(rows)<100: return
    df=pd.DataFrame([dict(r) for r in rows])
    target='risk_score'
    features=['city','state','hour','day_of_week','is_weekend','road_type','lanes','traffic_signal','weather','visibility','temperature','traffic_density','is_peak_hour','festival']
    X=df[features].copy(); y=df[target].astype(float)
    categorical=[x for x in features if X[x].dtype=='object']
    numeric=[x for x in features if x not in categorical]
    prep=ColumnTransformer([
        ('cat',Pipeline([('impute',SimpleImputer(strategy='most_frequent')),('onehot',OneHotEncoder(handle_unknown='ignore'))]),categorical),
        ('num',Pipeline([('impute',SimpleImputer(strategy='median'))]),numeric)
    ])
    model=Pipeline([('prep',prep),('model',RandomForestRegressor(n_estimators=120,max_depth=12,random_state=42,n_jobs=-1))])
    Xtr,Xte,ytr,yte=train_test_split(X,y,test_size=.2,random_state=42)
    model.fit(Xtr,ytr); pred=model.predict(Xte)
    RISK_MODEL=model
    MODEL_SUMMARY={
        'model':'Random Forest Regressor', 'target':'risk_score', 'records':len(df),
        'train_records':len(Xtr), 'test_records':len(Xte),
        'mae':round(float(mean_absolute_error(yte,pred)),4),
        'r2':round(float(r2_score(yte,pred)),4),
        'features':features,
        'note':'Metrics are calculated on a held-out 20% test split. Post-event fields such as severity, casualties, cause and vehicles are excluded from the prediction features to reduce target leakage. This is a baseline model, not a safety-critical prediction system.'
    }

def init_db():
    c = db()
    if DB_ENGINE == "mysql":
        schema = """
        CREATE TABLE IF NOT EXISTS users(
            id INT PRIMARY KEY AUTO_INCREMENT, name VARCHAR(255) NOT NULL, email VARCHAR(320) UNIQUE NOT NULL,
            password_hash TEXT NOT NULL, role VARCHAR(32) NOT NULL, department VARCHAR(100), created_at VARCHAR(64) NOT NULL
        );
        CREATE TABLE IF NOT EXISTS complaints(
            id INT PRIMARY KEY AUTO_INCREMENT, public_id VARCHAR(64) UNIQUE NOT NULL, user_id INT NOT NULL,
            title TEXT NOT NULL, description TEXT NOT NULL, category VARCHAR(100) NOT NULL, department VARCHAR(100) NOT NULL,
            latitude DOUBLE, longitude DOUBLE, address TEXT, severity DOUBLE NOT NULL, priority VARCHAR(32) NOT NULL,
            confidence DOUBLE NOT NULL, escalation_probability DOUBLE NOT NULL, status VARCHAR(32) NOT NULL,
            authority_id INT, duplicate_of INT, ai_json LONGTEXT NOT NULL, sla_due_at VARCHAR(64) NOT NULL,
            citizen_confirmed TINYINT DEFAULT 0, created_at VARCHAR(64) NOT NULL, updated_at VARCHAR(64) NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id), FOREIGN KEY(authority_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS complaint_images(
            id INT PRIMARY KEY AUTO_INCREMENT, complaint_id INT NOT NULL, filename TEXT NOT NULL, created_at VARCHAR(64) NOT NULL,
            FOREIGN KEY(complaint_id) REFERENCES complaints(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS actions(
            id INT PRIMARY KEY AUTO_INCREMENT, complaint_id INT NOT NULL, actor_id INT NOT NULL, action VARCHAR(64) NOT NULL,
            note TEXT, created_at VARCHAR(64) NOT NULL, FOREIGN KEY(complaint_id) REFERENCES complaints(id) ON DELETE CASCADE,
            FOREIGN KEY(actor_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS risk_observations(
            id INT PRIMARY KEY AUTO_INCREMENT, latitude DOUBLE NOT NULL, longitude DOUBLE NOT NULL, category VARCHAR(100) NOT NULL,
            severity DOUBLE NOT NULL, occurred_at VARCHAR(64) NOT NULL
        );
        CREATE TABLE IF NOT EXISTS zones(
            id INT PRIMARY KEY AUTO_INCREMENT, name VARCHAR(255) NOT NULL, category VARCHAR(100) NOT NULL, latitude DOUBLE NOT NULL,
            longitude DOUBLE NOT NULL, risk DOUBLE NOT NULL, source VARCHAR(255) NOT NULL
        );
        """
    else:
        schema = """
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
            role TEXT NOT NULL, department TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS complaints(
            id INTEGER PRIMARY KEY AUTOINCREMENT, public_id TEXT UNIQUE NOT NULL, user_id INTEGER NOT NULL, title TEXT NOT NULL,
            description TEXT NOT NULL, category TEXT NOT NULL, department TEXT NOT NULL, latitude REAL, longitude REAL, address TEXT,
            severity REAL NOT NULL, priority TEXT NOT NULL, confidence REAL NOT NULL, escalation_probability REAL NOT NULL, status TEXT NOT NULL,
            authority_id INTEGER, duplicate_of INTEGER, ai_json TEXT NOT NULL, sla_due_at TEXT NOT NULL, citizen_confirmed INTEGER DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id), FOREIGN KEY(authority_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS complaint_images(
            id INTEGER PRIMARY KEY AUTOINCREMENT, complaint_id INTEGER NOT NULL, filename TEXT NOT NULL, created_at TEXT NOT NULL,
            FOREIGN KEY(complaint_id) REFERENCES complaints(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS actions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, complaint_id INTEGER NOT NULL, actor_id INTEGER NOT NULL, action TEXT NOT NULL, note TEXT,
            created_at TEXT NOT NULL, FOREIGN KEY(complaint_id) REFERENCES complaints(id) ON DELETE CASCADE, FOREIGN KEY(actor_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS risk_observations(
            id INTEGER PRIMARY KEY AUTOINCREMENT, latitude REAL NOT NULL, longitude REAL NOT NULL, category TEXT NOT NULL, severity REAL NOT NULL, occurred_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS zones(
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, category TEXT NOT NULL, latitude REAL NOT NULL, longitude REAL NOT NULL, risk REAL NOT NULL, source TEXT NOT NULL
        );
        """
    c.executescript(schema)
    indexes = [
        "CREATE INDEX idx_complaints_created ON complaints(created_at)",
        "CREATE INDEX idx_complaints_category ON complaints(category)",
        "CREATE INDEX idx_complaints_status ON complaints(status)",
        "CREATE INDEX idx_observations_time ON risk_observations(occurred_at)",
        "CREATE INDEX idx_observations_category ON risk_observations(category)",
    ]
    for statement in indexes:
        try: c.execute(statement)
        except Exception: pass
    for u in DEMO_USERS:
        if not c.execute("SELECT id FROM users WHERE email=?", (u[1],)).fetchone():
            c.execute("INSERT INTO users(name,email,password_hash,role,department,created_at) VALUES(?,?,?,?,?,?)",
                      (u[0], u[1], hash_password(u[2]), u[3], u[4], now()))
    if c.execute("SELECT COUNT(*) FROM zones").fetchone()[0] == 0:
        c.executemany("INSERT INTO zones(name,category,latitude,longitude,risk,source) VALUES(?,?,?,?,?,?)", [
            ("Central Flood Watch", "Flood", 12.9716, 77.5946, .72, "demo seed"),
            ("East Traffic Hotspot", "Traffic", 12.9784, 77.6408, .76, "demo seed"),
            ("South Accident Cluster", "Accident", 12.9352, 77.6245, .81, "demo seed"),
            ("Hill Landslide Watch", "Landslide", 11.4102, 76.6950, .68, "demo seed"),
        ])
    import_accident_dataset(c)
    if c.execute("SELECT COUNT(*) FROM risk_observations").fetchone()[0] < 40:
        sample=c.execute("SELECT latitude,longitude,accident_severity,risk_score,date FROM accident_records ORDER BY accident_id LIMIT 120").fetchall()
        severity_map={"minor":.35,"major":.65,"fatal":.92}
        c.executemany("INSERT INTO risk_observations(latitude,longitude,category,severity,occurred_at) VALUES(?,?,?,?,?)", [(r[0],r[1],"Accident",severity_map.get(r[2],r[3]),r[4]+"T12:00:00+00:00") for r in sample])
    if c.execute("SELECT COUNT(*) FROM complaints").fetchone()[0] == 0:
        citizen = c.execute("SELECT id FROM users WHERE role='citizen' LIMIT 1").fetchone()[0]
        roads_authority = c.execute("SELECT id FROM users WHERE department='Roads' LIMIT 1").fetchone()[0]
        electrical_authority = c.execute("SELECT id FROM users WHERE department='Electrical' LIMIT 1").fetchone()[0]
        seed_complaint(c, citizen, roads_authority, "Large pothole near junction", "Deep pothole creating a hazard for two-wheelers and buses.", "Pothole", "Roads", 12.9600,77.6000, "MG Road junction", .78, "HIGH", .91, .62)
        seed_complaint(c, citizen, electrical_authority, "Streetlight not working", "Streetlight has been off for several nights.", "Streetlight", "Electrical", 12.9850,77.6000, "Market Road", .58, "MEDIUM", .82, .25)
    electrical_authority = c.execute("SELECT id FROM users WHERE role='authority' AND department='Electrical' LIMIT 1").fetchone()
    if electrical_authority:
        c.execute("UPDATE complaints SET authority_id=? WHERE department='Electrical'", (electrical_authority[0],))
        c.execute("UPDATE actions SET actor_id=? WHERE action='SEEDED' AND complaint_id IN (SELECT id FROM complaints WHERE department='Electrical')", (electrical_authority[0],))
    c.commit(); train_risk_model(c); c.close()


def seed_complaint(c, user_id, authority_id, title, description, category, department, lat, lon, address, severity, priority, confidence, escalation):
    pid = "CC-" + uuid.uuid4().hex[:7].upper()
    due = (datetime.now(timezone.utc) + timedelta(hours=24 if priority == "HIGH" else 48)).isoformat()
    cur = c.execute("""INSERT INTO complaints(public_id,user_id,title,description,category,department,latitude,longitude,address,severity,priority,confidence,escalation_probability,status,authority_id,ai_json,sla_due_at,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (pid,user_id,title,description,category,department,lat,lon,address,severity,priority,confidence,escalation,"OPEN",authority_id,json.dumps({"engine":"CivicCare Local AI","category":category,"department":department}),due,now(),now()))
    c.execute("INSERT INTO actions(complaint_id,actor_id,action,note,created_at) VALUES(?,?,?,?,?)", (cur.lastrowid, authority_id, "SEEDED", "Demo record created for local installation.", now()))


def current_user(authorization: Optional[str]):
    if not authorization:
        raise HTTPException(401, "Authentication required")
    raw = authorization.replace("Bearer ", "", 1)
    try:
        payload = jwt.decode(raw, JWT_SECRET, algorithms=["HS256"])
    except Exception:
        raise HTTPException(401, "Invalid or expired session")
    c = db(); u = c.execute("SELECT * FROM users WHERE id=?", (payload.get("sub"),)).fetchone(); c.close()
    if not u: raise HTTPException(401, "User not found")
    return u


def token(user):
    return jwt.encode({"sub": str(user["id"]), "role": user["role"], "exp": datetime.now(timezone.utc)+timedelta(hours=12)}, JWT_SECRET, algorithm="HS256")


def classify(title: str, description: str):
    text = (title + " " + description).lower()
    best = ("Other", "General Services", .55)
    matched = []
    for word, rule in RULES.items():
        if word in text:
            matched.append((word, rule))
            if rule[2] > best[2]: best = rule
    severity = best[2]
    if any(w in text for w in HIGH_RISK_WORDS): severity = min(0.99, severity + .12)
    elif any(w in text for w in MEDIUM_RISK_WORDS): severity = min(0.96, severity + .05)
    if any(w in text for w in ("children", "school", "hospital", "blocked", "injury", "emergency")): severity = min(.99, severity + .07)
    severity = round(severity, 2)
    priority = "CRITICAL" if severity >= .9 else "HIGH" if severity >= .72 else "MEDIUM" if severity >= .5 else "LOW"
    confidence = min(.98, best[2] + (0.04 if matched else 0))
    escalation = min(.95, max(.08, severity * .65 + (0.12 if priority in ("CRITICAL", "HIGH") else 0)))
    return {"category":best[0],"department":best[1],"severity":severity,"priority":priority,"confidence":round(confidence,2),"escalation_probability":round(escalation,2),"matched_keywords":[x[0] for x in matched],"engine":"CivicCare Local AI v1"}


def distance(lat1, lon1, lat2, lon2):
    r=6371; p1=math.radians(lat1); p2=math.radians(lat2); dp=math.radians(lat2-lat1); dl=math.radians(lon2-lon1)
    a=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*r*math.asin(math.sqrt(min(1,a)))


def nearest_duplicate(c, user_id, lat, lon, title):
    if lat is None or lon is None: return None
    words=set(w for w in title.lower().split() if len(w)>3)
    rows=c.execute("SELECT id,title,latitude,longitude FROM complaints WHERE status NOT IN ('REJECTED') ORDER BY id DESC LIMIT 200").fetchall()
    for r in rows:
        if r["latitude"] is None or r["longitude"] is None: continue
        if distance(lat,lon,r["latitude"],r["longitude"]) <= .35:
            other=set(w for w in r["title"].lower().split() if len(w)>3)
            if words and other and len(words & other)/max(1,len(words|other)) >= .25:
                return r["id"]
    return None


def authority_for(c, department):
    return c.execute("SELECT * FROM users WHERE role IN ('authority','admin') AND (department=? OR role='admin') ORDER BY role='authority' DESC LIMIT 1", (department,)).fetchone()


def complaint_dict(r, c=None):
    d=dict(r)
    d["citizen_confirmed"] = bool(d.get("citizen_confirmed"))
    d["analysis"] = json.loads(d.pop("ai_json") or "{}")
    return d


init_db()


@app.get("/")
def home(): return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    return {
        "status":"ok",
        "database":DB_ENGINE.upper(),
        "database_path":str(DB),
        "database_exists":DB.exists(),
        "database_size_bytes":DB.stat().st_size if DB.exists() else 0,
        "database_mode":"configured persistent path" if os.getenv("CIVICCARE_DB_PATH") else "project local database",
        "uploads_path":str(UPLOADS),
        "version":"5.8.0",
        "live_intelligence":True,
        "traffic_provider_configured":bool(TOMTOM_API_KEY)
    }


@app.post("/api/auth/login")
def login(email: str = Form(...), password: str = Form(...), role: str = Form("citizen"), department: str = Form("")):
    email_clean = email.strip().lower()
    if not email_clean or not password:
        raise HTTPException(400, "Email and password are required")
    c=db(); u=c.execute("SELECT * FROM users WHERE lower(email)=?",(email_clean,)).fetchone(); c.close()
    if not u or not verify_password(password,u["password_hash"]):
        raise HTTPException(401,"Email or password is incorrect. Check your email/password and make sure the correct workspace is selected.")
    selected_role=(role or "citizen").strip().lower()
    if selected_role in {"citizen","authority"} and u["role"] != selected_role:
        raise HTTPException(403, f"This account belongs to the {u['role']} workspace. Select the correct workspace and sign in again.")
    if selected_role == "authority" and department.strip() and u["department"] != department.strip():
        raise HTTPException(403, f"This account is assigned to {u['department']} Department. Select that department to continue.")
    return {"token":token(u),"user":{"id":u["id"],"name":u["name"],"email":u["email"],"role":u["role"],"department":u["department"]}}


@app.post("/api/auth/register")
def register(name: str=Form(...), email: str=Form(...), password: str=Form(...)):
    if len(password)<8: raise HTTPException(400,"Password must contain at least 8 characters")
    c=db()
    try:
        cur=c.execute("INSERT INTO users(name,email,password_hash,role,department,created_at) VALUES(?,?,?,?,?,?)",(name.strip(),email.strip().lower(),hash_password(password),"citizen","Citizen",now()))
        c.commit(); u=c.execute("SELECT * FROM users WHERE id=?",(cur.lastrowid,)).fetchone()
    except Exception as exc:
        c.close()
        if isinstance(exc, sqlite3.IntegrityError) or getattr(exc, "errno", None) == 1062 or "duplicate" in str(exc).lower():
            raise HTTPException(409,"An account with this email already exists")
        raise
    c.close(); return {"token":token(u),"user":{"id":u["id"],"name":u["name"],"email":u["email"],"role":u["role"],"department":u["department"]}}


@app.get("/api/me")
def me(authorization: Optional[str]=Header(None)):
    u=current_user(authorization); return {"id":u["id"],"name":u["name"],"email":u["email"],"role":u["role"],"department":u["department"]}


@app.get("/api/admin/database")
def admin_database(authorization: Optional[str]=Header(None)):
    u=current_user(authorization)
    if u["role"] != "admin":
        raise HTTPException(403, "Administration access required")
    c=db()
    counts={
        "users": c.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "complaints": c.execute("SELECT COUNT(*) FROM complaints").fetchone()[0],
        "actions": c.execute("SELECT COUNT(*) FROM actions").fetchone()[0],
        "accident_records": c.execute("SELECT COUNT(*) FROM accident_records").fetchone()[0],
    }
    c.close()
    return {"engine":DB_ENGINE.upper(),"path":str(DB) if DB_ENGINE != "mysql" else f"{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}","exists":(DB.exists() if DB_ENGINE != "mysql" else True),"size_bytes":(DB.stat().st_size if DB_ENGINE != "mysql" and DB.exists() else None),"mode":"local MySQL" if DB_ENGINE == "mysql" else ("persistent configured path" if os.getenv("CIVICCARE_DB_PATH") else "local project database"),"counts":counts}


@app.get("/api/admin/config")
def admin_config(authorization: Optional[str]=Header(None)):
    u=current_user(authorization)
    if u["role"] != "admin":
        raise HTTPException(403, "Administration access required")
    return {
        "tomtom_configured": bool(TOMTOM_API_KEY),
        "tomtom_key_source": "environment/.env" if TOMTOM_API_KEY else None,
        "overpass_url": OVERPASS_URL,
        "open_meteo": True,
        "nominatim": True,
        "traffic_provider": "TomTom",
    }


@app.get("/api/admin/config/tomtom/test")
def test_tomtom(authorization: Optional[str]=Header(None)):
    u=current_user(authorization)
    if u["role"] != "admin":
        raise HTTPException(403, "Administration access required")
    if not TOMTOM_API_KEY:
        return {"configured":False,"connected":False,"status":"not_configured","message":"TOMTOM_API_KEY is not configured."}
    # Bengaluru is only a validation point; the actual map uses the selected location.
    result=_traffic_flow(12.9716,77.5946)
    if result.get("available"):
        return {
            "configured":True, "connected":True, "status":"connected",
            "message":"TomTom Traffic Flow API responded successfully.",
            "sample":{"current_speed_kmh":result.get("current_speed_kmh"),"free_flow_speed_kmh":result.get("free_flow_speed_kmh"),"traffic_density":result.get("traffic_density")}
        }
    error=result.get("error") or result.get("reason") or "TomTom request failed"
    return {
        "configured":True, "connected":False, "status":"error",
        "message":error,
        "http_status":result.get("status_code"),
        "provider_error":result.get("provider_error"),
    }


@app.post("/api/admin/config/tomtom")
def set_tomtom_key(authorization: Optional[str]=Header(None), api_key: str=Form(...)):
    global TOMTOM_API_KEY
    u=current_user(authorization)
    if u["role"] != "admin":
        raise HTTPException(403, "Administration access required")
    key=api_key.strip()
    if len(key) < 12:
        raise HTTPException(400, "Enter a valid TomTom API key")
    env_path=BASE / ".env"
    existing=env_path.read_text() if env_path.exists() else ""
    lines=[]; replaced=False
    for line in existing.splitlines():
        if line.startswith("TOMTOM_API_KEY="):
            lines.append("TOMTOM_API_KEY="+key); replaced=True
        else:
            lines.append(line)
    if not replaced:
        lines.append("TOMTOM_API_KEY="+key)
    env_path.write_text("\n".join(lines).rstrip()+"\n")
    TOMTOM_API_KEY=key
    _live_cache.clear()
    return {"saved":True,"tomtom_configured":True,"message":"TomTom key saved locally and live traffic/incident calls are enabled."}


@app.get("/api/dashboard")
def dashboard(authorization: Optional[str]=Header(None)):
    u=current_user(authorization); c=db()
    if u["role"] == "admin":
        where=""; params=()
    elif u["role"] == "authority":
        where="WHERE authority_id=?"; params=(u["id"],)
    else:
        where="WHERE user_id=?"; params=(u["id"],)
    total=c.execute(f"SELECT COUNT(*) FROM complaints {where}",params).fetchone()[0]
    open_count=c.execute(f"SELECT COUNT(*) FROM complaints {where} {'AND' if where else 'WHERE'} status IN ('OPEN','ACKNOWLEDGED','IN_PROGRESS','ESCALATED')",params).fetchone()[0]
    resolved=c.execute(f"SELECT COUNT(*) FROM complaints {where} {'AND' if where else 'WHERE'} status='RESOLVED'",params).fetchone()[0]
    critical=c.execute(f"SELECT COUNT(*) FROM complaints {where} {'AND' if where else 'WHERE'} priority='CRITICAL'",params).fetchone()[0]
    recent=c.execute(f"SELECT * FROM complaints {where} ORDER BY id DESC LIMIT 8",params).fetchall()
    cats=c.execute(f"SELECT category,COUNT(*) count FROM complaints {where} GROUP BY category ORDER BY count DESC",params).fetchall()
    c.close(); return {"stats":{"total":total,"open":open_count,"resolved":resolved,"critical":critical},"recent":[complaint_dict(x) for x in recent],"categories":[dict(x) for x in cats]}


@app.get("/api/complaints")
def complaints(authorization: Optional[str]=Header(None), status: str="", category: str=""):
    u=current_user(authorization); c=db(); clauses=[]; params=[]
    if u["role"] == "authority": clauses.append("authority_id=?"); params.append(u["id"])
    elif u["role"] != "admin": clauses.append("user_id=?"); params.append(u["id"])
    if status: clauses.append("status=?"); params.append(status)
    if category: clauses.append("category=?"); params.append(category)
    where=" WHERE "+" AND ".join(clauses) if clauses else ""
    rows=c.execute("SELECT * FROM complaints"+where+" ORDER BY id DESC",params).fetchall(); c.close()
    return [complaint_dict(x) for x in rows]


@app.post("/api/complaints")
async def create_complaint(authorization: Optional[str]=Header(None), title: str=Form(...), description: str=Form(...), latitude: Optional[float]=Form(None), longitude: Optional[float]=Form(None), address: str=Form(""), image: Optional[UploadFile]=File(None)):
    u=current_user(authorization)
    if len(title.strip())<5 or len(description.strip())<10: raise HTTPException(400,"Provide a meaningful title and description")
    a=classify(title,description); c=db(); auth=authority_for(c,a["department"])
    duplicate=nearest_duplicate(c,u["id"],latitude,longitude,title)
    sla_hours=12 if a["priority"]=="CRITICAL" else 24 if a["priority"]=="HIGH" else 48 if a["priority"]=="MEDIUM" else 72
    due=(datetime.now(timezone.utc)+timedelta(hours=sla_hours)).isoformat(); pid="CC-"+uuid.uuid4().hex[:7].upper()
    cur=c.execute("""INSERT INTO complaints(public_id,user_id,title,description,category,department,latitude,longitude,address,severity,priority,confidence,escalation_probability,status,authority_id,duplicate_of,ai_json,sla_due_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (pid,u["id"],title.strip(),description.strip(),a["category"],a["department"],latitude,longitude,address.strip(),a["severity"],a["priority"],a["confidence"],a["escalation_probability"],"OPEN",auth["id"] if auth else None,duplicate,json.dumps(a),due,now(),now()))
    complaint_id=cur.lastrowid
    c.execute("INSERT INTO actions(complaint_id,actor_id,action,note,created_at) VALUES(?,?,?,?,?)",(complaint_id,u["id"],"SUBMITTED","Complaint submitted by citizen and analyzed by CivicCare AI.",now()))
    if auth:
        c.execute("INSERT INTO actions(complaint_id,actor_id,action,note,created_at) VALUES(?,?,?,?,?)",(complaint_id,auth["id"],"ASSIGNED","Complaint received by the responsible authority and added to its department queue.",now()))
    if duplicate: c.execute("INSERT INTO actions(complaint_id,actor_id,action,note,created_at) VALUES(?,?,?,?,?)",(complaint_id,u["id"],"DUPLICATE_CHECK","A nearby similar complaint was detected.",now()))
    if image and image.filename:
        content=await image.read()
        if len(content)>8*1024*1024: c.rollback(); c.close(); raise HTTPException(413,"Image must be smaller than 8 MB")
        try:
            im=Image.open(__import__('io').BytesIO(content)); im.verify()
        except Exception:
            c.rollback(); c.close(); raise HTTPException(400,"Upload a valid image file")
        safe=f"{uuid.uuid4().hex}{Path(image.filename).suffix.lower()}"; (UPLOADS/safe).write_bytes(content)
        c.execute("INSERT INTO complaint_images(complaint_id,filename,created_at) VALUES(?,?,?)",(complaint_id,safe,now()))
    c.commit(); r=c.execute("SELECT * FROM complaints WHERE id=?",(complaint_id,)).fetchone(); c.close()
    assigned = None
    if auth:
        assigned = {"id": auth["id"], "name": auth["name"], "department": auth["department"], "role": auth["role"]}
    return {"complaint":complaint_dict(r),"analysis":a,"assigned_authority":assigned,"duplicate_of":duplicate}


@app.get("/api/complaints/{complaint_id}")
def complaint_detail(complaint_id:int, authorization:Optional[str]=Header(None)):
    u=current_user(authorization); c=db(); r=c.execute("SELECT * FROM complaints WHERE id=?",(complaint_id,)).fetchone()
    if not r: c.close(); raise HTTPException(404,"Complaint not found")
    if u["role"]=="citizen" and r["user_id"]!=u["id"]: c.close(); raise HTTPException(403,"Access denied")
    actions=c.execute("SELECT a.*,u.name actor FROM actions a JOIN users u ON u.id=a.actor_id WHERE complaint_id=? ORDER BY a.id DESC",(complaint_id,)).fetchall()
    images=c.execute("SELECT * FROM complaint_images WHERE complaint_id=? ORDER BY id DESC",(complaint_id,)).fetchall()
    authority=c.execute("SELECT id,name,email,department,role FROM users WHERE id=?",(r["authority_id"],)).fetchone() if r["authority_id"] else None
    citizen=c.execute("SELECT id,name,email FROM users WHERE id=?",(r["user_id"],)).fetchone()
    d=complaint_dict(r)
    d["assigned_authority"]=dict(authority) if authority else None
    d["citizen"]={"id":citizen["id"],"name":citizen["name"]} if citizen else None
    d["actions"]= [dict(x) for x in actions]; d["images"]=[{"id":x["id"],"url":"/uploads/"+x["filename"]} for x in images]
    c.close()
    return d


@app.get("/api/authority/queue")
def authority_queue(authorization: Optional[str]=Header(None), status: str=""):
    u=current_user(authorization)
    if u["role"] not in ("authority", "admin"):
        raise HTTPException(403, "Authority access required")
    c=db()
    if u["role"] == "admin":
        clauses=[]; params=[]
    else:
        clauses=["authority_id=?"]; params=[u["id"]]
    if status:
        clauses.append("status=?"); params.append(status)
    where=" WHERE "+" AND ".join(clauses) if clauses else ""
    rows=c.execute("SELECT c.*, u.name citizen_name, u.email citizen_email, a.name authority_name, a.email authority_email FROM complaints c LEFT JOIN users u ON u.id=c.user_id LEFT JOIN users a ON a.id=c.authority_id"+where.replace("authority_id", "c.authority_id")+" ORDER BY CASE priority WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 WHEN 'MEDIUM' THEN 3 ELSE 4 END, id DESC",params).fetchall()
    out=[]
    for x in rows:
        d=complaint_dict(x); d["citizen"]={"name":x["citizen_name"],"email":x["citizen_email"]}; d["assigned_authority"]={"name":x["authority_name"],"email":x["authority_email"],"department":d.get("department")} if x["authority_name"] else None; out.append(d)
    c.close()
    return out


@app.post("/api/complaints/{complaint_id}/action")
async def complaint_action(complaint_id:int, authorization:Optional[str]=Header(None), status:str=Form(...), note:str=Form(...), proof:Optional[UploadFile]=File(None)):
    u=current_user(authorization)
    if u["role"] not in ("authority","admin"): raise HTTPException(403,"Authority access required")
    allowed={"ACKNOWLEDGED","IN_PROGRESS","RESOLVED","REJECTED","ESCALATED"}
    if status not in allowed: raise HTTPException(400,"Unsupported status")
    c=db(); r=c.execute("SELECT * FROM complaints WHERE id=?",(complaint_id,)).fetchone()
    if not r: c.close(); raise HTTPException(404,"Complaint not found")
    if u["role"] == "authority" and r["authority_id"] != u["id"]:
        c.close(); raise HTTPException(403,"This complaint is assigned to another authority")
    c.execute("UPDATE complaints SET status=?,updated_at=? WHERE id=?",(status,now(),complaint_id))
    c.execute("INSERT INTO actions(complaint_id,actor_id,action,note,created_at) VALUES(?,?,?,?,?)",(complaint_id,u["id"],status,note.strip(),now()))
    if proof and proof.filename:
        content=await proof.read()
        if len(content)>8*1024*1024: c.rollback(); c.close(); raise HTTPException(413,"Proof image must be smaller than 8 MB")
        safe=f"{uuid.uuid4().hex}{Path(proof.filename).suffix.lower()}"; (UPLOADS/safe).write_bytes(content)
        c.execute("INSERT INTO complaint_images(complaint_id,filename,created_at) VALUES(?,?,?)",(complaint_id,safe,now()))
    c.commit(); c.close(); return {"message":"Action saved","status":status}


@app.post("/api/complaints/{complaint_id}/confirm")
def confirm(complaint_id:int, authorization:Optional[str]=Header(None)):
    u=current_user(authorization); c=db(); r=c.execute("SELECT * FROM complaints WHERE id=? AND user_id=?",(complaint_id,u["id"])).fetchone()
    if not r: c.close(); raise HTTPException(404,"Complaint not found")
    if r["status"]!="RESOLVED": c.close(); raise HTTPException(400,"Complaint is not resolved")
    c.execute("UPDATE complaints SET citizen_confirmed=1,updated_at=? WHERE id=?",(now(),complaint_id)); c.execute("INSERT INTO actions(complaint_id,actor_id,action,note,created_at) VALUES(?,?,?,?,?)",(complaint_id,u["id"],"CONFIRMED","Citizen confirmed the resolution.",now())); c.commit(); c.close(); return {"message":"Resolution confirmed"}


@app.post("/api/complaints/{complaint_id}/reopen")
def reopen(complaint_id:int, authorization:Optional[str]=Header(None), reason:str=Form(...)):
    u=current_user(authorization); c=db(); r=c.execute("SELECT * FROM complaints WHERE id=? AND user_id=?",(complaint_id,u["id"])).fetchone()
    if not r: c.close(); raise HTTPException(404,"Complaint not found")
    c.execute("UPDATE complaints SET status='OPEN',citizen_confirmed=0,updated_at=? WHERE id=?",(now(),complaint_id)); c.execute("INSERT INTO actions(complaint_id,actor_id,action,note,created_at) VALUES(?,?,?,?,?)",(complaint_id,u["id"],"REOPENED",reason.strip(),now())); c.commit(); c.close(); return {"message":"Complaint reopened"}


@app.post("/api/escalations/{complaint_id}")
def escalate(complaint_id:int, authorization:Optional[str]=Header(None)):
    u=current_user(authorization)
    if u["role"] not in ("authority","admin"): raise HTTPException(403,"Authority access required")
    c=db(); r=c.execute("SELECT * FROM complaints WHERE id=?",(complaint_id,)).fetchone()
    if not r: c.close(); raise HTTPException(404,"Complaint not found")
    c.execute("UPDATE complaints SET status='ESCALATED',updated_at=? WHERE id=?",(now(),complaint_id)); c.execute("INSERT INTO actions(complaint_id,actor_id,action,note,created_at) VALUES(?,?,?,?,?)",(complaint_id,u["id"],"ESCALATED","Escalated for higher-priority review.",now())); c.commit(); c.close(); return {"message":"Escalation recorded"}


@app.get("/api/risk")
def risk(latitude:float, longitude:float, authorization:Optional[str]=Header(None)):
    current_user(authorization); c=db()
    rows=c.execute("SELECT * FROM risk_observations").fetchall(); zones=c.execute("SELECT * FROM zones").fetchall()
    by={"Traffic":[],"Accident":[],"Flood":[],"Landslide":[]}
    nearby=[]
    for r in rows:
        d=distance(latitude,longitude,r["latitude"],r["longitude"])
        if d<=5: nearby.append((r,d));
        if r["category"] in by and d<=10: by[r["category"]].append((r["severity"],d))
    def score(items):
        if not items:return .08
        vals=[s*(1-min(d/10,1)*.65) for s,d in items]
        return round(min(.98,max(vals)),2)
    traffic=score(by["Traffic"]); accident=score(by["Accident"]); flood=score(by["Flood"]); landslide=score(by["Landslide"])
    zr=max([z["risk"]*(1-min(distance(latitude,longitude,z["latitude"],z["longitude"])/8,1)) for z in zones] or [.05])
    weather=0.12
    combined=min(.99, .25*traffic+.3*accident+.2*flood+.15*landslide+.1*weather)
    safety=round((1-combined)*100); level="LOW" if combined<.35 else "MODERATE" if combined<.6 else "HIGH" if combined<.78 else "CRITICAL"
    c.close(); return {"safety_score":safety,"level":level,"traffic_risk":traffic,"accident_risk":accident,"flood_risk":flood,"landslide_risk":landslide,"weather_risk":weather,"zone_risk":round(zr,2),"historical_count":len(nearby),"features":{"traffic":traffic,"accident":accident,"flood":flood,"landslide":landslide,"zone":round(zr,2)},"data_note":"Local historical observations and seeded risk zones. Weather is a conservative offline baseline; no external weather API is required."}


def _date_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()


def _risk_level(value: float) -> str:
    return "LOW" if value < .35 else "MODERATE" if value < .60 else "HIGH" if value < .78 else "CRITICAL"


@app.get("/api/dataset/summary")
def dataset_summary():
    c=db()
    total=c.execute("SELECT COUNT(*) FROM accident_records").fetchone()[0]
    cities=[dict(x) for x in c.execute("SELECT city,COUNT(*) count,ROUND(AVG(risk_score),3) avg_risk,ROUND(AVG(casualties),2) avg_casualties FROM accident_records GROUP BY city ORDER BY avg_risk DESC").fetchall()]
    weather=[dict(x) for x in c.execute("SELECT weather,COUNT(*) count,ROUND(AVG(risk_score),3) avg_risk FROM accident_records GROUP BY weather ORDER BY avg_risk DESC").fetchall()]
    severity=[dict(x) for x in c.execute("SELECT accident_severity severity,COUNT(*) count,ROUND(AVG(risk_score),3) avg_risk FROM accident_records GROUP BY accident_severity ORDER BY avg_risk DESC").fetchall()]
    roads=[dict(x) for x in c.execute("SELECT road_type,COUNT(*) count,ROUND(AVG(risk_score),3) avg_risk FROM accident_records GROUP BY road_type ORDER BY avg_risk DESC").fetchall()]
    hourly=[dict(x) for x in c.execute("SELECT hour,COUNT(*) count,ROUND(AVG(risk_score),3) avg_risk FROM accident_records GROUP BY hour ORDER BY hour").fetchall()]
    top_causes=[dict(x) for x in c.execute("SELECT cause,COUNT(*) count,ROUND(AVG(risk_score),3) avg_risk FROM accident_records GROUP BY cause ORDER BY avg_risk DESC").fetchall()]
    c.close(); return {'total_records':total,'cities':cities,'weather':weather,'severity':severity,'road_types':roads,'hourly':hourly,'causes':top_causes,'model':MODEL_SUMMARY}


@app.post("/api/dataset/predict")
def dataset_predict(city:str=Form(...), hour:int=Form(...), road_type:str=Form(...), weather:str=Form(...), traffic_density:str=Form(...), visibility:str=Form(...), lanes:int=Form(...), traffic_signal:int=Form(...), temperature:float=Form(...), cause:str=Form(...), accident_severity:str=Form(...), vehicles_involved:int=Form(...), casualties:int=Form(...), day_of_week:str=Form(...), is_weekend:int=Form(...), is_peak_hour:int=Form(...), festival:str=Form(""), authorization:Optional[str]=Header(None)):
    current_user(authorization)
    if RISK_MODEL is None: raise HTTPException(503,'Risk model is not ready')
    X=pd.DataFrame([{'city':city,'state':{'Bangalore':'Karnataka','Mumbai':'Maharashtra','Pune':'Maharashtra','Delhi':'Delhi','Hyderabad':'Telangana','Chennai':'Tamil Nadu','Kolkata':'West Bengal','Chandigarh':'Punjab'}.get(city,''),'hour':hour,'day_of_week':day_of_week,'is_weekend':is_weekend,'road_type':road_type,'lanes':lanes,'traffic_signal':traffic_signal,'weather':weather,'visibility':visibility,'temperature':temperature,'traffic_density':traffic_density,'cause':cause,'accident_severity':accident_severity,'vehicles_involved':vehicles_involved,'casualties':casualties,'is_peak_hour':is_peak_hour,'festival':festival or None}])
    value=float(RISK_MODEL.predict(X)[0]); value=max(.0,min(1.,value))
    return {'predicted_risk':round(value,3),'level':_risk_level(value),'model':MODEL_SUMMARY['model'],'note':'Scenario estimate from the supplied accident dataset. It is not a safety-critical prediction.'}


@app.get("/api/analytics")
def analytics(authorization:Optional[str]=Header(None)):
    current_user(authorization); c=db()
    total=c.execute("SELECT COUNT(*) FROM accident_records").fetchone()[0]
    categories=[dict(x) for x in c.execute("SELECT accident_severity category, COUNT(*) count, ROUND(AVG(risk_score),3) avg_severity FROM accident_records GROUP BY accident_severity ORDER BY count DESC").fetchall()]
    max_date=c.execute("SELECT MAX(date) FROM accident_records").fetchone()[0]
    trend=[]
    for days_back in range(29,-1,-1):
        day=(datetime.strptime(max_date,'%Y-%m-%d')-timedelta(days=days_back)).date().isoformat()
        row=c.execute("SELECT COUNT(*) count, ROUND(AVG(risk_score),3) avg_severity FROM accident_records WHERE date=?",(day,)).fetchone()
        trend.append({"date":day,"count":row[0] or 0,"avg_severity":row[1] or 0})
    hours=[dict(x) for x in c.execute("SELECT printf('%02d',hour) hour, COUNT(*) count FROM accident_records GROUP BY hour ORDER BY count DESC LIMIT 6").fetchall()]
    recent=c.execute("SELECT accident_severity, COUNT(*) count, ROUND(AVG(risk_score),3) avg_severity FROM accident_records WHERE date>=date(?, '-14 day') GROUP BY accident_severity ORDER BY count DESC",(max_date,)).fetchall()
    c.close()
    return {"total_observations":total,"categories":categories,"trend":trend,"peak_hours":hours,"recent_14d":[{"category":x[0],"count":x[1],"avg_severity":x[2] or 0} for x in recent],"data_note":f"Observed records from the supplied CSV, stored in the configured database. Dataset period: 2022-01-01 to {max_date}. Trend values are descriptive, not forecasts."}


@app.get("/api/risk/hotspots")
def hotspots(authorization:Optional[str]=Header(None)):
    current_user(authorization)
    c=db(); rows=c.execute("SELECT latitude,longitude,accident_severity,risk_score,cause FROM accident_records").fetchall(); c.close()
    severity_map={"minor":.35,"major":.65,"fatal":.92}; cells={}
    for r in rows:
        key=(round(r[0],1),round(r[1],1))
        cell=cells.setdefault(key,{"latitude":key[0],"longitude":key[1],"count":0,"severity":0,"risk":0,"causes":{}})
        cell["count"]+=1; cell["severity"]+=severity_map.get(r[2],.5); cell["risk"]+=r[3]; cell["causes"][r[4]]=cell["causes"].get(r[4],0)+1
    out=[]
    for cell in cells.values():
        avg=cell["severity"]/cell["count"]; avg_risk=cell["risk"]/cell["count"]; dominant=max(cell["causes"],key=cell["causes"].get)
        score=min(.99,.45*avg_risk+.55*avg)
        out.append({"latitude":cell["latitude"],"longitude":cell["longitude"],"count":cell["count"],"avg_severity":round(avg,2),"risk":round(score,2),"level":_risk_level(score),"dominant_category":"Accident / "+dominant})
    return sorted(out,key=lambda x:(x["risk"],x["count"]),reverse=True)[:10]



def _issue_level(value: float) -> str:
    return _risk_level(max(0.0, min(1.0, value)))


def _cached(key, loader, ttl=LIVE_CACHE_TTL):
    now_ts = datetime.now(timezone.utc).timestamp()
    hit = _live_cache.get(key)
    if hit and now_ts - hit[0] < ttl:
        return hit[1]
    value = loader()
    _live_cache[key] = (now_ts, value)
    return value


def _http_get(url, params=None, headers=None):
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True, headers=headers or {"User-Agent":"CivicCare-AI/5.6 (local civic analytics project)"}) as client:
            r = client.get(url, params=params)
            if r.status_code >= 400:
                try:
                    body = r.json()
                except Exception:
                    body = r.text[:500]
                return {
                    "_error": f"HTTP {r.status_code}",
                    "_status_code": r.status_code,
                    "_provider_body": body,
                }
            try:
                return r.json()
            except Exception as exc:
                return {"_error": f"Invalid JSON response: {exc}", "_status_code": r.status_code}
    except Exception as exc:
        return {"_error": str(exc), "_status_code": None}


def _weather_code(code):
    code = int(code or 0)
    if code in (0, 1): return "Clear"
    if code in (2, 3): return "Cloudy"
    if code in (45, 48): return "Fog"
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82): return "Rain"
    if code in (71, 73, 75, 77, 85, 86): return "Snow"
    if code in (95, 96, 99): return "Storm"
    return "Cloudy"


def _weather_live(lat, lon):
    key=f"weather:{round(lat,3)}:{round(lon,3)}"
    def load():
        return _http_get(OPEN_METEO_URL, {
            "latitude":lat,"longitude":lon,
            "current":"temperature_2m,relative_humidity_2m,precipitation,rain,weather_code,wind_speed_10m,visibility",
            "timezone":"auto"
        })
    d=_cached(key,load,60)
    if "_error" in d or "current" not in d:
        return {"available":False,"source":"Open-Meteo","error":d.get("_error","unavailable")}
    c=d["current"]
    return {"available":True,"source":"Open-Meteo","observed_at":c.get("time"),"timezone":d.get("timezone"),"temperature_c":c.get("temperature_2m"),"humidity":c.get("relative_humidity_2m"),"precipitation_mm":c.get("precipitation"),"rain_mm":c.get("rain"),"weather":_weather_code(c.get("weather_code")),"wind_kmh":c.get("wind_speed_10m"),"visibility_m":c.get("visibility")}


def _traffic_flow(lat, lon):
    if not TOMTOM_API_KEY:
        return {"available":False,"source":"TomTom Traffic","reason":"TOMTOM_API_KEY is not configured"}
    key=f"flow:{round(lat,3)}:{round(lon,3)}"
    def load():
        url="https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
        return _http_get(url,{"point":f"{lat},{lon}","unit":"KMPH","key":TOMTOM_API_KEY})
    d=_cached(key,load,30)
    if "_error" in d or "flowSegmentData" not in d:
        provider_body=d.get("_provider_body")
        if isinstance(provider_body,dict):
            provider_error=provider_body.get("detailedError") or provider_body.get("errorText") or provider_body.get("message") or str(provider_body)
        else:
            provider_error=str(provider_body) if provider_body else None
        return {"available":False,"source":"TomTom Traffic","error":d.get("_error","unavailable"),"status_code":d.get("_status_code"),"provider_error":provider_error}
    f=d["flowSegmentData"]
    current=f.get("currentSpeed")
    free=f.get("freeFlowSpeed")
    ratio=(float(current)/float(free)) if current is not None and free else None
    if ratio is None: density="unknown"
    elif ratio < .35: density="high"
    elif ratio < .65: density="medium"
    else: density="low"
    return {"available":True,"source":"TomTom Traffic","observed_at":datetime.now(timezone.utc).isoformat(),"current_speed_kmh":current,"free_flow_speed_kmh":free,"congestion_ratio":round(max(0,min(1,1-ratio)),3) if ratio is not None else None,"traffic_density":density,"confidence":"provider observation"}


def _traffic_incidents(lat, lon, radius_km=10):
    if not TOMTOM_API_KEY:
        return {"available":False,"source":"TomTom Traffic Incidents","incidents":[],"reason":"TOMTOM_API_KEY is not configured"}
    dlat=radius_km/111.0; dlon=radius_km/(111.0*max(.2,math.cos(math.radians(lat))))
    bbox=f"{lon-dlon},{lat-dlat},{lon+dlon},{lat+dlat}"
    key=f"inc:{round(lat,2)}:{round(lon,2)}:{radius_km}"
    def load():
        url="https://api.tomtom.com/traffic/services/5/incidentDetails"
        fields="{incidents{type,geometry{type,coordinates},properties{iconCategory,magnitudeOfDelay,events{description,code},startTime,endTime,from,to,delay,roadNumbers}}}"
        return _http_get(url,{"bbox":bbox,"fields":fields,"language":"en-GB","timeValidityFilter":"present","key":TOMTOM_API_KEY})
    d=_cached(key,load,30)
    if "_error" in d:
        return {"available":False,"source":"TomTom Traffic Incidents","incidents":[],"error":d["_error"]}
    # TomTom may return incidents as a nested object or directly as a list.
    # Normalize both shapes so a provider response can never crash the live-area endpoint.
    payload=d.get("incidents",[]) if isinstance(d,dict) else []
    if isinstance(payload,dict):
        items=payload.get("incidents",[])
    elif isinstance(payload,list):
        items=payload
    else:
        items=[]
    if not isinstance(items,list):
        items=[]
    out=[]
    for item in items[:300]:
        if not isinstance(item,dict):
            continue
        prop=item.get("properties",{}) or {}; geo=item.get("geometry",{}) or {}; coords=geo.get("coordinates") or []
        if isinstance(coords,list) and coords and isinstance(coords[0],list): coords=coords[0]
        if len(coords)>=2:
            out.append({"lat":coords[1],"lng":coords[0],"category":prop.get("iconCategory","incident"),"delay_sec":prop.get("delay"),"magnitude":prop.get("magnitudeOfDelay"),"description":((prop.get("events") or [{}])[0] or {}).get("description","Traffic incident")})
    return {"available":True,"source":"TomTom Traffic Incidents","observed_at":datetime.now(timezone.utc).isoformat(),"incidents":out}


def _reverse_geocode(lat,lon):
    key=f"geo:{round(lat,4)}:{round(lon,4)}"
    def load(): return _http_get(f"{NOMINATIM_URL}/reverse",{"format":"jsonv2","lat":lat,"lon":lon,"zoom":18,"addressdetails":1})
    d=_cached(key,load,3600)
    if "_error" in d: return {"available":False,"error":d["_error"]}
    a=d.get("address",{})
    city=a.get("city") or a.get("town") or a.get("municipality") or a.get("village") or ""
    state=a.get("state") or ""
    return {"available":True,"display_name":d.get("display_name",""),"city":city,"state":state}


def _road_context(lat,lon):
    key=f"road:{round(lat,4)}:{round(lon,4)}"
    def load():
        q=f'[out:json][timeout:6];way(around:80,{lat},{lon})[highway];out tags center;'
        try:
            with httpx.Client(timeout=HTTP_TIMEOUT,headers={"User-Agent":"CivicCare-AI/3.0"}) as client:
                r=client.post(OVERPASS_URL,data=q); r.raise_for_status(); return r.json()
        except Exception as exc: return {"_error":str(exc)}
    d=_cached(key,load,900)
    if "_error" in d: return {"available":False,"error":d["_error"]}
    els=d.get("elements",[])
    if not els:return {"available":False,"reason":"No nearby OSM road metadata"}
    # Prefer a road with the closest center when available.
    tags=els[0].get("tags",{})
    highway=tags.get("highway", "road")
    mapping={"motorway":"Highway","trunk":"Highway","primary":"Main Road","secondary":"Main Road","tertiary":"Main Road","residential":"Residential","unclassified":"Road","service":"Service Road","living_street":"Residential"}
    lanes=tags.get("lanes")
    try: lanes=int(float(lanes))
    except: lanes=2
    signal=1 if tags.get("traffic_signals") in ("yes","true","1") else 0
    return {"available":True,"road_type":mapping.get(highway,"Road"),"lanes":max(1,min(12,lanes)),"traffic_signal":signal,"osm_highway":highway}


def _live_bundle(lat,lon,radius_km=10):
    weather=_weather_live(lat,lon); traffic=_traffic_flow(lat,lon); incidents=_traffic_incidents(lat,lon,radius_km); geo=_reverse_geocode(lat,lon); road=_road_context(lat,lon)
    try:
        tz=ZoneInfo(weather.get("timezone")) if weather.get("timezone") else datetime.now().astimezone().tzinfo
    except Exception:
        tz=datetime.now().astimezone().tzinfo
    now_dt=datetime.now(tz); hour=now_dt.hour; weekend=1 if now_dt.weekday()>=5 else 0
    return {"location":{"latitude":lat,"longitude":lon,**geo},"weather":weather,"traffic":traffic,"incidents":incidents,"road":road,"time":{"local_iso":now_dt.isoformat(),"hour":hour,"day_of_week":now_dt.strftime('%A'),"is_weekend":weekend,"is_peak_hour":int(hour in [7,8,9,10,17,18,19,20])},"freshness_seconds":LIVE_CACHE_TTL}


def _live_model_prediction(bundle):
    if RISK_MODEL is None:return None
    w=bundle["weather"]; t=bundle["traffic"]; g=bundle["location"]; road=bundle["road"]; tm=bundle["time"]
    if not (w.get("available") and g.get("city")): return {"available":False,"reason":"Live weather or geocoded city unavailable"}
    density=t.get("traffic_density") if t.get("available") else "medium"
    if density not in ("low","medium","high"): density="medium"
    visibility=w.get("visibility_m")
    vis="good" if visibility is None or visibility>=5000 else "moderate" if visibility>=2000 else "poor"
    weather=w.get("weather","Cloudy")
    X=pd.DataFrame([{
        "city":g.get("city",""),"state":g.get("state",""),"hour":tm["hour"],"day_of_week":tm["day_of_week"],"is_weekend":tm["is_weekend"],
        "road_type":road.get("road_type","Road"),"lanes":road.get("lanes",2),"traffic_signal":road.get("traffic_signal",0),"weather":weather,"visibility":vis,
        "temperature":float(w.get("temperature_c") or 25),"traffic_density":density,"is_peak_hour":tm["is_peak_hour"],"festival":None
    }])
    value=float(RISK_MODEL.predict(X)[0]); value=max(0,min(1,value))
    return {"available":True,"predicted_risk":round(value,3),"level":_risk_level(value),"inputs":X.iloc[0].to_dict(),"model":MODEL_SUMMARY.get("model")}


@app.get("/api/live/weather")
def live_weather(latitude:float,longitude:float,authorization:Optional[str]=Header(None)):
    current_user(authorization)
    weather=_weather_live(latitude,longitude)
    geo=_reverse_geocode(latitude,longitude)
    return {"location":{"latitude":latitude,"longitude":longitude,**geo},"weather":weather,"source":"Open-Meteo","is_live":bool(weather.get("available")),"freshness_seconds":60}


def _area_evidence(latitude,longitude,radius_km,bundle):
    c=db()
    rows=c.execute("SELECT latitude,longitude,risk_score,cause,accident_severity,weather,hour FROM accident_records WHERE latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ?", (latitude-radius_km/111,latitude+radius_km/111,longitude-radius_km/(111*max(.2,math.cos(math.radians(latitude)))),longitude+radius_km/(111*max(.2,math.cos(math.radians(latitude)))))).fetchall()
    complaints=c.execute("SELECT id,title,category,severity,priority,status,latitude,longitude,created_at FROM complaints WHERE latitude IS NOT NULL AND longitude IS NOT NULL ORDER BY created_at DESC LIMIT 2000").fetchall(); c.close()
    nearby=[r for r in rows if distance(latitude,longitude,r[0],r[1])<=radius_km]
    near_complaints=[r for r in complaints if distance(latitude,longitude,r[6],r[7])<=radius_km]
    hist=sum(float(r[2]) for r in nearby)/len(nearby) if nearby else 0.08
    causes={}
    hours={}
    weather={}
    for r in nearby:
        if r[3]: causes[r[3]]=causes.get(r[3],0)+1
        if r[6] is not None: hours[int(r[6])]=hours.get(int(r[6]),0)+1
        if r[5]: weather[r[5]]=weather.get(r[5],0)+1
    top_cause=max(causes,key=causes.get) if causes else "No nearby historical accidents"
    peak_hour=max(hours,key=hours.get) if hours else None
    common_weather=max(weather,key=weather.get) if weather else "—"
    incident_count=len(bundle["incidents"].get("incidents",[])) if bundle["incidents"].get("available") else 0
    complaint_pressure=min(1,len(near_complaints)/12)
    live_traffic=bundle["traffic"].get("congestion_ratio") if bundle["traffic"].get("available") else None
    model=_live_model_prediction(bundle)
    components=[]
    def add(name,val,w,source):
        if val is not None: components.append((name,float(max(0,min(1,val))),w,source))
    if model and model.get("available"):
        add("model",model["predicted_risk"],.45,"Random Forest live-context estimate")
    add("traffic",live_traffic,.25,"TomTom live traffic")
    if bundle["incidents"].get("available"):
        add("incidents",min(1,incident_count/5),.20,"TomTom live incidents")
    add("complaints",complaint_pressure,.10,"CivicCare reports")
    denom=sum(w for _,_,w,_ in components)
    overall=sum(v*w for _,v,w,_ in components)/denom if denom else hist
    return nearby,near_complaints,hist,top_cause,peak_hour,common_weather,model,components,denom,overall,incident_count,complaint_pressure

@app.get("/api/live/area")
def live_area(latitude:float,longitude:float,radius_km:float=10):
    radius_km=max(.5,min(25,float(radius_km)))
    bundle=_live_bundle(latitude,longitude,radius_km)
    nearby,near_complaints,hist,top_cause,peak_hour,common_weather,model,components,denom,overall,incident_count,complaint_pressure=_area_evidence(latitude,longitude,radius_km,bundle)
    traffic_value=bundle["traffic"].get("congestion_ratio") if bundle["traffic"].get("available") else None
    normalized=[{"name":n,"value":round(v,3),"weight":round(w/denom,3),"source":src} for n,v,w,src in components] if denom else []
    return {"location":bundle["location"],"live":bundle,"historical":{"accidents":len(nearby),"average_risk":round(hist,3),"top_cause":top_cause,"peak_hour":peak_hour,"common_weather":common_weather},"complaints":{"nearby":len(near_complaints)},"model":model,"risk":{"score":round(overall,3),"level":_risk_level(overall),"components":normalized,"method":"Weighted evidence score with live-source renormalization. Missing providers are excluded; this is decision support, not an accident probability."},"data_quality":{"live_traffic":bool(bundle["traffic"].get("available")),"live_weather":bool(bundle["weather"].get("available")),"live_incidents":bool(bundle["incidents"].get("available")),"road_context":bool(bundle["road"].get("available")),"ml_evaluation":bool(model and model.get("available"))},"overall_risk":round(overall,2),"level":_risk_level(overall),"accidents":len(nearby),"complaints":len(near_complaints),"traffic_risk":round(traffic_value,2) if traffic_value is not None else None,"accident_risk":round(hist,2),"complaint_risk":round(complaint_pressure,2),"top_cause":top_cause,"peak_hour":peak_hour,"common_weather":common_weather,"live_incidents":incident_count}


@app.get("/api/map/live")
def map_live(latitude:float=12.9716,longitude:float=77.5946,radius_km:float=10):
    bundle=_live_bundle(latitude,longitude,radius_km)
    issues=[]
    if bundle["traffic"].get("available"):
        t=bundle["traffic"]; issues.append({"type":"live-traffic","lat":latitude,"lng":longitude,"title":"Live traffic flow","detail":f"{t.get('traffic_density','unknown').title()} congestion · {t.get('current_speed_kmh','—')} km/h vs {t.get('free_flow_speed_kmh','—')} free-flow","risk":t.get("congestion_ratio") or 0,"source":"TomTom Traffic","observed_at":t.get("observed_at")})
    for x in bundle["incidents"].get("incidents",[]):
        issues.append({"type":"live-incident","lat":x["lat"],"lng":x["lng"],"title":"Live traffic incident","detail":x.get("description","Traffic incident"),"risk":min(1,.25+.15*float(x.get("magnitude") or 1)),"source":"TomTom Traffic Incidents","observed_at":bundle["incidents"].get("observed_at")})
    return {"issues":issues,"live":bundle,"note":"Only provider observations are labelled LIVE. Historical accident records are intentionally excluded from this live layer."}


@app.get("/api/map/issues")
def map_issues(city:str="", latitude:Optional[float]=None, longitude:Optional[float]=None, radius_km:float=10):
    c=db(); params=[]; clauses=[]
    if city: clauses.append("city LIKE ?"); params.append(f"%{city}%")
    if latitude is not None and longitude is not None:
        radius_km=max(.5,min(25,float(radius_km)))
        dlat=radius_km/111; dlon=radius_km/(111*max(.2,math.cos(math.radians(latitude))))
        clauses.extend(["latitude BETWEEN ? AND ?","longitude BETWEEN ? AND ?"]); params.extend([latitude-dlat,latitude+dlat,longitude-dlon,longitude+dlon])
    where=(" WHERE "+" AND ".join(clauses)) if clauses else ""
    rows=c.execute(f"SELECT accident_id,city,latitude,longitude,accident_severity,risk_score,traffic_density,weather,cause,hour,date FROM accident_records{where} ORDER BY date DESC LIMIT 2200",params).fetchall()
    complaints=c.execute("SELECT id,public_id,title,category,department,latitude,longitude,severity,priority,status,address,created_at FROM complaints WHERE latitude IS NOT NULL AND longitude IS NOT NULL ORDER BY created_at DESC LIMIT 1000").fetchall(); c.close()
    issues=[]
    for r in rows:
        risk=float(r[5] or 0); issues.append({"type":"accident","lat":r[2],"lng":r[3],"title":f"Historical accident · {r[1]}","category":"Accident","risk":round(risk,2),"level":_issue_level(risk),"detail":f"{r[4]} · {r[6]} traffic · {r[7]} · {r[9]}:00","source":"historical dataset","date":r[10]})
    for r in complaints:
        risk=min(.99,float(r[7] or .5)+(.15 if r[8] in ("CRITICAL","HIGH") else 0)); issues.append({"type":"complaint","lat":r[5],"lng":r[6],"title":r[2],"category":r[3],"risk":round(risk,2),"level":_issue_level(risk),"detail":f"{r[4]} · {r[8]} · {r[9]}","source":"CivicCare complaint","date":r[11],"public_id":r[1]})
    return {"issues":issues,"note":"This endpoint is historical/contextual only. Traffic is not live traffic. Use /api/map/live and /api/live/area for current provider observations."}


@app.get("/api/map/area")
def map_area(latitude:float,longitude:float,radius_km:float=5,authorization:Optional[str]=Header(None)):
    current_user(authorization)
    # Backward-compatible route now delegates to the live intelligence engine.
    return live_area(latitude,longitude,radius_km)


@app.get("/api/risk/forecast")
def risk_forecast(latitude:float,longitude:float,authorization:Optional[str]=Header(None)):
    current_user(authorization)
    return live_area(latitude,longitude,10)

@app.get("/api/zones")
def zones(authorization:Optional[str]=Header(None)):
    current_user(authorization); c=db(); r=[dict(x) for x in c.execute("SELECT * FROM zones ORDER BY risk DESC").fetchall()]; c.close(); return r


@app.get("/api/public/summary")
def public_summary():
    c=db(); total=c.execute("SELECT COUNT(*) FROM complaints").fetchone()[0]; resolved=c.execute("SELECT COUNT(*) FROM complaints WHERE status='RESOLVED'").fetchone()[0]; open_=c.execute("SELECT COUNT(*) FROM complaints WHERE status NOT IN ('RESOLVED','REJECTED')").fetchone()[0]; cats=[dict(x) for x in c.execute("SELECT category,COUNT(*) count FROM complaints GROUP BY category ORDER BY count DESC").fetchall()]; obs=[dict(x) for x in c.execute("SELECT category,COUNT(*) count FROM risk_observations GROUP BY category ORDER BY count DESC").fetchall()]; c.close(); return {"complaints":{"total":total,"resolved":resolved,"open":open_},"categories":cats,"risk_observations":obs}


@app.get("/api/admin/data-quality")
def data_quality(authorization:Optional[str]=Header(None)):
    u=current_user(authorization)
    if u["role"] not in ("admin","authority"): raise HTTPException(403,"Admin access required")
    c=db(); r={"observations":c.execute("SELECT COUNT(*) FROM risk_observations").fetchone()[0],"categories":c.execute("SELECT COUNT(DISTINCT category) FROM risk_observations").fetchone()[0],"zones":c.execute("SELECT COUNT(*) FROM zones").fetchone()[0],"complaints":c.execute("SELECT COUNT(*) FROM complaints").fetchone()[0]}; c.close(); return r


@app.post("/api/admin/reset-demo")
def reset_demo(authorization:Optional[str]=Header(None)):
    u=current_user(authorization)
    if u["role"]!="admin": raise HTTPException(403,"Admin access required")
    c=db(); c.execute("DELETE FROM actions"); c.execute("DELETE FROM complaint_images"); c.execute("DELETE FROM complaints"); c.commit(); init_seed_only(c); c.commit(); c.close(); return {"message":"Demo complaint data reset"}


def init_seed_only(c):
    citizen=c.execute("SELECT id FROM users WHERE role='citizen' LIMIT 1").fetchone()[0]
    roads=c.execute("SELECT id FROM users WHERE department='Roads' LIMIT 1").fetchone()[0]
    electrical=c.execute("SELECT id FROM users WHERE department='Electrical' LIMIT 1").fetchone()[0]
    seed_complaint(c,citizen,roads,"Large pothole near junction","Deep pothole creating a hazard for two-wheelers and buses.","Pothole","Roads",12.9600,77.6000,"MG Road junction",.78,"HIGH",.91,.62)
    seed_complaint(c,citizen,electrical,"Streetlight not working","Streetlight has been off for several nights.","Streetlight","Electrical",12.9850,77.6000,"Market Road",.58,"MEDIUM",.82,.25)
