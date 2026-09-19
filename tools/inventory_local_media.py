#!/usr/bin/env python3
"""Inventory already-acquired local media without fabricating originals.

This utility does not scrape sites. Point --vault at media you already possess
or are authorized to process. It emits provenance metadata for the viewer.
"""
from __future__ import annotations
import argparse, hashlib, json, mimetypes
from datetime import datetime, timezone
from pathlib import Path

MEDIA_EXT={".jpg",".jpeg",".png",".webp",".gif",".mp4",".webm",".mov",".m4v"}

def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def kind_for(path: Path) -> str:
    mt=mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return "video" if mt.startswith("video/") else "photo"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--vault", required=True, type=Path)
    ap.add_argument("--out", default="catalog.acquired.json", type=Path)
    args=ap.parse_args()
    root=args.vault.expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"vault not found: {root}")
    items=[]
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in MEDIA_EXT:
            continue
        rel=p.relative_to(root).as_posix()
        mime=mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        items.append({
            "id": f"vault-{len(items)+1}",
            "source": "Vault",
            "kind": kind_for(p),
            "title": p.stem,
            "file": p.name,
            "relPath": rel,
            "bytes": p.stat().st_size,
            "mimeDetected": mime,
            "sha256": sha256(p),
            "acquiredAt": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(),
            "provenanceStatus": "acquired",
            "syntheticThumb": False
        })
    payload={"generatedAt":datetime.now(timezone.utc).isoformat(),"count":len(items),"items":items}
    args.out.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(f"Wrote {len(items)} verified local entries to {args.out}")

if __name__=="__main__":
    main()
