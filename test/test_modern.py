import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib import crypto
from lib import keys
from lib import scanner
from lib import session


KEY = 'RiF8XOJ0nxerGZxn'
MASTERPASS = 'hunter2'


def make_db(path, key, store_as, with_masterpass=False):
    db = sqlite3.connect(path)
    db.executescript("""
        create table user (
            id integer primary key, password text, masterpass_check text,
            username text
        );
        create table server (
            id integer primary key, user_id integer, name text, host text,
            port integer, username text, password text
        );
        create table sharedserver (
            id integer primary key, osid integer, user_id integer,
            server_owner text, name text, host text, port integer,
            username text, password text
        );
    """)
    check = crypto.encrypt(crypto.MASTERPASS_CHECK_TEXT, key).hex() \
        if with_masterpass else None
    db.execute(
        'insert into user (id, password, masterpass_check, username) '
        'values (1, ?, ?, ?)',
        ('$pbkdf2-sha512$25000$aaa$bbb', check, 'alice'))
    ct = crypto.encrypt('S3cret-Modern-Pass', key)
    stored = ct.hex() if store_as == 'hex' else ct.decode()
    db.execute(
        'insert into server (id, user_id, name, host, port, username, '
        'password) values (1, 1, ?, ?, 5432, ?, ?)',
        ('srv', '10.0.0.5', 'alice', stored))
    db.commit()
    return db


class TestModernStorage(unittest.TestCase):
    def test_decrypts_hex_encoded_ciphertext(self):
        ct = crypto.encrypt('secret', KEY).hex()
        self.assertEqual(crypto.decrypt(ct, KEY).decode(), 'secret')

    def test_decrypts_legacy_base64_ciphertext(self):
        ct = crypto.encrypt('secret', KEY).decode()
        self.assertEqual(crypto.decrypt(ct, KEY).decode(), 'secret')

    def test_validate_key(self):
        check = crypto.encrypt(crypto.MASTERPASS_CHECK_TEXT, MASTERPASS)
        self.assertTrue(crypto.validate_key(MASTERPASS, check))
        self.assertFalse(crypto.validate_key('wrong', check))

    def test_storage_format(self):
        self.assertEqual(
            crypto.storage_format(crypto.encrypt('x', KEY).hex()), 'hex')
        self.assertEqual(
            crypto.storage_format(crypto.encrypt('x', KEY).decode()), 'base64')


class TestDiagnostics(unittest.TestCase):
    def test_reports_database_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_db(os.path.join(tmp, 'pgadmin4.db'), KEY, 'hex',
                         with_masterpass=True)
            text = '\n'.join(session.database_diagnostics(db))
        self.assertIn('Users: 1', text)
        self.assertIn('Master password check set: yes', text)
        self.assertIn('Servers: 1 (1 with saved passwords)', text)
        self.assertIn('Storage format: hex', text)


class TestScannerWithKeys(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, 'pgadmin4.db')

    def tearDown(self):
        self.tmp.cleanup()

    def test_scans_modern_hex_with_explicit_key(self):
        db = make_db(self.path, KEY, 'hex')
        rows = scanner.read_and_decrypt_servers(db, key=KEY)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['password'], 'S3cret-Modern-Pass')

    def test_scans_legacy_base64_with_stored_key(self):
        db = make_db(self.path, '$pbkdf2-sha512$25000$aaa$bbb', 'b64')
        rows = scanner.read_and_decrypt_servers(db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['password'], 'S3cret-Modern-Pass')

    def test_wrong_key_yields_nothing(self):
        db = make_db(self.path, KEY, 'hex', with_masterpass=True)
        self.assertEqual(scanner.read_and_decrypt_servers(db, key='wrong'), [])

    def test_shared_servers_are_included(self):
        db = make_db(self.path, KEY, 'hex')
        ct = crypto.encrypt('shared-pass', KEY).hex()
        db.execute(
            'insert into sharedserver (id, osid, user_id, server_owner, '
            'name, host, port, username, password) '
            'values (1, 1, 1, ?, ?, ?, 5432, ?, ?)',
            ('alice', 'shared', '10.0.0.6', 'bob', ct))
        db.commit()
        rows = scanner.read_and_decrypt_servers(db, key=KEY)
        self.assertEqual(len(rows), 2)
        self.assertIn('shared-pass', [row['password'] for row in rows])


class TestDatabaseDiscovery(unittest.TestCase):
    def test_uses_sqlite_path_environment_variable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'custom.db'
            path.write_bytes(b'')
            old = os.environ.get('SQLITE_PATH')
            os.environ['SQLITE_PATH'] = str(path)
            try:
                self.assertIn(path, keys.candidate_databases())
            finally:
                if old is None:
                    del os.environ['SQLITE_PATH']
                else:
                    os.environ['SQLITE_PATH'] = old


class TestKeyringLookup(unittest.TestCase):
    def test_reads_the_master_key(self):
        class FakeKeyring:
            @staticmethod
            def get_password(service, username):
                if (service, username) == (
                        'pgAdmin4', 'pgadmin4-master-password'):
                    return 'key-from-keyring'
                return None

        with patch.object(keys, 'keyring', FakeKeyring):
            self.assertEqual(keys.get_master_key(), 'key-from-keyring')

    def test_returns_none_when_keyring_has_no_entry(self):
        class EmptyKeyring:
            @staticmethod
            def get_password(service, username):
                return None

        with patch.object(keys, 'keyring', EmptyKeyring):
            self.assertIsNone(keys.get_master_key())

    def test_keyring_errors_are_ignored(self):
        class BrokenKeyring:
            @staticmethod
            def get_password(service, username):
                raise RuntimeError('no backend')

        with patch.object(keys, 'keyring', BrokenKeyring):
            self.assertIsNone(keys.get_master_key())


if __name__ == '__main__':
    unittest.main()
