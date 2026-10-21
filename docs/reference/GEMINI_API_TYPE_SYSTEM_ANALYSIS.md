# Gemini-API Type System Analysis

Complete analysis of the HanaokaYuzu/Gemini-API data models and type definitions (Python library that reverse-engineers the Gemini web interface). Reference: `master` branch.

---

## 1. `types/candidate.py` — Candidate

### Complete Source Code

```python
import html
from pydantic import BaseModel, field_validator

from .image import Image, WebImage, GeneratedImage


class Candidate(BaseModel):
    """
    A single reply candidate object in the model output. A full response from Gemini usually contains multiple reply candidates.

    Parameters
    ----------
    rcid: `str`
        Reply candidate ID to build the metadata
    text: `str`
        Text output
    thoughts: `str`, optional
        Model's thought process, can be empty. Only populated with `-thinking` models
    web_images: `list[WebImage]`, optional
        List of web images in reply, can be empty.
    generated_images: `list[GeneratedImage]`, optional
        List of generated images in reply, can be empty
    """

    rcid: str
    text: str
    text_delta: str | None = None
    thoughts: str | None = None
    thoughts_delta: str | None = None
    web_images: list[WebImage] = []
    generated_images: list[GeneratedImage] = []

    def __str__(self):
        return self.text

    def __repr__(self):
        return f"Candidate(rcid='{self.rcid}', text='{len(self.text) <= 20 and self.text or self.text[:20] + '...'}', images={self.images})"

    @field_validator("text", "thoughts")
    @classmethod
    def decode_html(cls, value: str) -> str:
        """
        Auto unescape HTML entities in text/thoughts if any.
        """
        if value:
            value = html.unescape(value)
        return value

    @property
    def images(self) -> list[Image]:
        return self.web_images + self.generated_images
```

### Class Definition Summary

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `rcid` | `str` | required | Reply candidate ID |
| `text` | `str` | required | Text output |
| `text_delta` | `str \| None` | `None` | Streaming: new text since last chunk |
| `thoughts` | `str \| None` | `None` | Model thinking (thinking-capable models) |
| `thoughts_delta` | `str \| None` | `None` | Streaming: new thoughts since last chunk |
| `web_images` | `list[WebImage]` | `[]` | Web-sourced images |
| `generated_images` | `list[GeneratedImage]` | `[]` | AI-generated images |

### JSON Mapping (from `client.py`)

Response structure (per frame in streaming):

```
part_json = json.loads(inner_json_str)   # part[2] is the inner JSON string
candidates_list = part_json[4]           # List of candidate objects
```

For each `candidate_data` in `candidates_list`:

| Candidate Field | JSON Path | Notes |
|-----------------|-----------|-------|
| `rcid` | `candidate_data[0]` | Reply candidate ID |
| `text` | `candidate_data[1][0]` | Primary text; fallback to `candidate_data[22][0]` if text matches `http://googleusercontent.com/card_content/\d+` |
| `thoughts` | `candidate_data[37][0][0]` | Thinking model internal reasoning |
| (streaming) | `candidate_data[2]` | If list → final chunk |
| (streaming) | `candidate_data[8][0]` | If `== 2` → final chunk |

---

## 2. `types/image.py` — Image, WebImage, GeneratedImage

### Complete Source Code

