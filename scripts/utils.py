import re
import unicodedata
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
VENV_PYTHON = SKILL_DIR / ".venv" / "bin" / "python3"
DB_PATH = SKILL_DIR / "db" / "nudge_library.db"
MANIFEST_PATH = SKILL_DIR / "manifest.json"

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
TARGET_CHUNK_TOKENS = 450
OVERLAP_TOKENS = 60
MIN_CHUNK_TOKENS = 80

CHAPTER_PATTERNS = [
    re.compile(
        r"^(\d+)\.\s+[A-Z]", re.MULTILINE
    ),
    re.compile(
        r"^Chapter\s+(\d+)", re.MULTILINE | re.IGNORECASE
    ),
    re.compile(
        r"^CHAPTER\s+(\d+)", re.MULTILINE
    ),
    re.compile(
        r"^Part\s+(One|Two|Three|Four|Five|\d+)",
        re.MULTILINE | re.IGNORECASE,
    ),
    re.compile(
        r"^(HOW|WHAT|WHY|WHEN|WHERE|WHO|WHICH|CAN|DO|IS|ARE|WILL|SHOULD)\s",
        re.MULTILINE,
    ),
]

JUNK_LINES = [
    re.compile(r"^Anna's? Archive$", re.IGNORECASE),
    re.compile(r"^\d+\s*$"),
    re.compile(r"^Page\s+\d+", re.IGNORECASE),
    re.compile(r"^\s*$"),
    re.compile(r"^[A-Z\s]{2,30}$"),
]


def clean_text(raw: str) -> str:
    text = raw
    text = unicodedata.normalize("NFKD", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"-\n(\w)", r"\1", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_junk_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    for pat in JUNK_LINES:
        if pat.match(stripped):
            return True
    return False


def approx_token_count(text: str) -> int:
    return max(1, int(len(text.split()) * 1.3))


def detect_chapters(pages: list[dict]) -> list[dict]:
    has_section_titles = any("section_title" in p for p in pages)

    if has_section_titles:
        chapters = []
        seen = set()
        for page in pages:
            title = page.get("section_title", "Unknown")
            if title not in seen:
                seen.add(title)
                chapters.append({
                    "title": title,
                    "page_start": page["page_num"],
                    "page_end": page["page_num"],
                })
            else:
                for ch in chapters:
                    if ch["title"] == title:
                        ch["page_end"] = page["page_num"]
                        break
        if not chapters:
            chapters.append({"title": "All", "page_start": 1, "page_end": pages[-1]["page_num"]})
        return chapters

    chapters = []
    current_chapter = "Front Matter"
    current_start_page = 1

    for page in pages:
        text = page["text"]
        lines = text.split("\n")
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            for pat in CHAPTER_PATTERNS:
                m = pat.match(stripped)
                if m:
                    if current_chapter != "Front Matter" or chapters:
                        chapters.append(
                            {
                                "title": current_chapter,
                                "page_start": current_start_page,
                                "page_end": page["page_num"] - 1,
                            }
                        )
                    current_chapter = stripped
                    if len(current_chapter) > 120:
                        current_chapter = current_chapter[:120]
                    current_start_page = page["page_num"]
                    break

    chapters.append(
        {
            "title": current_chapter,
            "page_start": current_start_page,
            "page_end": pages[-1]["page_num"] if pages else 1,
        }
    )
    return chapters


def assign_chapter(page_num: int, chapters: list[dict]) -> str:
    for ch in chapters:
        if ch["page_start"] <= page_num <= ch["page_end"]:
            return ch["title"]
    return "Unknown"


def chunk_pages(
    pages: list[dict], chapters: list[dict]
) -> list[dict]:
    paragraphs = []
    for page in pages:
        text = page["text"]
        page_num = page["page_num"]
        chapter = assign_chapter(page_num, chapters)

        lines = text.split("\n")
        filtered = [l for l in lines if not is_junk_line(l)]
        cleaned = "\n".join(filtered).strip()
        if not cleaned:
            continue

        paras = re.split(r"\n\n+", cleaned)
        for p in paras:
            p = p.strip()
            if not p or approx_token_count(p) < 10:
                continue
            paragraphs.append(
                {
                    "text": p,
                    "page_num": page_num,
                    "chapter": chapter,
                }
            )

    chunks = []
    current_text = ""
    current_pages = set()
    current_chapter = ""

    for para in paragraphs:
        para_tokens = approx_token_count(para["text"])
        current_tokens = approx_token_count(current_text)

        if current_chapter and current_chapter != para["chapter"]:
            if current_text and approx_token_count(current_text) >= MIN_CHUNK_TOKENS:
                chunks.append(_make_chunk(current_text, current_pages, current_chapter, len(chunks)))
            current_text = para["text"]
            current_pages = {para["page_num"]}
            current_chapter = para["chapter"]
            continue

        combined = (current_text + "\n\n" + para["text"]).strip() if current_text else para["text"]

        if approx_token_count(combined) > TARGET_CHUNK_TOKENS + OVERLAP_TOKENS:
            if current_text and approx_token_count(current_text) >= MIN_CHUNK_TOKENS:
                chunks.append(_make_chunk(current_text, current_pages, current_chapter, len(chunks)))

            overlap_text = _get_overlap_text(current_text)
            current_text = (overlap_text + "\n\n" + para["text"]).strip() if overlap_text else para["text"]
            current_pages = {para["page_num"]}
            current_chapter = para["chapter"]
        else:
            current_text = combined
            current_pages.add(para["page_num"])
            current_chapter = para["chapter"]

    if current_text and approx_token_count(current_text) >= MIN_CHUNK_TOKENS:
        chunks.append(_make_chunk(current_text, current_pages, current_chapter, len(chunks)))

    return chunks


def _make_chunk(text: str, pages: set, chapter: str, index: int) -> dict:
    sorted_pages = sorted(pages)
    return {
        "index": index,
        "text": text,
        "chapter": chapter,
        "page_start": sorted_pages[0],
        "page_end": sorted_pages[-1],
        "token_count": approx_token_count(text),
    }


def _get_overlap_text(text: str) -> str:
    words = text.split()
    overlap_word_count = int(OVERLAP_TOKENS / 1.3)
    if len(words) <= overlap_word_count:
        return text
    return " ".join(words[-overlap_word_count:])


import numpy as np


def serialize_embedding(emb: np.ndarray) -> bytes:
    return emb.astype(np.float32).tobytes()


def deserialize_embedding(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)
