"""Macrobenchmark: acquire UI snapshots from a running emulator with adb.

For each screen the script opens a system Settings page, waits a fixed
settling time, then repeats ``uiautomator dump`` + ``exec-out cat`` and
records the latency of both stages. The first successful dump of each
screen is stored in ``data/snapshots`` as the realistic workload for the
microbenchmark.

Requires a booted emulator or device visible to ``adb``.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
REMOTE_PATH = "/sdcard/window_dump.xml"
SETTINGS_PACKAGE = "com.android.settings"

# Screen id -> Android Settings intent action.
SCREENS = (
    ("settings_main", "android.settings.SETTINGS"),
    ("wifi", "android.settings.WIFI_SETTINGS"),
    ("bluetooth", "android.settings.BLUETOOTH_SETTINGS"),
    ("security", "android.settings.SECURITY_SETTINGS"),
    ("display", "android.settings.DISPLAY_SETTINGS"),
    ("sound", "android.settings.SOUND_SETTINGS"),
    ("date_time", "android.settings.DATE_SETTINGS"),
    ("accessibility", "android.settings.ACCESSIBILITY_SETTINGS"),
)


def adb(serial, *args, timeout=60):
    command = ["adb"] + (["-s", serial] if serial else []) + list(args)
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout)


def timed(serial, *args):
    start = time.perf_counter()
    completed = adb(serial, *args)
    return (time.perf_counter() - start) * 1000.0, completed


def top_activity(serial):
    output = adb(serial, "shell", "dumpsys", "activity", "activities").stdout
    for line in output.splitlines():
        if "topResumedActivity=" in line:
            return line.strip()
    return ""


def device_info(serial):
    props = {}
    for key in ("ro.product.model", "ro.build.version.release",
                "ro.build.version.sdk", "ro.product.cpu.abi"):
        props[key] = adb(serial, "shell", "getprop", key).stdout.strip()
    props["uiautomator_dump"] = "adb shell uiautomator dump " + REMOTE_PATH
    return props


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default=None, help="adb device serial")
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--settle-seconds", type=float, default=3.0)
    parser.add_argument("--snapshots-dir", type=Path, default=ROOT / "data" / "snapshots")
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "macro")
    args = parser.parse_args(argv)

    args.snapshots_dir.mkdir(parents=True, exist_ok=True)
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    seen_digests = {}
    for screen, action in SCREENS:
        for _ in range(3):
            # A fresh Settings task prevents the previous page from being reused.
            adb(args.serial, "shell", "am", "force-stop", SETTINGS_PACKAGE)
            adb(args.serial, "shell", "input", "keyevent", "KEYCODE_HOME")
            adb(args.serial, "shell", "am", "start", "-W", "-a", action)
            time.sleep(args.settle_seconds)
            if SETTINGS_PACKAGE + "/" in top_activity(args.serial):
                break
        else:
            print("skip {}: Settings is not in the foreground".format(screen), file=sys.stderr)
            continue
        saved = False
        for repeat in range(1, args.repeats + 1):
            dump_ms, dump = timed(args.serial, "shell", "uiautomator", "dump", REMOTE_PATH)
            pull_ms, pulled = timed(args.serial, "exec-out", "cat", REMOTE_PATH)
            ok = dump.returncode == 0 and "dumped to" in dump.stdout \
                and pulled.stdout.lstrip().startswith("<?xml") \
                and 'package="{}"'.format(SETTINGS_PACKAGE) in pulled.stdout
            rows.append({
                "screen": screen, "repeat": repeat, "status": "ok" if ok else "error",
                "dump_ms": round(dump_ms, 1), "pull_ms": round(pull_ms, 1),
                "total_ms": round(dump_ms + pull_ms, 1),
                "xml_bytes": len(pulled.stdout.encode("utf-8")) if ok else 0,
            })
            if ok and not saved:
                digest = hashlib.sha256(pulled.stdout.encode("utf-8")).hexdigest()
                if digest in seen_digests:
                    print("WARNING: {} duplicates {}".format(screen, seen_digests[digest]),
                          file=sys.stderr)
                seen_digests[digest] = screen
                (args.snapshots_dir / (screen + ".xml")).write_text(pulled.stdout, encoding="utf-8")
                saved = True
        print("{}: {} repeats".format(screen, args.repeats))

    with (args.output / "dump_latency.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    info = device_info(args.serial)
    info.update({"repeats": args.repeats, "settle_seconds": args.settle_seconds,
                 "captured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    (args.output / "device.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
