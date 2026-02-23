"""Interactive installer helpers for IDE MCP configuration."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SERVER_NAME = "coding-memory"

SUPPORTED_IDES: dict[str, str] = {
    "factory": "Factory",
    "copilot-vscode": "GitHub Copilot (VS Code)",
    "copilot-jetbrains": "GitHub Copilot (JetBrains)",
    "claude-code": "Claude Code",
    "codex": "Codex",
}


@dataclass
class InstallWriteResult:
    ide: str
    path: Path
    changed: bool


def parse_ide_selection(raw: str) -> list[str]:
    """Parse comma-separated list of ide ids or numeric indexes."""
    entries = [part.strip().lower() for part in raw.split(",") if part.strip()]
    if not entries:
        return []

    ordered = list(SUPPORTED_IDES.keys())
    seen: set[str] = set()
    selected: list[str] = []

    for entry in entries:
        resolved = None
        if entry.isdigit():
            idx = int(entry)
            if 1 <= idx <= len(ordered):
                resolved = ordered[idx - 1]
        elif entry in SUPPORTED_IDES:
            resolved = entry
        else:
            # tolerate friendly labels
            for ide_id, label in SUPPORTED_IDES.items():
                normalized = label.lower().replace(" ", "-").replace("(", "").replace(")", "")
                if entry in {label.lower(), normalized}:
                    resolved = ide_id
                    break

        if resolved and resolved not in seen:
            seen.add(resolved)
            selected.append(resolved)

    return selected


def build_server_env(
    *,
    cb_connection_string: str,
    cb_username: str,
    cb_password: str,
    cb_bucket: str,
    project_id: str,
    openai_api_key: str | None,
    ollama_host: str,
    ollama_embedding_model: str,
) -> dict[str, str]:
    env = {
        "CB_CONNECTION_STRING": cb_connection_string,
        "CB_USERNAME": cb_username,
        "CB_PASSWORD": cb_password,
        "CB_BUCKET": cb_bucket,
        "CURRENT_PROJECT_ID": project_id,
        "DEFAULT_PROJECT_ID": "default",
        "INCLUDE_ALL_PROJECTS_BY_DEFAULT": "true",
        "AUTO_IMPORT_CLAUDE_ON_START": "true",
        "AUTO_IMPORT_CLAUDE_PATH": str(Path.home() / ".claude/projects"),
        "AUTO_IMPORT_CODEX_ON_START": "true",
        "AUTO_IMPORT_CODEX_PATH": str(Path.home() / ".codex"),
        "OLLAMA_HOST": ollama_host,
        "OLLAMA_EMBEDDING_MODEL": ollama_embedding_model,
    }
    if openai_api_key:
        env["OPENAI_API_KEY"] = openai_api_key
    return env


def write_env_file(env_path: Path, values: dict[str, str], *, dry_run: bool = False) -> bool:
    """Upsert key=value entries into an env file, preserving unknown keys."""
    existing: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            existing[key.strip()] = value.strip()

    merged = dict(existing)
    merged.update(values)

    if dry_run:
        return merged != existing

    lines = [f"{k}={v}" for k, v in sorted(merged.items())]
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return merged != existing


def install_ide_configs(
    *,
    ide_ids: Iterable[str],
    project_root: Path,
    env: dict[str, str],
    dry_run: bool = False,
) -> list[InstallWriteResult]:
    results: list[InstallWriteResult] = []
    for ide_id in ide_ids:
        path, payload = _config_payload_for_ide(ide_id=ide_id, project_root=project_root, env=env)
        changed = _write_json_with_server(path=path, payload=payload, dry_run=dry_run)
        results.append(InstallWriteResult(ide=ide_id, path=path, changed=changed))
    return results


def _config_payload_for_ide(ide_id: str, project_root: Path, env: dict[str, str]) -> tuple[Path, dict]:
    if ide_id == "factory":
        path = Path.home() / ".factory" / "settings.json"
        return path, {
            "container_key": "mcpServers",
            "server": {
                "command": "python",
                "args": ["-m", "cb_memory.server"],
                "env": env,
            },
        }

    if ide_id == "copilot-vscode":
        path = project_root / ".vscode" / "mcp.json"
        return path, {
            "container_key": "servers",
            "server": {
                "type": "stdio",
                "command": "python",
                "args": ["-m", "cb_memory.server"],
                "env": env,
            },
        }

    if ide_id == "copilot-jetbrains":
        path = project_root / ".idea" / "mcp.json"
        return path, {
            "container_key": "servers",
            "server": {
                "type": "stdio",
                "command": "python",
                "args": ["-m", "cb_memory.server"],
                "env": env,
            },
        }

    if ide_id == "claude-code":
        path = Path.home() / ".claude" / "settings.json"
        return path, {
            "container_key": "mcpServers",
            "server": {
                "command": "python",
                "args": ["-m", "cb_memory.server"],
                "env": env,
            },
        }

    if ide_id == "codex":
        path = Path.home() / ".codex" / "config.toml"
        return path, {
            "format": "toml",
            "server": {
                "command": "python",
                "args": ["-m", "cb_memory.server"],
                "env": env,
            },
        }

    raise ValueError(f"Unsupported IDE id: {ide_id}")


def _write_json_with_server(path: Path, payload: dict, *, dry_run: bool = False) -> bool:
    if payload.get("format") == "toml":
        return _write_toml_with_server(path=path, payload=payload, dry_run=dry_run)

    current = {}
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))

    container_key = payload["container_key"]
    server = payload["server"]

    updated = dict(current)
    container = dict(updated.get(container_key, {}))
    before = container.get(SERVER_NAME)
    container[SERVER_NAME] = server
    updated[container_key] = container

    changed = before != server or current.get(container_key) != updated.get(container_key)

    if dry_run:
        return changed

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
    return changed


def _write_toml_with_server(path: Path, payload: dict, *, dry_run: bool = False) -> bool:
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    updated = _upsert_codex_server_toml(current, payload["server"])
    changed = updated != current

    if dry_run:
        return changed

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated, encoding="utf-8")
    return changed


def _upsert_codex_server_toml(content: str, server: dict) -> str:
    cleaned = _drop_toml_section(content, "mcp_servers.coding-memory.env")
    cleaned = _drop_toml_section(cleaned, "mcp_servers.coding-memory")
    cleaned = cleaned.rstrip()

    args = ", ".join(_toml_quote(arg) for arg in server.get("args", []))
    lines = [
        "[mcp_servers.coding-memory]",
        f'command = {_toml_quote(server.get("command", "python"))}',
        f"args = [{args}]",
        "",
        "[mcp_servers.coding-memory.env]",
    ]
    for key, value in sorted(server.get("env", {}).items()):
        lines.append(f"{key} = {_toml_quote(value)}")
    block = "\n".join(lines) + "\n"

    if cleaned:
        return f"{cleaned}\n\n{block}"
    return block


def _drop_toml_section(content: str, section_name: str) -> str:
    pattern = rf"(?ms)^\[{re.escape(section_name)}\]\n.*?(?=^\[|\Z)"
    return re.sub(pattern, "", content)


def _toml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
