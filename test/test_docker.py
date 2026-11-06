import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from lib import docker


class TestDockerCommands(unittest.TestCase):
    def test_exec_for_a_container(self):
        command = docker._exec_command('pg', ['rm', '-f', 'x'])
        self.assertEqual(command, ['docker', 'exec', 'pg', 'rm', '-f', 'x'])

    def test_cp_for_a_container(self):
        command = docker._cp_command('pg', '/remote.db', '/local.db')
        self.assertEqual(command,
                         ['docker', 'cp', 'pg:/remote.db', '/local.db'])


class TestComposeResolution(unittest.TestCase):
    def test_finds_a_running_container_by_service_label(self):
        output = 'abc123\tpgadmin\trunning\tmyproject\n'
        calls = []

        def fake_run(command):
            calls.append(command)
            return SimpleNamespace(stdout=output)

        with patch.object(docker, '_run', side_effect=fake_run):
            self.assertEqual(
                docker.find_compose_container('pgadmin4_container'), 'abc123')

        self.assertIn('label=com.docker.compose.service=pgadmin4_container',
                      calls[0])

    def test_prefers_a_running_container(self):
        output = ('old\told-pgadmin\texited\tproj\n'
                  'new\tnew-pgadmin\trunning\tproj\n')
        with patch.object(docker, '_run',
                          return_value=SimpleNamespace(stdout=output)):
            self.assertEqual(
                docker.find_compose_container('pgadmin'), 'new')

    def test_filters_by_project(self):
        output = ('one\tpgadmin-one\trunning\tproject-a\n'
                  'two\tpgadmin-two\trunning\tproject-b\n')
        with patch.object(docker, '_run',
                          return_value=SimpleNamespace(stdout=output)):
            self.assertEqual(
                docker.find_compose_container('pgadmin', 'project-b'), 'two')

    def test_reports_multiple_projects(self):
        output = ('one\tpgadmin-one\trunning\tproject-a\n'
                  'two\tpgadmin-two\trunning\tproject-b\n')
        with patch.object(docker, '_run',
                          return_value=SimpleNamespace(stdout=output)):
            with self.assertRaises(docker.DockerError):
                docker.find_compose_container('pgadmin')

    def test_reports_a_missing_service(self):
        with patch.object(docker, '_run',
                          return_value=SimpleNamespace(stdout='')):
            with self.assertRaises(docker.DockerError):
                docker.find_compose_container('missing')

    def test_resolve_uses_labels_without_a_compose_file(self):
        with patch.object(docker, 'find_compose_container',
                          return_value='resolved-id'):
            self.assertEqual(
                docker.resolve_container(
                    compose_service='pgadmin4_container'), 'resolved-id')


class TestListContainers(unittest.TestCase):
    def test_parses_ps_output(self):
        output = ('abc123\tpgadmin\t\tdpage/pgadmin4\n'
                  'def456\tpostgres\tpostgres:16\n')
        with patch.object(docker, '_run',
                          return_value=SimpleNamespace(stdout=output)):
            containers = docker.list_containers()
        self.assertEqual(containers[0]['name'], 'pgadmin')
        self.assertEqual(containers[1]['image'], 'postgres:16')


class TestCopyDatabase(unittest.TestCase):
    def test_copies_via_sqlite_backup(self):
        calls = []

        def fake_run(command):
            calls.append(command)
            return SimpleNamespace(stdout='', stderr='')

        with patch.object(docker, 'available', return_value=True), \
                patch.object(docker, '_run', side_effect=fake_run):
            destination = docker.copy_database(container='pg')

        self.assertTrue(os.path.exists(destination))
        self.assertEqual(os.stat(destination).st_mode & 0o777, 0o600)
        self.assertEqual(calls[0][:4], ['docker', 'exec', 'pg', 'python3'])
        self.assertEqual(calls[1][:2], ['docker', 'cp'])
        self.assertTrue(calls[1][2].startswith(
            'pg:/tmp/pga4decrypt-backup-'))
        self.assertEqual(calls[1][3], destination)
        self.assertIn('rm', calls[2])
        os.unlink(destination)

    def test_falls_back_to_plain_cp_when_exec_fails(self):
        calls = []

        def fake_run(command):
            calls.append(command)
            if 'python3' in command:
                raise docker.DockerError('container is stopped')
            return SimpleNamespace(stdout='', stderr='')

        with patch.object(docker, 'available', return_value=True), \
                patch.object(docker, '_run', side_effect=fake_run):
            destination = docker.copy_database(container='pg')

        self.assertTrue(os.path.exists(destination))
        self.assertEqual(calls[1][:2], ['docker', 'cp'])
        os.unlink(destination)

    def test_resolves_a_compose_service_before_copying(self):
        with patch.object(docker, 'available', return_value=True), \
                patch.object(docker, 'resolve_container',
                             return_value='container-id'), \
                patch.object(docker, '_run',
                             return_value=SimpleNamespace(stdout='')):
            destination = docker.copy_database(
                compose_service='pgadmin4_container')
        self.assertTrue(os.path.exists(destination))
        os.unlink(destination)


if __name__ == '__main__':
    unittest.main()
