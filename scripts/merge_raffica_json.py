import json
import sys
from datetime import datetime


def load_json(path):
    try:
        with open(path, "r") as file:
            return json.load(file)
    except Exception:
        return None


def to_record(obj):
    if isinstance(obj, dict):
        gust = obj.get("gust")
        timestamp = obj.get("timestamp")
        try:
            gust = float(gust)
        except Exception:
            return None
        return {"timestamp": timestamp if isinstance(timestamp, str) else None, "gust": gust}

    if isinstance(obj, (int, float)):
        return {"timestamp": None, "gust": float(obj)}

    return None


def hour_key(timestamp):
    if not isinstance(timestamp, str):
        return None

    try:
        return datetime.fromisoformat(timestamp).strftime("%Y-%m-%d %H")
    except Exception:
        return timestamp[:13] if len(timestamp) >= 13 else None


def choose(remote, local):
    if remote and local:
        remote_hour = hour_key(remote.get("timestamp"))
        local_hour = hour_key(local.get("timestamp"))

        if remote_hour and local_hour:
            if remote_hour == local_hour:
                return local if local["gust"] >= remote["gust"] else remote
            return local if local_hour > remote_hour else remote

        if local_hour and not remote_hour:
            return local
        if remote_hour and not local_hour:
            return remote

        return local if local["gust"] >= remote["gust"] else remote

    if local:
        return local
    if remote:
        return remote

    return {"timestamp": datetime.now().isoformat(), "gust": 0.0}


def main():
    if len(sys.argv) != 4:
        raise SystemExit("Usage: merge_raffica_json.py <remote_json> <local_json> <out_json>")

    remote_path, local_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]

    remote = to_record(load_json(remote_path))
    local = to_record(load_json(local_path))
    chosen = choose(remote, local)

    if not chosen.get("timestamp"):
        chosen["timestamp"] = datetime.now().isoformat()

    output = {
        "timestamp": chosen["timestamp"],
        "gust": round(float(chosen["gust"]), 1),
    }

    with open(out_path, "w") as file:
        json.dump(output, file)


if __name__ == "__main__":
    main()