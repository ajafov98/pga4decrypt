"""Shared database, key and export helpers."""

import getpass
import json
import os
import sqlite3
import sys
from pathlib import Path

from lib.cli import bright_red
from lib.cli import bright_yellow
from lib import crypto
from lib import keys
from lib import scanner


def export(servers, format, path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        os.chmod(path, 0o600)
        if format == 'text':
            for server in servers:
                print('Name: ' + str(server['name']), file=f)
                print('Host: ' + str(server['host']), file=f)
                print('Port: ' + str(server['port']), file=f)
                print('Username: ' + str(server['username']), file=f)
                print('Password: ' + server['password'], file=f)
                print('-----------------------------------', file=f)
        else:
            f.write(json.dumps(servers))


def open_database(path):
    """Open the config DB read-only so a wrong path cannot create a file."""
    uri = '{0}?mode=ro'.format(Path(path).resolve().as_uri())
    return sqlite3.connect(uri, uri=True)


def find_database(explicit):
    if explicit:
        return Path(explicit).expanduser()

    found = keys.candidate_databases()
    if not found:
        print(bright_red('Error: could not find a pgadmin4.db automatically'))
        print('Pass the path explicitly: ./pga4decrypt /path/to/pgadmin4.db',
              file=sys.stderr)
        return None

    if len(found) > 1:
        print(bright_yellow(
            'Found several databases; using {0} (use --db to choose):'.format(
                found[0])), file=sys.stderr)
        for candidate in found:
            print('  ' + str(candidate), file=sys.stderr)

    return found[0]


def prompt_secret(label):
    if not sys.stdin.isatty():
        print(bright_red('No TTY available to prompt for the {0}'.format(
            label)), file=sys.stderr)
        return None
    try:
        return getpass.getpass('pgAdmin {0}: '.format(label))
    except (EOFError, KeyboardInterrupt):
        print('', file=sys.stderr)
        return None


def try_legacy(db):
    """Per-server key = user.password (old pgAdmin behaviour)."""
    return scanner.read_and_decrypt_servers(db, key=None)


def try_with_key(db, key):
    """Return servers decrypted with key, but only if the key is valid."""
    checks = keys.masterpass_checks(db)
    if checks:
        if not any(crypto.validate_key(key, check)
                   for check in checks.values()):
            return []
    return scanner.read_and_decrypt_servers(db, key=key)


def database_diagnostics(db):
    """Human-readable facts about the database, useful when decryption fails."""
    lines = []

    try:
        row = db.execute(
            "SELECT value FROM version WHERE name = 'ConfigDB'").fetchone()
        if row:
            lines.append('ConfigDB version: {0}'.format(row[0]))
    except sqlite3.DatabaseError:
        pass

    try:
        columns = keys.user_columns(db)
        select = ['id']
        if 'email' in columns:
            select.append('email')
        if 'username' in columns:
            select.append('username')
        cursor = db.execute(
            'SELECT {0} FROM user'.format(', '.join(select)))
        names = [description[0] for description in cursor.description]
        rows = cursor.fetchall()
        labels = []
        for row in rows:
            account = dict(zip(names, row))
            labels.append(str(account.get('username') or
                               account.get('email') or account.get('id')))
        with_hash = db.execute(
            'SELECT COUNT(*) FROM user WHERE password IS NOT NULL'
        ).fetchone()[0]
        lines.append('Users: {0} ({1} with a stored password hash){2}'.format(
            len(rows), with_hash,
            ' [' + ', '.join(labels) + ']' if labels else ''))
    except sqlite3.DatabaseError:
        pass

    checks = keys.masterpass_checks(db)
    lines.append('Master password check set: {0}'.format(
        'yes' if checks else 'no'))

    total = saved = 0
    formats = set()
    for table in ('server', 'sharedserver'):
        if not keys.has_table(db, table):
            continue
        try:
            total += db.execute(
                'SELECT COUNT(*) FROM {0}'.format(table)).fetchone()[0]
            rows = db.execute(
                "SELECT password FROM {0} WHERE password IS NOT NULL "
                "AND password != ''".format(table)).fetchall()
        except sqlite3.DatabaseError:
            continue
        saved += len(rows)
        for (value,) in rows:
            formats.add(crypto.storage_format(value))

    lines.append('Servers: {0} ({1} with saved passwords)'.format(total, saved))
    if formats:
        lines.append('Storage format: {0}'.format(', '.join(sorted(formats))))
    return lines


def print_diagnostics(db, stream=sys.stderr):
    print('Database diagnostics:', file=stream)
    for line in database_diagnostics(db):
        print('  ' + line, file=stream)


def resolve_key(db, key=None, key_file=None, master_password=False,
                login_password=False):
    """Return (key, source, servers). key=None means legacy per-user keys."""
    candidates = []

    if key is not None:
        candidates.append((key, 'command line'))
    if key_file:
        try:
            with open(os.path.expanduser(key_file)) as f:
                candidates.append((f.read().strip(), 'key file'))
        except OSError as exc:
            print(bright_red('Error reading key file: {0}'.format(exc)),
                  file=sys.stderr)

    master_key = keys.get_master_key()
    if master_key:
        candidates.append((master_key, 'OS keyring'))

    for candidate, source in candidates:
        servers = try_with_key(db, candidate)
        if servers:
            return candidate, source, servers

    servers = try_legacy(db)
    if servers:
        return None, 'legacy user.password', servers

    checks = keys.masterpass_checks(db)

    want_master = master_password or (
        not login_password and sys.stdin.isatty() and checks)
    if want_master:
        for _ in range(3):
            secret = prompt_secret('master password')
            if secret is None:
                break
            servers = try_with_key(db, secret)
            if servers:
                return secret, 'master password', servers
            print(bright_red('Wrong master password'), file=sys.stderr)

    want_login = login_password or (
        not master_password and sys.stdin.isatty() and not checks)
    if want_login:
        for _ in range(3):
            secret = prompt_secret('login password (email not needed)')
            if secret is None:
                break
            servers = try_with_key(db, secret)
            if servers:
                return secret, 'login password', servers
            print(bright_red('Wrong login password'), file=sys.stderr)

    return None, None, []
