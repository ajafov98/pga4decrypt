"""Interactive wizard for pga4decrypt."""

import os
import sqlite3
from pathlib import Path

from lib.cli import bold
from lib.cli import bright_green
from lib.cli import bright_red
from lib.cli import bright_yellow

from lib import docker
from lib import keys
from lib import session


def ask(prompt, default=''):
    try:
        value = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print('')
        return None
    return value if value else default


def ask_yes_no(prompt, default=False):
    suffix = '[Y/n]' if default else '[y/N]'
    value = ask('{0} {1}: '.format(prompt, suffix))
    if value is None:
        return False
    value = value.lower()
    if value in ('y', 'yes'):
        return True
    if value in ('n', 'no'):
        return False
    return default


def choose(prompt, count, default=1):
    value = ask('{0} [1-{1}] ({2}): '.format(prompt, count, default),
                str(default))
    if value is None:
        return None
    try:
        number = int(value)
    except ValueError:
        return None
    if 1 <= number <= count:
        return number
    return None


def pick_docker():
    if not docker.available():
        print(bright_red('docker is not installed or not on PATH'))
        return None

    try:
        containers = docker.list_containers()
    except docker.DockerError as exc:
        print(bright_red('Docker error: {0}'.format(exc)))
        return None

    if containers:
        print(bold('\nDocker containers:'))
        for index, container in enumerate(containers, 1):
            print('  {0}) {1}  ({2})'.format(
                index, container['name'], container['image']))
        print('  {0}) Enter a container name or ID'.format(
            len(containers) + 1))
        choice = choose('Select container', len(containers) + 1, 1)
        if choice is None:
            return None
        if choice <= len(containers):
            target = containers[choice - 1]['name']
        else:
            target = ask('Container name or ID: ')
    else:
        target = ask('Container name or ID: ')

    if not target:
        return None

    remote_path = ask(
        'Database path in container [{0}]: '.format(
            docker.DEFAULT_REMOTE_DB), docker.DEFAULT_REMOTE_DB)
    if remote_path is None:
        return None

    try:
        copied = docker.copy_database(container=target,
                                      remote_path=remote_path)
    except docker.DockerError as exc:
        print(bright_red('Docker error: {0}'.format(exc)))
        return None

    print(bright_green('Copied {0}:{1}'.format(target, remote_path)))
    return Path(copied)


def pick_database():
    found = keys.candidate_databases()

    print(bold('Database:'))
    for index, candidate in enumerate(found, 1):
        print('  {0}) {1}'.format(index, candidate))

    enter_path = len(found) + 1
    from_docker = len(found) + 2
    print('  {0}) Enter a path'.format(enter_path))
    print('  {0}) Read from a running Docker container'.format(from_docker))

    default = 1 if found else enter_path
    choice = choose('Select database', from_docker, default)
    if choice is None:
        return None

    if choice <= len(found):
        return found[choice - 1]

    if choice == from_docker:
        return pick_docker()

    while True:
        value = ask('Path to pgadmin4.db: ')
        if value is None:
            return None
        path = Path(value).expanduser()
        if path.is_file():
            return path
        print(bright_red('File not found: {0}'.format(path)))


def show_servers(servers):
    print('\nDecrypted {0} sets of credentials\n'.format(len(servers)))
    for server in servers:
        print(bold('Name: ') + str(server['name']))
        print(bold('Host: ') + str(server['host']))
        print(bold('Port: ') + str(server['port']))
        print(bold('Username: ') + str(server['username']))
        print(bold('Password: ') + bright_green(server['password']))
        print('-----------------------------------')
    print('')


def save_servers(servers):
    format_choice = choose('Format 1) text  2) json', 2, 1)
    if format_choice is None:
        return
    output_format = 'json' if format_choice == 2 else 'text'

    default_name = 'pgadmin-credentials.' + (
        'json' if output_format == 'json' else 'txt')
    value = ask('Output file [{0}]: '.format(default_name), default_name)
    if value is None:
        return

    path = os.path.expanduser(value)
    try:
        session.export(servers, output_format, path)
    except OSError as exc:
        print(bright_red('Could not write {0}: {1}'.format(path, exc)))
        return
    print(bright_green('Saved to ' + path + ' (mode 600)'))


def pick_key_source(db):
    """Return (key, source, servers)."""
    print(bold('\nKey source:'))
    print('  1) Automatic (keyring, stored key, then prompt)')
    print('  2) OS keyring')
    print('  3) Master password')
    print('  4) Login password')
    print('  5) Paste the encryption key')
    print('  6) Read the key from a file')

    choice = choose('Select key source', 6, 1)
    if choice is None:
        return None, None, []

    if choice == 1:
        return session.resolve_key(db)

    if choice == 2:
        key = keys.get_master_key()
        if not key:
            print(bright_red('No pgAdmin master key found in the OS keyring'))
            return None, None, []
        return key, 'OS keyring', session.try_with_key(db, key)

    if choice in (3, 4):
        label = 'master password' if choice == 3 else \
            'login password (email not needed)'
        for _ in range(3):
            secret = session.prompt_secret(label)
            if secret is None:
                return None, None, []
            servers = session.try_with_key(db, secret)
            if servers:
                return secret, label, servers
            print(bright_red('Wrong ' + label))
        return None, None, []

    if choice == 5:
        secret = session.prompt_secret('encryption key')
        if secret is None:
            return None, None, []
        return secret, 'entered key', session.try_with_key(db, secret)

    path = ask('Key file: ')
    if path is None:
        return None, None, []
    try:
        with open(os.path.expanduser(path)) as f:
            secret = f.read().strip()
    except OSError as exc:
        print(bright_red('Could not read {0}: {1}'.format(path, exc)))
        return None, None, []
    return secret, 'key file', session.try_with_key(db, secret)


def run():
    print(bold('\npga4decrypt interactive mode'))
    print('---------------------------')

    recovered_any = False

    while True:
        path = pick_database()
        if path is None:
            return 1

        try:
            db = session.open_database(path)
            db.execute('SELECT 1 FROM sqlite_master LIMIT 1').fetchone()
        except sqlite3.DatabaseError as exc:
            print(bright_red('Not a readable pgAdmin SQLite database: '
                             '{0}'.format(exc)))
            return 1

        print('Database: ' + str(path))

        servers = []
        while not servers:
            key, source, servers = pick_key_source(db)
            if servers:
                print('Key source: ' + source)
                break
            print(bright_red('Could not decrypt with that key source.'))
            if not ask_yes_no('Try a different key source?', True):
                break

        if servers:
            recovered_any = True
            show_servers(servers)
            if ask_yes_no('Save the credentials to a file?', False):
                save_servers(servers)
        else:
            print(bright_yellow(
                'No credentials recovered. A database copied without its key '
                'cannot be decrypted.'))
            session.print_diagnostics(db)

        if not ask_yes_no('Decrypt another database?', False):
            return 0 if recovered_any else 1
