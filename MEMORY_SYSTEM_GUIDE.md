# Couchbase Coding Memory - Quick Reference

## ✅ Setup Complete

Your coding memory system is **fully operational** and automatically integrated with Claude Code and Codex.

### Current Status
- **Database**: Couchbase running on Docker (ports 18091-18097, 21210-21211)
- **Sessions Stored**: 29 total (24 Codex + 5 Claude Code)
- **MCP Server**: Auto-configured in `~/.claude/settings.json`
- **Auto-Import**: Claude Code and Codex chats sync automatically on startup

## How It Works

### Automatic Behavior

1. **When you start Claude Code**:
   - MCP server automatically starts
   - Imports new Claude Code sessions from `~/.claude/projects/`
   - Imports new Codex sessions from `~/.codex/`
   - All sessions are searchable immediately

2. **During conversations**:
   - Claude Code has instructions in `~/.claude/CLAUDE.md` to:
     - Check memory BEFORE answering technical questions
     - Save important decisions, bugs, and patterns AFTER work
   - Memory retrieval happens automatically (per CLAUDE.md instructions)

3. **What gets stored**:
   - All conversation messages (user + assistant)
   - Tool calls and results
   - Architectural decisions
   - Bug fixes and solutions
   - Code patterns
   - Developer notes

## MCP Tools Available

### Retrieval Tools (Used Automatically)
```
memory_context_for_request    - Get relevant context for current request
memory_kv_semantic_search      - Keyword + semantic search
memory_search                  - General semantic search
memory_recall_decision         - Find past decisions
memory_recall_bug              - Find past bug fixes
memory_list_sessions           - List past sessions
memory_project_context         - Get project overview
```

### Knowledge Capture Tools (Used After Work)
```
memory_save_decision           - Save architectural choices
memory_save_bug                - Save bug fixes
memory_save_pattern            - Save code patterns
memory_save_thought            - Save notes/observations
```

## Configuration Files

### Global Settings
- `~/.claude/CLAUDE.md` - Instructions for ALL Claude Code sessions
- `~/.claude/settings.json` - MCP server configuration
- `~/.claude/bin/coding-memory-mcp.sh` - MCP server startup script

### Project Settings
- `.claude/settings.local.json` - Project-specific permissions
- `CLAUDE.md` - Project-specific memory instructions

## Database Access

### Web UI
- URL: http://localhost:18091
- Username: Administrator
- Password: password

### Query Console
- N1QL endpoint: http://localhost:18093/query/service

### CLI Management
```bash
# View stats
curl -u Administrator:password -X POST \
  http://localhost:18093/query/service \
  -d 'statement=SELECT source, COUNT(*) as cnt FROM `coding-memory`.conversations.sessions GROUP BY source'

# View recent sessions
curl -u Administrator:password -X POST \
  http://localhost:18093/query/service \
  -d 'statement=SELECT title, source, created_at FROM `coding-memory`.conversations.sessions ORDER BY created_at DESC LIMIT 10'
```

## Searching Memory Manually

### Example Queries

**Find sessions about authentication:**
```
Use MCP tool: memory_search
Query: "authentication implementation"
```

**Find bug fixes related to login:**
```
Use MCP tool: memory_recall_bug
Query: "login error"
```

**Find past architectural decisions:**
```
Use MCP tool: memory_recall_decision
Query: "database choice" or "framework selection"
```

**Get context for current project:**
```
Use MCP tool: memory_project_context
Project ID: /Users/ruchit/Downloads/cb-retrival
```

## Cross-Project Memory

By default, memory searches are scoped to the current project. To search globally:

```
memory_search(
  query: "your search",
  include_all_projects: true  // Search across ALL projects
)
```

Or search specific projects:
```
memory_search(
  query: "your search",
  related_project_ids: ["/path/to/project1", "/path/to/project2"]
)
```

## Expected Behavior

### ✅ What Should Happen Automatically

1. **Before Claude answers technical questions**:
   - Calls `memory_context_for_request` to check past work
   - References relevant past sessions in the answer
   - Says "Based on session X..." or "We previously decided..."

2. **After completing work**:
   - Saves important decisions with `memory_save_decision`
   - Saves bug fixes with `memory_save_bug`
   - Saves patterns with `memory_save_pattern`

3. **New sessions auto-import**:
   - Every time Claude Code starts, new sessions sync to memory
   - Codex sessions also sync automatically
   - No manual import needed

### 🔍 How to Verify It's Working

Ask Claude: "What past work have we done in this project?"
- Should call `memory_project_context` or `memory_list_sessions`
- Should list actual past sessions

Ask Claude: "Have we ever implemented authentication before?"
- Should call `memory_search` or `memory_recall_decision`
- Should find relevant past work if it exists

## Troubleshooting

### Memory not being used?
- Check `~/.claude/CLAUDE.md` exists and has the instructions
- Restart Claude Code to reload settings
- Explicitly ask: "Check memory for [topic]"

### Sessions not importing?
- Check MCP server is running: Look for "coding-memory" in Claude settings
- Check Docker container: `docker ps | grep couchbase`
- Manually trigger import: See "Manual Operations" below

### Connection issues?
- Verify Couchbase is running: `curl http://localhost:18091`
- Check container IP: Should be 172.17.0.3
- Container should be named `couchbase-memory-local`

## Manual Operations

### Force Import
```bash
# Import Claude Code sessions
docker run --rm --network bridge \
  -v ~/.claude/projects:/claude-projects:ro \
  -e CB_CONNECTION_STRING=couchbase://172.17.0.3 \
  -e CB_USERNAME=Administrator \
  -e CB_PASSWORD=password \
  -e CB_BUCKET=coding-memory \
  cb-memory-mcp sh -c "cb-memory import --source claude-code --path /claude-projects"
```

### View Memory Stats
```bash
curl -u Administrator:password -X POST \
  http://localhost:18093/query/service \
  -d 'statement=SELECT COUNT(*) FROM `coding-memory`.conversations.sessions'
```

### Search via N1QL
```bash
curl -u Administrator:password -X POST \
  http://localhost:18093/query/service \
  -d 'statement=SELECT title FROM `coding-memory`.conversations.sessions WHERE title LIKE "%authentication%"'
```

## Architecture Summary

```
Claude Code / Codex
        ↓
   MCP Protocol
        ↓
  cb-memory MCP Server (Docker)
        ↓
    Couchbase SDK
        ↓
  Couchbase Database (Docker)
        ↓
  Persistent Memory Storage
  (conversations + knowledge)
```

## Next Steps

### To verify it's working:
1. Ask Claude: "What have we worked on in this project?"
2. Check if it calls memory tools and shows past sessions
3. Do some work, then ask: "Did you save that decision to memory?"

### To test cross-agent memory:
1. Work on something in Codex
2. Switch to Claude Code
3. Ask: "What did we do in Codex recently?"
4. Should find and reference the Codex sessions

### To customize:
- Edit `~/.claude/CLAUDE.md` for global behavior changes
- Edit project `CLAUDE.md` for project-specific instructions
- Adjust MCP settings in `~/.claude/settings.json`

## Support

- Documentation: See README.md and SETUP_GUIDE.md
- Couchbase UI: http://localhost:18091
- Check logs: `docker logs couchbase-memory-local`

---

**🎉 Your coding memory system is ready!**

All Claude Code and Codex conversations are automatically saved and searchable. Past decisions, bugs, and patterns are instantly retrievable across all projects.
