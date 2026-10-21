"""Custom exceptions for the Gemini web MCP CLI."""


class GeminiError(Exception):
    """Base exception for all Gemini-related errors."""

    pass


class AuthError(GeminiError):
    """Authentication failure: invalid cookies, expired tokens, or failed login."""

    pass


class APIError(GeminiError):
    """API-level error: unexpected response format, parsing failure, or unknown error code."""

    def __init__(self, message: str, error_code: int | None = None):
        self.error_code = error_code
        super().__init__(message)


class UsageLimitExceeded(GeminiError):
    """Usage limit exceeded (error code 1037)."""

    pass


class ModelInvalid(GeminiError):
    """Model unavailable or header invalid (error codes 1050, 1052)."""

    pass


class TemporarilyBlocked(GeminiError):
    """IP temporarily blocked by Google (error code 1060)."""

    pass


class TimeoutError(GeminiError):
    """Request timed out or watchdog triggered due to stalled stream."""

    pass


class ImageGenerationError(APIError):
    """Error during image generation or parsing image response."""

    pass


class VideoGenerationError(APIError):
    """Error during video generation or parsing video response."""

    pass


class MusicGenerationError(APIError):
    """Error during music generation or parsing music response."""

    pass


class ResearchError(APIError):
    """Error during deep research or polling for results."""

    pass


class ProfileError(GeminiError):
    """Error with profile management: not found, invalid, or filesystem issues."""

    pass


class TokenFactoryError(GeminiError):
    """Chrome/BotGuard token capture failure."""

    pass


class PromptEscaped(GeminiError):
    """Chrome sent the prompt through a request Token Factory did not capture.

    Raised instead of retrying, which would send the prompt a second time.
    Deliberately NOT a TokenFactoryError, so the client does not fall back to
    a direct HTTP request (a third copy of the prompt).
    """

    pass


class GeminiReplyError(GeminiError):
    """Gemini answered with its generic failure text instead of an answer.

    e.g. "I seem to be encountering an error. Can I try something else for
    you?" Raised so callers don't use that sentence as content.
    """

    def __init__(self, message: str, reply: str = ""):
        self.reply = reply
        super().__init__(message)


class AttachmentNotRead(GeminiError):
    """Gemini's reply says it could not open the attached file(s) (issue #6).

    Such replies often go on to invent a plausible description, so the answer
    is withheld. ``reply`` holds the full text for inspection.
    """

    def __init__(self, message: str, reply: str = ""):
        self.reply = reply
        super().__init__(message)


class ToolActivationError(GeminiError):
    """A Gemini composer tool (Images/Videos/Music) could not be activated.

    Raised instead of silently sending a request without the tool, which
    would produce a chat or image response instead of the requested media.
    Deliberately NOT a TokenFactoryError so the client surfaces it instead
    of falling back to a direct HTTP request.
    """

    pass
