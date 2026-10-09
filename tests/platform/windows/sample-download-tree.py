"""Independent fast RSS sampling of a real download in the dedicated Win10 VM."""

import argparse
import ctypes
import json
import os
import re
import statistics
import time
from pathlib import Path

import psutil


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=120)
    args = parser.parse_args()
    root = Path(os.environ["USERPROFILE"]) / "AppData/Local/Temp/bilix-171-validation"
    output = args.output.resolve()
    if os.name != "nt" or output.parent != root.resolve():
        raise RuntimeError("Dedicated Windows validation root required")
    if not re.fullmatch(r"native-rss(?:170|171)-[a-z0-9-]+", output.name):
        raise RuntimeError("Unexpected sampler output name")
    target = root / output.name.replace("native-rss", "native-download", 1)
    target_record = json.loads((target / "result.json").read_text(encoding="utf-8"))
    process = psutil.Process(target_record["pid"])
    if not Path(process.exe()).resolve().is_relative_to(root.resolve()):
        raise RuntimeError("Target executable must be inside validation root")
    output.mkdir(exist_ok=False)
    report = {
        "status": "running",
        "target": target.name,
        "pid": process.pid,
        "version": target_record["version"],
        "requested_interval_seconds": 0.002,
        "scope": "one snapshot sums concurrently alive target and recursive children",
        "peak_scope": "observed sample maximum, not the absolute unsampled maximum",
        "samples": [],
    }
    (output / "ready.json").write_text(json.dumps(report), encoding="utf-8")
    deadline = time.perf_counter() + args.seconds
    check_at = 0
    download_finished = None
    ctypes.windll.winmm.timeBeginPeriod(1)
    try:
        while time.perf_counter() < deadline:
            now = time.perf_counter()
            try:
                processes = [process, *process.children(recursive=True)]
            except psutil.Error:
                break
            members = []
            for member in processes:
                try:
                    working = member.memory_info().rss
                    members.append({"pid": member.pid, "name": member.name(), "rss": working})
                except psutil.Error:
                    continue
            report["samples"].append(
                {"seconds": now, "rss": sum(m["rss"] for m in members), "members": members}
            )
            if now >= check_at:
                check_at = now + 0.25
                try:
                    target_record = json.loads((target / "result.json").read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    pass
                download_finished = (target_record.get("real_download") or {}).get("finished")
            if download_finished and now >= download_finished + 0.5:
                break
            time.sleep(0.002)
    finally:
        ctypes.windll.winmm.timeEndPeriod(1)
    report["download"] = target_record.get("real_download")
    download = report["download"] or {}
    scoped = [
        s
        for s in report["samples"]
        if download.get("started", float("inf")) <= s["seconds"] <= download.get("finished", 0)
    ]
    ffmpeg = [s for s in scoped if any(m["name"].lower() == "ffmpeg.exe" for m in s["members"])]
    report["download_samples"] = len(scoped)
    report["ffmpeg_samples"] = len(ffmpeg)
    report["peak_sample"] = max(scoped, key=lambda s: s["rss"]) if scoped else None
    report["ffmpeg_peak_sample"] = max(ffmpeg, key=lambda s: s["rss"]) if ffmpeg else None
    intervals = [
        b["seconds"] - a["seconds"] for a, b in zip(report["samples"], report["samples"][1:])
    ]
    report["actual_interval_median_seconds"] = statistics.median(intervals) if intervals else None
    report["status"] = (
        "passed" if download.get("states") == ["completed"] and scoped and ffmpeg else "failed"
    )
    temporary = output / "result.tmp"
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output / "result.json")


if __name__ == "__main__":
    main()