```python
import re
from pathlib import Path
from datetime import datetime
from typing import Any

from httpx import AsyncClient, Cookies, HTTPError
from pydantic import BaseModel, field_validator

from ..utils import logger


class Image(BaseModel):
    """
    A single image object returned from Gemini.

    Parameters
    ----------
    url: `str`
        URL of the image.
    title: `str`, optional
        Title of the image, by default is "[Image]".
    alt: `str`, optional
        Optional description of the image.
    proxy: `str`, optional
        Proxy used when saving image.
    """

    url: str
    title: str = "[Image]"
    alt: str = ""
    proxy: str | None = None

    def __str__(self):
        return (
            f"Image(title='{self.title}', alt='{self.alt}', "
            f"url='{len(self.url) <= 20 and self.url or self.url[:8] + '...' + self.url[-12:]}')"
        )

    async def save(
        self,
        path: str = "temp",
        filename: str | None = None,
        cookies: dict | Cookies | None = None,
        verbose: bool = False,
        skip_invalid_filename: bool = False,
    ) -> str | None:
        """
        Save the image to disk.
        ... (see docstring in source)
        """
        filename = filename or self.url.split("/")[-1].split("?")[0]
        match = re.search(r"^(.*\.\w+)", filename)
        if match:
            filename = match.group()
        else:
            if verbose:
                logger.warning(f"Invalid filename: {filename}")
            if skip_invalid_filename:
                return None

        async with AsyncClient(
            http2=True, follow_redirects=True, cookies=cookies, proxy=self.proxy
        ) as client:
            response = await client.get(self.url)
            if response.status_code == 200:
                content_type = response.headers.get("content-type")
                if content_type and "image" not in content_type:
                    logger.warning(
                        f"Content type of {filename} is not image, but {content_type}."
                    )

                path = Path(path)
                path.mkdir(parents=True, exist_ok=True)

                dest = path / filename
                dest.write_bytes(response.content)

                if verbose:
                    logger.info(f"Image saved as {dest.resolve()}")

                return str(dest.resolve())
            else:
                raise HTTPError(
                    f"Error downloading image: {response.status_code} {response.reason_phrase}"
                )


class WebImage(Image):
    """
    Image retrieved from web. Returned when ask Gemini to "SEND an image of [something]".
    """

    pass


class GeneratedImage(Image):
    """
    Image generated by ImageFX, Google's AI image generator. Returned when ask Gemini to "GENERATE an image of [something]".

    Parameters
    ----------
    cookies: `dict | httpx.Cookies`
        Cookies used for requesting the content of the generated image, inherit from GeminiClient object or manually set.
        Should contain valid "__Secure-1PSID" and "__Secure-1PSIDTS" values.
    """

    cookies: Any

    @field_validator("cookies")
    @classmethod
    def validate_cookies(cls, v: Any) -> Any:
        if len(v) == 0:
            raise ValueError(
                "GeneratedImage is designed to be initialized with same cookies as GeminiClient."
            )
        return v

    async def save(
        self,
        path: str = "temp",
        filename: str | None = None,
        cookies: dict | Cookies | None = None,
        verbose: bool = False,
        skip_invalid_filename: bool = False,
        full_size: bool = True,
    ) -> str | None:
        """Save the image to disk. Generated images: adds =s2048 for full size."""
        if full_size:
            self.url += "=s2048"

        return await super().save(
            path=path,
            filename=filename
            or f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{self.url[-10:]}.png",
            cookies=cookies or self.cookies,
            verbose=verbose,
            skip_invalid_filename=skip_invalid_filename,
        )
```

### Class Definition Summary

| Class | Base | Fields | Notes |
|-------|------|--------|-------|
| `Image` | `BaseModel` | `url`, `title`, `alt`, `proxy` | Base for all image types |
| `WebImage` | `Image` | (inherits) | Web-sourced images |
| `GeneratedImage` | `Image` | + `cookies` (required, non-empty) | AI-generated; needs auth cookies |

### Image Extraction — JSON Mapping

**Web images** (from `candidate_data[12][1]`):

```python
for web_img_data in get_nested_value(candidate_data, [12, 1], []):
    url = get_nested_value(web_img_data, [0, 0, 0])
    if url:
        web_images.append(WebImage(
            url=url,
            title=get_nested_value(web_img_data, [7, 0], ""),
            alt=get_nested_value(web_img_data, [0, 4], ""),
            proxy=self.proxy,
        ))
```

| WebImage Field | JSON Path |
|----------------|-----------|
| `url` | `web_img_data[0][0][0]` |
| `title` | `web_img_data[7][0]` |
| `alt` | `web_img_data[0][4]` |

**Generated images** (from `candidate_data[12][7][0]`):

```python
for gen_img_data in get_nested_value(candidate_data, [12, 7, 0], []):
    url = get_nested_value(gen_img_data, [0, 3, 3])
    if url:
        img_num = get_nested_value(gen_img_data, [3, 6])
        generated_images.append(GeneratedImage(
            url=url,
            title=f"[Generated Image {img_num}]" if img_num else "[Generated Image]",
            alt=get_nested_value(gen_img_data, [3, 5, 0], ""),
            proxy=self.proxy,
            cookies=self.cookies,
        ))
```

| GeneratedImage Field | JSON Path |
|----------------------|-----------|
| `url` | `gen_img_data[0][3][3]` |
| `title` | `f"[Generated Image {img_num}]"` where `img_num = gen_img_data[3][6]` |
| `alt` | `gen_img_data[3][5][0]` |
| `cookies` | From GeminiClient (not in JSON) |

### Image Handling Summary

- **Web images**: `candidate_data[12][1]` → list of objects with `[0][0][0]` = url, `[7][0]` = title, `[0][4]` = alt.
- **Generated images**: `candidate_data[12][7][0]` → list of objects with `[0][3][3]` = url; require client cookies.
- **Saving**: `Image.save()` for web images; `GeneratedImage.save()` adds `=s2048` for full resolution and uses cookies.
- **Filename**: Web = from URL; Generated = `{timestamp}_{url[-10:]}.png`.

---

## 3. `types/modeloutput.py` — ModelOutput

### Complete Source Code

