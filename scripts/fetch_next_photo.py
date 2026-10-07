#!/usr/bin/env python3

import json
import socket
import time
from urllib import request, error
from urllib.parse import urlparse

from sync_icloud import (
    ROOT,
    CONFIG_PATH,
    QUEUE_PATH,
    album_token,
    load_json,
    post_json,
)

PREVIEW_DIR = ROOT / "preview"
PREVIEW_PATH = PREVIEW_DIR / "next.jpg"
PREVIEW_META_PATH = PREVIEW_DIR / "next.json"

ALLOWED_CDN_SUFFIX = ".icloud-content.com"


def validate_cdn_url(url):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()

    if parsed.scheme != "https":
        raise RuntimeError("La URL de imagen no usa HTTPS")

    if not (
        host == "icloud-content.com"
        or host.endswith(ALLOWED_CDN_SUFFIX)
    ):
        raise RuntimeError(f"Host CDN inesperado: {host}")

    return url


def build_asset_url(data, checksum):
    items = data.get("items") or {}
    locations = data.get("locations") or {}

    item = items.get(checksum)

    if not item:
        raise RuntimeError(
            "No se encontró el checksum solicitado en webasseturls"
        )

    location = item.get("url_location")
    path = item.get("url_path")

    if not location or not path:
        raise RuntimeError(
            "Respuesta de iCloud sin url_location/url_path"
        )

    loc = locations.get(location, {})

    scheme = loc.get("scheme", "https")
    hosts = loc.get("hosts") or [location]
    host = hosts[0]

    return validate_cdn_url(
        f"{scheme}://{host}{path}"
    )


def fetch_asset_data(token, partition, photo_guid):
    host = f"p{partition}-sharedstreams.icloud.com"

    endpoint = (
        f"https://{host}/{token}/sharedstreams/webasseturls"
    )

    status, headers, data = post_json(
        endpoint,
        {"photoGuids": [photo_guid]},
    )

    redirect_host = None

    if isinstance(data, dict):
        redirect_host = data.get("X-Apple-MMe-Host")

    redirect_host = (
        redirect_host
        or headers.get("x-apple-mme-host")
        or headers.get("X-Apple-MMe-Host")
    )

    if redirect_host:
        endpoint = (
            f"https://{redirect_host}/{token}"
            "/sharedstreams/webasseturls"
        )

        status, headers, data = post_json(
            endpoint,
            {"photoGuids": [photo_guid]},
        )

    if status != 200:
        raise RuntimeError(
            f"iCloud webasseturls respondió HTTP {status}"
        )

    return data


def download_icloud_image(
    url,
    destination,
    attempts=3,
    timeout=180,
):
    last_exc = None

    for attempt in range(1, attempts + 1):

        try:
            print(
                f"Descargando preview "
                f"(intento {attempt}/{attempts})..."
            )

            req = request.Request(
                validate_cdn_url(url),
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "image/*",
                },
            )

            with request.urlopen(
                req,
                timeout=timeout,
            ) as resp:

                content_type = resp.headers.get(
                    "Content-Type",
                    "",
                )

                if not content_type.lower().startswith(
                    "image/"
                ):
                    raise RuntimeError(
                        f"Contenido inesperado: {content_type}"
                    )

                payload = resp.read()

                if not payload:
                    raise RuntimeError(
                        "La imagen descargada está vacía"
                    )

                destination.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                destination.write_bytes(payload)

                return content_type, len(payload)

        except (
            TimeoutError,
            socket.timeout,
            error.URLError,
            RuntimeError,
        ) as exc:

            last_exc = exc

            if attempt < attempts:
                wait = attempt * 10

                print(
                    f"Descarga fallida. "
                    f"Reintentando en {wait}s..."
                )

                time.sleep(wait)

    raise RuntimeError(
        f"No se pudo descargar la imagen: {last_exc}"
    )


def main():
    config = load_json(
        CONFIG_PATH,
        {},
    )

    queue_doc = load_json(
        QUEUE_PATH,
        {"queue": []},
    )

    queue = queue_doc.get("queue") or []

    if not queue:
        raise RuntimeError(
            "La cola está vacía"
        )

    candidate = queue[0]

    photo_guid = candidate["photo_guid"]

    derivative = (
        candidate.get("best_derivative")
        or {}
    )

    checksum = derivative.get("checksum")

    partition = str(
        candidate.get("partition")
        or ""
    )

    if not checksum:
        raise RuntimeError(
            "La foto no tiene checksum"
        )

    if not partition:
        raise RuntimeError(
            "La foto no tiene partición"
        )

    token = album_token(
        config["album_url"]
    )

    asset_data = fetch_asset_data(
        token,
        partition,
        photo_guid,
    )

    asset_url = build_asset_url(
        asset_data,
        checksum,
    )

    content_type, byte_count = (
        download_icloud_image(
            asset_url,
            PREVIEW_PATH,
        )
    )

    meta = {
        "photo_guid": photo_guid,
        "date_created": candidate.get(
            "date_created"
        ),
        "width": candidate.get("width"),
        "height": candidate.get("height"),
        "checksum": checksum,
        "content_type": content_type,
        "bytes": byte_count,
        "status": "ready_for_review",
    }

    PREVIEW_META_PATH.write_text(
        json.dumps(
            meta,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        f"Preview listo: "
        f"{photo_guid} "
        f"({byte_count} bytes)"
    )


if __name__ == "__main__":
    main()
