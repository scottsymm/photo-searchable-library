"""Command-line entry point."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

import httpx

from core import jobs
from core.conn import connect


MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".mov", ".mp4", ".avif", ".dng"}


def scan(path: str) -> None:
    root = Path(path).expanduser()
    paths = [str(item) for item in root.rglob("*") if item.is_file() and item.suffix.lower() in MEDIA_SUFFIXES]
    with connect(os.environ.get("PICS_DB", "catalog.db")) as conn:
        job_id = jobs.push(conn, "scan", {"paths": paths})
    print(f"queued {len(paths)} files as job {job_id}")


def query(text: str, args) -> None:
    response = httpx.get(
        os.environ.get("PICS_API", "http://localhost:8000") + "/search",
        params={"q": text, "who": args.who, "place": args.place, "limit": args.limit},
        timeout=120,
    )
    response.raise_for_status()
    for result in response.json()["results"]:
        print(f"{result['id']}\t{result.get('distance', '')}\t{result['path']}")


def upload(path: str) -> None:
    root = Path(path).expanduser()
    paths = [root] if root.is_file() else [
        item for item in root.rglob("*")
        if item.is_file() and item.suffix.lower() in MEDIA_SUFFIXES
    ]
    base = os.environ.get("PICS_API", "http://localhost:8000")
    with httpx.Client(timeout=120) as client:
        for index, item in enumerate(paths, 1):
            with item.open("rb") as source:
                response = client.post(
                    f"{base}/assets/upload",
                    files={"file": (item.name, source, "application/octet-stream")},
                )
            response.raise_for_status()
            print(f"[{index}/{len(paths)}] {item} -> job {response.json()['job_id']}")


def strip_exif(path: str) -> None:
    source = Path(path).expanduser()
    output = source.with_name(f"{source.stem}.clean{source.suffix}")
    subprocess.run(["exiftool", "-all=", "-o", str(output), str(source)], check=True)
    print(output)


def cluster(args) -> None:
    with connect(os.environ.get("PICS_DB", "catalog.db")) as conn:
        job_id = jobs.push(
            conn,
            "cluster_faces",
            {"eps": args.eps, "min_samples": args.min_samples},
        )
    print(f"queued face clustering job {job_id}")


def people(args) -> None:
    if args.json:
        response = httpx.get(
            os.environ.get("PICS_API", "http://localhost:8000") + "/persons",
            timeout=30,
        )
        response.raise_for_status()
        print(response.text)
        return
    response = httpx.get(
        os.environ.get("PICS_API", "http://localhost:8000") + "/persons",
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    for person in data["persons"]:
        print(f"person {person['id']}\t{person['name'] or '(unnamed)'}\t{person['face_count']} faces")
    for suggestion in data.get("suggestions", []):
        print(f"suggestion {suggestion['id']}\t{suggestion['confidence']}\t{suggestion['face_count']} faces\t{suggestion['status']}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="pics")
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan_parser = subparsers.add_parser("scan")
    scan_parser.add_argument("path")
    query_parser = subparsers.add_parser("query")
    query_parser.add_argument("text")
    query_parser.add_argument("--who")
    query_parser.add_argument("--place")
    query_parser.add_argument("--limit", type=int, default=20)
    upload_parser = subparsers.add_parser("upload", help="Upload files to the running API")
    upload_parser.add_argument("path")
    upload_parser.set_defaults(func=lambda args: upload(args.path))
    strip_parser = subparsers.add_parser("strip-exif")
    strip_parser.add_argument("path")
    cluster_parser = subparsers.add_parser("cluster")
    cluster_parser.add_argument("--eps", type=float, default=0.30)
    cluster_parser.add_argument("--min-samples", type=int, default=3)
    cluster_parser.set_defaults(func=cluster)
    people_parser = subparsers.add_parser("people")
    people_parser.add_argument("--json", action="store_true")
    people_parser.set_defaults(func=people)
    args = parser.parse_args()
    if args.command == "scan":
        scan(args.path)
    elif args.command == "query":
        query(args.text, args)
    elif args.command == "upload":
        args.func(args)
    else:
        if args.command == "strip-exif":
            strip_exif(args.path)
        else:
            args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
