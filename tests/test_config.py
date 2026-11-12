import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server.config import Settings
from tools.check_config import summary


class DotenvTests(unittest.TestCase):
    def test_file_aliases_literal_dollars_and_no_environment_mutation(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}, clear=True):
            path = Path(temp)/'.env'
            path.write_text('\ufeffDEEPGRAM_API_KEY="test-${MISSING}-value"\nGROQ_API_KEY=test-groq\n', encoding='utf-8')
            settings = Settings.from_env(path)
            self.assertEqual(settings.deepgram_key, 'test-${MISSING}-value')
            self.assertEqual(settings.groq_key, 'test-groq')
            self.assertNotIn('DEEPGRAM_API_KEY', os.environ)
            self.assertFalse(settings.experimental_audio)
            self.assertNotIn('test-groq', repr(settings))
            self.assertNotIn('test-groq', str(summary(settings)))

    def test_process_alias_wins_over_file_canonical_name(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'GROQ_API_KEY': 'process-value'}, clear=True):
            path = Path(temp)/'.env'
            path.write_text('CT_GROQ_KEY=file-value\n', encoding='utf-8')
            self.assertEqual(Settings.from_env(path).groq_key, 'process-value')

    def test_no_parent_env_search(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}, clear=True):
            root = Path(temp)
            (root/'.env').write_text('CT_GROQ_KEY=must-not-load\n', encoding='utf-8')
            self.assertEqual(Settings.from_env(root/'child'/'.env').groq_key, '')

    def test_invalid_numeric_value_does_not_echo_value(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}, clear=True):
            path = Path(temp)/'.env'
            path.write_text('CT_PORT=private-accidental-value\n', encoding='utf-8')
            with self.assertRaises(ValueError) as error:
                Settings.from_env(path)
            self.assertNotIn('private-accidental-value', str(error.exception))
