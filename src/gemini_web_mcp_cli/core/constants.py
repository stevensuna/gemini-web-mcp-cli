"""Constants for the Gemini web interface.

Endpoints, RPC IDs, model hashes, headers, error codes.
"""

import base64
import hashlib
import json
from enum import IntEnum, StrEnum


class Endpoint(StrEnum):
    """Gemini web interface endpoints."""

    GOOGLE = "https://www.google.com"
    INIT = "https://gemini.google.com/app"
    GENERATE = (
        "https://gemini.google.com/_/BardChatUi/data/"
        "assistant.lamda.BardFrontendService/StreamGenerate"
    )
    BATCH_EXEC = "https://gemini.google.com/_/BardChatUi/data/batchexecute"
    UPLOAD = "https://content-push.googleapis.com/upload"
    ROTATE_COOKIES = "https://accounts.google.com/RotateCookies"
    PROCESS_GEM_FILE = (
        "https://gemini.google.com/_/BardChatUi/data/"
        "assistant.lamda.BardFrontendService/ProcessFile"
    )


class RPC(StrEnum):
    """Google RPC IDs used in the Gemini web interface via batchexecute."""

    # Chat management
    LIST_CHATS = "MaZiqc"
    READ_CHAT = "hNvQHb"
    DELETE_CHAT = "GzXR5e"

    # Gem management
    LIST_GEMS = "CNgdBe"
    CREATE_GEM = "oMH3Zd"
    UPDATE_GEM = "kHv0Vd"
    DELETE_GEM = "UXcSJb"
    LIST_NLM_NOTEBOOKS = "NXpLKc"

    # Activity
    BARD_ACTIVITY = "ESY5D"

    # Status / polling
    STATUS_POLL = "aPya6c"
    ASYNC_POLL = "kwDCne"  # Deep Research progress, video gen completion

    # Post-processing
    POST_PROCESS = "PCck7e"

    # Page init RPCs (discovered from live capture)
    INIT_CONFIG = "otAQ7b"
    INIT_FEATURES = "GPRiHf"
    INIT_SETTINGS = "maGuAc"
    INIT_STATE = "cYRIkd"
    INIT_CAPABILITIES = "ozz5Z"
    SYNC_STATE = "L5adhe"
    USER_PREFS = "K4WWud"
    USAGE_INFO = "qpEbW"
    ACCOUNT_INFO = "o30O0e"
    HISTORY_STATE = "DYBcR"
    NOTIFICATION_STATE = "ku4Jyf"


# Header used to select the model
MODEL_HEADER_KEY = "x-goog-ext-525001261-jspb"

# Additional headers discovered from live capture
TRACKING_HEADER_KEY = "x-goog-ext-73010989-jspb"
SESSION_HEADER_KEY = "x-goog-ext-525005358-jspb"


# Thinking level is the second header-tail number and inner[80].
# Captured from the live picker on 2026-10-13: Low=1, High=2 (the old
# Extended thinking toggle), Medium=4.
THINKING_TOGGLES: dict[str, int] = {"low": 1, "medium": 4, "high": 2}
THINKING_LABELS: dict[str, str] = {"low": "Low", "medium": "Medium", "high": "High"}
_TOGGLE_TO_THINKING = {str(value): name for name, value in THINKING_TOGGLES.items()}


