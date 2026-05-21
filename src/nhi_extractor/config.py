"""Project-wide constants. All paths and tunables live here."""

from pathlib import Path

# --- Source ---
SOURCE_URL = "https://www.nhi.gov.tw/ch/cp-7593-ad2a9-3397-1.html"
UPDATE_DATE_SELECTOR = "body > main > div.contentbox > section.pubInfo > dl > div:nth-child(2) > dd > time"
DOCX_LINK_PATTERN = r".*\.docx$"

# --- Output ---
TOPIC_PREFIX = "臺灣全民健康保險藥品給付規定/藥品健保給付/健保規定 (Taiwan NHI) \n"
SECTION_PATH_SEPARATOR = " > "

# --- Token budget (spec §2.3) ---
TARGET_BUDGET = 6000   # aim for this; chunker descends past it
HARD_BUDGET = 7000     # never exceed this; pipeline fails loudly if any item does
TIKTOKEN_ENCODING = "cl100k_base"

# --- has_significant_body threshold (spec §4.3) ---
TRIVIAL_BODY_TOKEN_THRESHOLD = 200

# --- Paths ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "regulations" / "medication"
CHAPTERS_DIR = DATA_DIR / "chapters"      # downloaded DOCX
CHANGELOG_PATH = PROJECT_ROOT / "CHANGELOG.md"
