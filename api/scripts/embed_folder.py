#!/usr/bin/env python3
"""Run buffalo_l detection + embedding over every image in a folder and
dump per-face results to JSON, for eyeballing real score/similarity
distributions before picking MATCH_THRESHOLD on actual event photos.

Usage:
    python scripts/embed_folder.py /path/to/photos --out results.json
    python scripts/embed_folder.py /path/to/photos --out results.json \
        --pairwise-csv similarities.csv

Run from the api/ directory with the project's dependencies installed
(insightface will download the buffalo_l model pack on first run, ~280MB).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.services.face_model import detect_and_embed  # noqa: E402

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def passes_gate(bbox_width: float, bbox_height: float, det_score: float) -> bool:
    return min(bbox_width, bbox_height) >= settings.min_face_bbox_px and det_score >= settings.min_det_score


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path, help="Folder of photos to scan")
    parser.add_argument("--out", type=Path, default=Path("embed_folder_results.json"))
    parser.add_argument(
        "--pairwise-csv",
        type=Path,
        default=None,
        help="Also dump all-pairs cosine similarity between gated faces, sorted descending -- "
        "the direct input for picking MATCH_THRESHOLD",
    )
    parser.add_argument("--recursive", action="store_true")
    args = parser.parse_args()

    if not args.folder.is_dir():
        print(f"Not a directory: {args.folder}", file=sys.stderr)
        sys.exit(1)

    pattern = "**/*" if args.recursive else "*"
    paths = sorted(p for p in args.folder.glob(pattern) if p.suffix.lower() in IMAGE_EXTENSIONS)
    if not paths:
        print(f"No images found under {args.folder}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(paths)} images. Loading {settings.face_model_pack} "
          f"(first run downloads the model pack)...")

    images: list[dict] = []
    all_gated: list[tuple[str, int, list[float]]] = []

    for i, path in enumerate(paths, 1):
        img = cv2.imread(str(path))
        if img is None:
            print(f"  [{i}/{len(paths)}] {path.name}: could not read, skipping", file=sys.stderr)
            continue

        faces = detect_and_embed(img)
        face_records = []
        for idx, face in enumerate(faces):
            gated = passes_gate(face.bbox_width, face.bbox_height, face.det_score)
            face_records.append(
                {
                    "index": idx,
                    "bbox": list(face.bbox),
                    "bbox_width": face.bbox_width,
                    "bbox_height": face.bbox_height,
                    "det_score": face.det_score,
                    "passes_gate": gated,
                    "embedding": face.embedding,
                }
            )
            if gated:
                all_gated.append((str(path.relative_to(args.folder)), idx, face.embedding))

        images.append(
            {
                "file": str(path.relative_to(args.folder)),
                "image_width": img.shape[1],
                "image_height": img.shape[0],
                "faces": face_records,
            }
        )
        gated_count = sum(1 for f in face_records if f["passes_gate"])
        print(
            f"  [{i}/{len(paths)}] {path.name}: {len(faces)} detected, {gated_count} pass the gate "
            f"(min_bbox_px={settings.min_face_bbox_px}, min_det_score={settings.min_det_score})"
        )

    output = {
        "config": {
            "face_model_pack": settings.face_model_pack,
            "min_face_bbox_px": settings.min_face_bbox_px,
            "min_det_score": settings.min_det_score,
            "match_threshold": settings.match_threshold,
        },
        "images": images,
    }
    args.out.write_text(json.dumps(output, indent=2))
    total_faces = sum(len(im["faces"]) for im in images)
    total_gated = sum(1 for im in images for f in im["faces"] if f["passes_gate"])
    print(f"\nWrote {args.out} -- {len(images)} images, {total_faces} faces detected, {total_gated} pass the gate.")

    if args.pairwise_csv is not None:
        if len(all_gated) < 2:
            print("Fewer than 2 gated faces -- skipping pairwise similarity output.", file=sys.stderr)
            return

        embeddings = np.array([e for _, _, e in all_gated])
        sims = embeddings @ embeddings.T
        rows = []
        n = len(all_gated)
        for a in range(n):
            for b in range(a + 1, n):
                file_a, idx_a, _ = all_gated[a]
                file_b, idx_b, _ = all_gated[b]
                rows.append((float(sims[a, b]), file_a, idx_a, file_b, idx_b))
        rows.sort(reverse=True)

        with args.pairwise_csv.open("w") as f:
            f.write("cosine_score,file_a,face_a,file_b,face_b\n")
            for score, file_a, idx_a, file_b, idx_b in rows:
                f.write(f"{score:.4f},{file_a},{idx_a},{file_b},{idx_b}\n")

        above = sum(1 for score, *_ in rows if score >= settings.match_threshold)
        print(
            f"Wrote {args.pairwise_csv} -- {len(rows)} pairs, sorted by similarity descending. "
            f"At MATCH_THRESHOLD={settings.match_threshold}, {above} pairs would match."
        )


if __name__ == "__main__":
    main()
