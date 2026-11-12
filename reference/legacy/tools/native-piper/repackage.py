"""Refresh installer/docs in the already tested binary package, without rebuilding it."""
import json
from pathlib import Path
import shutil
from datetime import datetime

root = Path(__file__).resolve().parents[2]
latest_path = root / 'dist/native-piper/latest.json'
latest = json.loads(latest_path.read_text(encoding='utf-8'))
package = Path(latest['package'])
if not package.resolve().is_relative_to((root / 'dist/native-piper').resolve()):
    raise RuntimeError('Unexpected package location')
for name in ('install.ps1', 'README.ru.md'):
    shutil.copy2(Path(__file__).parent / name, package / name)
stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
latest['archive'] = shutil.make_archive(str(package) + '-E-' + stamp, 'zip', package)
latest_path.write_text(json.dumps(latest, indent=2), encoding='utf-8')
print(json.dumps(latest, indent=2))
