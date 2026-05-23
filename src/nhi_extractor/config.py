"""Project-wide constants. All paths and tunables live here."""

from pathlib import Path

# --- Source ---
SOURCE_URL = "https://www.nhi.gov.tw/ch/cp-7593-ad2a9-3397-1.html"
UPDATE_DATE_SELECTOR = "body > main > div.contentbox > section.pubInfo > dl > div:nth-child(2) > dd > time"
DOCX_LINK_PATTERN = r".*\.docx$"
ODT_LINK_PATTERN = r".*\.odt$"

# Title-based classification of NHI source documents.
# 規定 (in-scope): 通則 + 第N節 chapters. These get downloaded + chunked.
# 附表 (out-of-scope for now, see docs/next-fixes.md Task G): application forms.
REGULATION_TITLE_PATTERN = r"^(通則|第[一二三四五六七八九十百零]+節)"
APPENDIX_FORM_TITLE_PATTERN = r"^附表"

# --- Output ---
TOPIC_PREFIX = "臺灣全民健康保險藥品給付規定/藥品健保給付/健保規定 (Taiwan NHI) \n"
SECTION_PATH_SEPARATOR = " > "

# --- Token budget (spec §2.3) ---
TARGET_BUDGET = 6000   # aim for this; chunker descends past it
HARD_BUDGET = 7000     # never exceed this; pipeline fails loudly if any item does
TIKTOKEN_ENCODING = "cl100k_base"

# --- Emit depth (Task I) ---
# Minimum tree depth at which a node may emit as a single row. Below this depth,
# the chunker MUST descend (ignoring whether the subtree fits TARGET_BUDGET).
# This decouples "editorial granularity" from "embedding ceiling" — see
# docs/emit-depth-plan.md for the design rationale.
#
# NHI source tree max depth is 5 (款 layer in 第五節 / 第八節). Setting >5 has
# no effect (no nodes that deep exist); setting <3 merges multiple drugs into
# the same row in some sections (verified pollution audit found 9/512 such rows
# under the pre-EMIT_DEPTH behavior).
EMIT_DEPTH = 5

# --- has_significant_body threshold (spec §4.3) ---
TRIVIAL_BODY_TOKEN_THRESHOLD = 200

# --- Paths ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "regulations" / "medication"
CHAPTERS_DIR = DATA_DIR / "chapters"      # downloaded DOCX
CHANGELOG_PATH = PROJECT_ROOT / "CHANGELOG.md"
