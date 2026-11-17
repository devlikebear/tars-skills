"""Parser and rule tests for deskops.py. No real system is read.

    python3 -m unittest skills/desk-ops/test_deskops.py
"""

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import deskops  # noqa: E402


class ParseDF(unittest.TestCase):
    def test_keeps_local_volumes_and_drops_system_and_images(self):
        text = (
            "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
            "/dev/disk3s1s1 239362496 12000000 25165824 33% /\n"
            "devfs 210 210 0 100% /dev\n"
            "/dev/disk3s5 239362496 180000000 25165824 88% /System/Volumes/Data\n"
            "/dev/disk3s6 239362496 4194304 25165824 15% /System/Volumes/VM\n"
            "/dev/disk5s1 976762584 600000 976162584 1% /Volumes/My Backup\n"
            "/dev/disk7s1 18665472 18100000 524288 98% /private/var/run/com.apple.security.cryptexd/mnt/x\n"
            "/dev/loop3 65536 65536 0 100% /snap/core/1\n"
        )
        vols = deskops.parse_df(text)
        self.assertEqual([v["mount"] for v in vols], ["/", "/Volumes/My Backup"])
        root = vols[0]
        self.assertEqual(root["free_gb"], 24.0)
        # Used comes from free space, not the volume's own Used column.
        self.assertAlmostEqual(root["used_pct"], 89.5, delta=0.1)


class ParsePS(unittest.TestCase):
    def test_names_with_spaces_and_bad_rows(self):
        text = (
            "  427     1 _windowserver  44.9  0.3  58700 05-00:34:26 /System/Library/WindowServer\n"
            "69866 69800 me             14.9  0.6 109568 01-00:48:55 /Applications/Aside.app/Contents/Aside Helper\n"
            "garbage\n"
        )
        procs = deskops.parse_ps(text)
        self.assertEqual(len(procs), 2)
        self.assertEqual(procs[1]["name"], "Aside Helper")
        self.assertEqual(procs[1]["rss_mb"], 107.0)
        self.assertEqual(procs[0]["user"], "_windowserver")


class ParseDU(unittest.TestCase):
    def test_children_sorted_and_total(self):
        text = "1048576\t/x/a\n3145728\t/x/b\n4194304\t/x\n"
        rows = deskops.parse_du(text, "/x")
        self.assertEqual([r["path"] for r in rows], ["/x/b", "/x/a"])
        self.assertEqual(deskops.du_total(text, "/x/"), 4.0)


class Listeners(unittest.TestCase):
    def test_split_host_port_forms(self):
        cases = {
            "127.0.0.1.43180": ("127.0.0.1", 43180),
            "*.22": ("*", 22),
            "*:22": ("*", 22),
            "[::1]:80": ("::1", 80),
            "::1.43180": ("::1", 43180),
            "0.0.0.0:22": ("0.0.0.0", 22),
            "127.0.0.53%lo:53": ("127.0.0.53", 53),
            "[::]:22": ("::", 22),
            "nonsense": None,
        }
        for addr, want in cases.items():
            self.assertEqual(deskops.split_host_port(addr), want, addr)

    def test_netstat_lsof_merge(self):
        netstat = (
            "Active Internet connections (including servers)\n"
            "Proto Recv-Q Send-Q  Local Address          Foreign Address        (state)\n"
            "tcp4       0      0  127.0.0.1.43180        *.*                    LISTEN\n"
            "tcp6       0      0  *.5900                 *.*                    LISTEN\n"
            "tcp4       0      0  *.5900                 *.*                    LISTEN\n"
            "tcp4       0      0  10.0.0.2.51000         1.2.3.4.443            ESTABLISHED\n"
        )
        lsof = "p698\ncrapportd\nf11\nn127.0.0.1:43180\n"
        merged = deskops.merge_listeners(deskops.parse_netstat_listen(netstat), deskops.parse_lsof_listen(lsof))
        self.assertEqual(merged[0], {"address": "*", "port": 5900, "process": None, "exposed": True})
        self.assertEqual(merged[1]["process"], "rapportd")
        self.assertFalse(merged[1]["exposed"])
        self.assertEqual(len(merged), 2)

    def test_ss(self):
        text = (
            'LISTEN 0 4096 127.0.0.53%lo:53 0.0.0.0:* users:(("systemd-resolve",pid=1,fd=14))\n'
            "LISTEN 0 128 0.0.0.0:22 0.0.0.0:*\n"
        )
        rows = deskops.parse_ss_listen(text)
        self.assertEqual(rows[0]["process"], "systemd-resolve")
        self.assertEqual(rows[1], {"address": "0.0.0.0", "port": 22, "process": None})


class SoftwareUpdate(unittest.TestCase):
    def test_labels_and_fields(self):
        text = (
            "Software Update Tool\n\nFinding available software\n"
            "Software Update found the following new or updated software:\n"
            "* Label: macOS Tahoe 26.1-25B78\n"
            "\tTitle: macOS Tahoe 26.1, Version: 26.1, Size: 1234567KiB, Recommended: YES, Action: restart, \n"
            "* Label: Safari26.1\n"
            "\tTitle: Safari, Version: 26.1, Size: 99999KiB, Recommended: YES, \n"
        )
        ups = deskops.parse_softwareupdate(text)
        self.assertEqual(len(ups), 2)
        self.assertTrue(ups[0]["restart"])
        self.assertEqual(ups[0]["version"], "26.1")
        self.assertFalse(ups[1]["restart"])
        self.assertTrue(ups[1]["recommended"])

    def test_none_available(self):
        self.assertEqual(deskops.parse_softwareupdate("Software Update Tool\n\nNo new software available.\n"), [])


