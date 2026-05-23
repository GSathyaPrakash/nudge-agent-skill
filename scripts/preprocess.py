#!/usr/bin/env python3
import argparse
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import (
    DB_PATH,
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    MANIFEST_PATH,
    SKILL_DIR,
    chunk_pages,
    clean_text,
    detect_chapters,
    serialize_embedding,
    approx_token_count,
)


def extract_epub_text(epub_path: str) -> list[dict]:
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup

    book = epub.read_epub(epub_path)
    pages = []
    spine_ids = [item_id for item_id, _ in book.spine]
    doc_map = {}
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        doc_map[item.get_id()] = item

    ordered_section = 0
    for sid in spine_ids:
        if sid not in doc_map:
            continue
        item = doc_map[sid]
        soup = BeautifulSoup(item.get_content(), "html.parser")
        text = soup.get_text(separator="\n", strip=True)
        text = clean_text(text)
        if not text or len(text) < 20:
            continue
        ordered_section += 1
        pages.append({"page_num": ordered_section, "text": text})

    return pages


def extract_pdf_text(pdf_path: str) -> list[dict]:
    import pdfplumber

    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        has_text = False
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if text and text.strip():
                has_text = True
                break

        if not has_text:
            print(f"  No text layer detected. Using OCR (this will be slower)...")
            pages = _ocr_extract(pdf_path, total)
        else:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text:
                    cleaned = clean_text(text)
                    if cleaned:
                        pages.append({"page_num": i + 1, "text": cleaned})
                if (i + 1) % 50 == 0:
                    print(f"  Extracted {i + 1}/{total} pages")

    return pages


def _ocr_extract(pdf_path: str, total_pages: int) -> list[dict]:
    import pdf2image
    import pytesseract

    pages = []
    batch_size = 10
    for start in range(1, total_pages + 1, batch_size):
        end = min(start + batch_size - 1, total_pages)
        images = pdf2image.convert_from_path(
            pdf_path, first_page=start, last_page=end, dpi=300
        )
        for idx, img in enumerate(images):
            page_num = start + idx
            text = pytesseract.image_to_string(img)
            cleaned = clean_text(text)
            if cleaned:
                pages.append({"page_num": page_num, "text": cleaned})
        print(f"  OCR'd {end}/{total_pages} pages")

    return pages


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS books (
            book_id      TEXT PRIMARY KEY,
            title        TEXT NOT NULL,
            author       TEXT,
            total_pages  INTEGER,
            file_path    TEXT NOT NULL,
            processed_at TEXT NOT NULL
        )
    """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id     TEXT PRIMARY KEY,
            book_id      TEXT NOT NULL,
            chapter      TEXT,
            page_start   INTEGER,
            page_end     INTEGER,
            text         TEXT NOT NULL,
            embedding    BLOB NOT NULL,
            token_count  INTEGER,
            FOREIGN KEY (book_id) REFERENCES books(book_id)
        )
    """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunks_book ON chunks(book_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunks_chapter ON chunks(chapter)"
    )
    conn.commit()
    return conn


def generate_book_id(file_path: str) -> str:
    return hashlib.sha256(file_path.encode()).hexdigest()[:16]


def infer_metadata(file_path: str) -> dict:
    import re
    name = Path(file_path).stem

    parts = re.split(r"\s*--\s*", name)

    title = parts[0].strip() if parts else name
    author = None
    year = None

    for part in parts[1:]:
        part = part.strip()
        if re.match(r"^\d{4}$", part):
            year = part
        elif re.match(r"^[a-f0-9]{10,}$", part):
            continue
        elif re.match(r"Anna'?s?\s*Archive", part, re.IGNORECASE):
            continue
        elif not author and part:
            author = part

    return {"title": title, "author": author, "year": year}


def re_sub(pattern, replacement, string):
    import re
    return re.sub(pattern, replacement, string)


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH) as f:
            return json.load(f)
    return {"books": []}


def save_manifest(manifest: dict):
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)


