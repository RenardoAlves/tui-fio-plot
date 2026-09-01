#!/usr/bin/env python3
"""
FIO Plot Automation - Interactive Console Application
Generates charts from FIO benchmark results selected as DIRECTORIES.

Each benchmark directory contains one FIO run produced by the tool:
  - resultado.json   -> full fio JSON output (used for compare/histogram/log meta)
  - *.N.log          -> per-job log files (used for the line chart)

The files inside each directory are detected and routed automatically according
to the selected chart option:
  - Compare benchmark results  -> uses each directory's resultado.json
  - Line chart (log data)      -> uses each directory's *.N.log files (auto-renamed)
  - Latency histogram          -> uses each directory's resultado.json

Charts are saved as PNG and opened automatically.
"""

import csv
import json
import os
import shutil
import sys
import tempfile
import tkinter as tk
from tkinter import filedialog

from fio_plot.fiolib import (
    defaultsettings,
    getdata,
    bar2d,
    barhistogram,
    graph2d,
    dataimport,
)


RWMODES = ["read", "write", "randread", "randwrite", "randrw", "trim"]

RESULT_JSON_NAME = "resultado.json"


def _return_folder_name_basename(filename, settings, override=False):
    """Show only the innermost folder name on the chart labels and merge keys.

    fio-plot calls this in two situations:
      - override=True with a *file* path (the merge key for log files);
      - override=False with a *directory* path (chart labels).
    In both cases we want the containing/owning folder's basename so that the
    multiple per-job log files of a run share the same merge key.
    """
    path = os.path.normpath(filename)
    if override or not os.path.isdir(path):
        path = os.path.dirname(path)
    base = os.path.basename(path)
    if not base:
        base = path
    return base

dataimport.return_folder_name = _return_folder_name_basename
VALID_TYPES = ["bw", "iops", "lat", "slat", "clat"]

TMP_ROOT = tempfile.mkdtemp(prefix="fio_plot_automacao_")


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def pause():
    try:
        input("\n  Press Enter to continue...")
    except (ValueError, EOFError):
        print()


def ask(prompt, options, allow_blank=False):
    """Generic textual menu."""
    print(prompt)
    while True:
        raw = input("\n  > ").strip()
        if allow_blank and raw == "":
            return None
        if raw in options:
            return raw
        print(f"  Invalid choice. Enter: {', '.join(options)}")


# ========================
# Directory helpers
# ========================

def find_result_json(directory):
    """Return the path of the FIO JSON result inside a benchmark directory.
    Prefers 'resultado.json', otherwise falls back to the only .json present."""
    if os.path.isdir(directory):
        candidate = os.path.join(directory, RESULT_JSON_NAME)
        if os.path.isfile(candidate):
            return candidate
        jsons = [os.path.join(directory, f) for f in os.listdir(directory)
                 if f.lower().endswith(".json")]
        if len(jsons) == 1:
            return jsons[0]
    return None


def find_log_files(directory):
    """Return a sorted list of FIO log file paths inside a directory."""
    if not os.path.isdir(directory):
        return []
    logs = [os.path.join(directory, f) for f in os.listdir(directory)
            if f.endswith(".log")]
    return sorted(logs)


def detect_workload(json_path):
    """Extract rw / iodepth / numjobs from a fio JSON file."""
    with open(json_path, encoding="utf-8") as fh:
        data = json.load(fh)
    job_options = data["jobs"][0].get("job options", {})
    opts = dict(job_options)
    global_options = data.get("global options", {})
    if isinstance(global_options, dict):
        for k, v in global_options.items():
            opts.setdefault(k, v)
    elif isinstance(global_options, list) and global_options and isinstance(global_options[0], dict):
        for k, v in global_options[0].items():
            opts.setdefault(k, v)
    return {
        "rw": opts.get("rw"),
        "iodepth": opts.get("iodepth"),
        "numjobs": opts.get("numjobs"),
    }


def detect_log_type(log_path):
    """Guess the metric type (bw/iops/lat/clat/slat) from a FIO log filename.
    fio names logs like '<prefix>_<type>.<job>.log', e.g. 'iops_iops.1.log'."""
    base = os.path.basename(log_path)
    stem = base.split(".")[0]
    parts = stem.rsplit("_", 1)
    if len(parts) == 2 and parts[1] in VALID_TYPES:
        return parts[1]
    return None


