#!/usr/bin/env python3
"""Read-only facts about this computer, for the desk-ops skill.

Every subcommand only reads. Nothing here kills, unloads, deletes, installs
or changes a setting: changes are the agent's, after the developer approved
them, and `check` is how a pipeline verifies one took effect.

    deskops.py snapshot
    deskops.py disk [--path P] [--top N]
    deskops.py procs [--sort cpu|mem] [--top N]
    deskops.py jobs
    deskops.py updates
    deskops.py security
    deskops.py check <name> [options]      exit 0 = pass, 1 = fail, 2 = error

Output is one JSON object on stdout. Command arguments, environment
variables and crontab command lines are never printed: they are where
tokens end up (a LaunchAgent once carried an API token in its arguments).

macOS first; Linux gets the same shape where a fact has an obvious source
and `"unsupported"` where it does not. Standard library only, Python 3.9+.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

DARWIN = sys.platform == "darwin"
LINUX = sys.platform.startswith("linux")

GB = 1024 ** 3


class Facts:
    """Collects non-fatal errors next to the facts they would have filled."""

    def __init__(self) -> None:
        self.errors: list[str] = []

    def run(self, argv: list[str], timeout: float = 30, ok_codes: tuple = (0,), env: dict | None = None) -> str | None:
        if shutil.which(argv[0]) is None and not os.path.isabs(argv[0]):
            self.errors.append(f"{argv[0]}: not found")
            return None
        if os.path.isabs(argv[0]) and not os.path.exists(argv[0]):
            self.errors.append(f"{argv[0]}: not found")
            return None
        full_env = dict(os.environ, LC_ALL="C", LANG="C")
        if env:
            full_env.update(env)
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=full_env,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            self.errors.append(f"{argv[0]}: timed out after {int(timeout)}s")
            return None
        except OSError as exc:
            self.errors.append(f"{argv[0]}: {exc.strerror}")
            return None
        if proc.returncode not in ok_codes:
            first = (proc.stderr or proc.stdout).strip().splitlines()[:1]
            self.errors.append(f"{argv[0]}: exit {proc.returncode}" + (f": {first[0][:200]}" if first else ""))
            return None
        return proc.stdout


# ---------------------------------------------------------------- parsers
# Pure functions over command output, so tests need no real system.


def parse_df(text: str) -> list[dict]:
    """`df -kP` → local volumes worth reporting."""
    volumes = []
    for line in text.splitlines()[1:]:
        parts = line.split(None, 5)
        if len(parts) < 6 or not parts[1].isdigit():
            continue
        device, total, _, avail, _, mount = parts
        if not device.startswith("/dev/") or device.startswith("/dev/loop"):
            continue
        # macOS: every /System/Volumes/* shares the root container, and
        # /private/var/... are mounted disk images (simulator runtimes).
        if mount.startswith(("/System/Volumes/", "/private/var/", "/Volumes/Recovery", "/boot", "/snap/")):
            continue
        total_b, avail_b = int(total) * 1024, int(avail) * 1024
        volumes.append(
            {
                "mount": mount,
                "total_gb": round(total_b / GB, 1),
                "free_gb": round(avail_b / GB, 1),
                # From free space, not the Used column: an APFS volume's Used
                # counts only itself while the container's space is shared.
                "used_pct": round(100 * (total_b - avail_b) / total_b, 1) if total_b else 0.0,
            }
        )
    return volumes


def parse_ps(text: str) -> list[dict]:
    """`ps -A -o pid=,ppid=,user=,%cpu=,%mem=,rss=,etime=,comm=`."""
    procs = []
    for line in text.splitlines():
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        pid, ppid, user, cpu, mem, rss, etime, comm = parts
        try:
            procs.append(
                {
                    "pid": int(pid),
                    "ppid": int(ppid),
                    "user": user,
                    "cpu_pct": float(cpu),
                    "mem_pct": float(mem),
                    "rss_mb": round(int(rss) / 1024, 1),
                    "elapsed": etime,
                    "name": os.path.basename(comm.strip()),
                    "path": comm.strip(),
                }
            )
        except ValueError:
            continue
    return procs


def parse_du(text: str, root: str) -> list[dict]:
    """`du -xk -d 1 <root>` → children of root, largest first."""
    rows = []
    for line in text.splitlines():
        parts = line.split("\t", 1)
        if len(parts) != 2 or not parts[0].isdigit():
            continue
        path = parts[1]
        if os.path.normpath(path) == os.path.normpath(root):
            continue
        rows.append({"path": path, "size_gb": round(int(parts[0]) * 1024 / GB, 2)})
    rows.sort(key=lambda r: r["size_gb"], reverse=True)
    return rows


def du_total(text: str, root: str) -> float | None:
    for line in text.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2 and parts[0].isdigit() and os.path.normpath(parts[1]) == os.path.normpath(root):
            return round(int(parts[0]) * 1024 / GB, 2)
    return None


def split_host_port(addr: str) -> tuple[str, int] | None:
    """Socket address in netstat (`127.0.0.1.443`, `*.22`), lsof (`*:22`,
    `[::1]:80`) or ss (`0.0.0.0:22`, `[::]:22`, `127.0.0.53%lo:53`) form."""
    addr = addr.strip()
    m = re.match(r"^\[?(.*?)\]?[:.](\d+)$", addr)
    if not m:
        return None
    host = m.group(1).split("%", 1)[0]
    return host, int(m.group(2))


def is_loopback(host: str) -> bool:
    return host.startswith("127.") or host in ("::1", "localhost", "0:0:0:0:0:0:0:1")


def parse_netstat_listen(text: str) -> list[dict]:
    """macOS `netstat -an -p tcp` LISTEN rows (all processes, no names)."""
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 6 or parts[-1] != "LISTEN" or not parts[0].startswith("tcp"):
            continue
        hp = split_host_port(parts[3])
        if hp:
            out.append({"address": hp[0], "port": hp[1]})
    return out


def parse_lsof_listen(text: str) -> dict[int, str]:
    """`lsof -nP -iTCP -sTCP:LISTEN -F pcn` → port → process name (only the
    processes the current user can see)."""
    names: dict[int, str] = {}
    command = ""
    for line in text.splitlines():
        if line.startswith("c"):
            command = line[1:]
        elif line.startswith("n"):
            hp = split_host_port(line[1:])
            if hp and command:
                names.setdefault(hp[1], command)
    return names


def parse_ss_listen(text: str) -> list[dict]:
    """Linux `ss -ltnpH`."""
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        hp = split_host_port(parts[3])
        if not hp:
            continue
        m = re.search(r'users:\(\("([^"]+)"', line)
        out.append({"address": hp[0], "port": hp[1], "process": m.group(1) if m else None})
    return out


def merge_listeners(rows: list[dict], names: dict[int, str]) -> list[dict]:
    seen = set()
    merged = []
    for row in rows:
        key = (row["address"], row["port"])
        if key in seen:
            continue
        seen.add(key)
        host = row["address"]
        merged.append(
            {
                "address": host,
                "port": row["port"],
                "process": row.get("process") or names.get(row["port"]),
                "exposed": not is_loopback(host),
            }
        )
    merged.sort(key=lambda r: (not r["exposed"], r["port"]))
    return merged


def parse_softwareupdate(text: str) -> list[dict]:
    """`softwareupdate -l`: `* Label: X` followed by a `Title: …, Key: value`
    line."""
    updates: list[dict] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("* Label:"):
            updates.append({"label": stripped[len("* Label:"):].strip()})
        elif updates and stripped.startswith("Title:"):
            for field in stripped.rstrip(",").split(", "):
                if ": " in field:
                    k, v = field.split(": ", 1)
                    updates[-1][k.strip().lower()] = v.strip()
    for u in updates:
        u["restart"] = u.get("action", "").lower() == "restart"
        u["recommended"] = u.get("recommended", "").upper() == "YES"
    return updates


def parse_brew_outdated(text: str) -> list[dict]:
    data = json.loads(text)
    out = []
    for kind in ("formulae", "casks"):
        for item in data.get(kind, []):
            out.append(
                {
                    "kind": "formula" if kind == "formulae" else "cask",
                    "name": item.get("name"),
                    "installed": (item.get("installed_versions") or [None])[-1],
                    "latest": item.get("current_version"),
                    "pinned": bool(item.get("pinned")),
                }
            )
    return out


def parse_launchctl_list(text: str) -> dict[str, dict]:
    """`launchctl list`: PID, last exit status, label."""
    loaded = {}
    for line in text.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        pid, status, label = parts
        loaded[label] = {
            "pid": int(pid) if pid.isdigit() else None,
            "last_exit": int(status) if status.lstrip("-").isdigit() else None,
        }
    return loaded


def describe_plist(data: dict) -> dict:
    """The parts of a launchd job worth showing. Never the arguments after
    argv[0] and never EnvironmentVariables."""
    args = data.get("ProgramArguments") or []
    program = data.get("Program") or (args[0] if args else None)
    schedule = []
    if data.get("RunAtLoad"):
        schedule.append("at load")
    if data.get("KeepAlive"):
        schedule.append("kept alive")
    if "StartInterval" in data:
        schedule.append(f"every {data['StartInterval']}s")
    cal = data.get("StartCalendarInterval")
    if cal:
        for entry in cal if isinstance(cal, list) else [cal]:
            schedule.append("calendar " + ",".join(f"{k}={v}" for k, v in sorted(entry.items())))
    if data.get("WatchPaths"):
        schedule.append("on path change")
    return {
        "label": data.get("Label"),
        "program": program,
        "args_count": max(len(args) - 1, 0),
        "schedule": schedule,
        "disabled": bool(data.get("Disabled")),
    }


def parse_crontab(text: str) -> list[dict]:
    """User crontab: the schedule and the program, not the command line."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", line):
            continue
        parts = line.split()
        if parts[0].startswith("@"):
            schedule, rest = parts[0], parts[1:]
        else:
            schedule, rest = " ".join(parts[:5]), parts[5:]
        rows.append({"schedule": schedule, "program": rest[0] if rest else None, "args_count": max(len(rest) - 1, 0)})
    return rows