def process_book(file_path: str, conn: sqlite3.Connection, force: bool = False):
    file_path = str(Path(file_path).resolve())
    book_id = generate_book_id(file_path)

    existing = conn.execute(
        "SELECT book_id FROM books WHERE book_id = ?", (book_id,)
    ).fetchone()

    if existing and not force:
        print(f"  Already indexed (use --force to re-index): {Path(file_path).name}")
        return

    if existing and force:
        conn.execute("DELETE FROM chunks WHERE book_id = ?", (book_id,))
        conn.execute("DELETE FROM books WHERE book_id = ?", (book_id,))
        conn.commit()
        print(f"  Re-indexing: {Path(file_path).name}")
    else:
        print(f"  Processing: {Path(file_path).name}")

    meta = infer_metadata(file_path)
    print(f"  Title: {meta['title']}")
    if meta["author"]:
        print(f"  Author: {meta['author']}")

    t0 = time.time()
    ext = Path(file_path).suffix.lower()
    if ext == ".epub":
        print(f"  Format: EPUB")
        pages = extract_epub_text(file_path)
    elif ext == ".pdf":
        print(f"  Format: PDF")
        pages = extract_pdf_text(file_path)
    elif ext in (".txt", ".md"):
        print(f"  Format: {ext}")
        raw = Path(file_path).read_text(encoding="utf-8", errors="ignore")
        text = clean_text(raw)
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        pages = []
        for i, para in enumerate(paragraphs, 1):
            pages.append({"page_num": i, "text": para})
    else:
        print(f"  ERROR: Unsupported format: {ext}")
        return
    if not pages:
        print(f"  ERROR: No text extracted from {file_path}")
        return
    print(f"  Extracted {len(pages)} pages in {time.time()-t0:.1f}s")

    t0 = time.time()
    chapters = detect_chapters(pages)
    print(f"  Detected {len(chapters)} sections")

    chunks = chunk_pages(pages, chapters)
    print(f"  Created {len(chunks)} chunks in {time.time()-t0:.1f}s")

    if not chunks:
        print(f"  ERROR: No chunks created from {file_path}")
        return

    total_tokens = sum(c["token_count"] for c in chunks)
    print(f"  Total tokens: {total_tokens}")

    print(f"  Loading embedding model ({EMBEDDING_MODEL})...")
    t0 = time.time()
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(EMBEDDING_MODEL)
    print(f"  Model loaded in {time.time()-t0:.1f}s")

    print(f"  Generating embeddings for {len(chunks)} chunks...")
    t0 = time.time()
    texts = [c["text"] for c in chunks]
    embeddings = model.encode(texts, batch_size=32, show_progress_bar=True)
    print(f"  Embeddings generated in {time.time()-t0:.1f}s")

    total_pages = max(c["page_end"] for c in chunks)
    conn.execute(
        "INSERT OR REPLACE INTO books VALUES (?, ?, ?, ?, ?, ?)",
        (
            book_id,
            meta["title"],
            meta["author"],
            total_pages,
            file_path,
            time.strftime("%Y-%m-%dT%H:%M:%S"),
        ),
    )

    for i, chunk in enumerate(chunks):
        chunk_id = f"{book_id}_{i:05d}"
        emb_blob = serialize_embedding(embeddings[i])
        conn.execute(
            "INSERT OR REPLACE INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                chunk_id,
                book_id,
                chunk["chapter"],
                chunk["page_start"],
                chunk["page_end"],
                chunk["text"],
                emb_blob,
                chunk["token_count"],
            ),
        )

    conn.commit()

    manifest = load_manifest()
    manifest["books"] = [
        b for b in manifest["books"] if b["book_id"] != book_id
    ]
    manifest["books"].append(
        {
            "book_id": book_id,
            "title": meta["title"],
            "author": meta["author"],
            "total_pages": total_pages,
            "chunks": len(chunks),
            "total_tokens": total_tokens,
            "file_path": file_path,
        }
    )
    save_manifest(manifest)

    print(f"  Done! {len(chunks)} chunks indexed.\n")


def main():
    parser = argparse.ArgumentParser(
        description="Index books (PDF, EPUB, TXT, MD) for the Nudge Agent"
    )
    parser.add_argument(
        "files", nargs="+", help="Book file(s) or glob pattern to index (PDF, EPUB, TXT, MD)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-index even if already processed",
    )
    args = parser.parse_args()

    import glob as globmod

    all_files = []
    for pattern in args.files:
        expanded = globmod.glob(pattern)
        if not expanded:
            print(f"WARNING: No files matched: {pattern}")
        all_files.extend(expanded)

    if not all_files:
        print("ERROR: No files to process.")
        sys.exit(1)

    all_files = sorted(set(all_files))
    print(f"Found {len(all_files)} file(s) to process\n")

    conn = init_db()
    for f in all_files:
        try:
            process_book(f, conn, force=args.force)
        except Exception as e:
            print(f"  ERROR processing {f}: {e}\n")
            import traceback
            traceback.print_exc()
    conn.close()

    print("All done!")


if __name__ == "__main__":
    main()
