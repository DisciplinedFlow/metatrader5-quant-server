"""
Singleton connection manager for the Neo4j trading knowledge graph.

Returns None if Neo4j is unavailable — callers must handle gracefully.
"""

import threading
import logging
from typing import Optional

logger = logging.getLogger('app.quant.knowledge')

_graph = None
_lock = threading.Lock()
_connect_attempted = False


def get_graph() -> Optional['ForexKnowledgeGraph']:
    """
    Get the singleton ForexKnowledgeGraph instance.

    Returns None if Neo4j is unavailable or not configured.
    Thread-safe with lazy initialization.
    """
    global _graph, _connect_attempted

    if _graph is not None and _graph.connected:
        return _graph

    with _lock:
        # Double-check after acquiring lock
        if _graph is not None and _graph.connected:
            return _graph

        # Don't retry on every call — only reconnect on worker restart
        if _connect_attempted:
            return None

        _connect_attempted = True

        try:
            from django.conf import settings
            from .graph import ForexKnowledgeGraph

            uri = getattr(settings, 'NEO4J_URI', 'bolt://neo4j:7687')
            user = getattr(settings, 'NEO4J_USER', 'neo4j')
            password = getattr(settings, 'NEO4J_PASSWORD', '')

            if not password:
                logger.info("NEO4J_PASSWORD not set — graph disabled")
                return None

            g = ForexKnowledgeGraph(uri=uri, user=user, password=password)
            if g.connect():
                _graph = g
                logger.info("Knowledge graph connected at %s", uri)
                return _graph
            else:
                logger.warning("Knowledge graph connection failed at %s", uri)
        except Exception as e:
            logger.debug("Graph connection error: %s", e)

    return None


def reset_connection():
    """Force reconnection on next get_graph() call. Used after container restart."""
    global _graph, _connect_attempted
    with _lock:
        if _graph is not None:
            try:
                _graph.disconnect()
            except Exception:
                pass
        _graph = None
        _connect_attempted = False
