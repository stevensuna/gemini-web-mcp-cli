"""MCP server for the Gemini web interface.

Exposes 10 consolidated tools, each with an action parameter:
- chat: send (with optional file attachments)
- image: generate, download
- video: generate, status, download
- music: generate, list_styles, download
- research: start, status, report, download
- gems: list, create, update, delete
- limits: check per-feature usage quotas
- canvas: create, update, export (stub)
- code: execute, download (stub)
- file: upload

All tools call the service layer directly.
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from gemini_web_mcp_cli.core.client import GeminiClient
from gemini_web_mcp_cli.core.exceptions import TokenFactoryError, VideoGenerationError

mcp = FastMCP("gemini-web-mcp")



# Shared client instance (initialized on first tool call)
_client: GeminiClient | None = None
_client_cookies_hash: str | None = None  # Track auth state for profile switch detection


def _reset_client() -> None:
    """Reset the shared client (e.g., on profile switch)."""
    global _client, _client_cookies_hash
    _client = None
    _client_cookies_hash = None


async def _get_client() -> GeminiClient:
    """Get or create the shared GeminiClient.

    Detects profile switches (via disk auth changes) and reinitializes
    the client automatically, adapted from notebooklm-mcp-cli's approach.
    """
    global _client, _client_cookies_hash

    # Check if auth changed on disk (profile switch in another terminal)
    if _client is not None:
        try:
            from gemini_web_mcp_cli.core.profiles import ProfileManager

            pm = ProfileManager()
            current_auth = pm.load_auth()
            current_cookies = current_auth.get("cookies", {})
            current_hash = str(sorted(current_cookies.items()))

            if _client_cookies_hash is not None and current_hash != _client_cookies_hash:
                import logging
                logging.getLogger(__name__).info(
                    "Authentication profile change detected, reloading client."
                )
                await _client.close()
                _reset_client()
        except Exception:
            pass  # Best-effort detection

    if _client is None:
        _client = GeminiClient()
        await _client.init()
        # Cache the cookies hash for future comparison
        try:
            auth_cookies = _client.auth_manager.state.cookies
            _client_cookies_hash = str(sorted(auth_cookies.items()))
        except Exception:
            pass
    return _client


# ── Chat tool ───────────────────────────────────────────────────────────────


@mcp.tool()
async def chat(
    action: str,
    prompt: str | None = None,
    model: str | None = None,
    gem_id: str | None = None,
    conversation_id: str | None = None,
    extensions: list[str] | None = None,
    files: list[str] | None = None,
    extended_thinking: bool | None = None,
    thinking_level: str | None = None,
    task: bool = False,
) -> str:
    """Chat with Gemini models. Supports sending messages and streaming responses.

    Actions:
    - send: Send a message and get a complete response
      - prompt (required): The message to send
      - model (optional): Model to use ("pro", "flash", "gemini-3.8-flash",
        "gemini-4-argon", "thinking")
      - extended_thinking (optional): Enable Thinking level High (formerly
        Extended thinking). The legacy "thinking" model implies high.
      - thinking_level (optional): "low", "medium", or "high". Overrides
        extended_thinking. Medium is the new balanced level; high is the old
        Extended thinking toggle.
      - task (optional): Send through the Task control instead of Chat.
      - gem_id (optional): Chat with a specific custom Gem persona by its ID
        (from gems action=list). Mutually exclusive with model.
      - conversation_id (optional): Continue an existing conversation
      - extensions (optional): Extensions to enable (e.g., ["youtube", "maps"])
      - files (optional): List of local file paths to upload and attach
    """
    if action == "send":
        if not prompt:
            return json.dumps({"error": "prompt is required for send action"})

        # Prepend extension syntax if extensions specified
        final_prompt = prompt
        if extensions:
            ext_prefix = " ".join(f"@{e}" for e in extensions)
            final_prompt = f"{ext_prefix} {prompt}"

        client = await _get_client()
        from gemini_web_mcp_cli.services.chat import ChatService

        svc = ChatService(client)
        try:
            response = await svc.send(
                final_prompt,
                model=model,
                gem_id=gem_id,
                conversation_id=conversation_id,
                files=files,
                extended_thinking=extended_thinking,
                thinking_level=thinking_level,
                task=task,
            )
        except TokenFactoryError:
            raise  # Let FastMCP set isError: true
        except Exception as e:
            return json.dumps({"error": str(e)})

        result = {
            "text": response.text,
            "conversation_id": response.metadata.cid if response.metadata else None,
            "model_used": model or "default",
            "has_images": response.has_images,
        }

        if response.has_images:
            images = response.candidates[0].generated_images
            result["image_count"] = len(images) if images else 0
            if images:
                urls = []
                for img in images:
                    try:
                        url = img[0][3][3] if isinstance(img, list) else str(img)
                        urls.append(url)
                    except (IndexError, TypeError):
                        pass
                result["image_urls"] = urls

        return json.dumps(result)

    return json.dumps({"error": f"Unknown action: {action}. Available: send"})


# ── Image tool ──────────────────────────────────────────────────────────────


@mcp.tool()
async def image(
    action: str,
    prompt: str | None = None,
    model: str | None = None,
    aspect: str | None = None,
    image_url: str | None = None,
    output_path: str | None = None,
) -> str:
    """Generate, edit, and download images using Gemini (Nano Banana).

    Actions:
    - generate: Create an image from a text prompt
      - prompt (required): Description of the image to generate
      - model (optional): "pro" (default, Nano Banana Pro) or "flash"
        (Nano Banana 2 — Pro quality at Flash speed)
      - aspect (optional): Aspect ratio — "1:1", "9:16", "3:4", "4:3", or
        "16:9". Aliases "square" / "portrait" / "landscape" accepted.
      - output_path (optional): Save the generated image to this local file path
    - download: Download a generated image to a local file
      - image_url (required): The image URL from a previous generate response
      - output_path (required): Local file path to save the image
    """
    client = await _get_client()
    from gemini_web_mcp_cli.services.image import ImageService

    svc = ImageService(client)

    if action == "generate":
        if not prompt:
            return json.dumps({"error": "prompt is required for generate action"})

        try:
            response = await svc.generate(prompt, model=model, aspect=aspect)
        except ValueError as e:
            return json.dumps({"error": str(e)})
        result = {
            "text": response.text,
            "has_images": response.has_images,
        }

        if response.has_images:
            images = response.candidates[0].generated_images
            result["image_count"] = len(images) if images else 0

            # Extract image URLs for the caller
            if images:
                urls = []
                for img in images:
                    try:
                        url = img[0][3][3] if isinstance(img, list) else str(img)
                        urls.append(url)
                    except (IndexError, TypeError):
                        pass
                result["image_urls"] = urls

            # Auto-download if output_path provided
            if output_path and images:
                try:
                    url = images[0][0][3][3] if isinstance(images[0], list) else str(images[0])
                    saved = await svc.download(url, output_path)
                    result["saved_to"] = str(saved)
                except Exception as e:
                    result["download_error"] = str(e)

        return json.dumps(result)

    elif action == "download":
        if not image_url:
            return json.dumps({"error": "image_url is required for download action"})
        if not output_path:
            return json.dumps({"error": "output_path is required for download action"})

        try:
            saved = await svc.download(image_url, output_path)
            return json.dumps({"saved_to": str(saved)})
        except Exception as e:
            return json.dumps({"error": f"Download failed: {e}"})

    return json.dumps({"error": f"Unknown action: {action}. Available: generate, download"})


# ── Video tool ──────────────────────────────────────────────────────────────


@mcp.tool()
async def video(
    action: str,
    prompt: str | None = None,
    model: str | None = None,
    orientation: str | None = None,
    template: str | None = None,
    files: list[str] | None = None,
    task_id: str | None = None,
    output_path: str | None = None,
    video_url: str | None = None,
) -> str:
    """Generate videos using Gemini Omni (Veo 3.1). Videos take 1-2 minutes to generate.

    Actions:
    - generate: Start video generation from a text prompt. If output_path is
      provided, automatically waits for completion and downloads the video.
      - prompt (required unless template is given): Description of the video
      - model (optional): Video model ("flash" default, "pro", "lite", "thinking")
      - orientation (optional): "landscape" (16:9, default) or "portrait" (9:16).
        Aliases "16:9" / "9:16" are accepted.
      - template (optional): Omni template name, e.g. "Anime", "Logo reveal",
        "8-bit adventure", "Storybook", "Product showcase". Templates prefill
        the style; prompt and orientation still apply.
      - files (optional): Local reference image/video paths to upload and use
        as references (e.g. animate a still image). Repeatable.
      - output_path (optional): Save completed video to this file path (.mp4)
    - status: Check video generation progress
    - download: Download a completed video to a local file
      - video_url (required): The video download URL from a completed generation
      - output_path (required): Local file path to save the video (.mp4)
    """
    client = await _get_client()
    from gemini_web_mcp_cli.services.video import (
        VideoService,
        extract_video_metadata,
        extract_video_url,
    )

    svc = VideoService(client)

    if action == "generate":
        if not prompt and not template:
            return json.dumps({
                "error": "prompt is required for generate action (or provide a template)"
            })
        try:
            response = await svc.generate(
                prompt or "",
                model=model,
                orientation=orientation or "landscape",
                template=template,
                files=files,
            )
        except ValueError as e:
            return json.dumps({"error": str(e)})

        result: dict = {
            "text": response.text,
            "status": "generating",
        }

        # Check if video data is already in the initial response
        video_data = None
        if response.has_video:
            for c in response.candidates:
                if c.generated_video:
                    video_data = c.generated_video
                    break

        # If output_path provided, wait for completion and download
        if not video_data and output_path:
            try:
                completed = await svc.wait_for_completion(
                    poll_interval=15.0,
                    max_wait=900.0,
                )
            except VideoGenerationError as e:
                return json.dumps({
                    "error": str(e),
                    "status": "quota_exceeded",
                    "has_video": False,
                })
            if completed and completed.has_video:
                for c in completed.candidates:
                    if c.generated_video:
                        video_data = c.generated_video
                        break
                if completed.text:
                    result["text"] = completed.text

        if video_data:
            result["status"] = "completed"
            result["has_video"] = True
            url = extract_video_url(video_data)
            if url:
                result["video_url"] = url
            meta = extract_video_metadata(video_data)
            if meta:
                result["metadata"] = meta

            # Auto-download if output_path provided
            if output_path and url:
                saved = await svc.download(url, output_path)
                result["saved_to"] = str(saved)
                result["message"] = f"Video saved to {saved}"
            elif not output_path:
                result["message"] = (
                    "Video ready. Use download action with video_url and "
                    "output_path to save the file."
                )
        else:
            result["has_video"] = False
            result["message"] = (
                "Video generation started. Use status action to check progress."
            )

        return json.dumps(result)

    elif action == "status":
        result = await svc.poll_status()
        return json.dumps(result)

    elif action == "download":
        if not video_url:
            return json.dumps({
                "error": "video_url is required for download action. "
                "Get it from a completed generate action."
            })
        if not output_path:
            return json.dumps({"error": "output_path is required for download action"})
        saved = await svc.download(video_url, output_path)
        return json.dumps({
            "status": "downloaded",
            "saved_to": str(saved),
            "message": f"Video saved to {saved}",
        })

    return json.dumps({"error": f"Unknown action: {action}. Available: generate, status, download"})


# ── Music tool ──────────────────────────────────────────────────────────────


@mcp.tool()
async def music(
    action: str,
    prompt: str | None = None,
    model: str | None = None,
    style: str | None = None,
    length: str | None = None,
    vocals: str | None = None,
    genre: str | None = None,
    template: str | None = None,
    download_url: str | None = None,
    output_path: str | None = None,
    format: str | None = None,
) -> str:
    """Generate music tracks using Gemini (Lyria 3.5). Produces tracks with
    vocals, lyrics, instrumentals, and auto-generated cover art.

    Actions:
    - generate: Generate a music track from a text prompt
      - prompt (optional when template is given): Music description
      - model (optional): Model to use ("pro", "flash", "lite", "thinking")
      - style (optional): Legacy style preset for remix-style generation.
        Available styles: 90s-rap, latin-pop, folk-ballad, 8-bit, workout,
        reggaeton, rnb-romance, kawaii-metal, cinematic, emo, afropop,
        forest-bath, k-pop, birthday-roast, folk-a-cappella, bad-music.
        Also accepts aliases like "rap", "metal", "ambient", etc.
      - length (optional): "short" or "standard"
      - vocals (optional): "custom" (from prompt), "vocals" (vocals on),
        or "instrumental"
      - genre (optional): "pop", "hip-hop & rap", "rock", "k-pop", "latin",
        "electronic", "r&b", "country", "afrobeats", "reggae", "jazz & blues",
        "classical", "folk", "lo-fi", "acoustic", "cinematic", "ambient"
      - template (optional): Music template card, e.g. "Soundscape",
        "Intro music", "Brand jingle", "Rap battle"
      - output_path (optional): Auto-download the track to this file path
      - format (optional): "audio" (MP3) or "video" (MP4 with cover art; default: audio)
    - list_styles: List all available music style presets
    - download: Download a generated track to a local file
      - download_url (required): The audio/video URL from a previous generate response
      - output_path (required): Local file path to save the track
      - format (optional): "audio" (MP3) or "video" (MP4; default: audio)
    """
    client = await _get_client()
    from gemini_web_mcp_cli.services.music import MusicFormat, MusicService

    svc = MusicService(client)

    if action == "list_styles":
        from gemini_web_mcp_cli.core.music_presets import MUSIC_PRESETS

        styles = [
            {"key": k, "name": v["name"]} for k, v in sorted(MUSIC_PRESETS.items())
        ]
        return json.dumps({"styles": styles})

    if action == "generate":
        if not prompt and not template:
            return json.dumps({
                "error": "prompt is required for generate action (or provide a template)"
            })

        try:
            response = await svc.generate(
                prompt or "",
                model=model,
                style=style,
                length=length,
                vocals=vocals,
                genre=genre,
                template=template,
            )
        except ValueError as e:
            return json.dumps({"error": str(e)})
        result: dict = {
            "text": response.text,
            "has_music": response.has_music,
        }

        if response.has_music:
            music_data = response.candidates[0].generated_music
            if music_data:
                # Extract metadata (entry 2)
                if len(music_data) > 2 and music_data[2] and isinstance(music_data[2], list):
                    md = music_data[2]
                    result["track"] = {
                        "title": md[0] if len(md) > 0 else None,
                        "album": md[2] if len(md) > 2 else None,
                        "genre": md[4] if len(md) > 4 else None,
                        "moods": md[5] if len(md) > 5 else None,
                    }

                # Extract lyrics (entry 3)
                if len(music_data) > 3 and music_data[3] and isinstance(music_data[3], list):
                    ly = music_data[3]
                    result["lyrics"] = ly[2] if len(ly) > 2 else None

                # Extract download URLs
                try:
                    result["audio_url"] = music_data[0][1][7][1]
                except (IndexError, TypeError):
                    pass
                try:
                    result["video_url"] = music_data[1][1][7][1]
                except (IndexError, TypeError):
                    pass

                # Auto-download if output_path provided
                if output_path:
                    dl_format = format or "audio"
                    music_fmt = MusicFormat(dl_format)
                    try:
                        if music_fmt == MusicFormat.VIDEO:
                            url = music_data[1][1][7][1]
                        else:
                            url = music_data[0][1][7][1]
                        saved = await svc.download(url, output_path, fmt=music_fmt)
                        result["saved_to"] = str(saved)
                    except (IndexError, TypeError) as e:
                        result["download_error"] = f"Could not extract URL: {e}"
                    except Exception as e:
                        result["download_error"] = str(e)

        return json.dumps(result)

    elif action == "download":
        if not download_url:
            return json.dumps({"error": "download_url is required for download action"})
        if not output_path:
            return json.dumps({"error": "output_path is required for download action"})

        dl_format = format or "audio"
        music_fmt = MusicFormat(dl_format)
        try:
            saved = await svc.download(download_url, output_path, fmt=music_fmt)
            return json.dumps({"saved_to": str(saved)})
        except Exception as e:
            return json.dumps({"error": f"Download failed: {e}"})

    return json.dumps({
        "error": f"Unknown action: {action}. Available: generate, list_styles, download"
    })


# ── Research tool ───────────────────────────────────────────────────────────


@mcp.tool()
async def research(
    action: str,
    query: str | None = None,
    model: str | None = None,
    output_path: str | None = None,
) -> str:
    """Deep Research: comprehensive multi-source research with structured reports.

    Actions:
    - start: Begin a deep research query (generates plan, then researches)
      - query (required): The research question or topic
      - model (optional): Model to use ("pro", "flash", "lite", "thinking")
    - status: Check research progress
    - report: Get the research report text
    - download: Save the report to a local file
      - output_path (required): Local file path to save the report
    """
    from mcp.server.fastmcp.exceptions import ToolError

    from gemini_web_mcp_cli.services.research import ResearchService

    try:
        if action not in ("start", "status", "report", "download"):
            raise ValueError("Available actions: start, status, report, download")
        if action == "start" and not query:
            raise ValueError("query is required for start action")
        if action == "download" and not output_path:
            raise ValueError("output_path is required for download action")
        svc = ResearchService(await _get_client())
        if action == "start":
            plan = await svc.create_plan(query, model=model)
            response = await svc.start()
            return json.dumps({"text": plan.text, "status": "running",
                               "conversation_id": response.metadata.cid})
        if action == "status":
            return json.dumps(await svc.poll_status())
        if action == "report":
            return json.dumps({"status": "completed", "text": await svc.report()})
        return json.dumps({"path": str(await svc.download(output_path))})
    except Exception as e:
        raise ToolError(str(e)) from e


# ── Gems tool ───────────────────────────────────────────────────────────────


@mcp.tool()
async def gems(
    action: str,
    gem_id: str | None = None,
    name: str | None = None,
    description: str | None = None,
    system_prompt: str | None = None,
    file_paths: list[str] | None = None,
    drive_file_ids: list[str] | None = None,
    notebook_ids: list[str] | None = None,
    default_tool: str | None = None,
    query: str | None = None,
    max_results: int = 20,
) -> str:
    """Manage Gemini Gems (custom AI personas with system prompts).

    Actions:
    - list: List all custom gems
    - list_predefined: List Google's premade gems
    - list_shared: List gems shared with you
    - list_notebooks: List NotebookLM notebooks available to attach as knowledge
      Returns list of {id, title, source_count}
    - create: Create a new gem
      - name (required): Display name
      - system_prompt (required): The system prompt text
      - description (optional): Short description
      - file_paths (optional): List of local file paths to attach as knowledge files
      - drive_file_ids (optional): List of Google Drive file IDs to attach as knowledge files
      - notebook_ids (optional): List of NotebookLM notebook IDs to attach as knowledge
      - default_tool (optional): Default tool name. Options: none, image, video, music,
        canvas, deep-research, learning
    - update: Update an existing gem
      - gem_id (required): ID of the gem to update
      - name, description, system_prompt: Fields to update
      - file_paths (optional): List of local file paths to replace knowledge files
      - drive_file_ids (optional): List of Google Drive file IDs to attach
      - notebook_ids (optional): List of NotebookLM notebook IDs to attach
      - default_tool (optional): Default tool name (same options as create)
    - delete: Delete a gem
      - gem_id (required): ID of the gem to delete
    - drive_search: Search Google Drive for files to attach as knowledge
      - query (required): Search term (e.g. "CSL", "Q4 report")
      - max_results (optional): Max files to return (default 20)
      Returns list of {id, name, mime_type} — pass ids to create/update via drive_file_ids
    """
    client = await _get_client()

    from gemini_web_mcp_cli.services.gems import GEM_TOOL_ALIASES, GemsService

    svc = GemsService(client)
    tool_code = GEM_TOOL_ALIASES.get(default_tool.lower(), 0) if default_tool else 0

    if action in ("list", "list_predefined", "list_shared"):
        gem_list = await svc.list_gems(
            predefined=(action == "list_predefined"),
            shared=(action == "list_shared"),
        )
        return json.dumps([
            {
                "id": g.id,
                "name": g.name,
                "description": g.description,
                "default_tool": g.default_tool_name,
                "resources": [
                    {
                        "name": r.name,
                        "mime_type": r.mime_type,
                        "source": r.source,
                        "drive_url": r.drive_url,
                        **({"notebook_id": r.notebook_id} if r.notebook_id else {}),
                    }
                    for r in g.resources
                ],
            }
            for g in gem_list
        ])

    elif action == "list_notebooks":
        notebooks = await svc.list_notebooks()
        return json.dumps(notebooks)

    elif action == "create":
        if not name or not system_prompt:
            return json.dumps({"error": "name and system_prompt are required for create"})
        result = await svc.create(
            name, description or "", system_prompt,
            knowledge_files=file_paths, drive_file_ids=drive_file_ids,
            notebook_ids=notebook_ids, default_tool=tool_code,
        )
        return json.dumps(result)

    elif action == "update":
        if not gem_id:
            return json.dumps({"error": "gem_id is required for update"})
        result = await svc.update(
            gem_id,
            name=name or "",
            description=description or "",
            prompt=system_prompt or "",
            knowledge_files=file_paths,
            drive_file_ids=drive_file_ids,
            notebook_ids=notebook_ids,
            default_tool=tool_code,
        )
        return json.dumps(result)

    elif action == "delete":
        if not gem_id:
            return json.dumps({"error": "gem_id is required for delete"})
        result = await svc.delete(gem_id)
        return json.dumps(result)

    elif action == "drive_search":
        if not query:
            return json.dumps({"error": "query is required for drive_search"})
        results = await client.search_drive(query=query, max_results=max_results)
        return json.dumps(results)

    return json.dumps({
        "error": (
            f"Unknown action: {action}. "
            "Available: list, list_notebooks, create, update, delete, drive_search"
        )
    })


# ── Canvas tool (stub) ──────────────────────────────────────────────────────


@mcp.tool()
async def canvas(
    action: str,
    canvas_id: str | None = None,
    content: str | None = None,
    output_path: str | None = None,
) -> str:
    """Canvas: collaborative document editing (coming soon).

    Actions:
    - create: Create a new canvas document
    - update: Update canvas content
    - export: Export canvas to file
    """
    return json.dumps({"error": "Canvas support is coming soon. Use chat for now."})


# ── Code tool (stub) ───────────────────────────────────────────────────────


@mcp.tool()
async def code(
    action: str,
    source_code: str | None = None,
    language: str | None = None,
    output_path: str | None = None,
) -> str:
    """Code execution: run Python code in Gemini's sandbox (coming soon).

    Actions:
    - execute: Run code in the sandbox
    - download: Download execution output
    """
    return json.dumps({"error": "Code execution support is coming soon. Use chat for now."})


# ── File tool ───────────────────────────────────────────────────────────────


@mcp.tool()
async def file(
    action: str,
    file_path: str | None = None,
) -> str:
    """Upload files to Gemini for context in conversations.

    Actions:
    - upload: Upload a file (image, PDF, document, audio)
      - file_path (required): Local path to the file.

    Returns the file identifier, which can be passed to chat tool via the files array.
    """
    client = await _get_client()
    from gemini_web_mcp_cli.services.file import FileService

    svc = FileService(client)

    if action == "upload":
        if not file_path:
            return json.dumps({"error": "file_path is required for upload action"})
        try:
            file_id = await svc.upload(file_path)
            return json.dumps({
                "status": "uploaded",
                "file_id": file_id,
                "message": (
                    "File uploaded. Use this file_id in the chat tool extensions/"
                    "attachments if needed, or just let chat tool handle it via the files list."
                ),
            })
        except Exception as e:
            return json.dumps({"error": f"Upload failed: {e}"})

    return json.dumps({"error": f"Unknown action: {action}. Available: upload"})


# ── Limits tool ─────────────────────────────────────────────────────────────


@mcp.tool()
async def limits() -> str:
    """Check current Gemini usage limits and remaining quota.

    Returns the account/profile the data belongs to plus per-feature usage:
    the server-reported usage percentage, credits left in the plan pool
    (size depends on the plan), and when each row resets (as reported by
    Google; not a fixed window). Requires
    Token Factory (Chrome) for browser cookie authentication.

    IMPORTANT: Call this BEFORE attempting video, music, image generation,
    or deep research to verify quota is available. This avoids wasting time
    on operations that will be rejected due to quota exhaustion. When a tool
    is disabled (100% used), retry with another profile via the CLI:
    `gemcli -p <profile> <command>`.

    Features tracked include: Video (Gemini Omni), Music (Lyria 3.5), Images,
    Nano Banana Pro/2, Deep Think, Deep Research, Pro prompts, Thinking
    prompts, Agent requests, and more.
    """
    client = await _get_client()

    from gemini_web_mcp_cli.services.limits import LimitsService

    svc = LimitsService(client)
    feature_limits = await svc.get_limits()

    if not feature_limits:
        return json.dumps({
            "error": "Could not retrieve limits. Browser cookies required.",
            "hint": "Token Factory (Chrome) must be available.",
        })

    result = {
        "account": (client.auth_manager.state.email or None),
        "profile": (
            client.auth_manager.profile_name
            or client.profile_manager.get_active_profile()
        ),
        "limits": [fl.to_dict() for fl in feature_limits if fl.limit > 0],
    }

    exhausted = [fl.name for fl in feature_limits if fl.is_exhausted]
    if exhausted:
        result["warning"] = f"Quota exhausted for: {', '.join(exhausted)}"

    return json.dumps(result)


# ── Server entry point ─────────────────────────────────────────────────────


def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