class Brew(unittest.TestCase):
    def test_outdated(self):
        text = json.dumps(
            {
                "formulae": [{"name": "git", "installed_versions": ["2.50.0"], "current_version": "2.51.0", "pinned": False}],
                "casks": [{"name": "tars-desktop", "installed_versions": ["0.68.0"], "current_version": "0.69.0"}],
            }
        )
        rows = deskops.parse_brew_outdated(text)
        self.assertEqual(rows[0], {"kind": "formula", "name": "git", "installed": "2.50.0", "latest": "2.51.0", "pinned": False})
        self.assertEqual(rows[1]["kind"], "cask")


class Jobs(unittest.TestCase):
    def test_plist_never_shows_arguments_or_environment(self):
        job = deskops.describe_plist(
            {
                "Label": "com.example.agent",
                "ProgramArguments": ["/usr/local/bin/tool", "--token", "secret-value"],
                "EnvironmentVariables": {"API_KEY": "secret-value"},
                "RunAtLoad": True,
                "StartCalendarInterval": [{"Hour": 3, "Minute": 0}],
            }
        )
        self.assertNotIn("secret-value", json.dumps(job))
        self.assertEqual(job["program"], "/usr/local/bin/tool")
        self.assertEqual(job["args_count"], 2)
        self.assertEqual(job["schedule"], ["at load", "calendar Hour=3,Minute=0"])

    def test_launchctl_list(self):
        text = "PID\tStatus\tLabel\n-\t0\tcom.a\n123\t-9\tcom.b\n"
        loaded = deskops.parse_launchctl_list(text)
        self.assertEqual(loaded["com.a"], {"pid": None, "last_exit": 0})
        self.assertEqual(loaded["com.b"], {"pid": 123, "last_exit": -9})

    def test_crontab_hides_command_line(self):
        text = "# comment\nMAILTO=me\n0 3 * * * /usr/bin/backup --password hunter2\n@reboot /bin/start\n"
        rows = deskops.parse_crontab(text)
        self.assertNotIn("hunter2", json.dumps(rows))
        self.assertEqual(rows[0], {"schedule": "0 3 * * *", "program": "/usr/bin/backup", "args_count": 2})
        self.assertEqual(rows[1]["schedule"], "@reboot")


class Findings(unittest.TestCase):
    def test_rules(self):
        facts = {
            "filevault": False,
            "sip": True,
            "gatekeeper": True,
            "firewall": False,
            "listeners": [
                {"address": "*", "port": 22, "process": None, "exposed": True},
                {"address": "127.0.0.1", "port": 43180, "process": "tars", "exposed": False},
                {"address": "*", "port": 8080, "process": "node", "exposed": True},
            ],
        }
        got = {f["id"]: f["severity"] for f in deskops.security_findings(facts)}
        self.assertEqual(got, {"filevault_off": "high", "firewall_off": "medium", "exposed_22": "medium", "exposed_8080": "info"})

    def test_unknown_facts_make_no_findings(self):
        self.assertEqual(deskops.security_findings({"listeners": []}), [])


class Checks(unittest.TestCase):
    def run_main(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = deskops.main(argv)
        return code, json.loads(buf.getvalue())

    def test_disk_free_pass_and_fail(self):
        usage = mock.Mock(free=30 * deskops.GB)
        with mock.patch.object(deskops.shutil, "disk_usage", return_value=usage):
            code, out = self.run_main(["check", "disk-free", "--path", "/", "--min-gb", "20"])
            self.assertEqual((code, out["pass"]), (0, True))
            code, out = self.run_main(["check", "disk-free", "--path", "/", "--min-gb", "40"])
            self.assertEqual((code, out["pass"]), (1, False))

    def test_port_closed_exposed_only(self):
        listeners = [{"address": "127.0.0.1", "port": 5900, "process": None, "exposed": False}]
        with mock.patch.object(deskops, "collect_listeners", return_value=listeners):
            self.assertEqual(self.run_main(["check", "port-closed", "--port", "5900", "--exposed-only"])[0], 0)
            self.assertEqual(self.run_main(["check", "port-closed", "--port", "5900"])[0], 1)

    def test_process_absent(self):
        procs = [{"pid": 1, "name": "Dropbox"}]
        with mock.patch.object(deskops, "collect_procs", return_value=procs):
            self.assertEqual(self.run_main(["check", "process-absent", "--name", "Dropbox"])[0], 1)
            self.assertEqual(self.run_main(["check", "process-absent", "--name", "Other"])[0], 0)

    def test_unreadable_flag_is_an_error_not_a_pass(self):
        with mock.patch.object(deskops, "collect_security", return_value={}):
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = deskops.main(["check", "firewall-on"])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
