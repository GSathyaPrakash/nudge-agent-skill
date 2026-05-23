# nudge-agent

A book-based nudging agent for AI coding assistants (OpenCode, Claude Code, Codex CLI, Amp, Droid).

It indexes your books into a searchable local library, then uses semantic search to find relevant passages and gives you **guidance — not answers**. Every suggestion is sourced with book name, chapter, and page number so you can verify it yourself.

**No cloud services. No API keys. No data leaves your machine.**

## How It Works

```
User asks a question
       │
       ▼
Agent searches indexed books (semantic embedding search)
       │
       ▼
Top relevant passages retrieved with context
       │
       ▼
Agent crafts a nudge response with citations (book, chapter, page)
```

### Under the Hood

- **Embedding model:** `all-MiniLM-L6-v2` (384-dimensional, runs locally on CPU, ~80 MB)
- **Chunking:** ~450-token semantic chunks with 60-token overlap, respects chapter boundaries
- **Search:** cosine similarity with context expansion (neighbor chunks included for fuller context)
- **Storage:** SQLite database (portable, no server needed)
- **OCR:** Auto-detects scanned PDFs and uses Tesseract for text extraction

## Installation

### Prerequisites

| Dependency | Why | Install |
|---|---|---|
| Python 3.10+ | Runs the scripts | System package manager |
| Tesseract OCR | Text extraction from scanned PDFs | `pacman -S tesseract` / `brew install tesseract` / `apt install tesseract-ocr` |
| Tesseract English data | English language OCR | Usually bundled, or `tesseract-ocr-eng` / `tesseract-data-eng` |
| Poppler utilities | PDF-to-image conversion for OCR | `pacman -S poppler` / `brew install poppler` / `apt install poppler-utils` |

### Quick Install

**Option A: One-command setup** (handles everything including system deps)

```bash
git clone https://github.com/GSathyaPrakash/nudge-agent-skill.git
cd nudge-agent
bash setup.sh
```

The setup script will:
1. Detect your OS (Arch, Debian/Ubuntu, Fedora, macOS)
2. Install system dependencies (Python, Tesseract, Poppler)
3. Create a Python virtual environment
4. Install all Python packages (sentence-transformers, pdfplumber, etc.)
5. Download the embedding model (~80 MB)

**Option B: Manual setup**

```bash
git clone https://github.com/GSathyaPrakash/nudge-agent-skill.git
cd nudge-agent

# Create venv and install deps
python3 -m venv .venv
.venv/bin/pip install sentence-transformers pdfplumber pytesseract pdf2image ebooklib beautifulsoup4 lxml
```

### Install for Your Agent

#### OpenCode

```bash
# User-level (available in all projects)
git clone https://github.com/GSathyaPrakash/nudge-agent-skill.git ~/.opencode/skills/nudge-agent
cd ~/.opencode/skills/nudge-agent
bash setup.sh

# Or project-level
git clone https://github.com/GSathyaPrakash/nudge-agent-skill.git .opencode/skills/nudge-agent
cd .opencode/skills/nudge-agent
bash setup.sh
```

#### Claude Code

Claude Code looks one level deep for `SKILL.md` files:

```bash
# Clone and setup
git clone https://github.com/GSathyaPrakash/nudge-agent-skill.git ~/nudge-agent
cd ~/nudge-agent
bash setup.sh

# Symlink into Claude skills directory
mkdir -p ~/.claude/skills
ln -s ~/nudge-agent ~/.claude/skills/nudge-agent
```

#### Codex CLI

```bash
git clone https://github.com/GSathyaPrakash/nudge-agent-skill.git ~/.codex/skills/nudge-agent
cd ~/.codex/skills/nudge-agent
bash setup.sh
```

#### Amp

```bash
git clone https://github.com/GSathyaPrakash/nudge-agent-skill.git ~/.config/amp/tools/nudge-agent
cd ~/.config/amp/tools/nudge-agent
bash setup.sh
```

#### Droid (Factory)

```bash
git clone https://github.com/GSathyaPrakash/nudge-agent-skill.git ~/.factory/skills/nudge-agent
cd ~/.factory/skills/nudge-agent
bash setup.sh
```

## Usage

### Indexing Books

