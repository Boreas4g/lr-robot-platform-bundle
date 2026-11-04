"""Exercise deployment isolation with mocked services and no hardware access."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest


SCRIPTS = Path(__file__).resolve().parent
MUTATING_SCRIPTS = (
    "start-local.sh", "start-all-local.sh", "start-bookarm-fake.sh",
    "start-vehicle-local.sh", "stop-vehicle-local.sh", "stop-local.sh",
)
MANAGED_UNITS = (
    "lr-robot-runtime.service", "lr-control-api.service",
    "lr-robot-mapping-agent.service", "lr-bookarm-takeout.service",
    "lr-platform.service",
)


class DeploymentIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.scripts = self.root / "deploy/local"
        self.scripts.mkdir(parents=True)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.events = self.root / "events"
        self.env = dict(os.environ, PATH=f"{self.bin}:/usr/bin:/bin",
                        TEST_EVENTS=str(self.events), TEST_MANAGED_UNIT="",
                        TEST_HEALTH_OK="1")
        for name in (*MUTATING_SCRIPTS, "desktop-start.sh", "deployment-mode.sh"):
            shutil.copyfile(SCRIPTS / name, self.scripts / name)
        # Reaching env.sh proves that the deployment guard permitted execution.
        (self.scripts / "env.sh").write_text('exit 97\n')
        self.command("systemctl", '''
[ "$1" = cat ] && [ "$2" = "$TEST_MANAGED_UNIT" ]
''')
        self.command("curl", '[ "$TEST_HEALTH_OK" = 1 ]\n')
        self.command("notify-send", 'exit 0\n')
        self.command("xdg-open", 'printf "OPEN %s\\n" "$1" >>"$TEST_EVENTS"\n')

    def command(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\n" + body)
        path.chmod(0o755)

    def run_script(self, name):
        return subprocess.run(["bash", str(self.scripts / name)], env=self.env,
                              capture_output=True, text=True, timeout=5)

    def test_installed_units_block_every_legacy_mutation_before_env(self):
        # cat succeeds for installed inactive units as well as running units.
        for unit in MANAGED_UNITS:
            self.env["TEST_MANAGED_UNIT"] = unit
            for script in MUTATING_SCRIPTS:
                with self.subTest(unit=unit, script=script):
                    result = self.run_script(script)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn(unit, result.stderr)

    def test_unmanaged_hosts_still_reach_local_environment(self):
        for script in MUTATING_SCRIPTS:
            with self.subTest(script=script):
                self.assertEqual(self.run_script(script).returncode, 97)

    def test_managed_desktop_opens_console_without_starting_local_stack(self):
        self.env["TEST_MANAGED_UNIT"] = "lr-robot-runtime.service"
        (self.scripts / "start-all-local.sh").write_text(
            'echo START >>"$TEST_EVENTS"\nexit 97\n')
        result = self.run_script("desktop-start.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        deadline = time.monotonic() + 1
        while not self.events.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.events.read_text(), "OPEN http://localhost:8000/\n")
        self.assertFalse((self.root / ".local-stack").exists())

    def test_unhealthy_managed_desktop_does_not_fall_back_to_local_stack(self):
        self.env.update(TEST_MANAGED_UNIT="lr-control-api.service", TEST_HEALTH_OK="0")
        (self.scripts / "start-all-local.sh").write_text(
            'echo START >>"$TEST_EVENTS"\nexit 97\n')
        self.assertEqual(self.run_script("desktop-start.sh").returncode, 1)
        self.assertFalse(self.events.exists())
        self.assertFalse((self.root / ".local-stack").exists())

    def test_local_stop_preserves_independent_mapping_process_and_dds(self):
        (self.scripts / "env.sh").write_text(f'STACK_RUN={self.root}/run\n')
        self.command("rm", '''
for item in "$@"; do
  case "$item" in /dev/shm/*) echo DDS_DELETE >>"$TEST_EVENTS";; esac
done
''')
        observer = subprocess.Popen(
            ["/usr/bin/python3", "-c", "import time; time.sleep(30)",
             str(self.root / "scripts/mapping_agent.py")])
        try:
            result = self.run_script("stop-vehicle-local.sh")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIsNone(observer.poll(), "independent mapping process was killed")
            self.assertFalse(self.events.exists(), "global DDS cleanup was attempted")
        finally:
            if observer.poll() is None:
                observer.terminate()
            observer.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
