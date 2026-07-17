# Complete Command Reference

Reference guide for MENTAT commands, with examples and expected output.

## Agent-Friendly Top-Level Usage

Mentat also exposes scriptable top-level commands for agent and shell use. These
commands do not require the interactive slash-command session.

### JSON Output

`chat`, `search`, `latest`, `links`, and `todo` support `--json`:

```bash
mentat chat "what changed recently?" --json
mentat search "machine learning" --json
mentat latest 25 --json
mentat links "research" --json
mentat todo pending --json
```

JSON mode prints one JSON object to stdout:

```json
{
  "schema_version": 1,
  "command": "latest",
  "success": true,
  "data": {}
}
```

Errors use the same envelope with `success: false` and an `error` object.
Human banners, progress text, and warnings are not printed to stdout in JSON
mode.

`chat --json` uses the same enhanced chat answer generation as normal chat, but
serializes the result instead of rendering Rich panels. The JSON data includes
the query, model, response, sources, patterns, connections, suggestions,
explorable references, and any structured `viewable_items`.

### Durable Targets

Top-level `view` and `delete` use memory IDs from JSON output:

```bash
mentat view 123
mentat delete 123 --yes
```

Top-level `mark` uses the opaque persisted todo ID from `mentat todo --json`:

```bash
mentat mark todo_abc123
```

Interactive `/view`, `/delete`, and `/mark` still use numbered results inside
the REPL.

### Stdin Capture

Use `mentat capture -` for long generated notes, transcripts, or handoffs:

```bash
cat summary.txt | mentat capture -
```

Top-level capture keeps URLs as part of the note. Use `mentat link <url>` when
you want a dedicated link memory containing the URL and your optional comment.

### Configuration

Use the guided setup for a first run or to revise the basic model setup later:

```bash
mentat config init
```

`init` configures the Mentat user ID, chat provider and model, helper behavior,
Markdown export, and optional voice settings. It previews changes before safely
updating `.env`, preserves unrelated variables and comments, and activates the
selected chat route.

Inspect the effective setup without exposing API keys:

```bash
mentat config show
```

Check required credentials, local endpoint/model availability, helper routing,
Markdown export, and optional voice setup:

```bash
mentat config doctor
```

`doctor` exits with a nonzero status when it finds a blocking setup problem.

## Content Capture Commands

### `/capture <content>`

**Purpose:** Analyze and save content with AI-generated metadata.

**Syntax:**
```bash
/capture <your content here>
/capture -w <content>        # With web search enrichment
/capture --web-search <content>  # Same as -w
/capture                     # Multi-line input mode
```

**What it does:**
- **Content Classification** - Automatically categorizes as `idea`, `task`, `link`, `reflection`, etc.
- **Entity Extraction** - Identifies people, organizations, technologies, projects, concepts, locations, dates on every capture
- **Tag Generation** - Creates relevant tags for discovery
- **Actionable Items** - Extracts todos and tasks
- **Web Enrichment** (optional, with `-w`) - First extracts entities, then uses OpenRouter web search to gather context for selected entities that are novel or stale in your memory. This is especially useful for current, niche, ambiguous, or model-unknown terms. The web context is used to improve tagging/classification; the original note is still what gets captured.
- **Plain URL Capture** - URLs stay in the captured note; use `/link` when you want a dedicated link memory

**Examples:**
```bash
# Simple thought capture
/capture I think the new React hooks pattern could simplify our state management

# Web-enriched capture (selected novel/stale entities get web context)
/capture -w Learning about Kimi K2 Thinking and whether it changes agent workflow design

# Multi-line mode
/capture
> Working on the garden project today. Key observations:
> - Soil pH is still too high in the west bed
> - Tomatoes showing signs of calcium deficiency
> - Compost pile temperature dropped, needs turning
> END

# Meeting notes
/capture Team standup notes: Alice working on auth refactor, Bob debugging the payment gateway, discussed moving to microservices architecture

# Research findings
/capture Found an interesting paper on vector databases that could improve our search performance significantly
```