class Model:
    """Gemini model definitions with hashes for the model selection header."""

    def __init__(
        self,
        name: str,
        hash: str | None = None,
        header_tail: str = "2",
        extended_thinking: bool = False,
    ):
        self.name = name
        self.hash = hash
        self.header_tail = header_tail
        self.extended_thinking = extended_thinking

    @property
    def header(self) -> dict[str, str]:
        """Return the model selection header dict. Empty if no hash (unspecified model)."""
        if not self.hash:
            return {}
        return {
            MODEL_HEADER_KEY: (
                f'[1,null,null,null,"{self.hash}",null,null,0,[4,5,6,8],'
                f"null,null,2,null,null,{self.header_tail}]"
            )
        }

    @property
    def thinking_level(self) -> str:
        """``low``, ``medium``, or ``high``. Models without a pair stay low."""
        category, sep, toggle = self.header_tail.partition(",")
        if not sep or not category:
            return "low"
        return _TOGGLE_TO_THINKING.get(toggle, "low")

    @property
    def thinking_label(self) -> str:
        """Picker label for this model's thinking level (Low, Medium, High)."""
        return THINKING_LABELS[self.thinking_level]

    def header_tail_pair(self) -> tuple[int, int] | None:
        """Category and thinking-level toggle, or None when the tail is not a pair."""
        category, sep, toggle = self.header_tail.partition(",")
        if not sep:
            return None
        try:
            return int(category), int(toggle)
        except ValueError:
            return None

    def with_thinking_level(self, level: str) -> "Model":
        """Return this model with Google's Thinking level set.

        Low is 1, Medium is 4, and High is 2. High is the control formerly
        labeled Extended thinking.
        """
        key = level.strip().lower()
        try:
            toggle = THINKING_TOGGLES[key]
        except KeyError:
            known = ", ".join(THINKING_LABELS)
            raise ValueError(
                f"Unknown thinking level: {level!r}. Available: {known}"
            ) from None
        if self.thinking_level == key:
            return self
        category, sep, _ = self.header_tail.partition(",")
        if not sep:
            category = "1"
        return Model(
            self.name,
            self.hash,
            header_tail=f"{category},{toggle}",
            extended_thinking=(key == "high"),
        )

    def with_extended_thinking(self, enabled: bool = True) -> "Model":
        """Return this model with Thinking level High, the old Extended toggle."""
        if not enabled or self.thinking_level == "high":
            return self
        return self.with_thinking_level("high")

    def __repr__(self) -> str:
        return f"Model(name={self.name!r}, hash={self.hash!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Model):
            return self.name == other.name
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.name)


# Known model-header metadata captured from the live Gemini web UI (Oct 13, 2026).
# 3.8 Flash kept the fast-category hash previously labeled 3.7 and 3.6.
# 4 Argon is a new hash. Thinking level is the tail's second number
# (Low=1, Medium=4, High=2) on whichever model is selected.
MODELS: dict[str, Model] = {
    "unspecified": Model("unspecified", None),
    # Current models (captured from live UI model picker)
    "lite": Model("lite", "8c46e95b1a07cecc", header_tail="6,1"),
    "fast": Model("fast", "56fdd199312815e2", header_tail="1,1"),  # Gemini 3.8 Flash
    "thinking": Model(
        "thinking",
        "56fdd199312815e2",
        header_tail="1,2",
        extended_thinking=True,
    ),
    "pro": Model("pro", "e6fa609c3fa255c0", header_tail="3,1"),
    "argon": Model("argon", "95a4c0abcba24364", header_tail="8,1"),  # Gemini 4 Argon
}

# Short aliases for convenience (gemcli chat "hi" -m pro)
MODEL_ALIASES: dict[str, str] = {
    "flash-lite": "lite",
    "gemini-3.5-flash-lite": "lite",
    "gemini-3.1-flash-lite": "lite",  # previous Flash-Lite generation
    "flash": "fast",       # "flash" is a common alias for the fast model
    "preview": "fast",     # backward compat with earlier config
    "default": "fast",
    "gemini-3.8-flash": "fast",
    "gemini-3.8-flash-thinking": "thinking",
    "gemini-3.8-flash-extended": "thinking",
    "gemini-3.7-flash": "fast",
    "gemini-3.7-flash-thinking": "thinking",
    "gemini-3.6-flash": "fast",
    "gemini-3.5-flash": "fast",
    "gemini-3.0-flash": "fast",
    "gemini-3.7-flash-extended": "thinking",
    "gemini-3.6-thinking": "thinking",
    "gemini-3.5-thinking": "thinking",
    "gemini-3.0-flash-thinking": "thinking",
    "gemini-3.1-pro": "pro",
    "gemini-3.5-pro": "pro",
    "gemini-3.0-pro": "pro",
    "gemini-3.1-omni": "pro",
    "gemini-omni": "pro",
    "omni": "pro",
    "gemini-4-argon": "argon",
    "gemini-4": "argon",
    "4-argon": "argon",
}

DEFAULT_MODEL = MODELS["fast"]

# Models that require BotGuard token (Token Factory) for model switching.
# Extended thinking is also routed through Token Factory because its model
# header variant must be signed by the browser.
TOKEN_FACTORY_MODELS = {"pro", "thinking", "argon"}

# Chrome User-Agent for Token Factory requests (macOS Chrome 145)
CHROME_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)

