import hashlib
import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from tools.verify_vps_release import verify


class VPSReleaseTests(unittest.TestCase):
    def test_traversal_and_archive_links_are_rejected_before_release_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp); (base/'incoming').mkdir()
            archive=base/'incoming/upload.tar.gz'
            for name,kind in [('../outside',tarfile.REGTYPE),('/absolute',tarfile.REGTYPE),('link',tarfile.SYMTYPE)]:
                with self.subTest(name=name):
                    with tarfile.open(archive,'w:gz') as output:
                        item=tarfile.TarInfo(name);item.type=kind
                        if kind==tarfile.REGTYPE:item.size=1;output.addfile(item,io.BytesIO(b'x'))
                        else:item.linkname='/etc';output.addfile(item)
                    checksum=hashlib.sha256(archive.read_bytes()).hexdigest()
                    with self.assertRaisesRegex(ValueError,'Unsafe archive member'):
                        verify(archive,checksum,'test-release',base)
                    self.assertFalse((base/'releases/test-release').exists())
            with self.assertRaisesRegex(ValueError,'Invalid release metadata'):
                verify(archive,checksum,'../outside',base)