def detect_log_job_number(log_path):
    """Extract the job number from a FIO log filename like 'iops_iops.2.log'."""
    base = os.path.basename(log_path)
    parts = base.split(".")
    for part in parts[:-1]:
        if part.isdigit():
            return part
    return None


def stage_dir_json(bench_dir):
    """Copy a directory's JSON into its own temp dir for compare/histogram."""
    json_file = find_result_json(bench_dir)
    if not json_file:
        return None
    name = os.path.basename(os.path.normpath(bench_dir)) or "benchmark"
    d = os.path.join(TMP_ROOT, name)
    os.makedirs(d, exist_ok=True)
    shutil.copy2(json_file, os.path.join(d, os.path.basename(json_file)))
    return d


def aggregate_log_file(src, dst, logtype, bin_ms=1000):
    """Rewrite a raw per-event FIO log into a per-interval log that fio-plot
    can plot as real throughput, and that is small/fast to render.

    fio writes iops/bw logs as one line per I/O unless log_avg_msec is set, so
    each line carries a tiny value (e.g. 1). Plotting those directly gives a
    meaningless y-axis (like 4 IOPS). Here we bucket them into fixed windows:

      - iops : value = number of I/Os in the window  -> IOPS for that second
      - bw   : value = summed KB in the window       -> KB/s  for that second
      - lat/clat/slat : value = average latency in the window

    Bins run contiguously from 0 (zero-filled when no events), keeping record
    spacing equal to bin_ms so fio-plot returns the data unchanged.
    """
    bins = {"0": {}, "1": {}}          # rwt -> {bin_ms: [count, sum]}

    with open(src, encoding="utf-8") as fh:
        reader = csv.reader(fh)
        for row in reader:
            try:
                ts_ms = int(row[0])
                value = float(row[1])
                rwt = row[2].strip()
            except (ValueError, IndexError):
                continue
            if rwt not in bins:
                continue
            b = int(ts_ms / bin_ms)
            acc = bins[rwt].setdefault(b, [0, 0.0])  # count, sum
            acc[0] += 1
            acc[1] += value

    if all(not v for v in bins.values()):
        return False

    last_bin = 0
    for rwt in bins:
        if bins[rwt]:
            last_bin = max(last_bin, max(bins[rwt]))

    with open(dst, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        for rwt in ("0", "1"):
            for b in range(last_bin + 1):
                acc = bins[rwt].get(b)
                if acc is None:
                    value = 0
                elif logtype == "iops":
                    value = int(acc[1])          # count of I/Os in the window
                elif logtype == "bw":
                    value = int(acc[1])          # KB transferred in the window
                else:
                    value = int(acc[1] / acc[0]) if acc[0] else 0  # avg latency
                writer.writerow([b * bin_ms, value, rwt, 4096, 0])
    return True


def stage_dir_logs(bench_dir, rw, iodepth, numjobs, logtype):
    """Copy a directory's JSON and its log files into a temp dir, renaming and
    aggregating the logs to fio-plot's expected convention so they are picked
    up automatically:
        <rw>-iodepth-<N>-numjobs-<M>_<type>.<job>.log
    """
    json_file = find_result_json(bench_dir)
    name = os.path.basename(os.path.normpath(bench_dir)) or "benchmark"
    d = os.path.join(TMP_ROOT, name)
    os.makedirs(d, exist_ok=True)
    if json_file:
        shutil.copy2(json_file, os.path.join(d, os.path.basename(json_file)))
    for log in find_log_files(bench_dir):
        job = detect_log_job_number(log)
        newname = f"{rw}-iodepth-{iodepth}-numjobs-{numjobs}_{logtype}"
        if job:
            newname += f".{job}.log"
        else:
            newname += ".log"
        aggregate_log_file(log, os.path.join(d, newname), logtype)
    return d


def browse_directory(title="Select a directory"):
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    path = filedialog.askdirectory(title=title)
    root.destroy()
    return path if path else None


def gather_directories(multi=False, title="Select benchmark directories"):
    """Open the directory browser to select benchmark directories.
    Returns a list of absolute directory paths."""

    def _show_selected():
        if selected:
            print(f"\n  Selected ({len(selected)}):")
            for s in selected:
                print(f"    - {os.path.basename(s)}")

    selected = []

    if multi:
        print(f"\n  {title}")
        print("  Pick a folder in the dialog; you can add more afterwards.\n")
        while True:
            path = browse_directory(title)
            if not path:
                if selected:
                    break
                print("  No directory selected.")
                continue
            path = os.path.abspath(path)
            if path in selected:
                print(f"  [!] Already added: {os.path.basename(path)}")
            else:
                selected.append(path)
                print(f"  Added: {os.path.basename(path)}")
            _show_selected()
            more = input("\n  Add another directory? [y/N] > ").strip().lower()
            if not more or more in ("n", "no", "0"):
                break
            if more not in ("y", "s", "sim", "yes"):
                print("  (treating as 'no')")
                break
    else:
        path = browse_directory(title)
        if path and os.path.isdir(path):
            selected.append(os.path.abspath(path))
            print(f"  Selected: {os.path.basename(path)}")
        else:
            print("  No directory selected.")

    if len(selected) > 1:
        _show_selected()
    return selected


# ========================
# Workload / filter config
# ========================

def gather_rw_filter(settings):
    print("\n  Data mode (--rw):")
    for i, mode in enumerate(RWMODES, 1):
        print(f"  [{i}] {mode}")
    choice = ask("  Choose the mode matching your benchmark:",
                 [str(i) for i in range(1, len(RWMODES) + 1)])
    settings["rw"] = RWMODES[int(choice) - 1]

    if settings["rw"] in ("randrw", "readwrite"):
        print("\n  Filter (read/write) for randrw data:")
        print("  [1] read (default)")
        print("  [2] write")
        f = ask("  Choose filter:", ["1", "2"], allow_blank=True)
        settings["filter"] = ["read"] if f != "2" else ["write"]
    elif settings["rw"] == "rw":
        print("\n  Filter (read/write) for rw data:")
        print("  [1] read")
        print("  [2] write")
        print("  [3] both (default)")
        f = ask("  Choose filter:", ["1", "2", "3"], allow_blank=True)
        if f == "1":
            settings["filter"] = ["read"]
        elif f == "2":
            settings["filter"] = ["write"]
        else:
            settings["filter"] = ["read", "write"]


def gather_title_source(settings):
    title = input("\n  Chart title (enter for default): ").strip()
    settings["title"] = title or "FIO Benchmark Results"
    source = input("  Source/author (enter to skip): ").strip()
    settings["source"] = source or None


def build_base_settings():
    """Return defaults merged with keys fio-plot expects from the CLI."""
    settings = defaultsettings.get_default_settings()
    settings.setdefault("input_directory", [])
    settings.setdefault("title", None)
    settings.setdefault("source", None)
    settings.setdefault("rw", None)
    settings.setdefault("iodepth", None)
    settings.setdefault("numjobs", None)
    settings.setdefault("graphtype", None)
    settings.setdefault("output_filename", None)
    for gt in ["bargraph3d", "bargraph2d_qd", "bargraph2d_nj",
               "histogram", "loggraph", "compare_graph"]:
        settings.setdefault(gt, False)
    return settings


# ========================
# 1) 2D Chart - Compare Benchmark Results (multiple directories)
# ========================

def chart_compare(settings):
    print("\n  COMPARE BENCHMARK RESULTS (2D Bar Chart)")
    print("  Select MULTIPLE benchmark directories to compare (one run each).\n")

    dirs = gather_directories(multi=True, title="Select the benchmark directories to compare")

    if not dirs:
        print("\n  No directory selected.")
        return
    if len(dirs) < 2:
        print("\n  [!] Need at least two directories to compare.")
        return

    staged = {}
    for d in dirs:
        if not find_result_json(d):
            print(f"\n  [!] No FIO JSON found in: {d}")
            return
        staged[d] = stage_dir_json(d)
        print(f"  - {os.path.basename(os.path.normpath(d))}")

    settings["input_directory"] = list(staged.values())

    workloads = [detect_workload(find_result_json(d)) for d in dirs]
    rws = {w["rw"] for w in workloads}
    iodepths = {int(w["iodepth"]) for w in workloads if w["iodepth"]}
    numjobs = {int(w["numjobs"]) for w in workloads if w["numjobs"]}

    if len(rws) == 1 and len(iodepths) == 1 and len(numjobs) == 1:
        settings["rw"] = rws.pop()
        settings["iodepth"] = [iodepths.pop()]
        settings["numjobs"] = [numjobs.pop()]
        print(f"\n  Auto-detected workload: rw={settings['rw']}, "
              f"iodepth={settings['iodepth'][0]}, numjobs={settings['numjobs'][0]}")
        if settings["rw"] in ("randrw", "readwrite"):
            print("  [1] read (default)\n  [2] write")
            f = ask("  Filter (read/write) for randrw data:", ["1", "2"], allow_blank=True)
            settings["filter"] = ["read"] if f != "2" else ["write"]
        else:
            print("  [1] read\n  [2] write\n  [3] both (default)")
            f = ask("  Filter (read/write) for rw data:", ["1", "2", "3"], allow_blank=True)
            if f == "1":
                settings["filter"] = ["read"]
            elif f == "2":
                settings["filter"] = ["write"]
            else:
                settings["filter"] = ["read", "write"]
    else:
        print("\n  [!] Files have different rw/iodepth/numjobs values.")
        gather_rw_filter(settings)
        gather_iodepth_numjobs(settings, require_both=True)

    gather_title_source(settings)

    settings["graphtype"] = "compare_graph"
    settings["compare_graph"] = True

    routing = getdata.get_routing_dict()
    settings = getdata.configure_default_settings(settings, routing, "compare_graph")
    data = getdata.get_json_data(settings)
    bar2d.compchart_2dbarchart_jsonlogdata(settings, data)


def gather_iodepth_numjobs(settings, require_both=True):
    print("\n  fio-plot needs iodepth and numjobs that match your data.")
    if require_both:
        iodepth = ask("  iodepth: ", [str(x) for x in range(1, 129)])
        numjobs = ask("  numjobs: ", [str(x) for x in range(1, 129)])
        settings["iodepth"] = [int(iodepth)]
        settings["numjobs"] = [int(numjobs)]
    else:
        iodepth = ask("  iodepth (enter for default): ", [str(x) for x in range(1, 129)], allow_blank=True)
        numjobs = ask("  numjobs (enter for default): ", [str(x) for x in range(1, 129)], allow_blank=True)
        settings["iodepth"] = [int(iodepth)] if iodepth else None
        settings["numjobs"] = [int(numjobs)] if numjobs else None
    return settings


# ========================
# 2) Line Chart - FIO Log Data (directory with *.N.log files)
# ========================

def chart_log(settings):
    print("\n  LINE CHART FROM FIO LOG DATA")
    print("  Select a benchmark directory containing its *.N.log files.\n")

    dirs = gather_directories(multi=False, title="Select the benchmark directory")
    if not dirs:
        print("\n  No directory selected.")
        return
    bench_dir = dirs[0]

    json_file = find_result_json(bench_dir)
    logs = find_log_files(bench_dir)
    if not logs:
        print(f"\n  [!] No .log files found in: {bench_dir}")
        return
    if not json_file:
        print(f"\n  [!] No FIO JSON found in: {bench_dir} (needed to auto-detect the workload).")
        return

    workload = detect_workload(json_file)
    if not all(workload.values()):
        print("\n  [!] Could not auto-detect rw/iodepth/numjobs from the JSON.")
        gather_rw_filter(settings)
        gather_iodepth_numjobs(settings, require_both=True)
    else:
        settings["rw"] = workload["rw"]
        settings["iodepth"] = [int(workload["iodepth"])]
        settings["numjobs"] = [int(workload["numjobs"])]
        print(f"\n  Auto-detected workload: rw={settings['rw']}, "
              f"iodepth={settings['iodepth'][0]}, numjobs={settings['numjobs'][0]}")

    logtype = detect_log_type(logs[0])
    if not logtype:
        print("\n  Could not detect the metric type from the log filename.")
        print("  Types: " + ", ".join(VALID_TYPES))
        choice = ask("  Choose metric:",
                     [str(i) for i in range(1, len(VALID_TYPES) + 1)])
        logtype = VALID_TYPES[int(choice) - 1]
    settings["type"] = [logtype]
    print(f"  Auto-detected metric type: {logtype}")

    iodepth = settings["iodepth"][0]
    numjobs = settings["numjobs"][0]
    settings["input_directory"] = [stage_dir_logs(bench_dir, settings["rw"], iodepth, numjobs, logtype)]

    if settings["rw"] in ("randrw", "readwrite"):
        settings["filter"] = ["read", "write"]
    else:
        settings["filter"] = ["read", "write"]

    gather_title_source(settings)

    settings["graphtype"] = "loggraph"
    settings["loggraph"] = True

    routing = getdata.get_routing_dict()
    settings = getdata.configure_default_settings(settings, routing, "loggraph")
    data = getdata.get_log_data(settings)
    graph2d.chart_2d_log_data(settings, data)


# ========================
# 3) Latency Histogram (directory with resultado.json)
# ========================

def chart_histogram(settings):
    print("\n  LATENCY HISTOGRAM")
    print("  Select a benchmark directory containing its FIO JSON result.\n")

    dirs = gather_directories(multi=False, title="Select the benchmark directory")
    if not dirs:
        print("\n  No directory selected.")
        return
    bench_dir = dirs[0]

    json_file = find_result_json(bench_dir)
    if not json_file:
        print(f"\n  [!] No FIO JSON found in: {bench_dir}")
        return

    print(f"  - {os.path.basename(os.path.normpath(bench_dir))}")
    settings["input_directory"] = [stage_dir_json(bench_dir)]

    workload = detect_workload(json_file)
    if all(workload.values()):
        settings["rw"] = workload["rw"]
        settings["iodepth"] = [int(workload["iodepth"])]
        settings["numjobs"] = [int(workload["numjobs"])]
        print(f"\n  Auto-detected workload: rw={settings['rw']}, "
              f"iodepth={settings['iodepth'][0]}, numjobs={settings['numjobs'][0]}")
        if settings["rw"] in ("randrw", "readwrite"):
            print("\n  Filter (read/write):")
            print("  [1] read (default)")
            print("  [2] write")
            f = ask("  Choose filter:", ["1", "2"], allow_blank=True)
            settings["filter"] = ["read"] if f != "2" else ["write"]
        else:
            print("\n  Filter (read/write):")
            print("  [1] read")
            print("  [2] write")
            print("  [3] both (default)")
            f = ask("  Choose filter:", ["1", "2", "3"], allow_blank=True)
            if f == "1":
                settings["filter"] = ["read"]
            elif f == "2":
                settings["filter"] = ["write"]
            else:
                settings["filter"] = ["read", "write"]
    else:
        gather_rw_filter(settings)
        gather_iodepth_numjobs(settings, require_both=True)

    gather_title_source(settings)

    settings["graphtype"] = "histogram"
    settings["histogram"] = True

    routing = getdata.get_routing_dict()
    settings = getdata.configure_default_settings(settings, routing, "histogram")
    data = getdata.get_json_data(settings)
    barhistogram.chart_latency_histogram(settings, data)


# ========================
# Output handling
# ========================

def make_output(settings):
    """Ensure output_filename points to an absolute path so we can auto-open it."""
    if not settings.get("output_filename"):
        title = (settings.get("title") or "fio_plot").replace(" ", "-").replace("/", "-")
        settings["output_filename"] = os.path.join(os.getcwd(), f"{title}.png")
    settings["output_filename"] = os.path.abspath(settings["output_filename"])
    return settings


def open_image(settings):
    path = settings.get("output_filename")
    if path and os.path.exists(path):
        print(f"\n  Chart saved to: {path}")
        try:
            if os.name == "nt":
                os.startfile(path)  # noqa: S606
            else:
                import subprocess
                subprocess.Popen(["xdg-open", path])
            print("  Opening chart...")
        except Exception as e:  # noqa: BLE001
            print(f"  Could not auto-open: {e}")
    else:
        print("\n  [!] Could not locate the output file.")


def run_plot(settings, func):
    try:
        settings = make_output(settings)
        func(settings)
        open_image(settings)
    except SystemExit:
        pass
    except Exception as e:  # noqa: BLE001
        print(f"\n  [ERROR] {type(e).__name__}: {e}")
    pause()


# ========================
# Main Menu
# ========================

def main():
    while True:
        clear_screen()
        print("=" * 52)
        print("   FIO PLOT AUTOMATION  (powered by fio-plot, directory-based)")
        print("=" * 52)
        print()
        print("  [1] 2D Chart - Compare Benchmark Results (multiple directories)")
        print("  [2] Line Chart - FIO Log Data (single directory)")
        print("  [3] Latency Histogram (single directory)")
        print()
        print("  [0] Exit")
        print()
        print("=" * 52)

        choice = input("\n  Choose an option > ").strip()

        if choice == "0":
            print("\n  Bye!")
            sys.exit(0)
        elif choice == "1":
            settings = build_base_settings()
            run_plot(settings, chart_compare)
        elif choice == "2":
            settings = build_base_settings()
            run_plot(settings, chart_log)
        elif choice == "3":
            settings = build_base_settings()
            run_plot(settings, chart_histogram)
        else:
            print("\n  Invalid option.")
            pause()


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP_ROOT, ignore_errors=True)