# API key for x-browser-validation computation
XBV_API_KEY = "AIzaSyDr2UxVnv_U85AbhhY8XSHSIavUW0DC-sY"

# Google Drive Picker API key (embedded in Google's public Drive Picker JS library,
# used for clients6.google.com/drive/v2internal calls with SAPISID auth)
DRIVE_PICKER_API_KEY = "AIzaSyAw-cTyp9Xotzvu3vNDWhDU3E9NConkKxQ"

# Chrome-like headers for Token Factory HTTP replay
CHROME_HEADERS: dict[str, str] = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
    "Origin": "https://gemini.google.com",
    "Referer": "https://gemini.google.com/",
    "User-Agent": CHROME_USER_AGENT,
    "X-Same-Domain": "1",
    "x-browser-channel": "stable",
    "x-browser-year": "2026",
    "x-client-data": "CJWJywE=",
    "Sec-Ch-Ua": '"Chromium";v="145", "Google Chrome";v="145", "Not-A.Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}


def compute_xbv(user_agent: str) -> str:
    """Compute x-browser-validation header: BASE64(SHA-1(API_KEY + UA))."""
    return base64.b64encode(
        hashlib.sha1((XBV_API_KEY + user_agent).encode()).digest()
    ).decode()


def rewrite_captured_model_header(value: str, model: Model) -> str:
    """Point a captured JSPB model header at ``model`` and keep every other field.

    Live headers (Oct 2026) continue past the category/thinking pair with a
    session id and build label. Category is index 14 and the thinking level is
    index 15, which is also where the short template puts that pair. Replacing
    the whole header would drop the fields Chrome added after the pair.
    """
    fallback = model.header.get(MODEL_HEADER_KEY, value)
    if not model.hash:
        return value
    try:
        header = json.loads(value)
    except json.JSONDecodeError:
        return fallback
    pair = model.header_tail_pair()
    if not isinstance(header, list) or pair is None or len(header) < 16:
        return fallback
    header[4] = model.hash
    header[14], header[15] = pair
    return json.dumps(header, separators=(",", ":"))


def get_model(name: str) -> Model:
    """Look up a model by name or alias. Raises ValueError if not found."""
    # Check direct name first
    if name in MODELS:
        return MODELS[name]
    # Check aliases
    if name in MODEL_ALIASES:
        return MODELS[MODEL_ALIASES[name]]
    # List available options
    all_options = sorted(set(list(MODELS.keys()) + list(MODEL_ALIASES.keys())))
    raise ValueError(
        f"Unknown model: {name!r}. Available: {', '.join(all_options)}"
    )


class ErrorCode(IntEnum):
    """Known error codes returned from the Gemini server."""

    TEMPORARY_ERROR = 1013
    USAGE_LIMIT_EXCEEDED = 1037
    MODEL_INCONSISTENT = 1050
    MODEL_HEADER_INVALID = 1052
    IP_TEMPORARILY_BLOCKED = 1060


# Standard headers for Gemini requests
GEMINI_HEADERS: dict[str, str] = {
    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
    "Host": "gemini.google.com",
    "Origin": "https://gemini.google.com",
    "Referer": "https://gemini.google.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36"
    ),
    "X-Same-Domain": "1",
}

ROTATE_COOKIES_HEADERS: dict[str, str] = {
    "Content-Type": "application/json",
}

UPLOAD_HEADERS: dict[str, str] = {
    "Push-ID": "feeds/mcudyrk2a4khkz",
}

# Regex patterns for extracting tokens from the Gemini init page HTML
TOKEN_PATTERNS: dict[str, str] = {
    "snlm0e": r'"SNlM0e":\s*"(.*?)"',
    "cfb2h": r'"cfb2h":\s*"(.*?)"',
    "fdrfje": r'"FdrFJe":\s*"(.*?)"',
}

# Regex pattern for extracting user email from WIZ_global_data.oPEP7c
EMAIL_PATTERN = r'"oPEP7c":\s*"([^"]+@[^"]+)"'

# Cookie names
COOKIE_1PSID = "__Secure-1PSID"
COOKIE_1PSIDTS = "__Secure-1PSIDTS"
COOKIE_DOMAIN = ".google.com"

# Auto-refresh interval for cookies (seconds)
COOKIE_REFRESH_INTERVAL = 540  # 9 minutes
COOKIE_REFRESH_COOLDOWN = 60  # Minimum seconds between refresh attempts

