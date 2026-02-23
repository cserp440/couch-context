"""MCP server entry point — wires all tools together."""

from __future__ import annotations

import logging

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from cb_memory.config import get_settings
from cb_memory.db import CouchbaseClient
from cb_memory.embeddings import get_embedding_provider
from cb_memory.sync import auto_sync_claude, auto_sync_codex, maybe_auto_sync_recent
from cb_memory.tools import context, recall, save, search, sessions

import sys

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger(__name__)

# Initialize globals
settings = get_settings()
db = CouchbaseClient.get_instance(settings)
provider = get_embedding_provider(settings)

# Create MCP server
app = Server("cb-memory")

QUERY_TOOLS = {
    "memory_search",
    "memory_kv_semantic_search",
    "memory_recall_decision",
    "memory_recall_bug",
    "memory_list_sessions",
    "memory_get_session",
    "memory_project_context",
    "memory_context_for_request",
}


# ---------------------------------------------------------------------------
# Tool Definitions
# ---------------------------------------------------------------------------

TOOLS = [
    Tool(
        name="memory_search",
        description="Semantic search across all coding memory — past sessions, decisions, bugs, patterns, and thoughts",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language search query"},
                "project_id": {"type": "string", "description": "Filter by project (optional)"},
                "related_project_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional additional project IDs for cross-project retrieval",
                },
                "include_all_projects": {
                    "type": "boolean",
                    "description": "If true, search globally across all projects (if omitted, server env defaults may apply)",
                },
                "limit": {"type": "integer", "description": "Max results", "default": 10},
                "collections": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Restrict to specific collections (optional)",
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="memory_kv_semantic_search",
        description="Keyword (KV/grep-style) search across memory + semantic search merge",
        inputSchema={
            "type": "object",
            "properties": {
                "terms": {"type": "array", "items": {"type": "string"}, "description": "Keyword terms"},
                "project_id": {"type": "string", "description": "Filter by project (optional)"},
                "related_project_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional additional project IDs for cross-project retrieval",
                },
                "include_all_projects": {
                    "type": "boolean",
                    "description": "If true, search globally across all projects (if omitted, server env defaults may apply)",
                },
                "limit": {"type": "integer", "description": "Max results", "default": 20},
                "per_collection_limit": {"type": "integer", "description": "Max per collection", "default": 10},
            },
            "required": ["terms"],
        },
    ),
    Tool(
        name="memory_recall_decision",
        description="Find past architectural or coding decisions by semantic similarity",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What decision are you looking for?"},
                "category": {"type": "string", "description": "Filter by category (optional)"},
                "project_id": {"type": "string", "description": "Filter by project (optional)"},
                "limit": {"type": "integer", "description": "Max results", "default": 5},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="memory_recall_bug",
        description="Find past bug reports and fixes by semantic similarity",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Describe the bug or error"},
                "severity": {"type": "string", "description": "Filter by severity (optional)"},
                "project_id": {"type": "string", "description": "Filter by project (optional)"},
                "limit": {"type": "integer", "description": "Max results", "default": 5},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="memory_list_sessions",
        description="List past coding sessions with pagination",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Filter by project (optional)"},
                "limit": {"type": "integer", "description": "Max sessions", "default": 20},
                "offset": {"type": "integer", "description": "Pagination offset", "default": 0},
                "sort_by": {"type": "string", "description": "Sort field", "default": "created_at"},
            },
        },
    ),
    Tool(
        name="memory_get_session",
        description="Get full session detail including messages and summary",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID"},
                "include_messages": {"type": "boolean", "description": "Include messages", "default": True},
                "message_limit": {"type": "integer", "description": "Max messages", "default": 5000},
            },
            "required": ["session_id"],
        },
    ),
    Tool(
        name="memory_project_context",
        description="Get aggregated project context — recent sessions, decisions, bugs, and patterns",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project ID", "default": "default"},
                "max_sessions": {"type": "integer", "description": "Max recent sessions", "default": 5},
                "max_decisions": {"type": "integer", "description": "Max decisions", "default": 10},
                "max_bugs": {"type": "integer", "description": "Max bugs", "default": 5},
                "max_patterns": {"type": "integer", "description": "Max patterns", "default": 5},
            },
        },
    ),
    Tool(
        name="memory_context_for_request",
        description="Build a rich context pack for a specific request (search + recent project context + retrieval reasoning)",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "User request or question"},
                "project_id": {"type": "string", "description": "Project ID", "default": "default"},
                "related_project_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional additional project IDs for cross-project retrieval",
                },
                "include_all_projects": {
                    "type": "boolean",
                    "description": "If true, search globally across all projects (if omitted, server env defaults may apply)",
                },
                "file_paths": {"type": "array", "items": {"type": "string"}, "description": "Relevant file paths"},
                "limit": {"type": "integer", "description": "Max search results", "default": 12},
                "per_type_limit": {"type": "integer", "description": "Max results per doc type", "default": 6},
                "include_messages": {"type": "boolean", "description": "Include message excerpts", "default": True},
                "message_limit": {"type": "integer", "description": "Max messages to return", "default": 20},
                "max_context_tokens": {
                    "type": "integer",
                    "description": "Cap for llm_context/context_text token estimate",
                    "default": 2000,
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="memory_save_decision",
        description="Record an architectural or coding decision",
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Decision title"},
                "description": {"type": "string", "description": "Detailed description"},
                "category": {"type": "string", "description": "Category (e.g. 'architecture', 'library-choice')"},
                "context": {"type": "string", "description": "Context that led to this decision"},
                "alternatives": {"type": "array", "items": {"type": "string"}, "description": "Alternatives considered"},
                "consequences": {"type": "array", "items": {"type": "string"}, "description": "Consequences"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags"},
                "project_id": {"type": "string", "description": "Project ID", "default": "default"},
                "source_session_id": {"type": "string", "description": "Source session (optional)"},
            },
            "required": ["title", "description"],
        },
    ),
    Tool(
        name="memory_save_bug",
        description="Record a bug report and its fix",
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Bug title"},
                "description": {"type": "string", "description": "Bug description"},
                "root_cause": {"type": "string", "description": "Root cause analysis"},
                "fix_description": {"type": "string", "description": "How it was fixed"},
                "files_affected": {"type": "array", "items": {"type": "string"}, "description": "Affected files"},
                "error_messages": {"type": "array", "items": {"type": "string"}, "description": "Error messages"},
                "severity": {"type": "string", "description": "Severity", "default": "medium"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags"},
                "project_id": {"type": "string", "description": "Project ID", "default": "default"},
                "source_session_id": {"type": "string", "description": "Source session (optional)"},
            },
            "required": ["title", "description"],
        },
    ),
    Tool(
        name="memory_save_thought",
        description="Save a developer thought, observation, or note",
        inputSchema={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The thought or observation"},
                "category": {"type": "string", "description": "Category (e.g. 'observation', 'idea', 'concern')"},
                "related_files": {"type": "array", "items": {"type": "string"}, "description": "Related files"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags"},
                "project_id": {"type": "string", "description": "Project ID", "default": "default"},
                "source_session_id": {"type": "string", "description": "Source session (optional)"},
            },
            "required": ["content"],
        },
    ),
    Tool(
        name="memory_save_pattern",
        description="Save a recurring code pattern",
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Pattern title"},
                "description": {"type": "string", "description": "Pattern description"},
                "code_example": {"type": "string", "description": "Code example"},
                "use_cases": {"type": "array", "items": {"type": "string"}, "description": "Use cases"},
                "language": {"type": "string", "description": "Programming language"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags"},
                "project_id": {"type": "string", "description": "Project ID", "default": "default"},
                "source_session_id": {"type": "string", "description": "Source session (optional)"},
            },
            "required": ["title", "description"],
        },
    ),
    Tool(
        name="memory_ingest_session",
        description="Save a full coding session (metadata + messages) to memory",
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Session title"},
                "messages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {"type": "string"},
                            "content": {"type": "string"},
                        },
                    },
                    "description": "List of messages",
                },
                "project_id": {"type": "string", "description": "Project ID", "default": "default"},
                "directory": {"type": "string", "description": "Working directory"},
                "source": {"type": "string", "description": "Source (e.g. 'opencode', 'manual')"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags"},
                "summary": {"type": "string", "description": "Session summary (optional)"},
            },
            "required": ["title", "messages"],
        },
    ),
    Tool(
        name="memory_ingest_message",
        description="Save a single message to an existing session",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Parent session ID"},
                "role": {"type": "string", "description": "Message role (user/assistant/system)"},
                "content": {"type": "string", "description": "Message content"},
                "tool_calls": {"type": "array", "items": {"type": "object"}, "description": "Tool calls (optional)"},
                "sequence_number": {"type": "integer", "description": "Position in conversation", "default": 0},
            },
            "required": ["session_id", "role", "content"],
        },
    ),
]


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List all available tools."""
    return TOOLS


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    import json

    logger.info(f"Tool called: {name}")

    result = None

    try:
        if name in QUERY_TOOLS:
            requested_project_id = arguments.get("project_id") if isinstance(arguments, dict) else None
            sync_status = maybe_auto_sync_recent(
                db=db,
                settings=settings,
                project_id=requested_project_id or getattr(settings, "current_project_id", None),
            )
            logger.info(f"Query-time sync status: {sync_status.get('status')}")

        # Search & Recall
        if name == "memory_search":
            result = await search.memory_search(db, provider, **arguments)
        elif name == "memory_kv_semantic_search":
            result = await search.memory_kv_semantic_search(db, provider, **arguments)
        elif name == "memory_recall_decision":
            result = await recall.memory_recall_decision(db, provider, **arguments)
        elif name == "memory_recall_bug":
            result = await recall.memory_recall_bug(db, provider, **arguments)

        # Sessions
        elif name == "memory_list_sessions":
            result = await sessions.memory_list_sessions(db, **arguments)
        elif name == "memory_get_session":
            result = await sessions.memory_get_session(db, **arguments)
        elif name == "memory_ingest_session":
            result = await sessions.memory_ingest_session(db, provider, **arguments)
        elif name == "memory_ingest_message":
            result = await sessions.memory_ingest_message(db, provider, **arguments)

        # Context
        elif name == "memory_project_context":
            result = await context.memory_project_context(db, provider, **arguments)
        elif name == "memory_context_for_request":
            result = await context.memory_context_for_request(db, provider, **arguments)

        # Save
        elif name == "memory_save_decision":
            result = await save.memory_save_decision(db, provider, **arguments)
        elif name == "memory_save_bug":
            result = await save.memory_save_bug(db, provider, **arguments)
        elif name == "memory_save_thought":
            result = await save.memory_save_thought(db, provider, **arguments)
        elif name == "memory_save_pattern":
            result = await save.memory_save_pattern(db, provider, **arguments)

        else:
            result = {"error": f"Unknown tool: {name}"}

    except Exception as e:
        logger.error(f"Tool execution error: {e}", exc_info=True)
        result = {"error": str(e)}

    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def _run_stdio_server() -> None:
    """Run MCP stdio loop using the current mcp-python API."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


def main():
    """Run the MCP server."""
    import asyncio

    logger.info("Starting cb-memory MCP server...")
    logger.info(f"Embedding provider: {settings.embedding_provider}")
    logger.info(f"Couchbase: {settings.cb_connection_string}")

    # Ensure connection
    db.connect()

    # Auto-ingest cross-agent history on startup.
    claude_sync = auto_sync_claude(db=db, settings=settings)
    codex_sync = auto_sync_codex(db=db, settings=settings)
    logger.info(f"Startup sync (claude-code): {claude_sync}")
    logger.info(f"Startup sync (codex): {codex_sync}")

    # Run server
    asyncio.run(_run_stdio_server())


if __name__ == "__main__":
    main()