**Output:** Shows AI analysis with extracted entities, tags, and connections to existing memories.

## 🔍 Search & Discovery Commands

### `/search <query>`

**Purpose:** Hybrid search across all your memories.

**Search Strategies (in priority order):**
1. **Keyword/Tag Search** - Exact matches in content and tags
2. **Strong Semantic Search** - Conceptually related content (high similarity)
3. **Entity-Based Search** - Memories sharing people, technologies, projects
4. **Weak Semantic Fallback** - Broader conceptual matches

**Examples:**
```bash
# Topic search
/search machine learning

# Technical search
/search React state management

# Project search
/search garden soil amendments

# Person search
/search conversations with Alice

# Technology search
/search Kubernetes deployment strategies
```

**Output:** Numbered results with "why matched" explanations and connection details.

### `/chat <query>`

**Purpose:** Context-aware AI conversation with transparent sourcing.

**Features:**
- **Entity-Aware Context** - Finds relevant memories via similarity AND shared entities
- **Corpus Pattern Signals** - Surfaces recurring terms, entities, and capture types from the memories you selected
- **AI Knowledge Synthesis** - Combines your context with AI's broader knowledge
- **Source Visibility** - Shows which retrieved memories were supplied as context

**Examples:**
```bash
# Exploration questions
/chat what patterns do you see in my React learning journey?

# Decision support
/chat based on my experience, should I use Redux or Context API?

# Knowledge synthesis
/chat what are the key themes in my gardening notes this season?

# Future planning
/chat what areas should I focus on next in my AI research?

# Temporal queries (see Temporal Search guide)
/chat what was I working on last week?
/chat what did I learn about React last month?
```

**Output:** AI response with source attribution showing which memories informed the answer.

### `/explore <number|concept>`

**Purpose:** Build a concept web around something you want to understand better.

Use a number when Mentat has just shown numbered concept references, or pass a concept name directly.

**Syntax:**
```bash
/explore <number>
/explore <concept name>
```

Top-level equivalent:
```bash
mentat explore "machine learning"
```

**Examples:**
```bash
# Explore a numbered concept from /view, /chat, or another result panel
/explore 4

# Explore a concept directly
/explore vector embeddings
/explore "soil chemistry"
```

**What it does:**
- Generates a related-concept tree for the starting concept
- Highlights paths that may connect to your existing memories
- Shows knowledge gaps and follow-up concepts worth exploring
- Prints the resolved ConceptExplorer provider/model settings before generation

**Output:** A concept exploration tree with numbered follow-up concepts. Those numbers can be used with `/explore` again or with `/explain` for a more focused explanation.

### `/explain <number|concept>`

**Purpose:** Get a focused explanation of one concept without expanding into a full concept web.

Use `/explain` when you want the idea clarified. Use `/explore` when you want adjacent ideas and learning paths.

**Syntax:**
```bash
/explain <number>
/explain <concept name>
```

Top-level equivalent:
```bash
mentat explain "vector embeddings"
```

**Examples:**
```bash
# Explain a numbered concept from a prior result
/explain 6

# Explain a concept directly
/explain higher-order functions
/explain "pH buffering"
```

**Output:** A concise but detailed explanation, usually including what the concept means, why it matters, how it connects to nearby ideas, and suggested next steps.

### `/latest`

**Purpose:** View recent content with AI analysis of patterns.

**Examples:**
```bash
/latest           # Last 10 items
/latest 20        # Last 20 items
```

**Output:** Numbered list of recent memories with timestamps, plus AI analysis of recent themes and patterns.

## 📊 Project & Organization Commands

### `/project <name>`

**Purpose:** Analyze all content related to a project with entity frequency analysis.

