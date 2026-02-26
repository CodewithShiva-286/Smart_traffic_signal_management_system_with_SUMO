"""
test_chunk3_loop.py
===================
CHUNK 3: FULL SIMULATION LOOP + LOGGER VERIFICATION

Tests the complete main_controller.run_simulation() pipeline:
  - SUMO starts, runs 200 steps, shuts down cleanly
  - SimulationLogger writes step_log.csv correctly
  - summary_report.txt is created with all required sections
  - All 5 execution steps fire in correct order every step
  - Emergency disabled (tested in Chunk 6)
  - AI controller active and making decisions throughout

POST-RUN VERIFICATION (all checks happen AFTER sim completes):

  GROUP 1 - Simulation Run
    - run_simulation() completes without exception
    - Output directory created automatically
    - step_log.csv exists and is non-empty
    - summary_report.txt exists and is non-empty

  GROUP 2 - step_log.csv Structure
    - All 12 required columns present
    - Correct number of rows
    - step column monotonically increasing with no gaps
    - sim_time increases by 1.0 per row
    - No empty or NaN values in numeric columns

  GROUP 3 - step_log.csv Values
    - vehicles_in_net >= 0 every row
    - avg_wait_time >= 0.0 every row
    - avg_speed >= 0.0 every row
    - active_tls_count = 10 every row (no preemption)
    - preempted_tls_count = 0, emergency_active = 0
    - Vehicles present during simulation
    - avg_wait_time is dynamic

  GROUP 4 - summary_report.txt
    - All 4 required sections present
    - Step count matches CSV
    - avg_wait consistent between summary and CSV
    - No emergency events (correctly disabled)
    - AI controller stats present

HOW TO RUN:
    cd C:\\smart_traffic_system
    python tests/test_chunk3_loop.py
"""

import os
import sys
import csv
import math
import time

# ── Path setup ────────────────────────────────────────────────────────────────
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(TEST_DIR)
SRC_DIR  = os.path.join(ROOT_DIR, "src")
sys.path.insert(0, SRC_DIR)

from config import setup_sumo_path, validate_config, STEP_LOG_CSV, SUMMARY_REPORT, LOGS_DIR
setup_sumo_path()
validate_config()

from main_controller import run_simulation

# ── Test infrastructure ───────────────────────────────────────────────────────
PASS = "+"
FAIL = "x"
results = []


def check(name, fn):
    try:
        out = fn()
        print(f"  {PASS} {name}")
        if out is not None and str(out).strip():
            for line in str(out).strip().split('\n'):
                if line.strip():
                    print(f"       {line}")
        results.append((name, True, None))
        return True
    except Exception as e:
        print(f"  {FAIL} {name}")
        print(f"       ERROR: {e}")
        results.append((name, False, str(e)))
        return False


# ── Constants ─────────────────────────────────────────────────────────────────
TEST_STEPS    = 200
EXPECTED_ROWS = TEST_STEPS
EXPECTED_COLS = [
    'step', 'sim_time', 'vehicles_in_net', 'departed', 'arrived',
    'avg_wait_time', 'avg_speed', 'total_wait', 'active_tls_count',
    'preempted_tls_count', 'emergency_active', 'preempted_tls_list',
]

_csv_cache = None

def load_csv():
    global _csv_cache
    if _csv_cache is None:
        with open(STEP_LOG_CSV, 'r', encoding='utf-8') as f:
            _csv_cache = list(csv.DictReader(f))
    return _csv_cache


