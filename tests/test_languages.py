import json
import unittest
from pathlib import Path
from local_component.call_translator_local.language_data import LANGUAGE_DATA,CALL_LANGUAGES,voice_test_text
from server.providers import LANGUAGES


class LanguageTests(unittest.TestCase):
    def test_library_metadata_is_identical_in_browser_native_and_server(self):
        source=Path('extension/language-library.js').read_text(encoding='utf-8')
        browser=json.loads(source.split('globalThis.CTLanguageLibrary=',1)[1].rstrip().removesuffix(';'))
        self.assertEqual(browser,LANGUAGE_DATA)
        self.assertEqual(len(browser),53)
        self.assertEqual(LANGUAGES,CALL_LANGUAGES)
        for language,item in LANGUAGE_DATA.items():
            self.assertTrue(voice_test_text(language).strip())
            self.assertEqual(language in LANGUAGES,item['stt'])
        self.assertNotIn('cy',LANGUAGES)
        self.assertIn('de',LANGUAGES)
