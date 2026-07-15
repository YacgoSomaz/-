import pathlib
import unittest


BAT = pathlib.Path(__file__).with_name('一键打包复盘虾.bat')
RUNNER = pathlib.Path(__file__).with_name('run_verified_release.ps1')
PROMPT = pathlib.Path(__file__).with_name('interactive_verified_release.ps1')


class VerifiedReleaseBatContractTests(unittest.TestCase):
    def test_bat_prompts_for_version_and_invokes_verified_release_script(self):
        source = BAT.read_text(encoding='utf-8-sig')
        self.assertIn('interactive_verified_release.ps1', source)
        self.assertIn('start "LiveWatch Official Build"', source)
        self.assertIn('-NoExit', source)
        self.assertNotIn('for /f', source.lower())
        self.assertIn('build-launch.log', source)

    def test_bat_does_not_interpolate_user_version_into_the_shell_command(self):
        source = BAT.read_text(encoding='utf-8-sig')
        self.assertTrue(source.isascii())
        self.assertIn('-File "%~dp0interactive_verified_release.ps1"', source)
        self.assertNotIn('-Version "%LIVEWATCH_BUILD_VERSION%"', source)

    def test_runner_passes_the_environment_value_without_a_command_shell(self):
        source = RUNNER.read_text(encoding='utf-8-sig')
        self.assertIn("$version = $env:LIVEWATCH_BUILD_VERSION", source)
        self.assertIn("& $scriptPath -Version $version", source)
        self.assertIn("Start-Transcript -LiteralPath $logPath -Force", source)
        self.assertNotIn('exit $exitCode', source)

    def test_interactive_script_collects_the_version_inside_powershell(self):
        source = PROMPT.read_text(encoding='utf-8-sig')
        self.assertIn("Read-Host 'Enter version", source)
        self.assertIn('next build: 1.1.15', source)
        self.assertIn('$env:LIVEWATCH_BUILD_VERSION = $version', source)
        self.assertIn('& $runnerPath', source)


if __name__ == '__main__':
    unittest.main()
