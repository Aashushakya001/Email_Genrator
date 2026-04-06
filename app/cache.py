import os
import json
import hashlib
import time

CACHE_DIR = os.path.join(os.path.dirname(__file__), 'cache')
os.makedirs(CACHE_DIR, exist_ok=True)


def _key_to_filename(key: str) -> str:
    h = hashlib.sha256(key.encode('utf-8')).hexdigest()
    return os.path.join(CACHE_DIR, f"{h}.json")


def get(key: str):
    path = _key_to_filename(key)
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # optional TTL check
        if data.get('_expires_at') and time.time() > data['_expires_at']:
            try:
                os.remove(path)
            except Exception:
                pass
            return None
        val = data.get('value')
        # Treat short sentinel-like cached values (eg. 'safe') as invalid
        try:
            if isinstance(val, str):
                low = val.strip().lower()
                if low in ('safe', 'unsafe', 'filtered') or len(val.strip()) < 10:
                    try:
                        os.remove(path)
                    except Exception:
                        pass
                    return None
        except Exception:
            pass
        return val
    except Exception:
        return None


def set(key: str, value, ttl: int = 24 * 3600):
    path = _key_to_filename(key)
    payload = {'value': value, '_expires_at': time.time() + ttl}
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f)
    except Exception:
        pass
