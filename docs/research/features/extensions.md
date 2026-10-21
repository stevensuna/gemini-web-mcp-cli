# Extensions

## Overview

Gemini extensions allow the model to interact with external Google services
like YouTube, Google Maps, Google Flights, Hotels, and Gmail.

## How Extensions Work

Extensions are activated through the chat interface using `@` syntax in prompts:
- `@YouTube search for...`
- `@Google Maps directions from...`
- `@Google Flights from SFO to JFK...`

No special RPC calls are needed -- extensions are triggered by the prompt content
and the model decides when to invoke them.

## Available Extensions

| Extension | Trigger | Description |
|-----------|---------|-------------|
| YouTube | `@YouTube` | Search and reference YouTube videos |
| Google Maps | `@Google Maps` | Directions, places, distances |
| Google Flights | `@Google Flights` | Flight search and pricing |
| Google Hotels | `@Google Hotels` | Hotel search and availability |
| Gmail | `@Gmail` | Search and reference emails |
| Google Workspace | `@Google Workspace` | Docs, Sheets, etc. |

## Response Handling

Extension results appear within the standard chat response. The model
integrates extension data into its text response with appropriate formatting
and links.

## Limitations

- Extension availability may vary by region and account type
- Some extensions require additional Google account permissions
- Age restrictions may apply to certain extensions

## Implementation Note

For our MCP, extensions can be exposed as a parameter on the `chat` tool:

```python
chat(action="send", prompt="Find flights from SFO to JFK", extensions=["flights"])
```

The CLI and MCP layer would prepend the appropriate `@` prefix to the prompt
if the user specifies extensions, or pass through prompts that already contain
`@` syntax.