# Rotate cookies request body
ROTATE_COOKIES_BODY = '[000,"-0000000000000000000"]'

# Config paths
CONFIG_DIR_NAME = ".gemini-web-mcp-cli"
NLM_CONFIG_DIR_NAME = ".notebooklm-mcp-cli"
PROFILES_DIR = "profiles"
CONFIG_FILE = "config.json"
AUTH_FILE = "auth.json"

# Environment variables
ENV_PROFILE = "GEMCLI_PROFILE"
DEFAULT_PROFILE_NAME = "default"

# Request ID management
REQID_INCREMENT = 100000

# StreamGenerate inner_req_list size
INNER_REQ_LIST_SIZE = 70

# Tool activation IDs for inner_req_list[49]
VIDEO_TOOL_ID = 11  # Activates Gemini Omni video generation (Veo 3.1 engine)
IMAGE_TOOL_ID = 14  # Activates image generation — Nano Banana 2 (Flash) and Nano Banana Pro
MUSIC_TOOL_ID = 21  # Activates Lyria 3.5 music generation

# ── Video orientation (Gemini Omni) ────────────────────────────────────────
# The Omni video UI exposes an aspect-ratio control with two options. Chrome
# encodes the choice in two body fields (captured from the live UI, Feb 2026):
#   inner[55]     = [[16]] landscape / [[17]] portrait (aspect-ratio IDs)
#   inner[0][9]   = [..., [[null, null, null, 1|2]]] (orientation flag)
# Landscape is the UI default.
VIDEO_ORIENTATIONS: dict[str, int] = {
    "landscape": 16,  # Landscape (16:9)
    "portrait": 17,   # Portrait (9:16)
}
VIDEO_ORIENTATION_FLAGS: dict[str, int] = {
    "landscape": 1,
    "portrait": 2,
}
# Dropdown labels used by the Token Factory to drive Chrome's video UI
VIDEO_ORIENTATION_LABELS: dict[str, str] = {
    "landscape": "Landscape (16:9)",
    "portrait": "Portrait (9:16)",
}
# Common aliases accepted from users
VIDEO_ORIENTATION_ALIASES: dict[str, str] = {
    "16:9": "landscape",
    "horizontal": "landscape",
    "wide": "landscape",
    "9:16": "portrait",
    "vertical": "portrait",
    "shorts": "portrait",
}


def normalize_video_orientation(orientation: str | None) -> str | None:
    """Normalize an orientation name/alias to 'landscape' or 'portrait'.

    Returns None when orientation is None. Raises ValueError for unknown values.
    """
    if orientation is None:
        return None
    key = orientation.strip().lower()
    key = VIDEO_ORIENTATION_ALIASES.get(key, key)
    if key not in VIDEO_ORIENTATIONS:
        valid = ", ".join(sorted(set(VIDEO_ORIENTATIONS) | set(VIDEO_ORIENTATION_ALIASES)))
        raise ValueError(f"Unknown video orientation: {orientation!r}. Valid: {valid}")
    return key


# ── Image aspect ratios (Nano Banana image UI) ─────────────────────────────
# The Images composer exposes 1:1, 9:16, 3:4, 4:3, 16:9. Chrome encodes the
# selection at inner[55] (aspect id) and inner[0][9][6] (label string).
IMAGE_ASPECTS: dict[str, int] = {
    "9:16": 59,
    "3:4": 60,
    "1:1": 61,
    "4:3": 62,
    "16:9": 63,
}
IMAGE_ASPECT_ALIASES: dict[str, str] = {
    "square": "1:1",
    "portrait": "9:16",
    "vertical": "9:16",
    "landscape": "16:9",
    "horizontal": "16:9",
    "wide": "16:9",
}


def normalize_image_aspect(aspect: str | None) -> str | None:
    """Normalize an image aspect ratio to its canonical 'W:H' form.

    Returns None when aspect is None. Raises ValueError for unknown values.
    """
    if aspect is None:
        return None
    key = aspect.strip().lower()
    key = IMAGE_ASPECT_ALIASES.get(key, key)
    if key not in IMAGE_ASPECTS:
        valid = ", ".join(sorted(set(IMAGE_ASPECTS) | set(IMAGE_ASPECT_ALIASES)))
        raise ValueError(f"Unknown image aspect ratio: {aspect!r}. Valid: {valid}")
    return key


