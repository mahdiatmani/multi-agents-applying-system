import os
import json
import tempfile
import threading
from datetime import datetime

DB_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "state", "database.json"))
db_lock = threading.Lock()


def _empty():
    return {
        "stats": {
            "jobsSearched": 0,
            "profilesFound": 0,
            "applicationsSent": 0,
            "draftsCreated": 0,
            "applicationsAttempted": 0,
            "applicationsFailed": 0,
        },
        "history": {"jobs": [], "profilesPosts": []},
    }


def _load_db():
    if not os.path.exists(DB_FILE):
        return _empty()
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        print(f"[db] load failed ({exc}); returning empty.", flush=True)
        return _empty()
    base = _empty()
    base["stats"].update(data.get("stats", {}))
    base["history"]["jobs"] = data.get("history", {}).get("jobs", [])
    base["history"]["profilesPosts"] = data.get("history", {}).get("profilesPosts", [])
    return base


def _save_db(data):
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".db-", suffix=".tmp", dir=os.path.dirname(DB_FILE))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp, DB_FILE)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def get_db_data():
    with db_lock:
        return _load_db()


def update_stat(stat_key, increment=1):
    with db_lock:
        db = _load_db()
        db["stats"][stat_key] = db["stats"].get(stat_key, 0) + increment
        _save_db(db)
        return db["stats"][stat_key]


def record_activity(category, item):
    with db_lock:
        db = _load_db()
        items = db["history"].get(category, [])
        item_id = item.get("id")
        existing_idx = next((i for i, x in enumerate(items) if x.get("id") == item_id), None)
        item["timestamp"] = datetime.now().isoformat()
        if existing_idx is not None:
            items[existing_idx].update(item)
        else:
            items.insert(0, item)
        db["history"][category] = items[:500]
        _save_db(db)


def reset_db():
    with db_lock:
        _save_db(_empty())