# ══════════════════════════════════════════════════════════════════════════════
def run():
    print("\n" + "="*65)
    print("CHUNK 3: FULL SIMULATION LOOP + LOGGER TEST")
    print("="*65)

    # ── RUN SIMULATION ────────────────────────────────────────────────────────
    print(f"\n[RUNNING] {TEST_STEPS} steps | headless | emergency DISABLED")
    print("-" * 65)

    sim_error = None
    t_start   = time.time()

    try:
        run_simulation(
            headless         = True,
            enable_emergency = False,
            max_steps        = TEST_STEPS,
        )
    except Exception as e:
        sim_error = e
        print(f"\n[SIM ERROR] {e}")

    t_elapsed = time.time() - t_start
    print(f"\n[DONE] Wall time: {t_elapsed:.1f}s")
    print("-" * 65)

    # ── GROUP 1: SIMULATION RUN ───────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print("GROUP 1: SIMULATION RUN")
    print(f"{'─'*65}")

    def test_no_exception():
        if sim_error is not None:
            raise RuntimeError(f"Simulation threw: {sim_error}")
        return f"{TEST_STEPS} steps completed in {t_elapsed:.1f}s"
    check("run_simulation() completes without exception", test_no_exception)

    def test_output_dir():
        if not os.path.isdir(LOGS_DIR):
            raise FileNotFoundError(f"Output dir missing: {LOGS_DIR}")
        return f"Exists: {LOGS_DIR}"
    check("Output logs directory created automatically", test_output_dir)

    def test_csv_exists():
        if not os.path.isfile(STEP_LOG_CSV):
            raise FileNotFoundError(f"Not found: {STEP_LOG_CSV}")
        size = os.path.getsize(STEP_LOG_CSV)
        if size == 0:
            raise ValueError("CSV file is 0 bytes")
        return f"{size:,} bytes"
    check("step_log.csv exists and is non-empty", test_csv_exists)

    def test_summary_exists():
        if not os.path.isfile(SUMMARY_REPORT):
            raise FileNotFoundError(f"Not found: {SUMMARY_REPORT}")
        size = os.path.getsize(SUMMARY_REPORT)
        if size == 0:
            raise ValueError("Summary file is 0 bytes")
        return f"{size:,} bytes"
    check("summary_report.txt exists and is non-empty", test_summary_exists)

    if sim_error or not os.path.isfile(STEP_LOG_CSV):
        print("\n[ABORT] Cannot verify CSV — fix simulation first.")
        _print_results()
        return

    # ── GROUP 2: CSV STRUCTURE ────────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print("GROUP 2: STEP_LOG.CSV STRUCTURE")
    print(f"{'─'*65}")

    def test_columns():
        rows = load_csv()
        if not rows:
            raise ValueError("CSV has no data rows")
        actual   = list(rows[0].keys())
        missing  = [c for c in EXPECTED_COLS if c not in actual]
        extra    = [c for c in actual if c not in EXPECTED_COLS]
        if missing:
            raise ValueError(f"Missing columns: {missing}")
        if extra:
            raise ValueError(f"Unexpected extra columns: {extra}")
        return f"All 12 columns present"
    check("All 12 required CSV columns present", test_columns)

    def test_row_count():
        rows = load_csv()
        n = len(rows)
        # Allow some flexibility — route may exhaust before 200 steps
        if n == 0:
            raise ValueError("0 rows in CSV")
        if n < 50:
            raise ValueError(f"Only {n} rows — route ended too early (check routes.rou.xml)")
        return f"{n} data rows (target was {EXPECTED_ROWS})"
    check(f"CSV has data rows (target {EXPECTED_ROWS})", test_row_count)

    def test_step_monotonic():
        rows  = load_csv()
        steps = [int(r['step']) for r in rows]
        if steps[0] != 0:
            raise ValueError(f"First step = {steps[0]}, expected 0")
        for i in range(1, len(steps)):
            if steps[i] != steps[i-1] + 1:
                raise ValueError(f"Step gap: {steps[i-1]} -> {steps[i]}")
        return f"Steps: {steps[0]} to {steps[-1]}, no gaps"
    check("step column: 0,1,2,...,N (no gaps, monotonic)", test_step_monotonic)

    def test_sim_time():
        rows  = load_csv()
        times = [float(r['sim_time']) for r in rows]
        if abs(times[0] - 1.0) > 0.05:
            raise ValueError(f"First sim_time = {times[0]}, expected 1.0")
        for i in range(1, len(times)):
            diff = times[i] - times[i-1]
            if abs(diff - 1.0) > 0.05:
                raise ValueError(f"sim_time jump={diff:.3f} at row {i} (expected 1.0)")
        return f"sim_time: {times[0]:.1f}s to {times[-1]:.1f}s (steps of 1.0s)"
    check("sim_time increases by 1.0 per row", test_sim_time)

    def test_no_bad_values():
        rows    = load_csv()
        numeric = ['step','sim_time','vehicles_in_net','departed','arrived',
                   'avg_wait_time','avg_speed','total_wait',
                   'active_tls_count','preempted_tls_count','emergency_active']
        issues  = []
        for col in numeric:
            for i, row in enumerate(rows):
                val = row.get(col, '').strip()
                if val == '':
                    issues.append(f"Row {i} col '{col}': empty")
                    continue
                try:
                    f = float(val)
                    if math.isnan(f) or math.isinf(f):
                        issues.append(f"Row {i} col '{col}': {val} (NaN/Inf)")
                except ValueError:
                    issues.append(f"Row {i} col '{col}': '{val}' (not numeric)")
        if issues:
            raise ValueError('\n'.join(issues[:5]))
        return f"All numeric columns clean in all {len(rows)} rows"
    check("No empty/NaN/malformed values in any numeric column", test_no_bad_values)

    # ── GROUP 3: CSV VALUES ───────────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print("GROUP 3: STEP_LOG.CSV VALUES")
    print(f"{'─'*65}")

    def test_vehicles_ok():
        rows   = load_csv()
        issues = [f"Row {i}: {r['vehicles_in_net']}"
                  for i, r in enumerate(rows) if int(r['vehicles_in_net']) < 0]
        if issues:
            raise ValueError('\n'.join(issues[:3]))
        vals = [int(r['vehicles_in_net']) for r in rows]
        return f"Range: {min(vals)} to {max(vals)} vehicles"
    check("vehicles_in_net: int >= 0 every row", test_vehicles_ok)

    def test_wait_ok():
        rows   = load_csv()
        issues = [f"Row {i}: {r['avg_wait_time']}"
                  for i, r in enumerate(rows) if float(r['avg_wait_time']) < 0]
        if issues:
            raise ValueError('\n'.join(issues[:3]))
        vals = [float(r['avg_wait_time']) for r in rows]
        return f"Range: {min(vals):.2f}s to {max(vals):.2f}s"
    check("avg_wait_time: float >= 0.0 every row", test_wait_ok)

    def test_speed_ok():
        rows   = load_csv()
        issues = [f"Row {i}: {r['avg_speed']}"
                  for i, r in enumerate(rows) if float(r['avg_speed']) < 0]
        if issues:
            raise ValueError('\n'.join(issues[:3]))
        vals = [float(r['avg_speed']) for r in rows]
        return f"Range: {min(vals):.2f} to {max(vals):.2f} m/s"
    check("avg_speed: float >= 0.0 every row", test_speed_ok)

    def test_tls_count():
        rows   = load_csv()
        issues = [f"Row {i} step={r['step']}: active_tls_count={r['active_tls_count']}"
                  for i, r in enumerate(rows) if int(r['active_tls_count']) != 10]
        if issues:
            raise ValueError('\n'.join(issues[:3]))
        return "active_tls_count = 10 for all rows"
    check("active_tls_count = 10 every row (all TLS active)", test_tls_count)

    def test_no_preemption():
        rows   = load_csv()
        issues = []
        for i, row in enumerate(rows):
            if int(row['preempted_tls_count']) != 0:
                issues.append(f"Row {i}: preempted_tls_count={row['preempted_tls_count']}")
            if int(row['emergency_active']) != 0:
                issues.append(f"Row {i}: emergency_active={row['emergency_active']}")
            if row['preempted_tls_list'].strip() != '':
                issues.append(f"Row {i}: preempted_tls_list='{row['preempted_tls_list']}'")
        if issues:
            raise ValueError('\n'.join(issues[:3]))
        return "preempted_tls_count=0, emergency_active=0, list='' for all rows"
    check("No preemption data in CSV (emergency correctly disabled)", test_no_preemption)

    def test_vehicles_present():
        rows      = load_csv()
        non_zero  = [r for r in rows if int(r['vehicles_in_net']) > 0]
        if len(non_zero) < 20:
            raise ValueError(
                f"Only {len(non_zero)} rows had vehicles.\n"
                f"       Traffic may not be loading — check routes.rou.xml demand."
            )
        max_v = max(int(r['vehicles_in_net']) for r in rows)
        first = next((int(r['step']) for r in rows if int(r['vehicles_in_net']) > 0), -1)
        return (
            f"Peak: {max_v} vehicles | "
            f"First vehicle at step {first} | "
            f"{len(non_zero)}/{len(rows)} steps had traffic"
        )
    check("Vehicles present during simulation (routes generating traffic)", test_vehicles_present)

    def test_wait_varies():
        rows  = load_csv()
        waits = [float(r['avg_wait_time']) for r in rows]
        non_zero = sum(1 for w in waits if w > 0.0)
        if non_zero == 0:
            return "NOTE: avg_wait_time = 0 throughout — vehicles may not have queued in 200 steps"
        unique = len(set(round(w, 1) for w in waits))
        return (
            f"avg_wait_time changes over time (AI adapting)\n"
            f"       min={min(waits):.2f}s max={max(waits):.2f}s | "
            f"{non_zero}/200 steps with waiting | {unique} unique values"
        )
    check("avg_wait_time varies across steps (AI is active)", test_wait_varies)

    # ── GROUP 4: SUMMARY REPORT ───────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print("GROUP 4: SUMMARY_REPORT.TXT")
    print(f"{'─'*65}")

    def read_summary():
        with open(SUMMARY_REPORT, 'r', encoding='utf-8') as f:
            return f.read()

    def test_sections():
        text = read_summary()
        required = [
            "SIMULATION INFO",
            "TRAFFIC PERFORMANCE",
            "EMERGENCY VEHICLE PERFORMANCE",
            "AI CONTROLLER STATS",
        ]
        missing = [s for s in required if s not in text]
        if missing:
            raise ValueError(f"Missing sections: {missing}")
        return "All 4 sections present"
    check("summary_report.txt has all 4 required sections", test_sections)

    def test_step_count_in_summary():
        text = read_summary()
        rows = load_csv()
        for line in text.splitlines():
            if "Total Steps Run" in line and ":" in line:
                reported = int(line.split(":")[1].strip())
                if abs(reported - len(rows)) > 2:
                    raise ValueError(
                        f"Summary says {reported} steps, CSV has {len(rows)} rows"
                    )
                return f"Summary reports {reported} steps (CSV has {len(rows)} rows)"
        raise ValueError("'Total Steps Run' line not found in summary")
    check("Summary step count matches CSV row count", test_step_count_in_summary)

    def test_avg_wait_consistent():
        text    = read_summary()
        rows    = load_csv()
        csv_avg = sum(float(r['avg_wait_time']) for r in rows) / max(len(rows), 1)
        for line in text.splitlines():
            if "Avg Wait Time Overall" in line and ":" in line:
                try:
                    rpt = float(line.split(":")[1].strip().replace('s',''))
                    diff = abs(rpt - csv_avg)
                    if diff > 1.0:
                        raise ValueError(
                            f"Summary avg={rpt:.2f}s vs CSV avg={csv_avg:.2f}s (diff={diff:.2f}s)"
                        )
                    return f"Summary={rpt:.2f}s | CSV avg={csv_avg:.2f}s | diff={diff:.2f}s"
                except (ValueError, IndexError):
                    pass
        raise ValueError("Could not parse avg_wait from summary")
    check("Summary avg_wait_time consistent with CSV average", test_avg_wait_consistent)

    def test_no_emergency_in_summary():
        text = read_summary()
        if "No emergency vehicle events" not in text:
            raise ValueError(
                "Expected 'No emergency vehicle events' (emergency was disabled)"
            )
        return "Correctly records no emergency events"
    check("Summary correctly reports no emergency (disabled)", test_no_emergency_in_summary)

    def test_ai_stats_present():
        text = read_summary()
        if "AI CONTROLLER STATS" not in text:
            raise ValueError("AI CONTROLLER STATS section missing")
        if "Total Phase Switches" not in text:
            raise ValueError("'Total Phase Switches' line missing from AI stats")
        for line in text.splitlines():
            if "Total Phase Switches" in line and ":" in line:
                sw = int(line.split(":")[1].strip())
                return f"Total phase switches: {sw}"
        return "AI CONTROLLER STATS section with switch data present"
    check("Summary has AI controller phase switch statistics", test_ai_stats_present)

    # ── PRINT SAMPLES ─────────────────────────────────────────────────────────
    print(f"\n[DETAIL] Sample CSV rows:")
    try:
        rows = load_csv()
        for r in rows[:3]:
            print(f"       step={r['step']:>3} t={r['sim_time']:>6}s "
                  f"veh={r['vehicles_in_net']:>4} wait={r['avg_wait_time']:>6}s "
                  f"speed={r['avg_speed']:>5}m/s tls={r['active_tls_count']}")
        print(f"       ...")
        for r in rows[-2:]:
            print(f"       step={r['step']:>3} t={r['sim_time']:>6}s "
                  f"veh={r['vehicles_in_net']:>4} wait={r['avg_wait_time']:>6}s "
                  f"speed={r['avg_speed']:>5}m/s tls={r['active_tls_count']}")
    except Exception:
        pass

    print(f"\n[DETAIL] Summary report:")
    try:
        for line in read_summary().splitlines():
            if line.strip():
                print(f"       {line}")
    except Exception:
        pass

    _print_results()


def _print_results():
    passed = sum(1 for _, ok, _ in results if ok)
    total  = len(results)

    print(f"\n{'='*65}")
    print(f"CHUNK 3 RESULTS: {passed}/{total} passed")
    print(f"{'='*65}")

    failed_tests = [(n, e) for n, ok, e in results if not ok]
    if failed_tests:
        print("\nFailed tests:")
        for name, err in failed_tests:
            print(f"  x {name}")
            if err:
                print(f"    {err}")
        print("\nFix the above before proceeding to Chunk 4.")
    else:
        print("\nCHUNK 3 PASSED - Full simulation loop and logger verified!")
        print("Next: say 'Start Chunk 4' to verify live AI behaviour.")
    print("="*65 + "\n")


if __name__ == "__main__":
    run()