**Features:**
- **Semantic Content Discovery** - Finds all related memories
- **Entity Frequency Analysis** - Shows counts: "Technologies: React (8), Node.js (5)"
- **Timeline Analysis** - Chronological view of project evolution
- **Related Memory Surfacing** - Discovers unexpected connections

**Examples:**
```bash
# Software project
/project authentication refactor

# Personal project
/project garden

# Learning project
/project machine learning study

# Work project
/project customer dashboard redesign
```

**Output:** Project dashboard with content timeline, entity frequencies, and related memories.

### `/links [search]`

**Purpose:** View and search saved web resources.

**Examples:**
```bash
/links                    # Show all links
/links kubernetes         # Search links about Kubernetes
/links machine learning   # Find ML-related bookmarks
/links garden            # Gardening resources
```

**Output:** Formatted list of links with URLs, comments or legacy summaries, and tags.

### `/link <url> [comment]`

**Purpose:** Save a URL and optional comment without fetching the webpage.

**Features:**
- **No Page Fetch** - Stores the URL without opening or downloading the linked page
- **Optional Commentary** - Preserve why the link matters or provide an agent-generated summary
- **Focused Analysis** - Creates tags and metadata from only the URL and supplied comment
- **Full Integration** - Saved links remain searchable memories

**Examples:**
```bash
# Save with the reason it deserves to remain
/link https://kubernetes.io/docs/concepts/overview/ The control-plane explanation keeps changing how I think about service ownership

# Save research link
/link https://arxiv.org/abs/2103.00020 Interesting paper on transformer architectures and attention mechanisms

# Save tutorial
/link https://www.gardening.com/soil-ph-guide.html Great guide for adjusting soil pH naturally
```

**What it does:**
1. **Parses The Input** - Separates the URL from the optional comment
2. **Focused Tagging** - Creates tags from only that user-supplied text
3. **Memory Creation** - Saves the URL and comment as a searchable link memory

Mentat can save a bare URL, but that recreates an ordinary bookmark collection.
The more useful habit is to include the question, reaction, or connection that
made the page worth keeping.

**Output:** Confirmation with the URL, optional comment, generated tags, and connections to existing memories.

### `/todo [search|status]`

**Purpose:** Show actionable items extracted from your memories with filtering.

**Examples:**
```bash
/todo                     # Pending todos (the default view)
/todo garden             # Garden-related tasks
/todo urgent             # Search for urgent items
/todo @alice             # Tasks involving Alice
/todo pending            # Show only pending todos
/todo done               # Show only completed todos
```

**Output:** Numbered list of extracted actionable items with source context, metadata, and status indicators.

### `/mark <number>`

**Purpose:** Toggle todo status between pending and done.

**Examples:**
```bash
# After viewing todos with numbers
/todo
# ... shows numbered list like 1. 2. 3. etc.
/mark 2          # Toggles status of todo #2 (pending ↔ done)
/mark 5          # Toggles status of todo #5
```

**Output:** Confirmation of todo status change with updated status indicator.

### `/hide`

**Purpose:** Hide completed todos and show only pending ones.

**Examples:**
```bash
# After viewing todos and marking some as done
/todo            # Shows pending todos
/mark 2          # Mark todo #2 as done
/hide            # Hide completed todos, show only pending ones
```

**Output:** Filtered todo list showing only pending todos with count summary.

### `/tag <tags>`

**Purpose:** Search content by specific tags.

**Examples:**
```bash
/tag #ai #productivity          # Content with both tags
/tag machine-learning          # Single tag search
/tag #garden #soil #compost    # Multiple gardening tags
```

**Output:** Memories matching the specified tags with relevance information.

## 🔢 Reference Commands

### `/view <number>`

**Purpose:** View full content of numbered items from previous command results.

**Examples:**
```bash
# After a search command shows numbered results
/search React hooks
# ... results show as 1. 2. 3. etc.
/view 2          # Shows full content of result #2

# Works with any command that shows numbered results
/latest
/view 1          # Shows full content of latest item #1

# View without number shows available references
/view            # Shows count of available items to view
```

