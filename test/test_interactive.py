import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib import interactive
from lib import keys


class TestPrompts(unittest.TestCase):
    def test_ask_yes_no_accepts_yes(self):
        with patch('builtins.input', return_value='y'):
            self.assertTrue(interactive.ask_yes_no('Continue?'))

    def test_ask_yes_no_accepts_default(self):
        with patch('builtins.input', return_value=''):
            self.assertFalse(interactive.ask_yes_no('Continue?', False))
            self.assertTrue(interactive.ask_yes_no('Continue?', True))

    def test_choose_valid_number(self):
        with patch('builtins.input', return_value='2'):
            self.assertEqual(interactive.choose('Pick', 3), 2)

    def test_choose_out_of_range(self):
        with patch('builtins.input', return_value='9'):
            self.assertIsNone(interactive.choose('Pick', 3))

    def test_choose_default(self):
        with patch('builtins.input', return_value=''):
            self.assertEqual(interactive.choose('Pick', 3, 2), 2)


class TestDatabasePicker(unittest.TestCase):
    def test_selects_a_detected_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'pgadmin4.db'
            path.write_bytes(b'')
            with patch.object(keys, 'candidate_databases',
                              return_value=[path]), \
                    patch('builtins.input', return_value='1'):
                self.assertEqual(interactive.pick_database(), path)

    def test_accepts_a_typed_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'my.db'
            path.write_bytes(b'')
            with patch.object(keys, 'candidate_databases',
                              return_value=[]), \
                    patch('builtins.input',
                          side_effect=['1', str(path)]):
                self.assertEqual(interactive.pick_database(), path)

    def test_copies_from_a_docker_container(self):
        with patch.object(keys, 'candidate_databases', return_value=[]), \
                patch.object(interactive.docker, 'available',
                             return_value=True), \
                patch.object(interactive.docker, 'list_containers',
                             return_value=[{'name': 'pgadmin',
                                            'image': 'dpage/pgadmin4'}]), \
                patch.object(interactive.docker, 'copy_database',
                             return_value='/tmp/copied.db'), \
                patch('builtins.input',
                      side_effect=['2', '1', '']):
            self.assertEqual(interactive.pick_database(),
                             Path('/tmp/copied.db'))


if __name__ == '__main__':
    unittest.main()
