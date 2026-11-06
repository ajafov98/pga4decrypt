"""Discovery of pgAdmin configuration databases and their encryption keys."""

import os
import sqlite3
import sys
import threading
from pathlib import Path

try:
    import keyring
except ImportError:  # keyring is optional
    keyring = None

KEYRING_SERVICE_NAME = 'pgAdmin4'
KEYRING_MASTER_USERNAME = 'pgadmin4-master-password'
KEYRING_SERVER_FORMAT = 'pgAdmin4-{0}-{1}'


def candidate_databases():
    """Return existing pgAdmin4.db paths in the order we should prefer."""
    candidates = []

    for env_name in ('SQLITE_PATH', 'PGADMIN_SQLITE_PATH'):
        value = os.environ.get(env_name)
        if value:
            candidates.append(Path(value))

    home = Path.home()
    candidates.extend([
        Path.cwd() / 'pgadmin4.db',
        home / '.pgadmin' / 'pgadmin4.db',
        home / '.pgadmin4' / 'pgadmin4.db',
        Path('/var/lib/pgadmin/pgadmin4.db'),
    ])

    if sys.platform == 'win32':
        appdata = os.environ.get('APPDATA')
        if appdata:
            candidates.append(Path(appdata) / 'pgAdmin' / 'pgadmin4.db')
    elif sys.platform == 'darwin':
        candidates.append(home / 'Library' / 'Application Support' /
                          'pgAdmin' / 'pgadmin4.db')

    result = []
    seen = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_file():
            result.append(resolved)
    return result


def user_columns(db):
    try:
        return [row[1] for row in db.execute('PRAGMA table_info(user)')]
    except sqlite3.DatabaseError:
        return []


def has_table(db, name):
    row = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,)).fetchone()
    return row is not None


def masterpass_checks(db):
    """Return {user_id: masterpass_check} (may be empty on legacy DBs)."""
    if 'masterpass_check' not in user_columns(db):
        return {}
    checks = {}
    for user_id, value in db.execute(
            'SELECT id, masterpass_check FROM user'):
        if value:
            checks[user_id] = value
    return checks


def get_keyring_password(username, service=KEYRING_SERVICE_NAME, timeout=3):
    """Read a value from the OS keyring, or return None if unavailable.

    Keyring backends can block indefinitely on a headless/D-Bus-less session,
    so the lookup runs in a daemon thread with a timeout.
    """
    if keyring is None:
        return None

    result = []

    def worker():
        try:
            result.append(keyring.get_password(service, username))
        except Exception:
            result.append(None)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout)
    return result[0] if result else None


def get_master_key():
    """Return pgAdmin's random desktop master key, if the keyring has it."""
    return get_keyring_password(KEYRING_MASTER_USERNAME)


def get_server_password(name, server_id):
    """Legacy pgAdmin 7.0/7.1 per-server keyring entry (plaintext)."""
    return get_keyring_password(
        KEYRING_SERVER_FORMAT.format(name, server_id))