**Output:** Complete content with all metadata, entities, and tags.

### `/delete <number>`

**Purpose:** Safely remove a memory from numbered results with preview and confirmation.

**Safety Features:**
- **Preview Display** - Shows item type, date, and content preview before deletion
- **Confirmation Required** - Must type 'DELETE' to confirm (case-sensitive)
- **Database Integrity** - Removes from all related tables (memories, embeddings, FTS)
- **Automatic Renumbering** - Updates remaining items and shows new numbering

**Works With:**
- `/latest` results
- `/search` results
- `/tag` results
- `/todo` results
- Any command showing numbered items

**Examples:**
```bash
# After viewing latest memories
/latest
# ... shows numbered results 1. 2. 3. etc.
/delete 2        # Shows preview and asks for confirmation
# Type 'DELETE' to confirm or anything else to cancel

# After a search
/search old project notes
/delete 1        # Remove the first search result

# After viewing todos
/todo
/delete 3        # Remove todo item #3
```

**Interactive Flow:**
1. Command shows preview: type, date, content snippet
2. Warning: "This action cannot be undone!"
3. Prompt: "Type 'DELETE' to confirm:"
4. If confirmed: removes from database and updates numbering
5. If cancelled: no changes made

**Output:**
- **Preview**: Item details before confirmation
- **Success**: "✓ Memory {id} deleted successfully" + updated numbering info
- **Cancel**: "Deletion cancelled" if not confirmed

### `/save`

**Purpose:** Save the last AI response in a separate AI-reference archive.

**When Available:** Only appears after AI chat responses that can be saved.

**Examples:**
```bash
# After a chat response
/chat what are the key patterns in my React learning?
# ... AI provides detailed analysis ...
/save            # Saves the AI response as a memory

# Find it later through explicit AI-response search
/search ai response React learning
```

Saved AI responses are intentionally excluded from ordinary memory retrieval and
latest-memory views. They remain searchable references, but Mentat does not use
them as evidence of what you think. Capture a conclusion in your own words when
you want it to become part of normal memory context.

**Output:** Confirmation of saved AI response with AI analysis and connections.

## ⚙️ Utility Commands

### `/model [name|number|local|ollama|openrouter]`

**Purpose:** View or switch the active **chat route** and model. The display also shows resolved LLM routes for normal chat, ConceptExplorer, entity extraction, concept connection, capture analysis, todo extraction, temporal intent, and online/web-backed calls.

**Examples:**
```bash
/model                                      # Show current route, model, endpoint, and available options
/model gpt-5.2-chat                         # Switch saved model by label; routes chat through OpenRouter
/model 3                                    # Switch using number from config/models.json; routes chat through OpenRouter
/model local                                # Switch chat to configured local/LM Studio route and model
/model local google/gemma-4-12b-qat         # Switch chat to local endpoint with explicit model string
/model ollama                               # Switch chat to configured native Ollama route and model
/model ollama llama3.2                      # Switch chat to native Ollama with explicit model string
/model openrouter x-ai/grok-4.1-fast        # Switch chat to exact pasted OpenRouter model id
```

**Model list source and persistence:**
- `config/models.json` is the curated saved OpenRouter model list used by numbered/name selection
- `/model <number>` and `/model <saved-name>` are equivalent to `/model openrouter <saved-model-id>`
- Unknown pasted OpenRouter IDs can be saved into `config/models.json` when prompted in interactive mode
- The active chat route is persisted in `data/runtime_settings.json` as `chat_provider` plus `current_model`
- Runtime route selection wins over `.env` defaults, so a saved OpenRouter model does not silently use `CHAT_BASE_URL`
- `/model local` uses configured `CHAT_BASE_URL`/`CHAT_MODEL` or `LOCAL_BASE_URL`/`LOCAL_MODEL`
- `/model ollama` uses `OLLAMA_BASE_URL`/`OLLAMA_MODEL` and native Ollama `/api/chat`
- Routes with `PROVIDER=chat` follow the active chat route selected by `/model`
- Blank feature providers inherit `HELPERS_PROVIDER`/`HELPERS_MODEL` when set, then fall back to chat
- Explicit feature routes are controlled by provider/model env vars such as `CONCEPT_EXPLORATION_PROVIDER`, `ENTITY_EXTRACTION_PROVIDER`, and `CONCEPT_CONNECTION_PROVIDER`; these `.env` overrides do not change when `/model` changes chat

