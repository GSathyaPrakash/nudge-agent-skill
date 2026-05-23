#!/usr/bin/env python3
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import (
    DB_PATH,
    EMBEDDING_MODEL,
    MANIFEST_PATH,
    deserialize_embedding,
)


def cosine_similarity(a, b):
    import numpy as np
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def search(query: str, top_k: int = 5, expand_context: bool = True):
    if not DB_PATH.exists():
        print("ERROR: Database not found. Run preprocess.py first.", file=sys.stderr)
        return []

    conn = sqlite3.connect(str(DB_PATH))

    rows = conn.execute(
        "SELECT chunk_id, book_id, chapter, page_start, page_end, text, embedding, token_count "
        "FROM chunks"
    ).fetchall()
    conn.close()

    if not rows:
        print("ERROR: No chunks in database.", file=sys.stderr)
        return []

    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(EMBEDDING_MODEL)
    query_emb = model.encode(query)

    scored = []
    for row in rows:
        chunk_id, book_id, chapter, page_start, page_end, text, emb_blob, token_count = row
        chunk_emb = deserialize_embedding(emb_blob)
        score = cosine_similarity(query_emb, chunk_emb)
        scored.append(
            {
                "chunk_id": chunk_id,
                "book_id": book_id,
                "chapter": chapter,
                "page_start": page_start,
                "page_end": page_end,
                "text": text,
                "token_count": token_count,
                "score": score,
            }
        )

    scored.sort(key=lambda x: x["score"], reverse=True)
    candidates = scored[: top_k * 2]

    book_meta = {}
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH) as f:
            manifest = json.load(f)
        for b in manifest.get("books", []):
            book_meta[b["book_id"]] = b

    if expand_context:
        all_chunks_by_id = {r[0]: r for r in rows}
        for candidate in candidates:
            context_before = _get_neighbor(candidate, -1, all_chunks_by_id)
            context_after = _get_neighbor(candidate, 1, all_chunks_by_id)
            if context_before:
                candidate["context_before"] = context_before
            if context_after:
                candidate["context_after"] = context_after

    results = []
    seen_chapters = set()
    for c in candidates[:top_k]:
        dedup_key = (c["book_id"], c["chapter"])
        if dedup_key in seen_chapters and len(results) >= top_k // 2:
            continue
        seen_chapters.add(dedup_key)

        book = book_meta.get(c["book_id"], {})
        result = {
            "rank": len(results) + 1,
            "score": round(c["score"], 4),
            "book_title": book.get("title", "Unknown"),
            "author": book.get("author", ""),
            "chapter": c["chapter"],
            "page_start": c["page_start"],
            "page_end": c["page_end"],
            "text": c["text"],
        }
        if "context_before" in c:
            result["context_before"] = c["context_before"]["text"]
        if "context_after" in c:
            result["context_after"] = c["context_after"]["text"]
        results.append(result)

    return results


def _get_neighbor(chunk: dict, offset: int, all_chunks: dict):
    parts = chunk["chunk_id"].rsplit("_", 1)
    if len(parts) != 2:
        return None
    prefix, idx_str = parts
    try:
        neighbor_id = f"{prefix}_{int(idx_str)+offset:05d}"
    except ValueError:
        return None

    if neighbor_id not in all_chunks:
        return None

    row = all_chunks[neighbor_id]
    neighbor_book_id = row[1]
    if neighbor_book_id != chunk["book_id"]:
        return None

    return {
        "text": row[5],
        "page_start": row[3],
        "page_end": row[4],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Search indexed books for relevant passages"
    )
    parser.add_argument("--query", "-q", required=True, help="Search query")
    parser.add_argument(
        "--top-k", "-k", type=int, default=5, help="Number of results"
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=["json", "text"],
        default="json",
        help="Output format",
    )
    parser.add_argument(
        "--no-expand",
        action="store_true",
        help="Disable context expansion",
    )
    args = parser.parse_args()

    results = search(
        args.query, top_k=args.top_k, expand_context=not args.no_expand
    )

    if args.format == "json":
        output = {
            "query": args.query,
            "total_results": len(results),
            "results": results,
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        for r in results:
            print(f"{'='*60}")
            print(f"  Rank:    {r['rank']}")
            print(f"  Score:   {r['score']}")
            print(f"  Book:    {r['book_title']}")
            if r["author"]:
                print(f"  Author:  {r['author']}")
            print(f"  Chapter: {r['chapter']}")
            print(f"  Pages:   {r['page_start']}-{r['page_end']}")
            print(f"{'-'*60}")
            if "context_before" in r:
                print(f"  [Before]: ...{r['context_before'][-200:]}")
                print()
            print(f"  {r['text']}")
            if "context_after" in r:
                print()
                print(f"  [After]: {r['context_after'][:200]}...")
            print()


if __name__ == "__main__":
    main()
