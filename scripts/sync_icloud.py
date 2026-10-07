#!/usr/bin/env python3
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib import request, error

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
PHOTOS_PATH = ROOT / "data" / "photos.json"
PUBLISHED_PATH = ROOT / "data" / "published.json"
QUEUE_PATH = ROOT / "data" / "queue.json"

BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
USER_AGENT = "Photos/5.0 (Macintosh; OS X 10.15.4) AppleWebKit/605.1.15"

def now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def load_json(path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

def album_token(url):
    if "#" not in url:
        raise ValueError("El URL de iCloud no contiene token")
    token = url.split("#", 1)[1].strip("/")
    if not token:
        raise ValueError("Token de álbum vacío")
    return token

def base62_to_int(value):
    result = 0
    for char in value:
        idx = BASE62.find(char)
        if idx < 0:
            raise ValueError(f"Carácter inválido en token: {char!r}")
        result = result * 62 + idx
    return result

def partition_from_token(token):
    if token[0] == "A":
        n = base62_to_int(token[1])
    else:
        n = base62_to_int(token[1:3])
    return f"{n:02d}"

def post_json(url, payload, attempts=3, timeout=180):
    body = json.dumps(payload).encode("utf-8")
    last_exc = None

    for attempt in range(1, attempts + 1):
        req = request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "text/plain",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "Connection": "close",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            print(f"Consultando iCloud (intento {attempt}/{attempts})...")
            with request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                return resp.status, dict(resp.headers), json.loads(raw)
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw)
            except Exception:
                data = {}
            # Los HTTP explícitos deben devolverse para que fetch_stream
            # pueda tratar redirecciones/respuestas de Apple.
            return exc.code, dict(exc.headers), data
        except (TimeoutError, socket.timeout, error.URLError) as exc:
            last_exc = exc
            if attempt < attempts:
                wait = attempt * 10
                print(f"iCloud tardó demasiado. Reintentando en {wait}s...")
                time.sleep(wait)

    raise RuntimeError(f"No se pudo leer iCloud tras {attempts} intentos: {last_exc}")

def fetch_stream(token):
    partition = partition_from_token(token)
    host = f"p{partition}-sharedstreams.icloud.com"
    url = f"https://{host}/{token}/sharedstreams/webstream"
    status, headers, data = post_json(url, {"streamCtag": None})

    redirect_host = data.get("X-Apple-MMe-Host") if isinstance(data, dict) else None
    if redirect_host:
        url = f"https://{redirect_host}/{token}/sharedstreams/webstream"
        status, headers, data = post_json(url, {"streamCtag": None})

    if status != 200:
        raise RuntimeError(f"iCloud webstream respondió HTTP {status}")

    part_header = headers.get("x-apple-user-partition") or headers.get("X-Apple-User-Partition")
    if part_header:
        partition = str(part_header)

    return data, partition

def best_derivative(derivatives):
    if not derivatives:
        return None

    def score(item):
        d = item[1]
        try:
            size = int(d.get("fileSize", 0) or 0)
        except (TypeError, ValueError):
            size = 0
        try:
            area = int(d.get("width", 0) or 0) * int(d.get("height", 0) or 0)
        except (TypeError, ValueError):
            area = 0
        return (size, area)

    key, d = max(derivatives.items(), key=score)
    return {
        "key": key,
        "checksum": d.get("checksum"),
        "width": int(d.get("width", 0) or 0),
        "height": int(d.get("height", 0) or 0),
        "file_size": int(d.get("fileSize", 0) or 0),
    }

def normalize_photo(photo, partition):
    return {
        "photo_guid": photo.get("photoGuid"),
        "batch_guid": photo.get("batchGuid"),
        "date_created": photo.get("dateCreated"),
        "batch_date_created": photo.get("batchDateCreated"),
        "caption": photo.get("caption") or "",
        "width": photo.get("width"),
        "height": photo.get("height"),
        "media_asset_type": photo.get("mediaAssetType", "image"),
        "best_derivative": best_derivative(photo.get("derivatives") or {}),
        "partition": partition,
        "status": "available",
    }

def main():
    config = load_json(CONFIG_PATH, {})
    token = album_token(config["album_url"])
    include_videos = bool(config.get("include_videos", False))
    queue_size = int(config.get("queue_size", 20))

    stream, partition = fetch_stream(token)
    inventory = []

    for item in stream.get("photos", []):
        if item.get("mediaAssetType") == "video" and not include_videos:
            continue
        normalized = normalize_photo(item, partition)
        if normalized["photo_guid"]:
            inventory.append(normalized)

    inventory.sort(key=lambda p: ((p.get("date_created") or ""), p["photo_guid"]))

    published_doc = load_json(PUBLISHED_PATH, {"published": []})
    published_ids = {
        item.get("photo_guid")
        for item in published_doc.get("published", [])
        if item.get("photo_guid")
    }

    for item in inventory:
        if item["photo_guid"] in published_ids:
            item["status"] = "published"

    available = [p for p in inventory if p["photo_guid"] not in published_ids]
    queue = [
        {
            "photo_guid": p["photo_guid"],
            "date_created": p.get("date_created"),
            "caption": p.get("caption", ""),
            "width": p.get("width"),
            "height": p.get("height"),
            "best_derivative": p.get("best_derivative"),
            "partition": p.get("partition"),
            "status": "pending",
        }
        for p in available[:queue_size]
    ]

    stamp = now_iso()
    save_json(PHOTOS_PATH, {
        "updated_at": stamp,
        "album_name": stream.get("streamName"),
        "items_returned_by_icloud": stream.get("itemsReturned"),
        "count": len(inventory),
        "photos": inventory,
    })
    save_json(QUEUE_PATH, {
        "updated_at": stamp,
        "count": len(queue),
        "queue": queue,
    })

    print(f"Álbum: {stream.get('streamName') or '(sin nombre)'}")
    print(f"Fotos inventariadas: {len(inventory)}")
    print(f"Ya publicadas: {len(published_ids)}")
    print(f"Disponibles: {len(available)}")
    print(f"Cola generada: {len(queue)}")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
