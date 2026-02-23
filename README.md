# cb-memory: Coding Memory System

A coding memory system powered by Couchbase that stores all past AI coding conversations, decisions, bug fixes, thoughts, and patterns — then exposes retrieval tools via MCP so any AI coding assistant can search and learn from past sessions.

## Features

- **Universal MCP Server**: Works with Claude Code, OpenCode, Cursor, Windsurf, and any MCP-compatible client
- **Semantic Search**: Vector search powered by OpenAI embeddings (with Ollama fallback)
- **Rich Memory Types**: Sessions, decisions, bugs, thoughts, patterns — all fully searchable
- **Import Tools**: Built-in importers for OpenCode, Claude Code, JSON, and Markdown
- **Full-Text + Vector Search**: Combines FTS and vector search for comprehensive retrieval

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Any MCP Client (Claude Code, OpenCode, Cursor) │
│                                                  │
│  Uses MCP tools:                                │
│    memory_search, memory_save_decision,         │
│    memory_save_bug, memory_recall, etc.         │
└──────────────────┬──────────────────────────────┘
                   │ MCP Protocol (stdio)
                   ▼
┌─────────────────────────────────────────────────┐
│           cb-memory MCP Server (Python)         │
│                                                  │
│  ┌──────────┐  ┌───────────┐  ┌──────────────┐ │
│  │ Retrieval│  │ Knowledge │  │  Embeddings  │ │
│  │  Tools   │  │  Capture  │  │  (OpenAI /   │ │
│  │          │  │  Tools    │  │   Ollama)    │ │
│  └────┬─────┘  └─────┬─────┘  └──────┬───────┘ │
│       └───────────────┼───────────────┘         │
└───────────────────────┼─────────────────────────┘
                        │ Couchbase SDK
                        ▼
┌─────────────────────────────────────────────────┐
│              Couchbase Server                   │
│                                                  │
│  Bucket: coding-memory                          │
│  ├── scope: conversations                       │
│  │   ├── sessions, messages, summaries          │
│  ├── scope: knowledge                           │
│  │   ├── decisions, bugs, thoughts, patterns    │
│  └── scope: metadata                            │
│      └── sync_state                             │
└─────────────────────────────────────────────────┘
```

## Quick Start

### 1. Install Dependencies

```bash
pip install -e .
```

### 2. Run Guided Installer (Factory + GitHub Copilot)

```bash
cb-memory install
```

This wizard asks for:
- IDE selection (`factory`, `copilot-vscode`, `copilot-jetbrains`, `claude-code`, `codex`)
- Couchbase credentials
- OpenAI key (optional) or Ollama fallback settings

It can write `.env`, run bootstrap (`cb-memory init`), and generate IDE MCP config files.

### 3. Setup Couchbase (Manual/Advanced)

Run Couchbase Server locally (or use an existing remote cluster), then initialize the cluster via the web UI at `http://localhost:8091`:
- Create an Administrator account
- Configure cluster settings (default RAM quotas are fine)

Optional one-command local bootstrap:

```bash
./scripts/bootstrap_macos.sh
# or
./scripts/bootstrap_linux.sh
```

### 4. Configure Environment

Copy the example env file and add your credentials:

```bash
cp .env.example .env
```

Edit `.env`:

```bash
# Couchbase
CB_CONNECTION_STRING=couchbase://localhost
CB_USERNAME=Administrator
CB_PASSWORD=your_password
CB_BUCKET=coding-memory

# OpenAI (optional — will fallback to Ollama if not set)
OPENAI_API_KEY=sk-...

# Ollama (used if no OpenAI key)
OLLAMA_HOST=http://localhost:11434

# Optional explicit workspace project id (absolute path).
# If omitted, runtime uses current working directory.
CURRENT_PROJECT_ID=/absolute/path/to/your/project

# Default retrieval scope controls:
# true => search across all projects unless a call explicitly narrows scope.
INCLUDE_ALL_PROJECTS_BY_DEFAULT=true
# Optional comma-separated project IDs for default cross-project scope.
# Leave empty when INCLUDE_ALL_PROJECTS_BY_DEFAULT=true.
DEFAULT_RELATED_PROJECTS=/Users/ruchit/Downloads/cb-retrival,/Users/ruchit/Downloads/local_agent

# Auto-import Claude chats when MCP server starts
AUTO_IMPORT_CLAUDE_ON_START=true
AUTO_IMPORT_CLAUDE_PATH=~/.claude/projects

# Auto-import Codex chats when MCP server starts
AUTO_IMPORT_CODEX_ON_START=true
AUTO_IMPORT_CODEX_PATH=~/.codex

# Also auto-import on query (with cooldown) so fresh chats are searchable
AUTO_IMPORT_ON_QUERY=true
AUTO_IMPORT_MIN_INTERVAL_SECONDS=45
```

`AUTO_IMPORT_CLAUDE_ON_START=false` disables startup sync.
`AUTO_IMPORT_ON_QUERY=false` disables query-time sync.

Scope behavior notes:
- `INCLUDE_ALL_PROJECTS_BY_DEFAULT=true` makes `memory_search`, `memory_kv_semantic_search`, and `memory_context_for_request` search all projects by default.
- `DEFAULT_RELATED_PROJECTS` lets you keep scope limited to a known set of project IDs (cross-project) instead of global.

### 5. Provision the Database

```bash
cb-memory setup
```

This creates:
- Bucket: `coding-memory`
- Scopes and collections (conversations, knowledge, metadata)
- Primary indexes
- Vector search index (1536-dim for OpenAI, 768-dim for Ollama)
- Full-text search index

### 6. Configure MCP Client

#### For Claude Code

Add to `.claude/settings.json` or your project's settings:

```json
{
  "mcpServers": {
    "coding-memory": {
      "command": "python",
      "args": ["-m", "cb_memory.server"],
      "env": {
        "CB_CONNECTION_STRING": "couchbase://localhost",
        "CB_USERNAME": "Administrator",
        "CB_PASSWORD": "password",
        "CB_BUCKET": "coding-memory",
        "CURRENT_PROJECT_ID": "/absolute/path/to/your/project",
        "OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

#### For OpenCode

Add to your `opencode.jsonc`:

```json
{
  "mcp": {
    "coding-memory": {
      "type": "local",
      "command": ["python", "-m", "cb_memory.server"],
      "environment": {
        "CB_CONNECTION_STRING": "couchbase://localhost",
        "CB_USERNAME": "Administrator",
        "CB_PASSWORD": "password",
        "CB_BUCKET": "coding-memory",
        "CURRENT_PROJECT_ID": "/absolute/path/to/your/project",
        "OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

### 7. Import Existing History (Optional)

Import from OpenCode:

```bash
cb-memory import --source opencode
```

Import from Claude Code:

```bash
cb-memory import --source claude-code
```

Import from JSON files:

```bash
cb-memory import --source json --path ./exports/
```

Generate embeddings for imported data:

```bash
cb-memory import --source opencode --backfill-embeddings
```

## MCP Tools

### Retrieval Tools

| Tool | Description |
|---|---|
| `memory_search` | Semantic search across all memory (vector + FTS) |
| `memory_recall_decision` | Find past architectural/coding decisions |
| `memory_recall_bug` | Find past bug reports and fixes |
| `memory_list_sessions` | List past coding sessions with pagination |
| `memory_get_session` | Get full session detail with messages |
| `memory_project_context` | Get aggregated project context summary |

### Knowledge Capture Tools

| Tool | Description |
|---|---|
| `memory_save_decision` | Record an architectural/coding decision |
| `memory_save_bug` | Record a bug report and its fix |
| `memory_save_thought` | Save a developer note or observation |
| `memory_save_pattern` | Save a recurring code pattern |

### Session Ingestion Tools

| Tool | Description |
|---|---|
| `memory_ingest_session` | Save a full session to memory |
| `memory_ingest_message` | Save a single message to a session |

## Usage Examples

### Search for past decisions

```
[In your AI coding assistant]

Can you use memory_search to find any past decisions about database choices?
```

### Record a decision

```
I just decided to use FastAPI instead of Flask.
Can you save this decision with memory_save_decision?

Title: "Use FastAPI for API Framework"
Description: "Chose FastAPI over Flask for better async support and automatic OpenAPI docs"
Category: "library-choice"
Alternatives: ["Flask", "Django"]
```

### Record a bug fix

```
I just fixed a null pointer exception in the login handler.
Can you save this with memory_save_bug?

Title: "Null pointer in login handler"
Root cause: "User object was accessed before null check"
Fix: "Added null check before accessing user.email"
```

### Get project context

```
Can you use memory_project_context to show me what we've worked on
in this project recently?
```

## CLI Commands

```bash
# One-shot bootstrap (Docker-free):
# verifies Couchbase REST API, provisions schema, imports chats,
# and keeps auto-sync enabled
cb-memory init

# Setup database schema only
cb-memory setup

# Deprecated alias (still works, no Docker behavior)
cb-memory replicate

# Import from various sources
cb-memory import --source opencode
cb-memory import --source claude-code
cb-memory import --source json --path ./exports/
cb-memory import --backfill-embeddings

# Show statistics
cb-memory stats
```

## Development

### Run Tests

```bash
pip install -e ".[dev]"
pytest
```

### Project Structure

```
cb-retrival/
├── src/cb_memory/
│   ├── config.py              # Settings from env vars
│   ├── db.py                  # Couchbase client
│   ├── embeddings.py          # OpenAI + Ollama embeddings
│   ├── models.py              # Pydantic document models
│   ├── server.py              # MCP server entry point
│   ├── tools/                 # MCP tool implementations
│   │   ├── search.py          # Semantic search
│   │   ├── recall.py          # Decision/bug recall
│   │   ├── save.py            # Knowledge capture
│   │   ├── sessions.py        # Session management
│   │   └── context.py         # Project context
│   ├── importers/             # Import from various sources
│   │   ├── opencode.py
│   │   ├── claude_code.py
│   │   └── generic.py
│   └── cli/
│       └── main.py            # CLI commands
└── tests/                     # Test suite
```

## Data Models

### Conversations Scope

- **SessionDoc**: Session metadata (title, project, tools used, files modified)
- **MessageDoc**: Individual messages within sessions
- **SummaryDoc**: AI-generated session summaries

### Knowledge Scope

- **DecisionDoc**: Architectural/coding decisions with context and alternatives
- **BugDoc**: Bug reports with root cause and fix descriptions
- **ThoughtDoc**: Developer notes and observations
- **PatternDoc**: Recurring code patterns with examples

All documents include embeddings for semantic search.

## Embedding Providers

### OpenAI (Primary)

- Model: `text-embedding-3-small`
- Dimensions: 1536
- Used when `OPENAI_API_KEY` is set

### Ollama (Fallback)

- Model: `nomic-embed-text`
- Dimensions: 768
- Used when no OpenAI key is configured
- Requires Ollama running locally

## Troubleshooting

### Search not finding results

- Ensure embeddings were generated: `cb-memory import --backfill-embeddings`
- Check that the search index is built: visit Couchbase UI at `localhost:8091` → Search

### Connection errors

- Verify Couchbase is running and reachable: `curl -sf http://127.0.0.1:8091/pools`
- Check connection string in `.env`
- Verify credentials in `.env`

### Import fails

- Check that source directories exist
- Verify file permissions
- Use `--verbose` flag for detailed logs: `cb-memory -v import ...`

## License

MIT

## Contributing

Contributions welcome! Please open an issue or PR.