# ── Music composer controls (Lyria 3.5 UI) ─────────────────────────────────
# The Music composer exposes Length, Vocals, and Genre dropdowns plus template
# cards. Chrome encodes the selections in inner[55] (option ids) and
# inner[0][9][6] (structured option codes).
MUSIC_LENGTHS: dict[str, str] = {
    "short": "Short",
    "standard": "Standard",
}
MUSIC_VOCALS: dict[str, str] = {
    "custom": "Custom, Based on your prompt",
    "vocals": "Vocals on",
    "vocals_on": "Vocals on",
    "instrumental": "Instrumental",
}
MUSIC_GENRES: tuple[str, ...] = (
    "Pop",
    "Hip-hop & rap",
    "Rock",
    "K-pop",
    "Latin",
    "Electronic",
    "R&B",
    "Country",
    "Afrobeats",
    "Reggae",
    "Jazz & blues",
    "Classical",
    "Folk",
    "Lo-fi",
    "Acoustic",
    "Cinematic",
    "Ambient",
)
MUSIC_GENRE_ALIASES: dict[str, str] = {
    "hip hop": "Hip-hop & rap",
    "hip-hop": "Hip-hop & rap",
    "hiphop": "Hip-hop & rap",
    "rap": "Hip-hop & rap",
    "rnb": "R&B",
    "r'n'b": "R&B",
    "r and b": "R&B",
    "jazz": "Jazz & blues",
    "blues": "Jazz & blues",
    "lofi": "Lo-fi",
    "kpop": "K-pop",
    "afrobeat": "Afrobeats",
    "afro beats": "Afrobeats",
}
MUSIC_TEMPLATES: tuple[str, ...] = (
    "Soundscape",
    "Background music",
    "Memorize something",
    "Text messages",
    "Intro music",
    "Montage",
    "Say it with a track",
    "Brand jingle",
    "Ringtone",
    "Streaming",
    "Speech to song",
    "Rap battle",
    "Comedy",
    "Team anthem",
    "Sports recap",
    "Party invite",
    "Happy birthday",
    "Friend appreciation",
    "Love story",
    "Birthday roast",
    "Ode to your pet",
    "Hometown tribute",
    "Weather report",
    "Business promo",
)


def normalize_music_length(length: str | None) -> str | None:
    """Normalize a music length to its UI dropdown label."""
    if length is None:
        return None
    key = length.strip().lower()
    if key not in MUSIC_LENGTHS:
        valid = ", ".join(MUSIC_LENGTHS)
        raise ValueError(f"Unknown music length: {length!r}. Valid: {valid}")
    return MUSIC_LENGTHS[key]


def normalize_music_vocals(vocals: str | None) -> str | None:
    """Normalize a music vocals mode to its UI dropdown label."""
    if vocals is None:
        return None
    key = vocals.strip().lower().replace("-", "_").replace(" ", "_")
    if key not in MUSIC_VOCALS:
        valid = ", ".join(sorted(set(MUSIC_VOCALS)))
        raise ValueError(f"Unknown music vocals mode: {vocals!r}. Valid: {valid}")
    return MUSIC_VOCALS[key]


def normalize_music_genre(genre: str | None) -> str | None:
    """Normalize a music genre to its UI dropdown label.

    'custom' (or None) leaves the genre based on the prompt.
    """
    if genre is None:
        return None
    key = genre.strip()
    if key.lower() in ("custom", "none", "prompt"):
        return "Custom, Based on your prompt"
    for label in MUSIC_GENRES:
        if key.lower() == label.lower():
            return label
    alias = MUSIC_GENRE_ALIASES.get(key.lower())
    if alias:
        return alias
    valid = ", ".join(MUSIC_GENRES)
    raise ValueError(f"Unknown music genre: {genre!r}. Valid: {valid}")

# Response parsing paths
RESPONSE_PATHS = {
    "inner_json": [2],
    "metadata": [1],
    "candidates": [4],
    "completion": [25],
    "error_code": [5, 2, 0, 1, 0],
    # Per candidate
    "candidate_rcid": [0],
    "candidate_text": [1, 0],
    "candidate_thoughts": [37, 0, 0],
    "candidate_web_images": [12, 1],
    "candidate_generated_images": [12, 7, 0],
    "candidate_generated_music": [12, 86],
    "candidate_generated_video": [12, 59],
}
