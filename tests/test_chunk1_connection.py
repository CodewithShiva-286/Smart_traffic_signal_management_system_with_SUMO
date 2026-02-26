"""
test_chunk1_connection.py
=========================
CHUNK 1 VERIFICATION SCRIPT

Run this first — before any other script.
This script validates that EVERYTHING needed for the project works:

  ✓ SUMO_HOME environment variable is set
  ✓ TraCI can be imported
  ✓ SUMO connects to your config file
  ✓ TLS IDs are discovered
  ✓ Phase states can be read
  ✓ Controlled lanes can be read
  ✓ getAllProgramLogics works
  ✓ Simulation steps advance correctly
  ✓ getNextSwitch works
  ✓ Network data can be collected
  ✓ Clean shutdown

HOW TO RUN:
    cd smart_traffic_system/src
    python ../tests/test_chunk1_connection.py

EXPECTED OUTPUT:
    All checks pass with ✓
    Phase state strings printed for 2-3 TLS
    Step counter increments shown
    "CHUNK 1 PASSED" at the end

If any ✗ appears, fix that item before proceeding to Chunk 2.
"""

import os
import sys
import traceback

# ── Add src/ to path ──────────────────────────────────────────────────────────
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR  = os.path.join(os.path.dirname(TEST_DIR), "src")
sys.path.insert(0, SRC_DIR)

# ── Import config (no TraCI yet) ──────────────────────────────────────────────
from config import setup_sumo_path, validate_config, SUMO_BINARY, SUMO_CONFIG, SUMO_OPTIONS

PASS = "✓"
FAIL = "✗"
results = []


def check(name: str, test_fn):
    """Run a test and record result."""
    try:
        result = test_fn()
        print(f"  {PASS} {name}")
        if result is not None:
            print(f"       → {result}")
        results.append((name, True, None))
        return True
    except Exception as e:
        print(f"  {FAIL} {name}")
        print(f"       ERROR: {e}")
        results.append((name, False, str(e)))
        return False