def security_findings(f: dict) -> list[dict]:
    """Fixed rules over the security facts. No guessing: an unknown fact
    yields no finding."""
    out = []

    def add(fid: str, severity: str, fact: str) -> None:
        out.append({"id": fid, "severity": severity, "fact": fact})

    if f.get("filevault") is False:
        add("filevault_off", "high", "FileVault is off: the disk is readable by anyone holding the machine.")
    if f.get("sip") is False:
        add("sip_off", "high", "System Integrity Protection is disabled.")
    if f.get("gatekeeper") is False:
        add("gatekeeper_off", "high", "Gatekeeper assessments are disabled.")
    if f.get("firewall") is False:
        add("firewall_off", "medium", "The application firewall is off.")
    if f.get("auto_check_updates") is False:
        add("auto_update_check_off", "low", "Automatic checking for software updates is off.")
    risky = {22: "remote login (ssh)", 445: "file sharing (smb)", 548: "file sharing (afp)", 3283: "remote management", 5900: "screen sharing (vnc)"}
    for lst in f.get("listeners", []):
        if lst["exposed"] and lst["port"] in risky:
            add(f"exposed_{lst['port']}", "medium", f"{risky[lst['port']]} listens on {lst['address'] or '*'}:{lst['port']}.")
    for lst in f.get("listeners", []):
        if lst["exposed"] and lst["port"] not in risky:
            add(f"exposed_{lst['port']}", "info", f"{lst.get('process') or 'a process'} listens on {lst['address'] or '*'}:{lst['port']} (reachable from the network).")
    return out


