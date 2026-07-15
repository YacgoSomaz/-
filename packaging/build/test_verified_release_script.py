import pathlib
import unittest


SCRIPT = pathlib.Path(__file__).with_name('build_verified_release.ps1')


class VerifiedReleaseScriptContractTests(unittest.TestCase):
    def test_local_release_script_requires_commercial_build_and_release_scan(self):
        source = SCRIPT.read_text(encoding='utf-8')
        self.assertIn('Commercial = $true', source)
        self.assertIn('AccountProductCode =', source)
        self.assertIn('replay_shrimp', source)
        self.assertIn('check_release.ps1', source)
        self.assertIn('Get-FileHash', source)
        self.assertIn('Get-AuthenticodeSignature', source)

    def test_script_contains_only_public_keys_and_no_private_key_parameter(self):
        source = SCRIPT.read_text(encoding='utf-8')
        self.assertIn('MCowBQYDK2VwAyEACqLAEE2KnduTFtw1gVQIExS1qLRa-XI3TaWpbchMbKc', source)
        self.assertIn('MCowBQYDK2VwAyEAlYg7Ws_9MxeQYmSVP6SNJ8ZgRh1isI8mv_SwIrP7eZ4', source)
        self.assertNotIn('PRIVATE_KEY', source)

    def test_script_resolves_node_from_local_drives_when_the_new_console_has_no_path(self):
        source = SCRIPT.read_text(encoding='utf-8')
        self.assertIn('Get-PSDrive -PSProvider FileSystem', source)
        self.assertIn("Join-Path $drive.Root 'node.exe'", source)
        self.assertIn('NodeExe = $NodeExe', source)

    def test_commercial_nuitka_build_uses_low_memory_single_job_mode(self):
        source = pathlib.Path(__file__).with_name('build_release.ps1').read_text(encoding='utf-8')
        self.assertIn('--low-memory', source)
        self.assertIn('--jobs=1', source)
        self.assertIn('--lto=no', source)


if __name__ == '__main__':
    unittest.main()
