# cb-memory Setup Guide

Complete step-by-step guide to get cb-memory running.

## Prerequisites

- Python 3.10 or higher
- Couchbase Server (local service or remote cluster)
- OpenAI API key (optional, will use Ollama as fallback)

## Step 1: Start Couchbase

Install/start Couchbase Server locally (or use an existing remote cluster).

### Initialize Cluster

1. Open `http://localhost:8091` in your browser
2. Click "Setup New Cluster"
3. Create Administrator credentials:
   - Username: `Administrator`
   - Password: Choose a secure password (save it for later)
4. Accept defaults for RAM quotas (256MB is sufficient)
5. Accept terms and finish setup

The initialization takes about 30 seconds.

## Step 2: Install cb-memory

```bash
cd /Users/ruchit/Downloads/cb-retrival
pip install -e .
```

This installs the package in editable mode with all dependencies.

### Easy Path (Recommended)

Run the guided installer:

```bash
cb-memory install
```

It prompts for IDE selection (`factory`, `copilot-vscode`, `copilot-jetbrains`, `claude-code`, `codex`) and Couchbase credentials, then can write `.env`, run bootstrap, and configure IDE MCP files.

## Step 3: Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```bash
# Couchbase credentials (from Step 1)
CB_CONNECTION_STRING=couchbase://localhost
CB_USERNAME=Administrator
CB_PASSWORD=your_password_from_step1
CB_BUCKET=coding-memory

# OpenAI API key (optional)
# If not provided, will use Ollama instead
OPENAI_API_KEY=sk-your-key-here

# Ollama settings (used if no OpenAI key)
OLLAMA_HOST=http://localhost:11434
OLLAMA_EMBEDDING_MODEL=nomic-embed-text

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
```

Set `AUTO_IMPORT_CLAUDE_ON_START=false` if you want manual import only.

### If Using Ollama (No OpenAI Key)

Install Ollama:

```bash
# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.com/install.sh | sh
```

Start Ollama and pull the embedding model:

```bash
ollama serve &
ollama pull nomic-embed-text
```

## Step 4: Provision the Database

Recommended one-command bootstrap:

```bash
cb-memory init
```

Schema-only provisioning:

```bash
cb-memory setup
```

`cb-memory init` is Docker-free and performs: Couchbase reachability check, schema provisioning, chat/tool import, and optional embedding backfill.

This creates:
- Bucket: `coding-memory`
- 3 scopes: `conversations`, `knowledge`, `metadata`
- 7 collections: sessions, messages, summaries, decisions, bugs, thoughts, patterns, sync_state
- Primary indexes on all collections
- Search index for vector + full-text search

You should see output like:

```
Connecting to couchbase://localhost ...
Ensuring bucket 'coding-memory' exists ...
  Scope: conversations
    Collection: sessions
    Collection: messages
    Collection: summaries
...
Setup complete!
```

### Verify in Couchbase UI

1. Go to `http://localhost:8091`
2. Navigate to "Buckets" → `coding-memory`
3. Click "Scopes & Collections" to see the schema
4. Navigate to "Search" to see the search index

## Step 5: Verify Installation

Check that the CLI works:

```bash
cb-memory stats
```

Should show:

```
Memory Statistics
========================================
  conversations.sessions: 0
  conversations.messages: 0
  conversations.summaries: 0
  knowledge.decisions: 0
  knowledge.bugs: 0
  knowledge.thoughts: 0
  knowledge.patterns: 0
  metadata.sync_state: 0
```

## Step 6: Configure MCP Client

### For Claude Code

Create or edit `.claude/settings.json`:

```json
{
  "mcpServers": {
    "coding-memory": {
      "command": "python",
      "args": ["-m", "cb_memory.server"],
      "env": {
        "CB_CONNECTION_STRING": "couchbase://localhost",
        "CB_USERNAME": "Administrator",
        "CB_PASSWORD": "your_password",
        "CB_BUCKET": "coding-memory",
        "CURRENT_PROJECT_ID": "/absolute/path/to/your/project",
        "OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

### For OpenCode

Edit your `opencode.jsonc`:

```json
{
  "mcp": {
    "coding-memory": {
      "type": "local",
      "command": ["python", "-m", "cb_memory.server"],
      "environment": {
        "CB_CONNECTION_STRING": "couchbase://localhost",
        "CB_USERNAME": "Administrator",
        "CB_PASSWORD": "your_password",
        "CB_BUCKET": "coding-memory",
        "CURRENT_PROJECT_ID": "/absolute/path/to/your/project",
        "OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

Restart your MCP client to load the server.

## Step 7: Test the MCP Tools

In your AI coding assistant, try:

```
Can you use memory_save_decision to save a test decision?

Title: "Test Decision"
Description: "This is a test to verify the MCP tools are working"
Category: "test"
```

Then search for it:

```
Can you use memory_search to find the test decision we just saved?
Query: "test decision"
```

You should get back the decision you just saved!

## Step 8: Import Existing History (Optional)

### From OpenCode

```bash
cb-memory import --source opencode --backfill-embeddings
```

### From Claude Code

```bash
cb-memory import --source claude-code --backfill-embeddings
```

### From JSON Files

Create a JSON file in the format:

```json
{
  "title": "My Session",
  "messages": [
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi there!"}
  ]
}
```

Then import:

```bash
cb-memory import --source json --path ./my-session.json --backfill-embeddings
```

Check the results:

```bash
cb-memory stats
```

## Troubleshooting

### "Connection refused" errors

- Check Couchbase service status on your host
- Verify REST endpoint: `curl -sf http://127.0.0.1:8091/pools`
- Wait 30 seconds for Couchbase to be ready

### "Authentication failed"

- Verify credentials in `.env` match what you set in Step 1
- Check username is exactly `Administrator` (capital A)

### Search not finding results

- Make sure you ran setup: `cb-memory setup`
- Check search index exists in Couchbase UI → Search
- Verify embeddings were generated (use `--backfill-embeddings`)

### MCP client not detecting tools

- Verify the MCP server starts: `python -m cb_memory.server`
  - Should print: "Starting cb-memory MCP server..."
  - Press Ctrl+C to stop
- Check your client's MCP config file syntax (valid JSON)
- Restart your MCP client completely

### Import fails with "Storage path not found"

- For OpenCode: check `~/.local/share/opencode/storage` exists
- For Claude Code: check `~/.claude/projects` exists
- Use `--path` to specify a custom location

## Next Steps

You're all set! Now you can:

1. **Use the memory tools** in your AI coding assistant to save decisions, bugs, and patterns
2. **Search your memory** with `memory_search` to find past solutions
3. **Get project context** with `memory_project_context` at the start of sessions
4. **Import more history** as you discover old conversation logs

## Advanced Configuration

### Increase Bucket RAM

If you're storing many large sessions:

```bash
cb-memory setup --bucket-ram 512
```

### Use a Remote Couchbase Cluster

Update `.env`:

```bash
CB_CONNECTION_STRING=couchbase://your-cluster.example.com
CB_USERNAME=your-username
CB_PASSWORD=your-password
```

### Switch Embedding Providers

To switch from OpenAI to Ollama:

```bash
# Remove OpenAI key from .env
# Add or verify:
OLLAMA_HOST=http://localhost:11434
```

Then re-run setup to recreate search indexes with correct dimensions:

```bash
cb-memory setup
```

## Support

If you encounter issues:

1. Check the troubleshooting section above
2. Run commands with `-v` for verbose output: `cb-memory -v setup`
3. Check Couchbase service logs on your host
4. Open an issue on GitHub with error details

Enjoy your persistent coding memory! 🧠
