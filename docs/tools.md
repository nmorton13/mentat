# Tools

Mentat keeps the tool surface deliberately small in the core branch.

## Memory Tools

These tools are available to core chat and voice surfaces.

| Tool | Purpose | Voice |
| --- | --- | --- |
| `capture_thought` | Save a thought to the memory database | yes |
| `find_related_thoughts` | Find memories related to a concept | yes |
| `check_forgotten_ideas` | Surface older related ideas | yes |
| `suggest_capture` | Suggest whether a message is worth capturing | yes |
| `get_recent_activity` | Return recent memory activity | no |

## Public API Boundary

The core branch does not expose a standalone public tool HTTP API. Tool definitions
are used by chat and voice surfaces inside the app. This keeps external clients
narrow and avoids exposing local file, command, scheduler, or experimental
tooling as a public server surface.