### `/summary [days]`

**Purpose:** Generate AI-powered summaries of captured memories.

**Examples:**
```bash
/summary          # Last 7 days (default)
/summary 14       # Last 14 days
/summary 30       # Last 30 days
/summary 1        # Yesterday only
```

**Output:** AI-generated summary of captured themes and insights over the specified period.

### `/synthesize <topic>`

**Purpose:** Combine related notes into a structured document.

**Examples:**
```bash
/synthesize React learning journey
/synthesize garden soil management
/synthesize machine learning fundamentals
/synthesize team meeting insights
```

**Output:** AI-synthesized document combining all related memories into a coherent narrative.

### `/help`

**Purpose:** Show command help and current system status.

**Output:**
- List of all available commands
- Current user and model
- Database statistics (memory count, links, todos)
- System configuration info

## 🚪 Session Commands

### `/voice`

**Purpose:** Start an interactive voice conversation session with AI-powered live transcript and dashboard.

**Features:**
- **Real-time Voice Chat**: Natural conversation with OpenAI or xAI Realtime API
- **Live Transcript Dashboard**: Rich terminal UI showing conversation in real-time
- **Session Control**: End with Ctrl+C and choose whether to save when auto-capture is disabled
- **Memory Integration**: Conversations can be analyzed, tagged, and saved to MENTAT
- **Status Display**: Visual indicators for listening, capturing, thinking, and speaking states

**Interface:**
```
┌─ Live Conversation ──────────────────────────────────────────┐
│ 👤 YOU: Can you help me brainstorm ideas for my React app?  │
│ 🤖 ASSISTANT: I'd be happy to help! What kind of React app  │
│              are you building? Is it for personal use,      │
│              a portfolio project, or something else?         │
│                                                              │
└──────────────────────────────────────────────────────────────┘
┌─ Status ─────────────────────────────────────────────────────┐
│ [👂 LISTENING] [🔴 REC] [ 03:42 ] Press Ctrl+C to End      │
└──────────────────────────────────────────────────────────────┘
```

**Session States:**
- **🔌 CONNECTING** - Establishing connection to voice API
- **⚙️ INITIALIZING** - Setting up audio and AI systems
- **👂 LISTENING** - Ready for your voice input
- **🗣️ CAPTURING** - Recording and processing your speech
- **THINKING** - AI processing your input
- **💬 SPEAKING** - AI delivering voice response

**Session Control:**
When `VOICE_AUTO_CAPTURE=false` and you press **Ctrl+C** to end a session with conversation data, you'll get options:
- **y** - Save conversation to MENTAT memory system
- **n** - Exit without saving

When `VOICE_AUTO_CAPTURE=true`, conversation data is saved automatically on normal exit.

**Examples:**
```bash
# Start a voice session
/voice

# During session: speak naturally with the AI
# "Help me think through my project architecture"
# "What are some good practices for React state management?"
# "Can you help me brainstorm features for my app?"

# End session: Ctrl+C → choose y/n when auto-capture is disabled
```

**Memory Integration:**
Voice conversations can be:
- **Analyzed by AI** - Extract key concepts, entities, and themes
- **Tagged and Categorized** - Generate relevant tags for discovery
- **Saved as Memories** - Full searchable integration with MENTAT
- **Connected to Context** - Link to related memories and projects