```python
from pydantic import BaseModel

from .image import Image
from .candidate import Candidate


class ModelOutput(BaseModel):
    """
    Classified output from gemini.google.com

    Parameters
    ----------
    metadata: `list[str]`
        List of chat metadata `[cid, rid, rcid]`, can be shorter than 3 elements
    candidates: `list[Candidate]`
        List of all candidates returned from gemini
    chosen: `int`, optional
        Index of the chosen candidate, by default will choose the first one
    """

    metadata: list[str]
    candidates: list[Candidate]
    chosen: int = 0

    def __str__(self):
        return self.text

    def __repr__(self):
        return f"ModelOutput(metadata={self.metadata}, chosen={self.chosen}, candidates={self.candidates})"

    @property
    def text(self) -> str:
        return self.candidates[self.chosen].text

    @property
    def text_delta(self) -> str:
        return self.candidates[self.chosen].text_delta or ""

    @property
    def thoughts(self) -> str | None:
        return self.candidates[self.chosen].thoughts

    @property
    def thoughts_delta(self) -> str:
        return self.candidates[self.chosen].thoughts_delta or ""

    @property
    def images(self) -> list[Image]:
        return self.candidates[self.chosen].images

    @property
    def rcid(self) -> str:
        return self.candidates[self.chosen].rcid
```

### Class Definition Summary

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `metadata` | `list[str]` | required | `[cid, rid, rcid]` (chat metadata) |
| `candidates` | `list[Candidate]` | required | All reply candidates |
| `chosen` | `int` | `0` | Index of selected candidate |

### JSON Mapping

From `client._generate()`:

```python
yield ModelOutput(
    metadata=get_nested_value(part_json, [1], []),
    candidates=output_candidates,  # Built from part_json[4]
)
```

| ModelOutput Field | JSON Path |
|-------------------|-----------|
| `metadata` | `part_json[1]` |
| `candidates` | Built from `part_json[4]` (each element → `Candidate`) |

### Response Frame Layout (High-Level)

```
part (parsed frame):
  [5]       → Error codes (e.g., [5][2][0][1][0])
  [2]       → Inner JSON string → part_json
  part_json:
    [1]     → metadata [cid, rid, rcid, ...]
    [4]     → candidates_list
    [25]    → context_str (completion signal)
```

---

## 4. `types/gem.py` — Gem, GemJar

### Complete Source Code

```python
from pydantic import BaseModel


class Gem(BaseModel):
    """
    Reusable Gemini Gem object working as a system prompt.

    Parameters
    ----------
    id: `str`
        Unique identifier for the gem.
    name: `str`
        User-friendly name of the gem.
    description: `str`, optional
        Brief description of the gem's purpose or content.
    prompt: `str`, optional
        The system prompt text that the gem provides to the model.
    predefined: `bool`
        Indicates whether the gem is predefined by Gemini or created by the user.
    """

    id: str
    name: str
    description: str | None = None
    prompt: str | None = None
    predefined: bool

    def __str__(self) -> str:
        return (
            f"Gem(id='{self.id}', name='{self.name}', description='{self.description}', "
            f"prompt='{self.prompt}', predefined={self.predefined})"
        )


class GemJar(dict[str, Gem]):
    """
    Helper class for handling a collection of `Gem` objects, stored by their ID.
    """

    def __iter__(self):
        return self.values().__iter__()

    def get(
        self, id: str | None = None, name: str | None = None, default: Gem | None = None
    ) -> Gem | None:
        """Retrieves a gem by id and/or name."""
        assert not (id is None and name is None), "At least one of gem id or name must be provided."
        # ... (see source for full logic)

    def filter(
        self, predefined: bool | None = None, name: str | None = None
    ) -> "GemJar":
        """Returns a new GemJar with matching gems."""
        # ...
```

### Gem Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | `str` | required | Unique identifier |
| `name` | `str` | required | Display name |
| `description` | `str \| None` | `None` | Description |
| `prompt` | `str \| None` | `None` | System instructions |
| `predefined` | `bool` | required | True = system gem, False = custom |

### GemJar Methods

- `get(id=..., name=..., default=...)` — Lookup by id, name, or both.
- `filter(predefined=..., name=...)` — New `GemJar` with filtered gems.
- Iteration — Over `values()` (gem objects).

---

## 5. `components/gem_mixin.py` — Gem CRUD

### Complete Source Code (excerpt)

See fetched source for full implementation.

### Gem Operations

**Fetch (list)**

- RPC: `GRPC.LIST_GEMS` (`CNgdBe`)
- Two calls:
  - `[4,['{language}'],0]` if `include_hidden` else `[3,['{language}'],0]` → `identifier="system"`
  - `[2,['{language}'],0]` → `identifier="custom"`
- Response: `part_body_str` at `part[-1]` (identifier), `part[2]` (body). Body parsed as JSON; gems at `part_body[2]`.
- Mapping:
  - `gem[0]` → id
  - `gem[1][0]` → name
  - `gem[1][1]` → description
  - `gem[2][0]` → prompt (if present)
  - `predefined=True` for system, `False` for custom