def run_chunk1_tests():
    print("\n" + "="*60)
    print("CHUNK 1: SUMO CONNECTION & TLS DISCOVERY TEST")
    print("="*60)

    # ─────────────────────────────────────────────────────────────────────────
    # GROUP 1: Environment
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[GROUP 1] Environment Setup")

    def test_sumo_home():
        sumo_home = os.environ.get("SUMO_HOME")
        if not sumo_home:
            raise EnvironmentError("SUMO_HOME not set")
        return f"SUMO_HOME = {sumo_home}"

    check("SUMO_HOME is set", test_sumo_home)

    def test_traci_import():
        setup_sumo_path()
        import traci  # noqa
        return f"TraCI version importable"

    traci_ok = check("TraCI can be imported", test_traci_import)
    if not traci_ok:
        print("\n[CRITICAL] Cannot import TraCI. Stopping test.")
        print_summary()
        return

    import traci  # Now safe to import

    def test_config_valid():
        validate_config()
        return None

    check("Config validates (files exist, weights sum to 1)", test_config_valid)

    # ─────────────────────────────────────────────────────────────────────────
    # GROUP 2: SUMO Connection
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[GROUP 2] SUMO Connection")

    # Use sumo (headless) for testing — no GUI needed
    test_binary = "sumo"
    sumo_cmd = [test_binary, "-c", SUMO_CONFIG] + [
        "--start",
        "--no-warnings",
        "--step-length", "1.0",
    ]

    def test_sumo_start():
        traci.start(sumo_cmd)
        return f"Connected to SUMO with binary: {test_binary}"

    connected = check("SUMO starts and TraCI connects", test_sumo_start)
    if not connected:
        print("\n[CRITICAL] Cannot connect to SUMO. Check:")
        print(f"  1. '{test_binary}' binary is in your PATH")
        print(f"  2. Config file exists: {SUMO_CONFIG}")
        print(f"  3. All referenced files exist in sumo_files/")
        print_summary()
        return

    # ─────────────────────────────────────────────────────────────────────────
    # GROUP 3: TLS Discovery (connected to SUMO now)
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[GROUP 3] Traffic Light Discovery")

    tls_ids = []

    def test_get_tls_ids():
        nonlocal tls_ids
        tls_ids = traci.trafficlight.getIDList()
        if not tls_ids:
            raise ValueError("No traffic lights found in network!")
        return f"Found {len(tls_ids)} traffic lights: {list(tls_ids)[:5]}{'...' if len(tls_ids) > 5 else ''}"

    check("TLS IDs discoverable", test_get_tls_ids)

    if tls_ids:
        sample_tls = list(tls_ids)[:3]  # Test first 3

        def test_controlled_lanes():
            results_str = []
            for tlsID in sample_tls:
                raw_lanes = traci.trafficlight.getControlledLanes(tlsID)
                unique    = list(dict.fromkeys(raw_lanes))
                results_str.append(f"'{tlsID}': {len(raw_lanes)} raw → {len(unique)} unique lanes")
            return " | ".join(results_str)

        check("getControlledLanes works (+ dedup check)", test_controlled_lanes)

        def test_program_logics():
            results_str = []
            for tlsID in sample_tls:
                logics = traci.trafficlight.getAllProgramLogics(tlsID)
                phases = logics[0].phases if logics else []
                states = [p.state for p in phases[:3]]
                results_str.append(f"'{tlsID}': {len(phases)} phases, first states: {states}")
            return "\n       ".join(results_str)

        check("getAllProgramLogics works + phase states readable", test_program_logics)

        def test_current_phase():
            results_str = []
            for tlsID in sample_tls:
                phase = traci.trafficlight.getPhase(tlsID)
                state = traci.trafficlight.getRedYellowGreenState(tlsID)
                results_str.append(f"'{tlsID}': phase={phase}, state='{state}'")
            return "\n       ".join(results_str)

        check("Current phase + state readable", test_current_phase)

        def test_next_switch():
            results_str = []
            for tlsID in sample_tls:
                ns = traci.trafficlight.getNextSwitch(tlsID)
                results_str.append(f"'{tlsID}': next switch at t={ns:.1f}s")
            return " | ".join(results_str)

        check("getNextSwitch works", test_next_switch)

        # ─── Detailed phase map for first TLS ────────────────────────────────
        print(f"\n[DETAIL] Phase map for first TLS '{list(tls_ids)[0]}':")
        first_tls = list(tls_ids)[0]
        logics    = traci.trafficlight.getAllProgramLogics(first_tls)
        if logics:
            phases     = logics[0].phases
            raw_lanes  = traci.trafficlight.getControlledLanes(first_tls)
            for i, phase in enumerate(phases):
                print(f"  Phase {i:2d}: state='{phase.state}' | duration={phase.duration}s")

    # ─────────────────────────────────────────────────────────────────────────
    # GROUP 4: Simulation Step Test
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[GROUP 4] Simulation Step Execution")

    def test_simulation_step():
        before = traci.simulation.getTime()
        traci.simulationStep()
        after  = traci.simulation.getTime()
        if after <= before:
            raise ValueError(f"Time did not advance: {before} → {after}")
        return f"Time advanced: {before:.1f} → {after:.1f}s"

    check("simulationStep() advances time", test_simulation_step)

    def test_min_expected():
        n = traci.simulation.getMinExpectedNumber()
        return f"Vehicles expected in network: {n}"

    check("getMinExpectedNumber() works", test_min_expected)

    def test_lane_data():
        """Test that lane data APIs return real values."""
        tls_sample = list(tls_ids)[0] if tls_ids else None
        if not tls_sample:
            raise ValueError("No TLS to test")
        raw_lanes = traci.trafficlight.getControlledLanes(tls_sample)
        unique    = list(dict.fromkeys(raw_lanes))
        if not unique:
            raise ValueError("No lanes found")

        lane = unique[0]
        count   = traci.lane.getLastStepVehicleNumber(lane)
        halting = traci.lane.getLastStepHaltingNumber(lane)
        wait    = traci.lane.getWaitingTime(lane)
        speed   = traci.lane.getLastStepMeanSpeed(lane)
        length  = traci.lane.getLength(lane)
        return f"Lane '{lane}': count={count}, halt={halting}, wait={wait:.1f}s, speed={speed:.1f}m/s, length={length:.1f}m"

    check("Lane data APIs return values", test_lane_data)

    # ─────────────────────────────────────────────────────────────────────────
    # GROUP 5: Run 10 steps to verify stability
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[GROUP 5] 10-Step Stability Test")

    def test_10_steps():
        for i in range(10):
            traci.simulationStep()
        t = traci.simulation.getTime()
        v = len(traci.vehicle.getIDList())
        return f"Ran 10 steps cleanly. t={t:.1f}s, vehicles={v}"

    check("10 consecutive steps run without error", test_10_steps)

    # ─────────────────────────────────────────────────────────────────────────
    # GROUP 6: Phase config utils from config.py
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[GROUP 6] Config Utility Functions")

    def test_phase_detection():
        from config import is_yellow_state, is_green_state
        # Yellow states
        assert is_yellow_state("yyrryyrr") == True,  "Should detect yellow"
        assert is_yellow_state("GGrrGGrr") == False, "Should NOT be yellow"
        assert is_green_state("GGrrGGrr")  == True,  "Should detect green"
        assert is_green_state("yyrryyrr")  == False, "Should NOT be green"
        assert is_green_state("rrrrrrrrr") == False,  "All-red should not be green"
        return "All phase detection logic correct"

    check("is_yellow_state() and is_green_state() correct", test_phase_detection)

    # ─────────────────────────────────────────────────────────────────────────
    # CLEANUP
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[CLEANUP] Closing TraCI...")

    def test_close():
        traci.close()
        return "TraCI closed cleanly"

    check("traci.close() exits without error", test_close)

    # ─────────────────────────────────────────────────────────────────────────
    # FINAL SUMMARY
    # ─────────────────────────────────────────────────────────────────────────
    print_summary()


def print_summary():
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    total  = len(results)

    print("\n" + "="*60)
    print(f"CHUNK 1 RESULTS: {passed}/{total} passed")
    print("="*60)

    if failed > 0:
        print("\nFailed tests:")
        for name, ok, err in results:
            if not ok:
                print(f"  ✗ {name}")
                print(f"    Error: {err}")
        print("\n⚠ Fix the above issues before proceeding to Chunk 2.")
    else:
        print("\n🎉 CHUNK 1 PASSED — All systems verified!")
        print("\nNext steps:")
        print("  1. Copy your SUMO files to smart_traffic_system/sumo_files/")
        print("  2. Run: python tests/test_chunk1_connection.py")
        print("  3. When it passes, say 'Start Chunk 2'")
    print("="*60 + "\n")


if __name__ == "__main__":
    run_chunk1_tests()
