"""Project ID helpers for per-project storage and retrieval."""

from __future__ import annotations

from pathlib import Path


def normalize_project_path(directory: str) -> str:
    """Normalize a project path into a stable absolute string."""
    if not directory:
        return ""
    try:
        return str(Path(directory).expanduser().resolve())
    except Exception:
        return str(Path(directory).expanduser().absolute())


def derive_project_id(
    configured_project_id: str,
    directory: str | None,
    default_project_id: str = "default",
) -> str:
    """Derive project_id from directory unless an explicit override is set."""
    if configured_project_id and configured_project_id != default_project_id:
        return configured_project_id

    normalized = normalize_project_path(directory or "")
    if normalized and normalized not in {"/", "."}:
        return normalized

    return default_project_id


def resolve_runtime_project_id(
    requested_project_id: str | None,
    current_project_id: str | None,
    default_project_id: str = "default",
    allow_unset: bool = False,
) -> str | None:
    """Resolve a runtime project selector against current workspace context.

    Rules:
    - Explicit non-default project IDs are preserved.
    - "default" resolves to current workspace path when available.
    - When allow_unset=True and no project is requested, return None.
    """
    if requested_project_id is None and allow_unset:
        return None

    requested = requested_project_id or default_project_id
    if requested and requested != default_project_id:
        return requested

    normalized_current = normalize_project_path(current_project_id or "")
    if normalized_current and normalized_current not in {"/", "."}:
        return normalized_current

    return requested


def normalize_project_ids(project_ids: list[str] | None) -> list[str]:
    """Normalize and deduplicate project IDs, preserving input order."""
    if not project_ids:
        return []
    out: list[str] = []
    seen = set()
    for pid in project_ids:
        normalized = normalize_project_path(pid or "")
        if not normalized or normalized in {"/", "."}:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def resolve_scope_overrides(
    requested_related_project_ids: list[str] | None,
    requested_include_all_projects: bool | None,
    default_related_project_ids: list[str] | None = None,
    include_all_projects_by_default: bool = False,
) -> tuple[list[str] | None, bool]:
    """Resolve effective scope flags with optional server-side defaults.

    Behavior:
    - Explicit request values always win.
    - If related project IDs are omitted, fall back to configured defaults.
    - If include_all_projects is omitted, fall back to configured default.
    """
    related = requested_related_project_ids
    if related is None:
        related = list(default_related_project_ids or [])
    related = normalize_project_ids(related)

    include_all = requested_include_all_projects
    if include_all is None:
        include_all = bool(include_all_projects_by_default)

    return related, bool(include_all)


def resolve_project_scope(
    requested_project_id: str | None,
    current_project_id: str | None,
    related_project_ids: list[str] | None = None,
    include_all_projects: bool = False,
    default_project_id: str = "default",
) -> tuple[str, list[str] | None]:
    """Resolve effective project and scope list for project-aware retrieval.

    Returns:
        (effective_project_id, scope_project_ids)
        - scope_project_ids=None means global scope (all projects).
    """
    effective = resolve_runtime_project_id(
        requested_project_id=requested_project_id,
        current_project_id=current_project_id,
        default_project_id=default_project_id,
    ) or default_project_id

    if include_all_projects:
        return effective, None

    scope = [effective]
    for pid in normalize_project_ids(related_project_ids):
        if pid != effective:
            scope.append(pid)
    return effective, scope
