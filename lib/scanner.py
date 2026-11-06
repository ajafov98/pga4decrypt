import sqlite3

from lib import crypto
from lib import keys


def read_servers(db):
    query = 'select ' \
            '	server.id as "id",' \
            '	server.name,' \
            '	server.host,' \
            '	server.port,' \
            '	server.username,' \
            '	server.password as "password", ' \
            '	user.password as "key"' \
            'from ' \
            '	server ' \
            'inner join ' \
            '	user on ' \
            '		user.id = server.user_id'

    db.row_factory = sqlite3.Row
    cursor = db.cursor()
    cursor.execute(query)
    return cursor.fetchall()


def read_shared_servers(db):
    """Read pgAdmin's sharedserver table when it exists (7.x+)."""
    if not keys.has_table(db, 'sharedserver'):
        return []

    has_username = 'username' in keys.user_columns(db)
    if has_username:
        query = (
            'select sharedserver.osid as "id", sharedserver.name, '
            'sharedserver.host, sharedserver.port, sharedserver.username, '
            'sharedserver.password as "password", user.password as "key" '
            'from sharedserver left join user '
            'on user.username = sharedserver.server_owner')
    else:
        query = (
            'select sharedserver.osid as "id", sharedserver.name, '
            'sharedserver.host, sharedserver.port, sharedserver.username, '
            'sharedserver.password as "password", NULL as "key" '
            'from sharedserver')

    db.row_factory = sqlite3.Row
    try:
        return db.cursor().execute(query).fetchall()
    except sqlite3.DatabaseError:
        return []


def decrypt_password(server, key=None):
    if key is None:
        key = server['key']
    return crypto.decrypt(server['password'], key).decode('utf-8')


def _keyring_password(server):
    """Legacy pgAdmin 7.0/7.1 stored passwords directly in the keyring."""
    try:
        server_id = server['id']
    except (IndexError, KeyError):
        return None
    if server_id is None:
        return None
    return keys.get_server_password(server['name'], server_id)


def _plausible(password):
    if password is None:
        return False
    return all(ch.isprintable() or ch in '\r\n\t' for ch in password)


def read_and_decrypt_servers(db, key=None):
    processed = []
    seen = set()

    for server in list(read_servers(db)) + read_shared_servers(db):
        password = None

        if server['password']:
            try:
                password = decrypt_password(server, key)
            except Exception:
                continue
        else:
            password = _keyring_password(server)

        if not _plausible(password):
            continue

        this = {
            'name': server['name'],
            'host': server['host'],
            'port': server['port'],
            'username': server['username'],
            'password': password,
        }

        identity = (this['name'], this['host'], this['port'],
                    this['username'], this['password'])
        if identity in seen:
            continue
        seen.add(identity)
        processed.append(this)

    return processed
