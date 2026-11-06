"""Copy a pgadmin4.db out of a running Docker / Docker Compose container."""

import atexit
import os
import shutil
import subprocess
import tempfile

DEFAULT_REMOTE_DB = '/var/lib/pgadmin/pgadmin4.db'

_BACKUP_SCRIPT = (
    'import sqlite3,sys;'
    'src=sqlite3.connect(sys.argv[1]);'
    'dst=sqlite3.connect(sys.argv[2]);'
    'src.backup(dst);'
    'dst.close();src.close()'
)


class DockerError(Exception):
    pass


def _remove(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def available():
    return shutil.which('docker') is not None


def _run(command):
    try:
        return subprocess.run(command, check=True, capture_output=True,
                              text=True)
    except FileNotFoundError:
        raise DockerError('docker is not installed')
    except subprocess.CalledProcessError as exc:
        message = (exc.stderr or exc.stdout or str(exc)).strip()
        raise DockerError(message or 'docker command failed')


def _compose_base(compose_file):
    command = ['docker', 'compose']
    if compose_file:
        command.extend(['-f', os.path.expanduser(compose_file)])
    return command


def list_containers():
    result = _run(['docker', 'ps', '--format',
                   '{{.ID}}\t{{.Names}}\t{{.Image}}'])
    containers = []
    for line in result.stdout.splitlines():
        parts = line.split('\t')
        if len(parts) >= 3:
            containers.append({
                'id': parts[0],
                'name': parts[1],
                'image': parts[2],
            })
    return containers


def find_compose_container(service, project=None):
    """Resolve a compose service name to a container ID using labels.

    This does not need the compose file or the project directory.
    """
    result = _run([
        'docker', 'ps', '-a',
        '--filter', 'label=com.docker.compose.service={0}'.format(service),
        '--format',
        '{{.ID}}\t{{.Names}}\t{{.State}}\t'
        '{{.Label "com.docker.compose.project"}}',
    ])

    matches = []
    for line in result.stdout.splitlines():
        parts = line.split('\t')
        if len(parts) < 2:
            continue
        row = {
            'id': parts[0],
            'name': parts[1],
            'state': parts[2] if len(parts) > 2 else '',
            'project': parts[3] if len(parts) > 3 else '',
        }
        if project is None or row['project'] == project:
            matches.append(row)

    running = [row for row in matches if row['state'] == 'running']
    if running:
        matches = running

    if not matches:
        where = ' in project {0!r}'.format(project) if project else ''
        raise DockerError(
            'no container found for Docker Compose service {0!r}{1}'.format(
                service, where))

    if len(matches) > 1:
        projects = ', '.join(sorted({row['project'] or '<none>'
                                     for row in matches}))
        raise DockerError(
            'service {0!r} exists in several projects ({1}); '
            'use --compose-project'.format(service, projects))

    return matches[0]['id']


def resolve_container(container=None, compose_service=None,
                      compose_project=None, compose_file=None):
    if container:
        return container
    if not compose_service:
        raise DockerError('a container name or compose service is required')

    if compose_file:
        try:
            result = _run(_compose_base(compose_file) + [
                'ps', '-q', compose_service])
            ids = result.stdout.split()
            if ids:
                return ids[0]
        except DockerError:
            pass

    return find_compose_container(compose_service, compose_project)


def _exec_command(container, arguments):
    return ['docker', 'exec', container] + arguments


def _cp_command(container, remote_path, destination):
    return ['docker', 'cp',
            '{0}:{1}'.format(container, remote_path), destination]


def copy_database(container=None, compose_service=None, compose_project=None,
                  compose_file=None, remote_path=DEFAULT_REMOTE_DB,
                  destination=None):
    """Copy the config DB from a container and return the local temp path.

    Uses SQLite's online backup inside the container when possible, so a
    running pgAdmin does not leave us with a torn copy. Falls back to a
    plain ``docker cp`` (e.g. when the container is stopped).
    """
    if not available():
        raise DockerError('docker is not installed')

    target = resolve_container(container, compose_service, compose_project,
                               compose_file)

    if destination is None:
        fd, destination = tempfile.mkstemp(prefix='pga4decrypt-', suffix='.db')
        os.close(fd)
        atexit.register(_remove, destination)
    os.chmod(destination, 0o600)

    inside_backup = '/tmp/pga4decrypt-backup-{0}.db'.format(os.getpid())

    try:
        _run(_exec_command(
            target, ['python3', '-c', _BACKUP_SCRIPT, remote_path,
                     inside_backup]))
        _run(_cp_command(target, inside_backup, destination))
    except DockerError:
        # Stopped container, no python3, etc. Fall back to a direct copy.
        _run(_cp_command(target, remote_path, destination))
    finally:
        try:
            _run(_exec_command(target, ['rm', '-f', inside_backup]))
        except DockerError:
            pass

    return destination


def describe(container=None, compose_service=None,
             remote_path=DEFAULT_REMOTE_DB):
    return '{0}:{1}'.format(compose_service or container, remote_path)
