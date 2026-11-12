"""Shipped language capabilities; never supplied by native requests."""
import json
from pathlib import Path

LANGUAGE_DATA=json.loads(Path(__file__).with_name('languages.json').read_text(encoding='utf-8'))
CALL_LANGUAGES={code:item['name'] for code,item in LANGUAGE_DATA.items() if item['stt']}


def voice_test_text(language):
    return LANGUAGE_DATA[language]['sample']
