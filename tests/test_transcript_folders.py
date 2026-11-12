import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from local_component.call_translator_local.transcripts import TranscriptFolders,FOLDER


class TranscriptFolderTests(unittest.TestCase):
    def test_choose_starts_at_current_custom_and_downloads_root(self):
        from local_component.call_translator_local.application import Application
        from local_component.call_translator_local.voices import VoiceStore
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);app=Application(VoiceStore(root/'voices',{}))
            custom=root/'custom'/FOLDER
            app.transcripts.configure(custom)
            with patch('local_component.call_translator_local.application.choose_folder',return_value=None) as picker:
                result=list(app.handle({'id':1,'type':'transcript-folder-choose'}))
                picker.assert_called_once_with(custom)
                self.assertEqual(result[0]['type'],'transcript-folder-choose')
            app.transcripts.configure(None)
            downloaded=root/'downloads'/FOLDER/'2026-11-12/CallTranslator_test.html'
            downloaded.parent.mkdir(parents=True);downloaded.write_text('fixture')
            with patch('local_component.call_translator_local.application.choose_folder',return_value=None) as picker:
                list(app.handle({'id':2,'type':'transcript-folder-choose','downloaded':str(downloaded)}))
                picker.assert_called_once_with(root/'downloads'/FOLDER)

    def test_custom_days_atomic_html_and_persistent_choice(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);folders=TranscriptFolders(root/'settings.json')
            folders.configure(root/'chosen')
            html='<!doctype html><html><p>Перевод</p></html>'
            folders.write('2026-11-12','CallTranslator_test.html',html)
            path=root/'chosen'/FOLDER/'2026-11-12/CallTranslator_test.html'
            self.assertEqual(path.read_text(encoding='utf-8'),html)
            self.assertEqual(TranscriptFolders(root/'settings.json').root(),root/'chosen'/FOLDER)
            with patch('local_component.call_translator_local.transcripts.open_folder') as opener:
                folders.open();opener.assert_called_once_with(root/'chosen'/FOLDER)
            for day,name in [('../outside','CallTranslator_test.html'),('2026-11-12','../outside.html')]:
                with self.assertRaises(ValueError):folders.write(day,name,html)
            folders.configure(None)
            self.assertTrue(path.is_file(),'Changing location must preserve old files')
            with patch('local_component.call_translator_local.transcripts.open_folder') as opener:
                folders.open(str(path));opener.assert_called_once_with(root/'chosen'/FOLDER)
            with self.assertRaises(ValueError):folders.open(str(root/'settings.json'))
