"""Playground subsystem — the real simulator: SQLite-backed event log,
atom-level data, live WebSocket protocol, chemistry rules engine.

Per docs/PLAYGROUND_SYSTEM.md.

Public surface:
    PlaygroundStore   — SQLite schema + CRUD
    EventBus          — per-session pub/sub + persistence
    RulesEngine       — RDKit + JSON rule wrapper
    get_store()       — singleton
    get_bus()         — singleton
    get_rules()       — singleton
"""
from .store import PlaygroundStore, get_store
from .bus import EventBus, get_bus
from .rules import RulesEngine, get_rules

__all__ = [
    "PlaygroundStore", "get_store",
    "EventBus", "get_bus",
    "RulesEngine", "get_rules",
]