By default, `VOICE_AUTO_CAPTURE=false`, so Mentat asks before saving. Set `VOICE_AUTO_CAPTURE=true` to save automatically.

**Technical Requirements:**
- **Voice API Key** - Set `OPENAI_API_KEY` (OpenAI) or `XAI_API_KEY` (xAI)
- **Audio Hardware** - Microphone and speakers/headphones
- **Python Dependencies** - install the optional voice extra with `uv sync --extra voice`
**Provider Configuration:**
- `VOICE_PROVIDER` - `openai` (default) or `xai`
- `VOICE_REALTIME_URL` - Optional override for the realtime WebSocket URL
- `VOICE_MODEL` - Model name for OpenAI realtime (default: `gpt-realtime-mini`) or the current xAI realtime model available to your account
- `VOICE_TRANSCRIBE_MODEL` - Optional override for the input transcription model
- `VOICE_NAME` - Voice selection (`alloy` for OpenAI, `Ara`/`Rex`/`Sal`/`Eve`/`Leo` for xAI)

xAI example:
```env
VOICE_PROVIDER=xai
XAI_API_KEY=your_xai_key
VOICE_MODEL=replace_with_xai_realtime_model
VOICE_NAME=Ara
```

**Output:** Real-time voice conversation with rich terminal dashboard and optional memory capture.

### `/exit` or `/quit`

**Purpose:** Exit MENTAT interactive mode.

## Command Tips

### Multi-line Input
Interactive `/capture` supports multi-line input. Type `END` on its own line or press Ctrl+D to finish:
```bash
/capture
> This is line one
> This is line two
> This is line three
> END
```

### Command History
- **↑ Arrow** - Previous commands
- **↓ Arrow** - Next commands
- **Ctrl+R** - Reverse search through history
- History persists between sessions

### ConceptExplorer Integration
Commands work together for knowledge discovery:
```bash
/search machine learning    # Find ML content
/view 3                     # Examine result + get concept mini-web
# Shows: Neural Networks [4], Statistics [5], Deep Learning [6]
/explore 5                  # Deep dive into Statistics
/explain 6                  # Focused explanation of Deep Learning
/chat based on my exploration, what should I focus on next?
```

### Context Building
Commands work together to build context:
```bash
/search machine learning    # Find ML content
/view 3                     # Examine specific result + concept suggestions
/chat what should I learn next based on result 3?  # AI uses the context
```

### Web Enrichment Strategy
Use `/capture -w` when:
- Mentioning new technologies, models, papers, products, or concepts
- The active model may be too old to recognize the entity accurately
- The term is niche, ambiguous, acronym-heavy, or needs disambiguation
- Recording research findings from fast-moving domains
- Capturing meeting notes with unfamiliar terms
- Documenting learning from external sources

You do **not** need `-w` for normal entity extraction. Plain `/capture` already extracts entities and stores them in memory metadata. The `-w` flag adds web lookup for selected entities before the final analysis, mainly to improve tags, summaries, and classification.

### Which Web Feature Should I Use?

| Goal | Use | Why |
| --- | --- | --- |
| Save your own note, with extra context for new or ambiguous entities | `/capture -w <note>` | Keeps your original note as the memory and uses web context only to improve analysis. |
| Save a URL and why it matters | `/link <url> [comment]` | Stores only the URL and supplied comment as a searchable link memory. |
| Ask a research-style chat question that needs live web context | `/chat ...` with online/research routing | Uses the online/web-backed LLM path; model choice is controlled by `ONLINE_MODEL`. |

Use plain `/capture` when the URL belongs inside a larger thought. Use `/link` when the URL and your comment should be a dedicated link memory. Neither command fetches the linked page unless `/capture -w` separately performs its explicit entity-enrichment workflow.

---

*These commands are meant to stay practical: capture messy input, find it later, and let structure emerge as you use the system.*
