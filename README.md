
# cb-memory: Coding Memory System

A coding memory system powered by Couchbase that stores all past AI coding conversations, decisions, bug fixes, thoughts, and patterns — then exposes retrieval tools via MCP so any AI coding assistant can search and learn from past sessions.

## Features

- **Universal MCP Server**: Works with Claude Code, OpenCode, Cursor, Windsurf, and any MCP-compatible client
- **Semantic Search**: Vector search powered by OpenAI embeddings (with Ollama fallback)
- **Rich Memory Types**: Sessions, decisions, bugs, thoughts, patterns — all fully searchable
- **Import Tools**: Built-in importers for OpenCode, Claude Code, and Factory
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

### Prerequisites

- Docker Desktop (for Couchbase)
- Python 3.10+
- Ollama (for local embeddings)

### One-Command Setup

**macOS:**
```bash
git clone https://github.com/cserp440/couch-context.git
cd couch-context
./scripts/bootstrap_macos.sh
```

**Linux:**
```bash
git clone https://github.com/cserp440/couch-context.git
cd couch-context
./scripts/bootstrap_linux.sh
```

The script will:
- Install Python 3.10+ and Ollama if needed
- Start Couchbase via Docker and provision the database
- Configure Factory MCP and import existing chat history

After bootstrap completes, restart your IDE and test with: "What have we worked on?"

### Manual Setup

1. **Install dependencies:**
   ```bash
   pip install -e .
   ```

2. **Run guided installer:**
   ```bash
   cb-memory install
   ```

3. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your Couchbase and OpenAI credentials
   ```

4. **Setup database:**
   ```bash
   cb-memory setup
   ```

5. **Import existing history (optional):**
   ```bash
   cb-memory import --source factory
   cb-memory import --source claude-code
   ```

## MCP Tools

### Retrieval
- `memory_search` - Semantic search across all memory
- `memory_recall_decision` - Find past architectural/coding decisions
- `memory_recall_bug` - Find past bug reports and fixes
- `memory_context_for_request` - Get comprehensive context for current request
- `memory_list_sessions` - List past coding sessions
- `memory_get_session` - Get full session detail with messages
- `memory_project_context` - Get aggregated project context

### Knowledge Capture
- `memory_save_decision` - Record architectural/coding decisions
- `memory_save_bug` - Record bug reports and fixes
- `memory_save_thought` - Save developer notes
- `memory_save_pattern` - Save recurring code patterns

### Session Management
- `memory_ingest_session` - Save a full session to memory
- `memory_ingest_message` - Save a single message to a session

## Usage

Ask your AI assistant to use memory tools:

```
"Search for past decisions about database choices"
"What bugs have we fixed related to authentication?"
"Show me the context for this project"
"Save this decision: Use FastAPI for better async support"
```

## CLI Commands

```bash
# Guided installation
cb-memory install

# Setup database schema
cb-memory setup

# Import from various sources
cb-memory import --source factory
cb-memory import --source claude-code
cb-memory import --backfill-embeddings

# Show statistics
cb-memory stats
```

## Configuration

### Environment Variables

Key settings in `.env`:

```bash
# Couchbase
CB_CONNECTION_STRING=couchbase://localhost
CB_USERNAME=Administrator
CB_PASSWORD=your_password
CB_BUCKET=coding-memory

# Embeddings (OpenAI or Ollama)
OPENAI_API_KEY=sk-...  # Optional, falls back to Ollama
OLLAMA_HOST=http://localhost:11434

# Project tracking
CURRENT_PROJECT_ID=/absolute/path/to/your/project

# Auto-import settings
AUTO_IMPORT_CLAUDE_ON_START=true
AUTO_IMPORT_CODEX_ON_START=true
AUTO_IMPORT_ON_QUERY=true
AUTO_IMPORT_MIN_INTERVAL_SECONDS=45

# Search scope
INCLUDE_ALL_PROJECTS_BY_DEFAULT=true
DEFAULT_RELATED_PROJECTS=/path/to/project1,/path/to/project2
```

### Embedding Providers

**OpenAI** (Primary): `text-embedding-3-small` (1536-dim)  
**Ollama** (Fallback): `nomic-embed-text` (768-dim)

## Development

```bash
# Run tests
pip install -e ".[dev]"
pytest

# Project structure
src/cb_memory/
├── server.py          # MCP server
├── tools/             # MCP tool implementations
├── importers/         # Import from various sources
└── cli/              # CLI commands
```
