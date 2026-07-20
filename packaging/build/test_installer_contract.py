"""Static safety contract for the Inno Setup upgrade/uninstall rules.

Run with: python packaging/build/test_installer_contract.py
"""

from __future__ import annotations

from pathlib import Path
import unittest


SCRIPT = (Path(__file__).resolve().parent / "livewatch.iss").read_text(encoding="utf-8")
BUILD_SCRIPT = (Path(__file__).resolve().parent / "build_release.ps1").read_text(encoding="utf-8")


class InstallerContractTests(unittest.TestCase):
    def test_upgrade_uses_one_stable_identity_and_waits_for_the_old_client(self) -> None:
        self.assertIn("AppId={{8F2A1C7E-4B3D-49A6-9E21-7C5D0A1B2E34}", SCRIPT)
        self.assertIn("CloseApplications=force", SCRIPT)
        self.assertIn("CloseApplicationsFilter=LiveWatchLauncher.exe", SCRIPT)
        self.assertIn("function WaitForLauncherExit", SCRIPT)
        self.assertIn("WaitForLauncherExit(12)", SCRIPT)

    def test_upgrade_removes_only_known_program_runtime_directories(self) -> None:
        self.assertIn('Type: filesandordirs; Name: "{app}\\app"', SCRIPT)
        self.assertIn('Type: filesandordirs; Name: "{app}\\_internal"', SCRIPT)
        self.assertIn('Type: filesandordirs; Name: "{app}\\models"', SCRIPT)
        self.assertIn('[UninstallDelete]', SCRIPT)
        self.assertNotIn('Name: "{app}"', SCRIPT)

    def test_uninstall_keeps_user_data_unless_the_user_explicitly_confirms(self) -> None:
        uninstall_delete = SCRIPT.split("[UninstallDelete]", 1)[1].split("[Code]", 1)[0]
        self.assertIn("{localappdata}\\LiveWatch\\data", SCRIPT)
        self.assertIn("MB_DEFBUTTON2", SCRIPT)
        self.assertIn("DelTree(dir, True, True, True)", SCRIPT)
        self.assertIn('Name: "{localappdata}\\LiveWatch\\app"', uninstall_delete)
        self.assertNotIn('Name: "{localappdata}\\LiveWatch\\data"', uninstall_delete)

    def test_certificate_builds_sign_the_embedded_uninstaller_too(self) -> None:
        self.assertIn("#ifdef InnoSignTool", SCRIPT)
        self.assertIn("SignTool=livewatch", SCRIPT)
        self.assertIn("SignedUninstaller=yes", SCRIPT)
        self.assertNotIn("DiskSpanning=yes", SCRIPT)
        self.assertNotIn("DiskSliceSize=max", SCRIPT)
        self.assertIn('"/Slivewatch=$innoSignCommand"', BUILD_SCRIPT)
        self.assertIn('"/DInnoSignTool=1"', BUILD_SCRIPT)

    def test_reopening_the_same_or_older_installer_launches_the_installed_client(self) -> None:
        self.assertIn("function ShouldLaunchInstalledApp", SCRIPT)
        self.assertIn("LiveWatchUninstallKey", SCRIPT)
        self.assertIn("Inno Setup: App Path", SCRIPT)
        self.assertIn("DisplayVersion", SCRIPT)
        self.assertIn("StrToVersion", SCRIPT)
        self.assertIn("ComparePackedVersion", SCRIPT)
        self.assertIn("Exec(InstalledLauncher", SCRIPT)
        self.assertIn("function InitializeSetup", SCRIPT)
        self.assertIn("ShouldLaunchInstalledApp", SCRIPT)

    def test_upgrade_without_dir_switch_reuses_the_registered_install_directory(self) -> None:
        """Old clients cannot pass /DIR, so the installer must recover the path itself."""
        self.assertIn("DefaultDirName={code:GetDefaultInstallDir}", SCRIPT)
        self.assertIn("function GetDefaultInstallDir", SCRIPT)
        self.assertIn("ReadInstalledValue('Inno Setup: App Path'", SCRIPT)
        self.assertIn("ExpandConstant('{autopf}\\LiveWatch')", SCRIPT)
        self.assertIn("procedure InitializeWizard", SCRIPT)
        self.assertIn("WizardForm.DirEdit.Text := InstalledDir", SCRIPT)
        self.assertIn("RemoveBackslashUnlessRoot(Candidate)", SCRIPT)
        self.assertIn("UsePreviousAppDir=no", SCRIPT)

    def test_invalid_previous_directory_requires_explicit_reselection(self) -> None:
        """A corrupt old registry path must not silently create another copy."""
        self.assertIn("PreviousInstallPathInvalid", SCRIPT)
        self.assertIn("function IsExistingInstallDir", SCRIPT)
        self.assertIn("wpSelectDir", SCRIPT)
        self.assertIn("请在安装目录页面选择原复盘虾目录", SCRIPT)


if __name__ == "__main__":
    unittest.main()