# ---------------------------------------------------------------- collectors


def collect_volumes(fx: Facts) -> list[dict]:
    text = fx.run(["df", "-kP"], timeout=15)
    return parse_df(text) if text else []


def collect_procs(fx: Facts) -> list[dict]:
    text = fx.run(["ps", "-A", "-o", "pid=,ppid=,user=,%cpu=,%mem=,rss=,etime=,comm="], timeout=15)
    if not text:
        return []
    me = os.getpid()
    return [p for p in parse_ps(text) if p["pid"] != me]


def collect_listeners(fx: Facts) -> list[dict]:
    if DARWIN:
        rows = parse_netstat_listen(fx.run(["netstat", "-an", "-p", "tcp"], timeout=15) or "")
        names = parse_lsof_listen(fx.run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-F", "pcn"], timeout=20, ok_codes=(0, 1)) or "")
        return merge_listeners(rows, names)
    if LINUX:
        return merge_listeners(parse_ss_listen(fx.run(["ss", "-ltnpH"], timeout=15) or ""), {})
    return []


def collect_memory(fx: Facts) -> dict:
    mem: dict = {}
    if DARWIN:
        total = fx.run(["sysctl", "-n", "hw.memsize"], timeout=5)
        if total and total.strip().isdigit():
            mem["total_gb"] = round(int(total) / GB, 1)
        pressure = fx.run(["memory_pressure", "-Q"], timeout=10)
        m = re.search(r"free percentage:\s*(\d+)%", pressure or "")
        if m:
            mem["free_pct"] = int(m.group(1))
        swap = fx.run(["sysctl", "-n", "vm.swapusage"], timeout=5)
        m = re.search(r"total = ([\d.]+)M\s+used = ([\d.]+)M", swap or "")
        if m:
            mem["swap_total_gb"] = round(float(m.group(1)) / 1024, 1)
            mem["swap_used_gb"] = round(float(m.group(2)) / 1024, 1)
    elif LINUX:
        info = {}
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                k, v = line.split(":", 1)
                info[k] = int(v.split()[0]) * 1024
        except OSError as exc:
            fx.errors.append(f"/proc/meminfo: {exc.strerror}")
        if "MemTotal" in info:
            mem["total_gb"] = round(info["MemTotal"] / GB, 1)
            mem["free_pct"] = round(100 * info.get("MemAvailable", 0) / info["MemTotal"])
            mem["swap_total_gb"] = round(info.get("SwapTotal", 0) / GB, 1)
            mem["swap_used_gb"] = round((info.get("SwapTotal", 0) - info.get("SwapFree", 0)) / GB, 1)
    return mem


def collect_snapshot(fx: Facts) -> dict:
    snap: dict = {"host": os.uname().nodename, "os": os.uname().sysname, "cpus": os.cpu_count()}
    if DARWIN:
        ver = fx.run(["sw_vers", "-productVersion"], timeout=5)
        if ver:
            snap["os"] = "macOS " + ver.strip()
        boot = fx.run(["sysctl", "-n", "kern.boottime"], timeout=5)
        m = re.search(r"sec = (\d+)", boot or "")
        if m:
            snap["uptime_hours"] = round((time.time() - int(m.group(1))) / 3600, 1)
        batt = fx.run(["pmset", "-g", "batt"], timeout=5)
        if batt:
            m = re.search(r"drawing from '([^']+)'", batt)
            pct = re.search(r"(\d+)%", batt)
            snap["power"] = {"source": m.group(1) if m else None, "battery_pct": int(pct.group(1)) if pct else None}
    elif LINUX:
        try:
            snap["uptime_hours"] = round(float(Path("/proc/uptime").read_text().split()[0]) / 3600, 1)
            rel = dict(
                line.split("=", 1) for line in Path("/etc/os-release").read_text().splitlines() if "=" in line
            )
            snap["os"] = rel.get("PRETTY_NAME", "Linux").strip('"')
        except OSError as exc:
            fx.errors.append(f"/proc: {exc.strerror}")
    try:
        snap["load"] = [round(x, 2) for x in os.getloadavg()]
    except OSError:
        pass
    snap["memory"] = collect_memory(fx)
    snap["volumes"] = collect_volumes(fx)
    procs = collect_procs(fx)
    snap["top_cpu"] = [slim(p) for p in sorted(procs, key=lambda p: p["cpu_pct"], reverse=True)[:5]]
    snap["top_mem"] = [slim(p) for p in sorted(procs, key=lambda p: p["rss_mb"], reverse=True)[:5]]
    snap["process_count"] = len(procs)
    return snap


def slim(p: dict) -> dict:
    return {k: p[k] for k in ("pid", "name", "user", "cpu_pct", "rss_mb", "elapsed")}


def launchd_dirs() -> list[tuple[str, Path]]:
    return [
        ("user_agent", Path.home() / "Library/LaunchAgents"),
        ("agent", Path("/Library/LaunchAgents")),
        ("daemon", Path("/Library/LaunchDaemons")),
    ]


def collect_launchd(fx: Facts) -> list[dict]:
    loaded = parse_launchctl_list(fx.run(["launchctl", "list"], timeout=10) or "")
    jobs = []
    for scope, folder in launchd_dirs():
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.plist")):
            try:
                with path.open("rb") as fh:
                    data = plistlib.load(fh)
            except Exception as exc:  # noqa: BLE001 - a broken plist is a fact to report
                fx.errors.append(f"{path}: unreadable ({type(exc).__name__})")
                continue
            job = describe_plist(data)
            job["scope"] = scope
            job["file"] = str(path)
            # The user's launchctl list sees only its own domain.
            job["loaded"] = (job["label"] in loaded) if scope == "user_agent" else None
            if job["loaded"]:
                job.update(loaded[job["label"]])
            jobs.append(job)
    return jobs


def collect_jobs(fx: Facts) -> dict:
    out: dict = {}
    if DARWIN:
        out["launchd"] = collect_launchd(fx)
    elif LINUX:
        timers = fx.run(["systemctl", "list-timers", "--all", "--no-pager", "--plain", "--no-legend"], timeout=10)
        out["systemd_timers"] = [line.split()[-2:] for line in (timers or "").splitlines() if line.strip()]
    crontab = fx.run(["crontab", "-l"], timeout=5, ok_codes=(0, 1))
    out["crontab"] = parse_crontab(crontab or "")
    if shutil.which("tars"):
        text = fx.run(["tars", "cron", "list"], timeout=15)
        if text is not None:
            try:
                out["tars_cron"] = json.loads(text)
            except ValueError:
                out["tars_cron"] = text[:4000]
    return out


def collect_updates(fx: Facts) -> dict:
    out: dict = {}
    if DARWIN:
        text = fx.run(["softwareupdate", "-l"], timeout=180)
        if text is not None:
            out["macos"] = parse_softwareupdate(text)
    elif LINUX and shutil.which("apt"):
        text = fx.run(["apt", "list", "--upgradable"], timeout=60)
        out["apt"] = [line.split("/", 1)[0] for line in (text or "").splitlines() if "/" in line]
    if shutil.which("brew"):
        text = fx.run(["brew", "outdated", "--json=v2"], timeout=180, env={"HOMEBREW_NO_AUTO_UPDATE": "1"})
        if text:
            try:
                out["brew"] = parse_brew_outdated(text)
            except ValueError:
                fx.errors.append("brew outdated: unreadable JSON")
    if shutil.which("tars"):
        text = fx.run(["tars", "update", "--check", "--json"], timeout=60)
        if text:
            try:
                out["tars"] = json.loads(text)
            except ValueError:
                out["tars"] = text.strip()[:500]
    return out


def collect_security(fx: Facts) -> dict:
    f: dict = {}
    if DARWIN:
        fw = fx.run(["/usr/libexec/ApplicationFirewall/socketfilterfw", "--getglobalstate"], timeout=10)
        if fw:
            f["firewall"] = "enabled" in fw.lower() or "state = 1" in fw.lower()
        stealth = fx.run(["/usr/libexec/ApplicationFirewall/socketfilterfw", "--getstealthmode"], timeout=10)
        if stealth:
            f["stealth_mode"] = bool(re.search(r"\b(on|enabled)\b", stealth.lower()))
        fv = fx.run(["fdesetup", "status"], timeout=10)
        if fv:
            f["filevault"] = "filevault is on" in fv.lower()
        sip = fx.run(["csrutil", "status"], timeout=10)
        if sip:
            f["sip"] = "status: enabled" in sip.lower()
        gk = fx.run(["spctl", "--status"], timeout=10)
        if gk:
            f["gatekeeper"] = "assessments enabled" in gk.lower()
        prefs = "/Library/Preferences/com.apple.SoftwareUpdate"
        for key, name in (
            ("AutomaticCheckEnabled", "auto_check_updates"),
            ("AutomaticallyInstallMacOSUpdates", "auto_install_macos"),
            ("CriticalUpdateInstall", "auto_install_security"),
        ):
            val = fx.run(["defaults", "read", prefs, key], timeout=5, ok_codes=(0, 1))
            if val and val.strip() in ("0", "1"):
                f[name] = val.strip() == "1"
    elif LINUX:
        if shutil.which("ufw"):
            out = fx.run(["ufw", "status"], timeout=10)
            if out:
                f["firewall"] = "status: active" in out.lower()
    f["listeners"] = collect_listeners(fx)
    f["findings"] = security_findings(f)
    return f


def collect_disk(fx: Facts, path: str, top: int) -> dict:
    root = os.path.expanduser(path)
    text = fx.run(["du", "-xk", "-d", "1", root], timeout=120, ok_codes=(0, 1))
    files = []
    try:
        with os.scandir(root) as it:
            for entry in it:
                if entry.is_file(follow_symlinks=False):
                    files.append({"path": entry.path, "size_gb": round(entry.stat(follow_symlinks=False).st_size / GB, 2)})
    except OSError as exc:
        fx.errors.append(f"{root}: {exc.strerror}")
    files.sort(key=lambda r: r["size_gb"], reverse=True)
    return {
        "path": root,
        "total_gb": du_total(text or "", root),
        "folders": parse_du(text or "", root)[:top],
        "files": files[:top],
    }


# ---------------------------------------------------------------- checks


def check_disk_free(fx: Facts, a) -> tuple[bool, str]:
    st = shutil.disk_usage(os.path.expanduser(a.path))
    free = st.free / GB
    return free >= a.min_gb, f"{free:.1f} GB free on {a.path} (need {a.min_gb})"


def _named(fx: Facts, name: str) -> list[dict]:
    return [p for p in collect_procs(fx) if p["name"] == name]


def check_process_absent(fx: Facts, a) -> tuple[bool, str]:
    found = _named(fx, a.name)
    return not found, f"{len(found)} process(es) named {a.name}"


def check_process_present(fx: Facts, a) -> tuple[bool, str]:
    found = _named(fx, a.name)
    return bool(found), f"{len(found)} process(es) named {a.name}"


def check_port_closed(fx: Facts, a) -> tuple[bool, str]:
    hits = [l for l in collect_listeners(fx) if l["port"] == a.port and (l["exposed"] or not a.exposed_only)]
    where = ", ".join(f"{l['address'] or '*'}:{l['port']}" for l in hits)
    return not hits, (f"listening on {where}" if hits else f"nothing listens on port {a.port}")


def check_port_open(fx: Facts, a) -> tuple[bool, str]:
    closed, detail = check_port_closed(fx, a)
    return not closed, detail


def _job(fx: Facts, label: str) -> list[dict]:
    if not DARWIN:
        raise SystemExit(_fail_usage("job checks need macOS launchd"))
    return [j for j in collect_launchd(fx) if j["label"] == label]


def check_job_absent(fx: Facts, a) -> tuple[bool, str]:
    jobs = _job(fx, a.label)
    loaded = [j for j in jobs if j.get("loaded")]
    return not jobs and not loaded, f"{len(jobs)} plist(s) for {a.label}, {len(loaded)} loaded"


def check_job_loaded(fx: Facts, a) -> tuple[bool, str]:
    jobs = [j for j in _job(fx, a.label) if j.get("loaded")]
    return bool(jobs), f"{a.label} {'is' if jobs else 'is not'} loaded"


def check_path_absent(fx: Facts, a) -> tuple[bool, str]:
    p = os.path.expanduser(a.path)
    return not os.path.lexists(p), f"{p} {'exists' if os.path.lexists(p) else 'is gone'}"


def _security_flag(fx: Facts, key: str, label: str) -> tuple[bool, str]:
    val = collect_security(fx).get(key)
    if val is None:
        raise SystemExit(_fail_usage(f"could not read {label} on this system"))
    return bool(val), f"{label} is {'on' if val else 'off'}"


def check_firewall_on(fx: Facts, a) -> tuple[bool, str]:
    return _security_flag(fx, "firewall", "the firewall")


def check_filevault_on(fx: Facts, a) -> tuple[bool, str]:
    return _security_flag(fx, "filevault", "FileVault")


def check_brew_current(fx: Facts, a) -> tuple[bool, str]:
    text = fx.run(["brew", "outdated", "--json=v2"], timeout=180, env={"HOMEBREW_NO_AUTO_UPDATE": "1"})
    if text is None:
        raise SystemExit(_fail_usage("brew outdated did not run"))
    stale = [p for p in parse_brew_outdated(text) if not p["pinned"] and (not a.name or p["name"] == a.name)]
    names = ", ".join(p["name"] for p in stale[:10])
    return not stale, (f"outdated: {names}" if stale else "nothing outdated")


CHECKS = {
    "disk-free": (check_disk_free, [("--path", {"default": "/"}), ("--min-gb", {"type": float, "required": True})]),
    "process-absent": (check_process_absent, [("--name", {"required": True})]),
    "process-present": (check_process_present, [("--name", {"required": True})]),
    "port-closed": (check_port_closed, [("--port", {"type": int, "required": True}), ("--exposed-only", {"action": "store_true"})]),
    "port-open": (check_port_open, [("--port", {"type": int, "required": True}), ("--exposed-only", {"action": "store_true"})]),
    "job-absent": (check_job_absent, [("--label", {"required": True})]),
    "job-loaded": (check_job_loaded, [("--label", {"required": True})]),
    "path-absent": (check_path_absent, [("--path", {"required": True})]),
    "firewall-on": (check_firewall_on, []),
    "filevault-on": (check_filevault_on, []),
    "brew-current": (check_brew_current, [("--name", {"default": ""})]),
}


def _fail_usage(msg: str) -> int:
    print(json.dumps({"ok": False, "error": msg}))
    return 2


# ---------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="deskops.py", description="Read-only facts about this computer.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("snapshot", help="OS, uptime, load, memory, volumes, top processes")
    d = sub.add_parser("disk", help="largest folders under a path")
    d.add_argument("--path", default="~")
    d.add_argument("--top", type=int, default=15)
    pr = sub.add_parser("procs", help="processes by CPU or memory")
    pr.add_argument("--sort", choices=("cpu", "mem"), default="cpu")
    pr.add_argument("--top", type=int, default=20)
    sub.add_parser("jobs", help="launchd jobs, crontab, TARS cron")
    sub.add_parser("updates", help="pending OS, Homebrew and TARS updates")
    sub.add_parser("security", help="firewall, FileVault, SIP, Gatekeeper, listening ports, findings")
    c = sub.add_parser("check", help="exit 0 when a condition holds (for verify commands)")
    csub = c.add_subparsers(dest="check", required=True)
    for name, (_, opts) in CHECKS.items():
        cp = csub.add_parser(name)
        for flag, kw in opts:
            cp.add_argument(flag, **kw)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not (DARWIN or LINUX):
        return _fail_usage(f"unsupported platform: {sys.platform}")
    fx = Facts()
    if args.cmd == "check":
        fn, _ = CHECKS[args.check]
        try:
            passed, detail = fn(fx, args)
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 2
        print(json.dumps({"check": args.check, "pass": passed, "detail": detail, "errors": fx.errors}))
        return 0 if passed else 1
    if args.cmd == "snapshot":
        data = collect_snapshot(fx)
    elif args.cmd == "disk":
        data = collect_disk(fx, args.path, max(1, min(args.top, 100)))
    elif args.cmd == "procs":
        key = "cpu_pct" if args.sort == "cpu" else "rss_mb"
        procs = sorted(collect_procs(fx), key=lambda p: p[key], reverse=True)
        data = {"sort": args.sort, "processes": [dict(slim(p), ppid=p["ppid"], path=p["path"]) for p in procs[: max(1, min(args.top, 200))]]}
    elif args.cmd == "jobs":
        data = collect_jobs(fx)
    elif args.cmd == "updates":
        data = collect_updates(fx)
    else:
        data = collect_security(fx)
    print(json.dumps({"ok": True, "platform": sys.platform, args.cmd: data, "errors": fx.errors}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
