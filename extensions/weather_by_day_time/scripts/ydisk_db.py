"""Shared SQLite storage for the Yandex Disk catalog (items + scan metadata)."""
import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    path       TEXT PRIMARY KEY,
    parent     TEXT NOT NULL,
    name       TEXT NOT NULL,
    name_lower TEXT NOT NULL,
    type       TEXT NOT NULL CHECK (type IN ('dir', 'file')),
    listed     INTEGER NOT NULL DEFAULT 0,
    modified   TEXT,
    size       INTEGER,
    mime_type  TEXT,
    media_type TEXT,
    file       TEXT,
    md5        TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_parent ON items(parent);
CREATE INDEX IF NOT EXISTS idx_items_name_lower ON items(name_lower);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

UPSERT_ITEM = """
INSERT INTO items (path, parent, name, name_lower, type, listed, modified, size, mime_type, media_type, file, md5)
VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)
ON CONFLICT(path) DO UPDATE SET
    parent = excluded.parent,
    name = excluded.name,
    name_lower = excluded.name_lower,
    type = excluded.type,
    modified = excluded.modified,
    size = excluded.size,
    mime_type = excluded.mime_type,
    media_type = excluded.media_type,
    file = excluded.file,
    md5 = excluded.md5
"""

DELETE_SUBTREE = """
WITH RECURSIVE sub(path) AS (
    SELECT ?1
    UNION ALL
    SELECT i.path FROM items i JOIN sub ON i.parent = sub.path
)
DELETE FROM items WHERE path IN (SELECT path FROM sub)
"""


def connect(db_path):
    conn = sqlite3.connect(db_path, timeout=15, check_same_thread=False)
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.executescript(SCHEMA)
    conn.row_factory = sqlite3.Row
    return conn


def parent_of(path):
    if path == "/":
        return ""
    head = path.rsplit("/", 1)[0]
    return head if head else "/"


def row_values(item):
    path = item.get("path", "")
    return (
        path,
        parent_of(path),
        item.get("name", ""),
        item.get("name", "").lower(),
        item.get("type", "file"),
        item.get("modified"),
        item.get("size"),
        item.get("mime_type"),
        item.get("media_type"),
        item.get("file"),
        item.get("md5"),
    )


def upsert_listing(conn, dir_path, dir_modified, items):
    """Replace children of dir_path with items. Returns number of removed subtrees."""
    old = {r["path"]: r["type"] for r in conn.execute(
        "SELECT path, type FROM items WHERE parent = ?", (dir_path,))}
    new = {it.get("path") for it in items}
    removed = [p for p in old if p not in new]
    for p in removed:
        if old[p] == "dir":
            conn.execute(DELETE_SUBTREE, (p,))
        else:
            conn.execute("DELETE FROM items WHERE path = ?", (p,))
    for it in items:
        conn.execute(UPSERT_ITEM, row_values(it))
    conn.execute(
        "INSERT INTO items (path, parent, name, name_lower, type, listed, modified) "
        "VALUES (?, '', ?, ?, 'dir', 1, ?) "
        "ON CONFLICT(path) DO UPDATE SET listed = 1, modified = excluded.modified, "
        "name = excluded.name, name_lower = excluded.name_lower, type = 'dir'",
        (dir_path, dir_path.rsplit("/", 1)[-1] or "/", dir_path.lower(), dir_modified),
    )
    return len(removed)


def get_row(conn, path):
    return conn.execute(
        "SELECT path, listed, modified FROM items WHERE path = ?", (path,)).fetchone()


def counts(conn):
    dirs = conn.execute("SELECT COUNT(*) FROM items WHERE type = 'dir'").fetchone()[0]
    files = conn.execute("SELECT COUNT(*) FROM items WHERE type = 'file'").fetchone()[0]
    return dirs, files


def set_meta(conn, key, value):
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default
