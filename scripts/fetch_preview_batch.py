#!/usr/bin/env python3
import json

from fetch_next_photo import (
    ROOT,
    CONFIG_PATH,
    QUEUE_PATH,
    album_token,
    load_json,
    fetch_asset_data,
    build_asset_url,
    download_icloud_image,
)

BATCH_DIR = ROOT / "preview_batch"
MANIFEST_PATH = BATCH_DIR / "manifest.json"
BATCH_SIZE = 22


def main():
    config = load_json(CONFIG_PATH, {})
    queue_doc = load_json(QUEUE_PATH, {"queue": []})
    queue = (queue_doc.get("queue") or [])[:BATCH_SIZE]

    if not queue:
        raise RuntimeError("La cola está vacía")

    token = album_token(config["album_url"])
    BATCH_DIR.mkdir(parents=True, exist_ok=True)

    manifest = []

    for index, candidate in enumerate(queue, start=1):
        photo_guid = candidate["photo_guid"]
        derivative = candidate.get("best_derivative") or {}
        checksum = derivative.get("checksum")
        partition = str(candidate.get("partition") or "")

        if not checksum or not partition:
            print(f"Saltando {photo_guid}: faltan checksum o partición")
            continue

        asset_data = fetch_asset_data(token, partition, photo_guid)
        asset_url = build_asset_url(asset_data, checksum)

        filename = f"{index:02d}_{photo_guid}.jpg"
        destination = BATCH_DIR / filename

        content_type, byte_count = download_icloud_image(
            asset_url,
            destination,
        )

        manifest.append({
            "index": index,
            "file": filename,
            "photo_guid": photo_guid,
            "batch_guid": candidate.get("batch_guid"),
            "batch_date_created": candidate.get("batch_date_created"),
            "date_created": candidate.get("date_created"),
            "width": candidate.get("width"),
            "height": candidate.get("height"),
            "checksum": checksum,
            "content_type": content_type,
            "bytes": byte_count,
            "status": "ready_for_review",
        })

        print(f"{index:02d}/{BATCH_SIZE} listo: {filename}")

    MANIFEST_PATH.write_text(
        json.dumps(
            {
                "count": len(manifest),
                "items": manifest,
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    print(f"Batch listo: {len(manifest)} previews")


if __name__ == "__main__":
    main()