**Create**

- RPC: `GRPC.CREATE_GEM` (`oMH3Zd`)
- Payload:
```python
[[
  name, description, prompt,
  None, None, None, None, None, 0, None, 1, None, None, None, []
]]
```
- Response: `part_body[0]` = new gem id.

**Update**

- RPC: `GRPC.UPDATE_GEM` (`kHv0Vd`)
- Payload:
```python
[gem_id, [
  name, description, prompt,
  None, None, None, None, None, 0, None, 1, None, None, None, [], 0
]]
```

**Delete**

- RPC: `GRPC.DELETE_GEM` (`UXcSJb`)
- Payload: `[gem_id]`

---

## 6. `exceptions.py` — Exception Hierarchy

### Complete Source Code

```python
class AuthError(Exception):
    """
    Exception for authentication errors caused by invalid credentials/cookies.
    """
    pass


class APIError(Exception):
    """
    Exception for package-level errors which need to be fixed in future development (e.g. validation errors).
    """
    pass


class ImageGenerationError(APIError):
    """
    Exception for generated image parsing errors.
    """
    pass


class GeminiError(Exception):
    """
    Exception for errors returned from Gemini server which are not handled by the package.
    """
    pass


class TimeoutError(GeminiError):
    """
    Exception for request timeouts.
    """
    pass


class UsageLimitExceeded(GeminiError):
    """
    Exception for model usage limit exceeded errors.
    """
    pass


class ModelInvalid(GeminiError):
    """
    Exception for invalid model header string errors.
    """
    pass


class TemporarilyBlocked(GeminiError):
    """
    Exception for 429 Too Many Requests when IP is temporarily blocked.
    """
    pass
```

### Exception Types and When Raised

| Exception | Base | When Raised |
|-----------|------|-------------|
| `AuthError` | `Exception` | Invalid credentials/cookies (e.g. token/cookie refresh failure) |
| `APIError` | `Exception` | Package/internal errors: unexpected response, parsing failure, unknown error codes, stalled stream |
| `ImageGenerationError` | `APIError` | Generated image parsing errors (defined but not used in current code) |
| `GeminiError` | `Exception` | Server-side / high-level generation failures (e.g. no output) |
| `TimeoutError` | `GeminiError` | `ReadTimeout` from httpx during request/stream |
| `UsageLimitExceeded` | `GeminiError` | Error code `1037` (usage limit) |
| `ModelInvalid` | `GeminiError` | Error codes `1050` (model inconsistent), `1052` (model header invalid) |
| `TemporarilyBlocked` | `GeminiError` | Error code `1060` (IP temporarily blocked) |

### Error Code Mapping (from `constants.py`)

```python
class ErrorCode(IntEnum):
    TEMPORARY_ERROR_1013 = 1013
    USAGE_LIMIT_EXCEEDED = 1037
    MODEL_INCONSISTENT = 1050
    MODEL_HEADER_INVALID = 1052
    IP_TEMPORARILY_BLOCKED = 1060
```

Location in response: `part[5][2][0][1][0]`.

---

## 7. Quick Reference: Response JSON Indices

### Streaming Frame Structure

```
part = parsed frame (from parse_response_by_frame)
  part[2]     → inner JSON string
  part[5]     → status / error info
  part[-1]    → identifier (for batched responses, e.g. gems)

part_json = json.loads(part[2])
  part_json[1]   → metadata [cid, rid, rcid, ...]
  part_json[4]   → candidates list
  part_json[25]  → context string (completion)

candidate_data = part_json[4][i]
  candidate_data[0]      → rcid
  candidate_data[1][0]   → text (primary)
  candidate_data[22][0]  → text (fallback)
  candidate_data[2]      → final-chunk marker (list)
  candidate_data[8][0]    → final-chunk marker (2)
  candidate_data[37][0][0] → thoughts
  candidate_data[12][1]     → web images list
  candidate_data[12][7][0]  → generated images list

web_img_data (in candidate_data[12][1])
  [0][0][0] → url
  [7][0]    → title
  [0][4]    → alt

gen_img_data (in candidate_data[12][7][0])
  [0][3][3] → url
  [3][6]    → image number
  [3][5][0] → alt
```

---

## 8. Dependencies

- `pydantic` — BaseModel, field_validator
- `httpx` — AsyncClient, Cookies, HTTPError, ReadTimeout
- `orjson` — JSON parsing
- `html` — html.unescape
- `pathlib.Path`, `datetime`, `re`

---

## 9. Type Exports (`types/__init__.py`)

```python
from .candidate import Candidate
from .gem import Gem, GemJar
from .grpc import RPCData
from .image import Image, WebImage, GeneratedImage
from .modeloutput import ModelOutput
```
