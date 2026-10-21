# Gems (Custom System Prompts)

## Overview

Gems are custom personas / system prompts in Gemini. Users can create, list,
update, and delete custom Gems. System-provided Gems are also accessible.

**Important**: All Gems RPCs require full browser cookies (Token Factory).
Basic auth tokens are insufficient — the server returns null data without them.

## RPC Calls

All Gems operations use the batchexecute endpoint.

### List Gems (CNgdBe)

**RPC ID**: `CNgdBe` (LIST_GEMS)

Payload format (updated Feb 2026): `[category, ["en"], 0]`

```python
# Category values:
# 1 = All (custom + shared combined)
# 2 = Custom (My Gems, user-created)
# 3 = Predefined (Premade by Google)
# 6 = Shared with me

# Custom (user-created) gems
payload = json.dumps([2, ["en"], 0])

# System (predefined) gems
payload = json.dumps([3, ["en"], 0])

# Shared gems
payload = json.dumps([6, ["en"], 0])
```

**Old format (no longer works)**: `[null, 0]` / `[null, 1]` — server returns
null with status code `[3]`.

**Response structure** (per gem in `part_body[2]`):

| Path | Content |
|------|---------|
| `gem[0]` | Gem ID |
| `gem[1][0]` | Name |
| `gem[1][1]` | Description |
| `gem[2][0]` | System prompt |

### Create Gem (oMH3Zd)

**RPC ID**: `oMH3Zd` (CREATE_GEM)

```python
payload = json.dumps([name, description, prompt, None, None, None, None, None, 1])
```

### Update Gem (kHv0Vd)

**RPC ID**: `kHv0Vd` (UPDATE_GEM)

```python
payload = json.dumps([gem_id, [name, description, prompt, None, None, None, None, None, 1]])
```

### Delete Gem (UXcSJb)

**RPC ID**: `UXcSJb` (DELETE_GEM)

```python
payload = json.dumps([gem_id])
```

## Using a Gem in Chat

To use a Gem in a chat, set `inner_req_list[19] = gem_id` in the StreamGenerate
request. This applies the Gem's system prompt to the conversation.

## Data Model

```python
class GemCategory(IntEnum):
    ALL = 1           # Custom + shared (combined view)
    CUSTOM = 2        # My Gems (user-created)
    PREDEFINED = 3    # Premade by Google
    SHARED = 6        # Shared with me

class Gem:
    id: str           # Unique identifier
    name: str         # Display name
    description: str  # Short description
    prompt: str       # System prompt text
    predefined: bool  # True for system gems, False for custom
    shared: bool      # True for gems shared by other users
```
