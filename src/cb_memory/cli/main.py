"""CLI commands: setup, import, stats."""

from __future__ import annotations

import copy
import json
import logging
import time
from pathlib import Path

import click

from cb_memory.cli.installer import (
    SUPPORTED_IDES,
    build_server_env,
    install_ide_configs,
    parse_ide_selection,
    write_env_file,
)
from cb_memory.config import get_settings
from cb_memory.db import SCOPES, CouchbaseClient
from cb_memory.project import normalize_project_path

logger = logging.getLogger(__name__)


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def cli(verbose: bool) -> None:
    """cb-memory — Coding memory powered by Couchbase."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--bucket-ram", default=256, help="RAM quota for bucket in MB")
def setup(bucket_ram: int) -> None:
    """Provision Couchbase bucket, scopes, collections, and indexes."""
    settings = get_settings()
    _provision_schema(settings, bucket_ram)


def _provision_schema(settings, bucket_ram: int) -> None:
    """Provision Couchbase schema (bucket/scopes/indexes)."""
    click.echo(f"Connecting to {settings.cb_connection_string} ...")

    db = CouchbaseClient(settings)
    db.connect()
    bm = db.cluster.buckets()

    # 1. Create bucket if it doesn't exist
    bucket_name = settings.cb_bucket
    click.echo(f"Ensuring bucket '{bucket_name}' exists ...")
    _ensure_bucket(bm, bucket_name, bucket_ram)

    # Wait for bucket to be ready (SDK compatibility across versions)
    timeout = __import__("datetime").timedelta(seconds=15)
    bucket = db.cluster.bucket(bucket_name)
    if hasattr(bucket, "wait_until_ready"):
        bucket.wait_until_ready(timeout)
    else:
        db.cluster.wait_until_ready(timeout)
    cm = bucket.collections()

    # 2. Create scopes and collections
    for scope_name, collections in SCOPES.items():
        click.echo(f"  Scope: {scope_name}")
        _ensure_scope(cm, scope_name)
        for coll_name in collections:
            click.echo(f"    Collection: {coll_name}")
            _ensure_collection(cm, scope_name, coll_name)

    # Give Couchbase a moment to propagate
    click.echo("Waiting for schema to propagate ...")
    time.sleep(3)

    # 3. Create primary indexes
    click.echo("Creating primary indexes ...")
    for scope_name, collections in SCOPES.items():
        for coll_name in collections:
            _create_primary_index(db, bucket_name, scope_name, coll_name)

    # 4. Create FTS / vector search index
    click.echo("Creating search indexes ...")
    _create_search_index(db, settings)

    click.echo("Setup complete!")
    db.close()


@cli.command("init")
@click.option("--bucket-ram", default=256, show_default=True, help="Bucket RAM quota in MB")
@click.option("--wait-timeout", default=180, show_default=True, help="Seconds to wait for Couchbase REST API")
@click.option("--skip-claude", is_flag=True, help="Skip Claude chat import")
@click.option("--skip-codex", is_flag=True, help="Skip Codex chat import")
@click.option("--skip-opencode", is_flag=True, help="Skip OpenCode chat import")
@click.option("--backfill-embeddings", is_flag=True, help="Backfill embeddings after import")
@click.option("--project-id", default=None, help="Override project ID for imported data")
def init_cmd(
    bucket_ram: int,
    wait_timeout: int,
    skip_claude: bool,
    skip_codex: bool,
    skip_opencode: bool,
    backfill_embeddings: bool,
    project_id: str | None,
) -> None:
    """Bootstrap local/remote Couchbase + schema + chat sync without Docker."""
    _run_init(
        bucket_ram=bucket_ram,
        wait_timeout=wait_timeout,
        skip_claude=skip_claude,
        skip_codex=skip_codex,
        skip_opencode=skip_opencode,
        backfill_embeddings=backfill_embeddings,
        project_id=project_id,
    )


def _run_init(
    *,
    bucket_ram: int,
    wait_timeout: int,
    skip_claude: bool,
    skip_codex: bool,
    skip_opencode: bool,
    backfill_embeddings: bool,
    project_id: str | None,
) -> None:
    settings = get_settings()
    sync_project_id = project_id or settings.current_project_id or settings.default_project_id

    host = _extract_rest_host(settings.cb_connection_string)
    click.echo(f"Step 1/4: Checking Couchbase REST API at http://{host}:8091 ...")
    _wait_for_couchbase_rest(host=host, timeout_seconds=wait_timeout)
    click.echo("Step 2/4: Provisioning Couchbase schema ...")
    _provision_schema(settings, bucket_ram)

    click.echo("Step 3/4: Importing chats and tool history ...")
    db = CouchbaseClient(settings)
    db.connect()
    import_stats = {}
    try:
        if not skip_claude:
            from cb_memory.importers.claude_code import ClaudeCodeImporter

            claude_path = str(Path(settings.auto_import_claude_path).expanduser())
            import_stats["claude-code"] = ClaudeCodeImporter(db, settings, sync_project_id).run(path=claude_path)
        if not skip_codex:
            from cb_memory.importers.codex import CodexImporter

            import_stats["codex"] = CodexImporter(db, settings, sync_project_id).run(path=None)
        if not skip_opencode:
            from cb_memory.importers.opencode import OpenCodeImporter

            import_stats["opencode"] = OpenCodeImporter(db, settings, sync_project_id).run(path=None)

        if backfill_embeddings:
            click.echo("Step 3.5/4: Backfilling embeddings ...")
            _backfill_embeddings(db, settings)
    finally:
        db.close()

    click.echo("Step 4/4: Complete. Auto-sync remains enabled at server startup.")
    click.echo(
        json.dumps(
            {
                "cb_connection_string": settings.cb_connection_string,
                "project_id": sync_project_id,
                "imports": import_stats,
                "auto_import_claude_on_start": settings.auto_import_claude_on_start,
                "auto_import_claude_path": settings.auto_import_claude_path,
            },
            indent=2,
        )
    )


@cli.command("replicate")
@click.option("--container-name", default="couchbase-memory", show_default=True, help="Deprecated; ignored")
@click.option("--image", default="couchbase:latest", show_default=True, help="Deprecated; ignored")
@click.option("--bucket-ram", default=256, show_default=True, help="Bucket RAM quota in MB")
@click.option("--cluster-ram", default=1024, show_default=True, help="Deprecated; ignored")
@click.option("--index-ram", default=256, show_default=True, help="Deprecated; ignored")
@click.option("--fts-ram", default=256, show_default=True, help="Deprecated; ignored")
@click.option("--wait-timeout", default=180, show_default=True, help="Seconds to wait for Couchbase REST API")
@click.option("--skip-claude", is_flag=True, help="Skip Claude chat import")
@click.option("--skip-codex", is_flag=True, help="Skip Codex chat import")
@click.option("--skip-opencode", is_flag=True, help="Skip OpenCode chat import")
@click.option("--backfill-embeddings", is_flag=True, help="Backfill embeddings after import")
@click.option("--project-id", default=None, help="Override project ID for imported data")
def replicate_cmd(
    container_name: str,
    image: str,
    bucket_ram: int,
    cluster_ram: int,
    index_ram: int,
    fts_ram: int,
    wait_timeout: int,
    skip_claude: bool,
    skip_codex: bool,
    skip_opencode: bool,
    backfill_embeddings: bool,
    project_id: str | None,
) -> None:
    """Deprecated alias for `cb-memory init`."""
    click.echo("Warning: `cb-memory replicate` is deprecated and no longer uses Docker.")
    ignored = {
        "container_name": container_name,
        "image": image,
        "cluster_ram": cluster_ram,
        "index_ram": index_ram,
        "fts_ram": fts_ram,
    }
    click.echo(f"Ignoring deprecated options: {json.dumps(ignored)}")
    _run_init(
        bucket_ram=bucket_ram,
        wait_timeout=wait_timeout,
        skip_claude=skip_claude,
        skip_codex=skip_codex,
        skip_opencode=skip_opencode,
        backfill_embeddings=backfill_embeddings,
        project_id=project_id,
    )


@cli.command("install")
@click.option("--ide", "ide_values", multiple=True, type=click.Choice(list(SUPPORTED_IDES.keys())), help="IDE to configure")
@click.option("--non-interactive", is_flag=True, help="Disable prompts and require all needed flags")
@click.option("--cb-connection-string", default=None, help="Couchbase connection string")
@click.option("--cb-username", default=None, help="Couchbase username")
@click.option("--cb-password", default=None, help="Couchbase password")
@click.option("--cb-bucket", default=None, help="Couchbase bucket name")
@click.option("--openai-api-key", default=None, help="OpenAI API key (optional)")
@click.option("--ollama-host", default=None, help="Ollama host URL")
@click.option("--ollama-embedding-model", default=None, help="Ollama embedding model")
@click.option("--project-id", default=None, help="Project id / workspace path")
@click.option("--write-env/--no-write-env", default=True, show_default=True, help="Write collected settings to .env")
@click.option("--bootstrap/--no-bootstrap", default=True, show_default=True, help="Run bootstrap (schema + import)")
@click.option("--dry-run", is_flag=True, help="Show changes without writing files or running bootstrap")
@click.pass_context
def install_cmd(
    ctx: click.Context,
    ide_values: tuple[str, ...],
    non_interactive: bool,
    cb_connection_string: str | None,
    cb_username: str | None,
    cb_password: str | None,
    cb_bucket: str | None,
    openai_api_key: str | None,
    ollama_host: str | None,
    ollama_embedding_model: str | None,
    project_id: str | None,
    write_env: bool,
    bootstrap: bool,
    dry_run: bool,
) -> None:
    """Interactive installer for IDE MCP wiring + Couchbase credentials."""
    settings = get_settings()
    project_root = Path.cwd().resolve()

    selected_ides = list(ide_values)
    if not selected_ides and not non_interactive:
        click.echo("Select IDE(s) to configure:")
        for idx, (ide_id, label) in enumerate(SUPPORTED_IDES.items(), start=1):
            click.echo(f"  {idx}. {label} ({ide_id})")
        raw = click.prompt("Enter comma-separated ids or numbers", default="factory,copilot-vscode,claude-code,codex")
        selected_ides = parse_ide_selection(raw)

    if not selected_ides:
        raise click.ClickException("No IDE selected. Use --ide or interactive selection.")

    connection = cb_connection_string or settings.cb_connection_string
    username = cb_username or settings.cb_username
    password = cb_password or settings.cb_password
    bucket = cb_bucket or settings.cb_bucket
    workspace = project_id or settings.current_project_id or str(project_root)
    ollama_host_value = ollama_host or settings.ollama_host
    ollama_model_value = ollama_embedding_model or settings.ollama_embedding_model
    openai_key_value = openai_api_key if openai_api_key is not None else settings.openai_api_key

    if not non_interactive:
        connection = click.prompt("Couchbase connection string", default=connection)
        username = click.prompt("Couchbase username", default=username)
        password = click.prompt("Couchbase password", default=password, hide_input=True)
        bucket = click.prompt("Couchbase bucket", default=bucket)
        workspace = click.prompt("Project id / workspace path", default=workspace)
        current_openai = openai_key_value or ""
        openai_key_value = (
            click.prompt(
                "OpenAI API key (optional, leave blank to use Ollama)",
                default=current_openai,
                show_default=False,
            ).strip()
            or None
        )
        if not openai_key_value:
            ollama_host_value = click.prompt("Ollama host", default=ollama_host_value)
            ollama_model_value = click.prompt("Ollama embedding model", default=ollama_model_value)

    server_env = build_server_env(
        cb_connection_string=connection,
        cb_username=username,
        cb_password=password,
        cb_bucket=bucket,
        project_id=workspace,
        openai_api_key=openai_key_value,
        ollama_host=ollama_host_value,
        ollama_embedding_model=ollama_model_value,
    )

    if write_env:
        env_changed = write_env_file(
            env_path=project_root / ".env",
            values=server_env,
            dry_run=dry_run,
        )
        suffix = "(dry-run)" if dry_run else ""
        click.echo(f".env {'would be updated' if env_changed else 'already up to date'} {suffix}".strip())

    if bootstrap:
        click.echo("Running bootstrap flow (init command) ...")
        if dry_run:
            click.echo("Dry run: skipped bootstrap execution.")
        else:
            ctx.invoke(
                init_cmd,
                bucket_ram=256,
                wait_timeout=180,
                skip_claude=False,
                skip_codex=False,
                skip_opencode=False,
                backfill_embeddings=False,
                project_id=workspace,
            )

    results = install_ide_configs(
        ide_ids=selected_ides,
        project_root=project_root,
        env=server_env,
        dry_run=dry_run,
    )

    click.echo("IDE configuration summary:")
    for res in results:
        label = SUPPORTED_IDES.get(res.ide, res.ide)
        status = "updated" if res.changed else "already up to date"
        if dry_run and res.changed:
            status = "would be updated"
        click.echo(f"  - {label}: {status} ({res.path})")

    click.echo("Done. Restart the selected IDE(s) so MCP tools are loaded.")


def _ensure_bucket(bm, name: str, ram_mb: int) -> None:
    from couchbase.management.buckets import CreateBucketSettings, BucketType

    try:
        bm.get_bucket(name)
        click.echo(f"  Bucket '{name}' already exists.")
    except Exception:
        bm.create_bucket(
            CreateBucketSettings(
                name=name,
                bucket_type=BucketType.COUCHBASE,
                ram_quota_mb=ram_mb,
                flush_enabled=False,
                num_replicas=0,
            )
        )
        click.echo(f"  Bucket '{name}' created.")
        time.sleep(2)


def _ensure_scope(cm, scope_name: str) -> None:
    if scope_name == "_default":
        return
    try:
        existing = [s.name for s in cm.get_all_scopes()]
        if scope_name not in existing:
            cm.create_scope(scope_name)
            time.sleep(1)
    except Exception as e:
        logger.debug(f"Scope create note: {e}")


def _ensure_collection(cm, scope_name: str, coll_name: str) -> None:
    from couchbase.management.collections import CollectionSpec

    try:
        existing_scopes = cm.get_all_scopes()
        for s in existing_scopes:
            if s.name == scope_name:
                if any(c.name == coll_name for c in s.collections):
                    return
        cm.create_collection(CollectionSpec(coll_name, scope_name=scope_name))
        time.sleep(0.5)
    except Exception as e:
        logger.debug(f"Collection create note: {e}")


def _create_primary_index(db: CouchbaseClient, bucket: str, scope: str, coll: str) -> None:
    query = (
        f"CREATE PRIMARY INDEX IF NOT EXISTS "
        f"ON `{bucket}`.`{scope}`.`{coll}`"
    )
    try:
        db.cluster.query(query).execute()
    except Exception as e:
        logger.debug(f"Primary index note: {e}")


def _create_search_index(db: CouchbaseClient, settings) -> None:
    """Create FTS indexes (one per scope) for Couchbase 8 compatibility."""
    dims = settings.embedding_dims
    bucket_name = settings.cb_bucket
    def _vector_type_mapping(scope_name: str, coll_name: str) -> dict:
        return {
            f"{scope_name}.{coll_name}": {
                "enabled": True,
                "dynamic": True,
                "properties": {
                    "embedding": {
                        "enabled": True,
                        "dynamic": False,
                        "fields": [
                            {
                                "name": "embedding",
                                "type": "vector",
                                "dims": dims,
                                "similarity": "dot_product",
                                "vector_index_optimized_for": "recall",
                            }
                        ],
                    }
                },
            }
        }

    conversations_types = {}
    for coll_name in ["summaries"]:
        conversations_types.update(_vector_type_mapping("conversations", coll_name))

    conversations_types["conversations.messages"] = {
        "enabled": True,
        "dynamic": True,
        "properties": {
            "text_content": {
                "enabled": True,
                "fields": [{"name": "text_content", "type": "text", "analyzer": "standard", "index": True, "store": True}],
            }
        },
    }
    conversations_types["conversations.sessions"] = {
        "enabled": True,
        "dynamic": True,
        "properties": {
            "title": {"enabled": True, "fields": [{"name": "title", "type": "text", "analyzer": "standard", "index": True}]},
            "summary": {"enabled": True, "fields": [{"name": "summary", "type": "text", "analyzer": "standard", "index": True}]},
        },
    }

    knowledge_types = {}
    for coll_name in ["decisions", "bugs", "thoughts", "patterns"]:
        knowledge_types.update(_vector_type_mapping("knowledge", coll_name))

    for coll_name, text_field in [
        ("decisions", "description"),
        ("bugs", "description"),
        ("thoughts", "content"),
        ("patterns", "description"),
    ]:
        key = f"knowledge.{coll_name}"
        knowledge_types[key].setdefault("properties", {})
        knowledge_types[key]["properties"][text_field] = {
            "enabled": True,
            "fields": [{"name": text_field, "type": "text", "analyzer": "standard", "index": True, "store": True}],
        }

    def _index_def(index_name: str, type_mappings: dict) -> dict:
        return {
            "type": "fulltext-index",
            "name": index_name,
            "sourceType": "gocbcore",
            "sourceName": bucket_name,
            "planParams": {"maxPartitionsPerPIndex": 1024, "indexPartitions": 1},
            "params": {
                "doc_config": {
                    "docid_prefix_delim": "",
                    "docid_regexp": "",
                    "mode": "scope.collection.type_field",
                    "type_field": "type",
                },
                "mapping": {
                    "analysis": {},
                    "default_analyzer": "standard",
                    "default_datetime_parser": "dateTimeOptional",
                    "default_field": "_all",
                    "default_mapping": {"dynamic": False, "enabled": False},
                    "default_type": "_default",
                    "docvalues_dynamic": False,
                    "index_dynamic": True,
                    "store_dynamic": False,
                    "type_field": "_type",
                    "types": type_mappings,
                },
                "store": {"indexType": "scorch"},
            },
        }

    index_defs = [
        _index_def("coding-memory-conversations-index", conversations_types),
        _index_def("coding-memory-knowledge-index", knowledge_types),
    ]

    import requests

    host = settings.cb_connection_string.replace("couchbase://", "").replace("couchbases://", "")

    for index_def in index_defs:
        index_name = index_def["name"]
        url = f"http://{host}:8094/api/index/{index_name}"
        try:
            resp = requests.put(
                url,
                json=index_def,
                auth=(settings.cb_username, settings.cb_password),
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code in (200, 201):
                click.echo(f"  Search index '{index_name}' created/updated.")
            elif resp.status_code == 400 and "same name" in resp.text.lower():
                click.echo(f"  Search index '{index_name}' already exists.")
            elif resp.status_code == 400 and "vector typed fields not supported" in resp.text.lower():
                click.echo(
                    f"  Search index '{index_name}' vector fields unsupported; "
                    "retrying with text-only mapping."
                )
                text_only = _strip_vector_fields(index_def)
                resp2 = requests.put(
                    url,
                    json=text_only,
                    auth=(settings.cb_username, settings.cb_password),
                    headers={"Content-Type": "application/json"},
                )
                if resp2.status_code in (200, 201):
                    click.echo(f"  Search index '{index_name}' created/updated (text-only).")
                elif resp2.status_code == 400 and "same name" in resp2.text.lower():
                    click.echo(f"  Search index '{index_name}' already exists.")
                else:
                    click.echo(
                        f"  Search index '{index_name}' fallback response "
                        f"({resp2.status_code}): {resp2.text[:200]}"
                    )
            else:
                click.echo(f"  Search index '{index_name}' response ({resp.status_code}): {resp.text[:200]}")
        except Exception as e:
            click.echo(f"  Could not create search index '{index_name}' via REST: {e}")


def _strip_vector_fields(index_def: dict) -> dict:
    """Return a copy of an index definition without vector fields.

    Couchbase Community Edition deployments may reject vector typed mappings.
    """
    result = copy.deepcopy(index_def)
    types = (
        result
        .get("params", {})
        .get("mapping", {})
        .get("types", {})
    )
    for type_mapping in types.values():
        props = type_mapping.get("properties")
        if not isinstance(props, dict):
            continue
        props.pop("embedding", None)
    return result


def _extract_rest_host(connection_string: str) -> str:
    host = connection_string.replace("couchbase://", "").replace("couchbases://", "")
    host = host.split(",")[0].strip()
    if not host:
        return "127.0.0.1"
    if ":" in host:
        return host.split(":")[0]
    return host


def _wait_for_couchbase_rest(host: str, timeout_seconds: int = 180) -> None:
    import requests

    url = f"http://{host}:8091/pools"
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            resp = requests.get(url, timeout=2)
            if resp.status_code in (200, 401):
                return
        except Exception:
            pass
        time.sleep(2)
    raise click.ClickException(f"Timed out waiting for Couchbase REST API on {url}")


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------

@cli.command("import")
@click.option(
    "--source",
    type=click.Choice(["opencode", "claude-code", "codex", "json", "markdown"]),
    required=True,
    help="Source to import from",
)
@click.option("--path", type=click.Path(exists=True), default=None, help="Path for json/markdown import")
@click.option("--backfill-embeddings", is_flag=True, help="Generate embeddings for docs missing them")
@click.option("--project-id", default=None, help="Override project ID for imported data")
def import_cmd(source: str, path: str | None, backfill_embeddings: bool, project_id: str | None) -> None:
    """Import conversation history from various sources."""
    settings = get_settings()
    db = CouchbaseClient(settings)
    db.connect()

    if project_id is None:
        project_id = settings.default_project_id

    if source == "opencode":
        from cb_memory.importers.opencode import OpenCodeImporter
        importer = OpenCodeImporter(db, settings, project_id)
    elif source == "claude-code":
        from cb_memory.importers.claude_code import ClaudeCodeImporter
        importer = ClaudeCodeImporter(db, settings, project_id)
    elif source == "codex":
        from cb_memory.importers.codex import CodexImporter
        importer = CodexImporter(db, settings, project_id)
    elif source in ("json", "markdown"):
        if path is None:
            click.echo("Error: --path is required for json/markdown import")
            raise SystemExit(1)
        from cb_memory.importers.generic import GenericImporter
        importer = GenericImporter(db, settings, project_id, fmt=source)
    else:
        click.echo(f"Unknown source: {source}")
        raise SystemExit(1)

    click.echo(f"Importing from {source} ...")
    stats = importer.run(path=path)
    click.echo(f"Import complete: {stats}")

    if backfill_embeddings:
        click.echo("Backfilling embeddings ...")
        _backfill_embeddings(db, settings)
        click.echo("Backfill complete.")

    db.close()


def _backfill_embeddings(db: CouchbaseClient, settings) -> None:
    """Generate embeddings for documents that don't have them."""
    from cb_memory.embeddings import get_embedding_provider

    provider = get_embedding_provider(settings)
    bucket_name = settings.cb_bucket

    collections_to_backfill = [
        ("conversations", "summaries", "summary"),
        ("knowledge", "decisions", "description"),
        ("knowledge", "bugs", "description"),
        ("knowledge", "thoughts", "content"),
        ("knowledge", "patterns", "description"),
    ]

    for scope_name, coll_name, text_field in collections_to_backfill:
        query = (
            f"SELECT META().id, `{text_field}` "
            f"FROM `{bucket_name}`.`{scope_name}`.`{coll_name}` "
            f"WHERE embedding IS NULL OR embedding IS MISSING"
        )
        try:
            rows = list(db.cluster.query(query))
        except Exception:
            continue

        if not rows:
            continue

        click.echo(f"  Backfilling {len(rows)} docs in {scope_name}.{coll_name} ...")
        texts = [r.get(text_field, "") or "" for r in rows]
        embeddings = provider.embed(texts)
        coll = db.collection(scope_name, coll_name)

        for row, emb in zip(rows, embeddings):
            doc_id = row["id"]
            coll.mutate_in(doc_id, [
                __import__("couchbase").subdocument.upsert("embedding", emb)
            ])


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

