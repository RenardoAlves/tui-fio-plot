#!/usr/bin/env python3
"""
FIO Plot Automation - Interactive Console Application
Generates charts from FIO benchmark results selected as FILES (single or multiple),
reusing the fio-plot library's rendering pipeline.

The user selects file(s); each file is staged into its own temporary directory
(because fio-plot internally works on directories). Charts are saved as PNG
and opened automatically.
"""

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
)


RWMODES = ["read", "write", "randread", "randwrite", "randrw", "trim"]
VALID_TYPES = ["bw", "iops", "lat", "slat", "clat"]

TMP_ROOT = tempfile.mkdtemp(prefix="fio_plot_automacao_")


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def pause():
    input("\n  Press Enter to continue...")


def select_file(title="Select a file", filetypes=None):
    """Open a dialog to select a single file."""
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    path = filedialog.askopenfilename(
        title=title,
        filetypes=filetypes or [("All files", "*.*")],
    )
    root.destroy()
    return path if path else None


def select_files(title="Select files", filetypes=None):
    """Open a dialog to select one or more files."""
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    paths = filedialog.askopenfilenames(
        title=title,
        filetypes=filetypes or [("All files", "*.*")],
    )
    root.destroy()
    return list(paths)


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


def stage_json_files(filepaths):
    """Copy each selected JSON into its own temp directory.
    Returns a list of input_directory paths (one per file)."""
    dirs = []
    for i, fp in enumerate(filepaths):
        d = os.path.join(TMP_ROOT, f"run_{i}")
        os.makedirs(d, exist_ok=True)
        shutil.copy2(fp, os.path.join(d, os.path.basename(fp)))
        dirs.append(d)
    return dirs


def detect_workload(filepath):
    """Extract rw / iodepth / numjobs from a fio JSON file so the user
    does not have to guess values (a mismatch triggers fio-plot's
    'Could not find any (matching) JSON files' error)."""
    with open(filepath, encoding="utf-8") as fh:
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


def stage_log_file(filepath):
    """Copy a selected log file into a single temp directory."""
    d = os.path.join(TMP_ROOT, "log_run")
    os.makedirs(d, exist_ok=True)
    shutil.copy2(filepath, os.path.join(d, os.path.basename(filepath)))
    return d


def gather_rw_filter(settings):
    print("\n  Data mode (--rw):")
    for i, mode in enumerate(RWMODES, 1):
        print(f"  [{i}] {mode}")
    choice = ask("  Choose the mode matching your benchmark:",
                 [str(i) for i in range(1, len(RWMODES) + 1)])
    settings["rw"] = RWMODES[int(choice) - 1]

    if settings["rw"] in ("randrw", "rw", "readwrite"):
        print("\n  Filter (read/write) for randrw/rw data:")
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
# 1) 2D Chart - Compare Benchmark Results (multiple JSON files)
# ========================

def chart_compare(settings):
    print("\n  COMPARE BENCHMARK RESULTS (2D Bar Chart)")
    print("  Select MULTIPLE JSON files (one benchmark run each) to compare.\n")

    filetypes = [("JSON files", "*.json"), ("All files", "*.*")]
    files = select_files("Select benchmark JSON files (one per run)", filetypes)

    if not files:
        print("\n  No file selected.")
        return
    if len(files) < 2:
        print("\n  [!] Need at least two files to compare.")
        return

    for f in files:
        print(f"  - {f}")

    settings["input_directory"] = stage_json_files(files)

    workloads = [detect_workload(f) for f in files]
    rws = {w["rw"] for w in workloads}
    iodepths = {int(w["iodepth"]) for w in workloads if w["iodepth"]}
    numjobs = {int(w["numjobs"]) for w in workloads if w["numjobs"]}

    if len(rws) == 1 and len(iodepths) == 1 and len(numjobs) == 1:
        settings["rw"] = rws.pop()
        settings["iodepth"] = [iodepths.pop()]
        settings["numjobs"] = [numjobs.pop()]
        print(f"\n  Auto-detected workload: rw={settings['rw']}, "
              f"iodepth={settings['iodepth'][0]}, numjobs={settings['numjobs'][0]}")
        print("  [1] read\n  [2] write\n  [3] both (default)")
        f = ask("  Filter (read/write) for randrw/rw data:", ["1", "2", "3"], allow_blank=True)
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


# ========================
# 2) Line Chart - FIO Log Data (single log file)
# ========================

def chart_log(settings):
    print("\n  LINE CHART FROM FIO LOG DATA")
    print("  Select a single FIO log file (.log or .csv).\n")

    filetypes = [
        ("Log files", "*.log *.csv"),
        ("All files", "*.*"),
    ]
    filepath = select_file("Select FIO log file", filetypes)
    if not filepath:
        print("\n  No file selected.")
        return

    print(f"  - {filepath}")
    settings["input_directory"] = [stage_log_file(filepath)]
    gather_rw_filter(settings)
    gather_title_source(settings)

    print("\n  Type of metric to plot (--type):")
    for i, t in enumerate(VALID_TYPES, 1):
        print(f"  [{i}] {t}")
    choice = ask("  Choose metric:", [str(i) for i in range(1, len(VALID_TYPES) + 1)])
    settings["type"] = [VALID_TYPES[int(choice) - 1]]

    gather_iodepth_numjobs(settings, require_both=False)
    if not settings["iodepth"]:
        settings["iodepth"] = [1]
    if not settings["numjobs"]:
        settings["numjobs"] = [1]

    settings["graphtype"] = "loggraph"
    settings["loggraph"] = True

    routing = getdata.get_routing_dict()
    settings = getdata.configure_default_settings(settings, routing, "loggraph")
    data = getdata.get_log_data(settings)
    graph2d.chart_2d_log_data(settings, data)


# ========================
# 3) Latency Histogram (single JSON file)
# ========================

def chart_histogram(settings):
    print("\n  LATENCY HISTOGRAM")
    print("  Select a single FIO JSON file containing latency histogram data.\n")

    filetype = [("JSON files", "*.json"), ("All files", "*.*")]
    filepath = select_file("Select FIO JSON file", filetype)
    if not filepath:
        print("\n  No file selected.")
        return

    print(f"  - {filepath}")
    settings["input_directory"] = stage_json_files([filepath])

    workload = detect_workload(filepath)
    if all(workload.values()):
        settings["rw"] = workload["rw"]
        settings["iodepth"] = [int(workload["iodepth"])]
        settings["numjobs"] = [int(workload["numjobs"])]
        print(f"\n  Auto-detected workload: rw={settings['rw']}, "
              f"iodepth={settings['iodepth'][0]}, numjobs={settings['numjobs'][0]}")
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
        print("   FIO PLOT AUTOMATION  (powered by fio-plot, file-based)")
        print("=" * 52)
        print()
        print("  [1] 2D Chart - Compare Benchmark Results (multiple JSON files)")
        print("  [2] Line Chart - FIO Log Data (single file)")
        print("  [3] Latency Histogram (single JSON file)")
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
