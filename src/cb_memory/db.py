"""Couchbase client singleton — manages connection, bucket, scopes, and collections."""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from couchbase.auth import PasswordAuthenticator
from couchbase.cluster import Cluster
from couchbase.options import ClusterOptions

from cb_memory.config import Settings, get_settings

# Schema constants
SCOPES = {
    "conversations": ["sessions", "messages", "summaries"],
    "knowledge": ["decisions", "bugs", "thoughts", "patterns"],
    "metadata": ["sync_state"],
}


class CouchbaseClient:
    """Thin wrapper around the Couchbase SDK providing easy access to collections."""

    _instance: Optional["CouchbaseClient"] = None

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()
        self._cluster: Optional[Cluster] = None

    # -- connection management ------------------------------------------------

    def connect(self) -> None:
        """Establish a connection to the Couchbase cluster."""
        auth = PasswordAuthenticator(
            self._settings.cb_username,
            self._settings.cb_password,
        )
        opts = ClusterOptions(auth)
        self._cluster = Cluster(self._settings.cb_connection_string, opts)
        self._cluster.wait_until_ready(timedelta(seconds=15))

    @property
    def cluster(self) -> Cluster:
        if self._cluster is None:
            self.connect()
        return self._cluster  # type: ignore[return-value]

    @property
    def bucket(self):
        return self.cluster.bucket(self._settings.cb_bucket)

    # -- collection helpers ---------------------------------------------------

    def collection(self, scope_name: str, collection_name: str):
        """Return a Collection object for the given scope and collection."""
        return self.bucket.scope(scope_name).collection(collection_name)

    def scope(self, scope_name: str):
        return self.bucket.scope(scope_name)

    # -- convenience shortcuts ------------------------------------------------

    # Conversations
    @property
    def sessions(self):
        return self.collection("conversations", "sessions")

    @property
    def messages(self):
        return self.collection("conversations", "messages")

    @property
    def summaries(self):
        return self.collection("conversations", "summaries")

    # Knowledge
    @property
    def decisions(self):
        return self.collection("knowledge", "decisions")

    @property
    def bugs(self):
        return self.collection("knowledge", "bugs")

    @property
    def thoughts(self):
        return self.collection("knowledge", "thoughts")

    @property
    def patterns(self):
        return self.collection("knowledge", "patterns")

    # Metadata
    @property
    def sync_state(self):
        return self.collection("metadata", "sync_state")

    # -- singleton ------------------------------------------------------------

    @classmethod
    def get_instance(cls, settings: Optional[Settings] = None) -> "CouchbaseClient":
        if cls._instance is None:
            cls._instance = cls(settings)
        return cls._instance

    def close(self) -> None:
        if self._cluster is not None:
            self._cluster.close()
            self._cluster = None
            CouchbaseClient._instance = None