@cli.command()
def stats() -> None:
    """Show memory statistics."""
    settings = get_settings()
    db = CouchbaseClient(settings)
    db.connect()
    bucket_name = settings.cb_bucket

    click.echo("Memory Statistics")
    click.echo("=" * 40)

    for scope_name, collections in SCOPES.items():
        for coll_name in collections:
            query = f"SELECT COUNT(*) as cnt FROM `{bucket_name}`.`{scope_name}`.`{coll_name}`"
            try:
                rows = list(db.cluster.query(query))
                count = rows[0]["cnt"] if rows else 0
            except Exception:
                count = "?"
            click.echo(f"  {scope_name}.{coll_name}: {count}")

    db.close()


@cli.command("migrate-project-ids")
@click.option("--from-project", default="default", help="Project ID to migrate from")
@click.option("--dry-run", is_flag=True, help="Show what would change without writing")
def migrate_project_ids(from_project: str, dry_run: bool) -> None:
    """Migrate legacy session/message docs to directory-derived project IDs."""
    settings = get_settings()
    db = CouchbaseClient(settings)
    db.connect()
    bucket_name = settings.cb_bucket

    q = (
        f"SELECT META(s).id AS id, s.directory "
        f"FROM `{bucket_name}`.conversations.sessions s "
        f"WHERE s.project_id = $from_project "
        f"AND s.directory IS NOT MISSING AND s.directory != ''"
    )
    rows = list(db.cluster.query(q, from_project=from_project))

    migrations: list[tuple[str, str]] = []
    for row in rows:
        session_id = row.get("id")
        directory = row.get("directory", "")
        normalized = normalize_project_path(directory)
        if not session_id or not normalized or normalized in {"/", ".", from_project}:
            continue
        migrations.append((session_id, normalized))

    if not migrations:
        click.echo("No legacy sessions found to migrate.")
        db.close()
        return

    per_project: dict[str, int] = {}
    for _, project in migrations:
        per_project[project] = per_project.get(project, 0) + 1

    click.echo(f"Sessions to migrate: {len(migrations)}")
    for project, count in sorted(per_project.items(), key=lambda item: item[1], reverse=True):
        click.echo(f"  {project}: {count}")

    if dry_run:
        click.echo("Dry run complete. No changes written.")
        db.close()
        return

    migrated_messages = 0
    migrated_summaries = 0

    for session_id, new_project_id in migrations:
        list(
            db.cluster.query(
                f"UPDATE `{bucket_name}`.conversations.sessions s "
                f"SET s.project_id = $new_project_id "
                f"WHERE META(s).id = $session_id AND s.project_id = $from_project "
                f"RETURNING RAW META(s).id",
                session_id=session_id,
                new_project_id=new_project_id,
                from_project=from_project,
            )
        )

        msg_res = list(
            db.cluster.query(
                f"UPDATE `{bucket_name}`.conversations.messages m "
                f"SET m.project_id = $new_project_id "
                f"WHERE m.session_id = $session_id "
                f"AND (m.project_id IS MISSING OR m.project_id = $from_project) "
                f"RETURNING RAW META(m).id",
                session_id=session_id,
                new_project_id=new_project_id,
                from_project=from_project,
            )
        )
        migrated_messages += len(msg_res)

        sum_res = list(
            db.cluster.query(
                f"UPDATE `{bucket_name}`.conversations.summaries su "
                f"SET su.project_id = $new_project_id "
                f"WHERE su.session_id = $session_id "
                f"AND (su.project_id IS MISSING OR su.project_id = $from_project) "
                f"RETURNING RAW META(su).id",
                session_id=session_id,
                new_project_id=new_project_id,
                from_project=from_project,
            )
        )
        migrated_summaries += len(sum_res)

    click.echo(
        f"Migrated {len(migrations)} sessions, "
        f"{migrated_messages} messages, "
        f"{migrated_summaries} summaries."
    )
    db.close()


if __name__ == "__main__":
    cli()
