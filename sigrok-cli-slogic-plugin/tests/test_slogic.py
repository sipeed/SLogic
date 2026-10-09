import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "skills/sigrok-cli-slogic/scripts/slogic.py"
SPEC = importlib.util.spec_from_file_location("slogic", SCRIPT)
slogic = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(slogic)


class ResolveCliTests(unittest.TestCase):
    def test_linux_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            cli = Path(directory) / "sigrok-cli"
            cli.write_text("#!/bin/sh\n", encoding="utf-8")
            cli.chmod(cli.stat().st_mode | stat.S_IXUSR)
            self.assertEqual(slogic.resolve_cli(str(cli), platform="linux"), cli.resolve())

    def test_linux_rejects_non_executable_file(self):
        with tempfile.TemporaryDirectory() as directory:
            cli = Path(directory) / "sigrok-cli"
            cli.write_text("not executable", encoding="utf-8")
            with self.assertRaises(SystemExit):
                slogic.resolve_cli(str(cli), platform="linux")

    def test_windows_accepts_exe_without_posix_execute_bit(self):
        with tempfile.TemporaryDirectory() as directory:
            cli = Path(directory) / "sigrok-cli.exe"
            cli.write_bytes(b"MZ")
            self.assertEqual(slogic.resolve_cli(str(cli), platform="windows"), cli.resolve())

    def test_windows_portable_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            cli = Path(directory) / "bin/sigrok-cli.exe"
            cli.parent.mkdir()
            cli.write_bytes(b"MZ")
            self.assertEqual(slogic.resolve_cli(directory, platform="windows"), cli.resolve())

    def test_macos_app_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "sigrok-cli.app"
            cli = app / "Contents/MacOS/sigrok-cli"
            cli.parent.mkdir(parents=True)
            cli.write_text("#!/bin/sh\n", encoding="utf-8")
            cli.chmod(cli.stat().st_mode | stat.S_IXUSR)
            self.assertEqual(slogic.resolve_cli(str(app), platform="macos"), cli.resolve())

    def test_macos_dmg_has_actionable_error(self):
        with self.assertRaisesRegex(SystemExit, "disk image"):
            slogic.resolve_cli("sigrok-cli.dmg", platform="macos")


class EnvironmentTests(unittest.TestCase):
    def test_linux_adds_adjacent_lib(self):
        with tempfile.TemporaryDirectory() as directory:
            cli = Path(directory) / "bin/sigrok-cli"
            cli.parent.mkdir()
            (Path(directory) / "lib").mkdir()
            env = slogic.command_env(cli, platform="linux")
            self.assertEqual(env["LD_LIBRARY_PATH"].split(os.pathsep)[0], str(Path(directory) / "lib"))

    def test_macos_adds_app_frameworks(self):
        with tempfile.TemporaryDirectory() as directory:
            contents = Path(directory) / "sigrok-cli.app/Contents"
            cli = contents / "MacOS/sigrok-cli"
            cli.parent.mkdir(parents=True)
            (contents / "Frameworks").mkdir()
            env = slogic.command_env(cli, platform="macos")
            self.assertEqual(env["DYLD_LIBRARY_PATH"].split(os.pathsep)[0], str(contents / "Frameworks"))

    def test_windows_prepends_executable_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            cli = Path(directory) / "sigrok-cli.exe"
            env = slogic.command_env(cli, platform="windows")
            self.assertEqual(env["PATH"].split(os.pathsep)[0], directory)


class ExecutionTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "POSIX fixture")
    def test_executable_and_arguments_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix="slogic test ") as directory:
            cli = Path(directory) / "fake sigrok-cli"
            cli.write_text("#!/bin/sh\nprintf '%s\\n' \"$1\"\n", encoding="utf-8")
            cli.chmod(cli.stat().st_mode | stat.S_IXUSR)
            result = slogic.execute(cli, ["argument with spaces"], capture=True)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "argument with spaces\n")


class ForwardArgsTests(unittest.TestCase):
    def test_extracts_sigrok_cli_option(self):
        self.assertEqual(slogic.split_args(["--sigrok-cli", "/x", "--scan"]), ("/x", ["--scan"]))

    def test_extracts_equals_form(self):
        self.assertEqual(slogic.split_args(["--sigrok-cli=/x", "-L"]), ("/x", ["-L"]))

    def test_strips_leading_double_dash(self):
        self.assertEqual(slogic.split_args(["--", "--version"]), (None, ["--version"]))

    def test_forwards_help_unchanged(self):
        # --help must reach sigrok-cli, not the wrapper
        self.assertEqual(slogic.split_args(["--help"]), (None, ["--help"]))

    def test_sigrok_cli_then_double_dash(self):
        self.assertEqual(
            slogic.split_args(["--sigrok-cli", "/x", "--", "--scan"]), ("/x", ["--scan"])
        )

    def test_missing_path_errors(self):
        with self.assertRaises(SystemExit):
            slogic.split_args(["--sigrok-cli"])


if __name__ == "__main__":
    unittest.main()