```bash
# Single book
.venv/bin/python3 scripts/preprocess.py "/path/to/book.pdf"

# Multiple books
.venv/bin/python3 scripts/preprocess.py book1.pdf book2.epub book3.txt

# All PDFs in a directory
.venv/bin/python3 scripts/preprocess.py ~/Books/*.pdf

# Re-index (overwrite existing)
.venv/bin/python3 scripts/preprocess.py --force "/path/to/book.pdf"
```

**Supported formats:** PDF (text or scanned), EPUB, TXT, MD

The agent will also auto-index books when you say things like "add this book" and provide a path.

### Searching

```bash
# JSON output (for agent consumption)
.venv/bin/python3 scripts/search.py --query "how to be more persuasive" --top-k 5 --format json

# Human-readable output (for debugging)
.venv/bin/python3 scripts/search.py --query "how to be more persuasive" --top-k 3 --format text
```

### Example Session

```
You: I'm writing a pitch for my new app. How can I make it more persuasive?

Agent: That's a great challenge. There's an interesting finding worth considering —
in "Yes!" (Goldstein, How can inconveniencing your audience increase your
persuasiveness?, pp. 21-22), an infomercial writer changed "Operators are waiting,
please call now" to "If operators are busy, please call again" — and sales
skyrocketed. The second version implies demand rather than availability.

So here's something to think about: What does your pitch currently show investors
about what other people are already doing with your product?

In "How to Write a Good Advertisement" (Schwab, Chapter 2), he's blunt: "Three
out of four readers who notice the advertisement are lost before they reach the end
of it." Are you making it easy for investors to picture the opportunity in your
first paragraph, or are you warming up?
```

## Supported Book Formats

| Format | Text Extraction | Notes |
|---|---|---|
| PDF (text-based) | pdfplumber | Fast, accurate |
| PDF (scanned) | Tesseract OCR | Slower (~2-5 min per book), auto-detected |
| EPUB | ebooklib | Fast, clean structure |
| TXT | Direct read | Simplest format |
| Markdown | Direct read | Preserves structure |

## Performance

| Metric | 1 Book (~300 pages) | 10 Books |
|---|---|---|
| Indexing (text PDF) | ~1 min | ~10 min |
| Indexing (scanned PDF) | ~5 min (OCR) | ~50 min |
| Indexing (EPUB) | <10 sec | ~1 min |
| Search query | ~1 sec | ~2 sec |
| Database size | ~1 MB | ~10 MB |
| RAM (search) | ~400 MB | ~600 MB |

All benchmarks on CPU. No GPU required.

## Directory Structure

```
nudge-agent/
├── SKILL.md          # Skill definition (loaded by your agent)
├── setup.sh          # Automated setup script
├── scripts/
│   ├── utils.py      # Text cleaning, chunking, chapter detection
│   ├── preprocess.py # Book → chunks → SQLite pipeline
│   └── search.py     # Embed query → retrieve relevant chunks
├── db/               # Auto-created — SQLite database lives here
├── .venv/            # Auto-created — Python virtual environment
├── manifest.json     # Auto-created — book registry
└── README.md
```

## Troubleshooting

| Issue | Fix |
|---|---|
| `externally-managed-environment` error | Use the included `setup.sh` which creates a venv automatically |
| OCR not working / poor quality | Ensure `tesseract` and `tesseract-ocr-eng` are installed |
| Out of memory during indexing | Close other apps — needs ~1 GB free RAM for embedding generation |
| Poor search results | Try rephrasing queries. Re-index with different content. More books = better results |
| `poppler` not found | Install poppler utilities for your OS |

## Extending

### Adding new file formats

Edit `scripts/preprocess.py` — the `process_book()` function dispatches by file extension. Add a new `extract_*` function for your format.

### Using a better embedding model

Edit `scripts/utils.py` and change `EMBEDDING_MODEL`:
- `"all-mpnet-base-v2"` — 768-dim, ~15% better accuracy, 3x slower, ~420 MB
- `"paraphrase-multilingual-MiniLM-L12-v2"` — multilingual support

Then re-index all books with `--force`.

### Adjusting chunk size

Edit `scripts/utils.py`:
- `TARGET_CHUNK_TOKENS` — default 450 (increase for more context per chunk, decrease for precision)
- `OVERLAP_TOKENS` — default 60 (prevents losing meaning at boundaries)

## License

MIT
