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


def strip_exif(path: str) -> None:
    source = Path(path).expanduser()
    output = source.with_name(f"{source.stem}.clean{source.suffix}")
    subprocess.run(["exiftool", "-all=", "-o", str(output), str(source)], check=True)
    print(output)


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
    strip_parser = subparsers.add_parser("strip-exif")
    strip_parser.add_argument("path")
    args = parser.parse_args()
    if args.command == "scan":
        scan(args.path)
    elif args.command == "query":
        query(args.text, args)
    else:
        strip_exif(args.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
