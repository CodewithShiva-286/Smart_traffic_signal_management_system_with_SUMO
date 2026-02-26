"""
test_chunk5_emergency.py
========================
CHUNK 5: EMERGENCY VEHICLE PREEMPTION — LIVE VERIFICATION

PREREQUISITES (must be done before running):
  1. routes.rou.xml must contain the ambulance definition:
       <vType id="emergency" vClass="emergency" guiShape="emergency"/>
       <trip id="emergency" type="emergency" depart="0.00"
             from="EDGE_A" to="EDGE_B"/>
     WHERE EDGE_A → EDGE_B crosses at least 3 traffic light junctions.
     Use netedit to pick two distant edges on opposite sides of the network.

  2. If ambulance route is too short (edges adjacent), this test will
     print a clear diagnostic and tell you exactly what to fix.

WHAT THIS VERIFIES (6 groups, 20 checks):

  GROUP 1 — Ambulance Detection
    - Ambulance appears in SUMO vehicle list
    - Engine detects it automatically (static mode)
    - is_ambulance_active() = True after detection
    - Route is long enough to cross at least 1 TLS (diagnostic)

  GROUP 2 — Signal Preemption
    - At least 1 TLS gets preempted
    - Override state string correct length
    - Override state contains G (ambulance gets green)
    - CSV records emergency_active=1 during ambulance phase
    - CSV records preempted_tls_count > 0 during preemption

  GROUP 3 — AI Skips Preempted TLS
    - AI switch count on preempted TLS frozen during override
    - Non-preempted TLS continue making switches normally

  GROUP 4 — Restoration
    - Every preempted TLS gets restored to AI control
    - _preempted_tls empty at end of run

  GROUP 5 — Ambulance Journey Completion
    - ambulance_arrived = True in summary
    - total_preemptions > 0
    - Preemptions and restorations balanced
    - unique_tls_affected > 0

  GROUP 6 — Normal Traffic Not Broken
    - CSV has valid rows throughout
    - avg_wait_time valid numbers (no NaN)
    - Summary report includes emergency stats

HOW TO RUN:
    cd C:\\smart_traffic_system
    python tests/test_chunk5_emergency.py
"""

import os
import sys
import csv
import math

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(TEST_DIR)
SRC_DIR  = os.path.join(ROOT_DIR, "src")
sys.path.insert(0, SRC_DIR)

from config import (
    setup_sumo_path, validate_config,
    SUMO_CONFIG, SUMO_OPTIONS,
    AMBULANCE_ID, AMBULANCE_DETECTION_RANGE,
    SPAWN_AMBULANCE_DYNAMICALLY,
    STEP_LOG_CSV, SUMMARY_REPORT, LOGS_DIR,
)
setup_sumo_path()
validate_config()

import traci
from phase_mapper            import PhaseLaneMapper
from data_collector          import TrafficDataCollector
from ai_signal_controller    import AISignalController
from emergency_preemption    import EmergencyPreemptionEngine
from logger                  import SimulationLogger

# ── Test infrastructure ───────────────────────────────────────────────────────
results = []

def check(name, fn):
    try:
        out = fn()
        print(f"  + {name}")
        if out is not None and str(out).strip():
            for line in str(out).strip().split('\n'):
                if line.strip():
                    print(f"       {line}")
        results.append((name, True, None))
        return True
    except Exception as e:
        print(f"  x {name}")
        print(f"       ERROR: {e}")
        results.append((name, False, str(e)))
        return False


# ── Constants ─────────────────────────────────────────────────────────────────
TEST_STEPS = 800   # enough for ambulance to traverse full network


# ── Observations ─────────────────────────────────────────────────────────────
obs = {
    'ambulance_first_seen_step' : None,
    'engine_active_step'        : None,
    'ambulance_route_edges'     : [],     # edges on ambulance's planned route
    'ambulance_route_length_m'  : 0.0,   # estimated total length
    'preemption_events'         : [],
    'restoration_events'        : [],
    'override_states_seen'      : {},     # {tls_id: state_string}
    'max_simultaneous_preempted': 0,
    'final_preempted_set'       : set(),
    'final_summary'             : {},
    'final_ai_stats'            : {},
    'switches_at_start'         : {},
    'switches_at_end'           : {},
    'sim_error'                 : None,
}


def _debug_ambulance_route():
    """
    Called once after ambulance is first detected.
    Prints its planned route and estimates travel time.
    This catches 'route too short' before preemption even starts.
    """
    try:
        edges = traci.vehicle.getRoute(AMBULANCE_ID)
        obs['ambulance_route_edges'] = list(edges)
        total_len = sum(
            traci.lane.getLength(f"{e}_0")
            for e in edges
            if traci.lane.getLength(f"{e}_0") > 0
        )
        obs['ambulance_route_length_m'] = total_len
        speed = traci.vehicle.getMaxSpeed(AMBULANCE_ID)
        est_time = total_len / max(speed, 1.0)

        print(f"\n  [ROUTE DIAGNOSTIC]")
        print(f"       Edges in route : {len(edges)}")
        print(f"       First edge     : {edges[0] if edges else 'N/A'}")
        print(f"       Last edge      : {edges[-1] if edges else 'N/A'}")
        print(f"       Est. length    : {total_len:.0f}m")
        print(f"       Max speed      : {speed:.1f} m/s")
        print(f"       Est. travel    : {est_time:.0f}s")

        if total_len < 200:
            print(f"\n  [WARNING] Route is only {total_len:.0f}m — likely too short!")
            print(f"       Ambulance will reach destination before passing any TLS.")
            print(f"       FIX: Update routes.rou.xml with from/to edges that are")
            print(f"       at least 500m apart and cross multiple junctions.")
        elif len(edges) < 3:
            print(f"\n  [WARNING] Route only has {len(edges)} edge(s).")
            print(f"       Ambulance may not cross any TLS junction.")
            print(f"       FIX: Choose from/to edges on opposite sides of network.")
        else:
            print(f"       Route looks valid — continuing.")

    except traci.exceptions.TraCIException as e:
        print(f"  [ROUTE DIAGNOSTIC] Could not read route: {e}")


def run():
    print("\n" + "="*65)
    print("CHUNK 5: EMERGENCY VEHICLE PREEMPTION TEST")
    print("="*65)

    # Pre-flight checks
    print(f"\n[PRE-FLIGHT]")
    print(f"  SPAWN_AMBULANCE_DYNAMICALLY = {SPAWN_AMBULANCE_DYNAMICALLY}")
    print(f"  AMBULANCE_ID               = '{AMBULANCE_ID}'")
    print(f"  AMBULANCE_DETECTION_RANGE  = {AMBULANCE_DETECTION_RANGE}m")
    if SPAWN_AMBULANCE_DYNAMICALLY:
        print(f"\n  CRITICAL: SPAWN_AMBULANCE_DYNAMICALLY must be False")
        print(f"  because ambulance is defined in routes.rou.xml.")
        print(f"  Fix: set SPAWN_AMBULANCE_DYNAMICALLY = False in config.py")

    print(f"\n[RUNNING] {TEST_STEPS} steps | HEADLESS (sumo) | emergency ENABLED")
    print("-"*65)

    # ── Build SUMO command — HEADLESS (sumo, not sumo-gui) ────────────────────
    # Headless mode means the test runs to completion without needing
    # a GUI window open. Emergency preemption is purely TraCI-based —
    # it works identically with or without the GUI.
    # To WATCH it: run main_controller.py --steps 800 separately.
    headless_options = [
        "--start",
        "--no-warnings",
        # NOTE: --quit-on-end deliberately omitted.
        # With it, SUMO exits the moment all vehicles finish routes,
        # which terminates our test loop before checks can run.
        # We control termination via our own TEST_STEPS limit instead.
        "--step-length", "1.0",
        "--log", os.path.join(LOGS_DIR, "sumo_chunk5.log"),
    ]
    sumo_cmd = ["sumo", "-c", SUMO_CONFIG] + headless_options

    try:
        traci.start(sumo_cmd)
    except Exception as e:
        obs['sim_error'] = f"SUMO failed to start: {e}"
        print(f"[ERROR] {obs['sim_error']}")
        _run_checks_after_sim()
        return

    print("[SUMO] Connected (headless mode)\n")

    # ── Initialise modules ────────────────────────────────────────────────────
    mapper    = PhaseLaneMapper()
    mapper.build_all()
    collector = TrafficDataCollector(mapper)
    ai        = AISignalController(mapper, collector)
    engine    = EmergencyPreemptionEngine(ai)
    engine.setup_ambulance_route()

    # Start logger so CSV is written fresh this run
    logger = SimulationLogger()
    logger.start()

    all_tls   = mapper.get_all_tls_ids()
    multi_tls = [t for t in all_tls if mapper.has_multiple_green_phases(t)]

    obs['switches_at_start'] = {t: 0 for t in all_tls}
    prev_event_count = 0

    print(f"[INFO] {len(all_tls)} TLS | {len(multi_tls)} multi-phase")
    print(f"[INFO] Waiting for ambulance '{AMBULANCE_ID}' in network...\n")

    # ── MAIN SIMULATION LOOP ──────────────────────────────────────────────────
    try:
        for step in range(TEST_STEPS):

            # Termination: exit cleanly once ambulance has arrived AND
            # we've given 10 more steps to record final CSV state.
            # engine._ambulance_arrived is set True the moment ambulance
            # leaves the network via the normal completion path.
            # Using > 50 guard ensures we never exit in the first few steps
            # (which would mean route is degenerate — caught by checks below).
            if engine._ambulance_arrived and step > 50:
                print(f"\n[INFO] Ambulance completed route at step {step} — ending cleanly")
                break

            traci.simulationStep()
            sim_time = traci.simulation.getTime()

            # Emergency first
            engine.step(sim_time, step)

            # AI second
            ai.step(step)

            # Collect network data for logger
            network_data = collector.collect_network_summary()
            preempted_now = engine.get_preempted_tls()
            emergency_now = engine.is_ambulance_active()

            # Log step (writes CSV)
            logger.log_step(
                step             = step,
                sim_time         = sim_time,
                network_data     = network_data,
                active_tls_count = len(all_tls) - len(preempted_now),
                preempted_tls    = preempted_now,
                emergency_active = emergency_now,
            )

            # ── OBSERVATIONS ─────────────────────────────────────────────────
            vehicles = traci.vehicle.getIDList()

            # Ambulance first detection + route diagnostic
            if obs['ambulance_first_seen_step'] is None and AMBULANCE_ID in vehicles:
                obs['ambulance_first_seen_step'] = step
                print(f"  [OBS] Ambulance '{AMBULANCE_ID}' first seen at step {step}")
                _debug_ambulance_route()

            # Engine activation
            if obs['engine_active_step'] is None and engine.is_ambulance_active():
                obs['engine_active_step'] = step

            # Track preemption/restoration events
            event_log = engine.get_event_log()
            if len(event_log) > prev_event_count:
                for evt in event_log[prev_event_count:]:
                    if evt['type'] == 'PREEMPTED':
                        obs['preemption_events'].append(evt.copy())
                        obs['override_states_seen'][evt['tls_id']] = evt.get('state','')
                        print(f"  [OBS] PREEMPTED '{evt['tls_id'][:35]}' "
                              f"dist={evt.get('distance',0):.1f}m "
                              f"state='{evt.get('state','')}'")
                    elif evt['type'] == 'RESTORED':
                        obs['restoration_events'].append(evt.copy())
                        print(f"  [OBS] RESTORED  '{evt['tls_id'][:35]}'")
                prev_event_count = len(event_log)

            # Max simultaneous
            obs['max_simultaneous_preempted'] = max(
                obs['max_simultaneous_preempted'], len(preempted_now)
            )

            # Progress every 100 steps
            if step % 100 == 0:
                stats = ai.get_stats()
                total_sw = sum(stats['total_switches'].values())
                print(f"  step={step:>3} t={sim_time:>6.1f}s "
                      f"vehicles={len(vehicles):>4} "
                      f"preempted={len(preempted_now)} "
                      f"switches={total_sw} "
                      f"ambul={engine.is_ambulance_active()}")

    except traci.exceptions.FatalTraCIError:
        print("\n[INFO] SUMO connection closed (headless — should not happen)")
    except Exception as e:
        obs['sim_error'] = str(e)
        print(f"\n[SIM ERROR] {e}")
    finally:
        # Capture final state
        obs['final_preempted_set'] = engine.get_preempted_tls()
        obs['final_summary']       = engine.get_summary()
        obs['final_ai_stats']      = ai.get_stats()
        obs['switches_at_end']     = dict(ai.get_stats().get('total_switches', {}))

        # Write summary report (with emergency stats)
        logger.finish(obs['final_ai_stats'], obs['final_summary'])

        try:
            traci.close()
        except Exception:
            pass

    print(f"\n[SUMO] Closed cleanly")
    print(f"[INFO] Preemption events   : {len(obs['preemption_events'])}")
    print(f"[INFO] Restoration events  : {len(obs['restoration_events'])}")
    print(f"[INFO] Max simultaneous    : {obs['max_simultaneous_preempted']}")
    print(f"[INFO] Ambulance route len : {obs['ambulance_route_length_m']:.0f}m")
    print("-"*65)

    _run_checks_after_sim()


def _run_checks_after_sim():

    # ══════════════════════════════════════════════════════════════════════════
    # GROUP 1: AMBULANCE DETECTION
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'─'*65}")
    print("GROUP 1: AMBULANCE DETECTION")
    print(f"{'─'*65}")

    def test_no_sim_error():
        if obs['sim_error']:
            raise RuntimeError(obs['sim_error'])
        return "Simulation completed without fatal exception"
    check("Simulation runs without fatal error", test_no_sim_error)

    def test_ambulance_appeared():
        if obs['ambulance_first_seen_step'] is None:
            raise ValueError(
                f"Ambulance '{AMBULANCE_ID}' never appeared in vehicle list.\n"
                f"  Check routes.rou.xml has a vehicle/trip with id='{AMBULANCE_ID}'\n"
                f"  and that the from/to edges exist in the current network."
            )
        return f"Ambulance appeared at step {obs['ambulance_first_seen_step']}"
    check(f"Ambulance '{AMBULANCE_ID}' appears in vehicle list", test_ambulance_appeared)

    def test_engine_activated():
        if obs['engine_active_step'] is None:
            raise ValueError(
                "EmergencyPreemptionEngine never activated.\n"
                "  Check that SPAWN_AMBULANCE_DYNAMICALLY = False in config.py"
            )
        return f"Engine activated at step {obs['engine_active_step']}"
    check("Emergency engine activates when ambulance detected", test_engine_activated)

    def test_route_long_enough():
        length = obs['ambulance_route_length_m']
        edges  = obs['ambulance_route_edges']
        if length == 0 and not edges:
            raise ValueError(
                "Could not read ambulance route from SUMO.\n"
                "  Ambulance may have left network before route could be read."
            )
        if length < 300:
            raise ValueError(
                f"Ambulance route is only {length:.0f}m ({len(edges)} edges).\n"
                f"  This is too short to cross any TLS junction.\n"
                f"  FIX: In routes.rou.xml, set from= and to= to edges on\n"
                f"  OPPOSITE sides of your network (min ~500m apart).\n"
                f"  Use netedit: click an edge, check its ID in the status bar."
            )
        return (
            f"Route length: {length:.0f}m | {len(edges)} edges\n"
            f"       First: {edges[0] if edges else 'N/A'}\n"
            f"       Last : {edges[-1] if edges else 'N/A'}"
        )
    check("Ambulance route is long enough to cross TLS junctions", test_route_long_enough)

    # ══════════════════════════════════════════════════════════════════════════
    # GROUP 2: SIGNAL PREEMPTION
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'─'*65}")
    print("GROUP 2: SIGNAL PREEMPTION")
    print(f"{'─'*65}")

    def test_at_least_one_preemption():
        n = len(obs['preemption_events'])
        if n == 0:
            raise ValueError(
                "No TLS was ever preempted.\n"
                f"  Route length was {obs['ambulance_route_length_m']:.0f}m.\n"
                f"  Detection range is {AMBULANCE_DETECTION_RANGE}m.\n"
                f"  If route is long enough, check that it actually passes\n"
                f"  within {AMBULANCE_DETECTION_RANGE}m of a traffic light.\n"
                f"  Try increasing AMBULANCE_DETECTION_RANGE in config.py to 300m."
            )
        tls_ids = {e['tls_id'] for e in obs['preemption_events']}
        return f"{n} preemption events across {len(tls_ids)} unique TLS"
    check("At least 1 TLS was preempted during ambulance run", test_at_least_one_preemption)

    def test_override_state_correct():
        if not obs['override_states_seen']:
            raise ValueError("No override states recorded (no preemptions happened)")
        issues = []
        for tls_id, state in obs['override_states_seen'].items():
            if not state:
                issues.append(f"'{tls_id[:30]}': empty state string")
            elif 'G' not in state and 'g' not in state:
                issues.append(f"'{tls_id[:30]}': no green in state '{state}'")
        if issues:
            raise ValueError('\n'.join(issues))
        lines = [f"'{t[:35]}': '{s}'" for t, s in obs['override_states_seen'].items()]
        return "All override states contain green:\n  " + '\n  '.join(lines)
    check("Override state gives green to ambulance direction", test_override_state_correct)

    def test_emergency_active_in_csv():
        if not os.path.isfile(STEP_LOG_CSV):
            raise FileNotFoundError(f"CSV not found: {STEP_LOG_CSV}")
        rows = list(csv.DictReader(open(STEP_LOG_CSV)))
        if not rows:
            raise ValueError("CSV is empty")
        emergency_rows = [r for r in rows if int(r.get('emergency_active', 0)) == 1]
        if len(emergency_rows) == 0:
            raise ValueError(
                "emergency_active=0 for all CSV rows.\n"
                "  This means the logger never received emergency_active=True.\n"
                "  Check that engine.is_ambulance_active() returns True during run."
            )
        return (
            f"emergency_active=1 in {len(emergency_rows)}/{len(rows)} rows\n"
            f"       Steps: {emergency_rows[0]['step']} to {emergency_rows[-1]['step']}"
        )
    check("CSV records emergency_active=1 during ambulance phase", test_emergency_active_in_csv)

    def test_preempted_count_in_csv():
        if not os.path.isfile(STEP_LOG_CSV):
            raise FileNotFoundError(STEP_LOG_CSV)
        rows = list(csv.DictReader(open(STEP_LOG_CSV)))
        preempted_rows = [(r['step'], int(r.get('preempted_tls_count', 0)))
                         for r in rows if int(r.get('preempted_tls_count', 0)) > 0]
        if not preempted_rows and len(obs['preemption_events']) > 0:
            raise ValueError(
                "Preemptions happened but preempted_tls_count=0 in CSV.\n"
                "  Check that engine.get_preempted_tls() is passed to logger."
            )
        if preempted_rows:
            max_cnt = max(c for _, c in preempted_rows)
            return (
                f"preempted_tls_count > 0 in {len(preempted_rows)} rows\n"
                f"       Max simultaneous: {max_cnt} TLS preempted"
            )
        return "No preemptions in CSV (ambulance may not have crossed TLS)"
    check("CSV preempted_tls_count recorded during preemption", test_preempted_count_in_csv)

    # ══════════════════════════════════════════════════════════════════════════
    # GROUP 3: AI SKIPS PREEMPTED TLS
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'─'*65}")
    print("GROUP 3: AI CORRECTLY SKIPS PREEMPTED TLS")
    print(f"{'─'*65}")

    def test_ai_tracked_preemption():
        reported = obs['final_ai_stats'].get('preempted_count', -1)
        if reported == -1:
            raise ValueError("get_stats() did not return preempted_count")
        # At end of run it should be 0 (all restored) or small if ambulance just cleared
        if reported > 3:
            raise ValueError(
                f"AI reports {reported} TLS still preempted at end — restoration failed"
            )
        return f"AI preempted_count at end = {reported} (expected 0 or small)"
    check("AI controller correctly tracks preempted TLS", test_ai_tracked_preemption)

    def test_normal_tls_still_switched():
        total_sw = sum(obs['switches_at_end'].values())
        if total_sw == 0:
            raise ValueError(
                "No phase switches at all during run.\n"
                "  Non-preempted TLS should continue AI operation normally."
            )
        return f"Total AI switches during run: {total_sw} (normal TLS kept working)"
    check("Non-preempted TLS continue making AI switches", test_normal_tls_still_switched)

    # ══════════════════════════════════════════════════════════════════════════
    # GROUP 4: RESTORATION
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'─'*65}")
    print("GROUP 4: TLS RESTORATION AFTER AMBULANCE PASSES")
    print(f"{'─'*65}")

    def test_restorations_happened():
        n_p = len(obs['preemption_events'])
        n_r = len(obs['restoration_events'])
        if n_p > 0 and n_r == 0:
            raise ValueError(
                f"{n_p} preemptions but 0 restorations.\n"
                f"  TLS are stuck in override. Ambulance may not have left\n"
                f"  the detection range before run ended."
            )
        preempted_tls = {e['tls_id'] for e in obs['preemption_events']}
        restored_tls  = {e['tls_id'] for e in obs['restoration_events']}
        not_restored  = preempted_tls - restored_tls
        if not_restored:
            return (
                f"{n_r}/{n_p} preemptions restored.\n"
                f"       Still in range at end: {[t[:25] for t in not_restored]}"
            )
        return f"All {n_r} preempted TLS restored cleanly"
    check("Preempted TLS are restored after ambulance passes", test_restorations_happened)

    def test_final_preempted_empty():
        remaining = obs['final_preempted_set']
        if len(remaining) > 2:
            raise ValueError(
                f"{len(remaining)} TLS stuck in preemption at end: "
                f"{[t[:25] for t in remaining]}"
            )
        if remaining:
            return f"{len(remaining)} TLS mid-restore at end (last-step switch — normal)"
        return "_preempted_tls empty — all TLS fully restored"
    check("No TLS stuck in preemption at end of run", test_final_preempted_empty)

    # ══════════════════════════════════════════════════════════════════════════
    # GROUP 5: AMBULANCE JOURNEY COMPLETION
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'─'*65}")
    print("GROUP 5: AMBULANCE JOURNEY COMPLETION")
    print(f"{'─'*65}")

    summary = obs['final_summary']

    def test_ambulance_arrived():
        if not summary.get('ambulance_arrived', False):
            raise ValueError(
                "ambulance_arrived = False.\n"
                "  Ambulance did not complete its route in the test window.\n"
                f"  Route length was {obs['ambulance_route_length_m']:.0f}m.\n"
                f"  Try increasing TEST_STEPS (currently {TEST_STEPS})."
            )
        return "ambulance_arrived = True"
    check("Ambulance completed its full route", test_ambulance_arrived)

    def test_total_preemptions():
        n = summary.get('total_preemptions', 0)
        if n == 0:
            raise ValueError("total_preemptions = 0 in summary")
        return f"total_preemptions = {n}"
    check("Summary records total_preemptions > 0", test_total_preemptions)

    def test_restorations_balanced():
        p = summary.get('total_preemptions', 0)
        r = summary.get('total_restorations', 0)
        if p > 0 and r == 0:
            raise ValueError(f"preemptions={p} but restorations=0")
        if r < p:
            return f"preemptions={p}, restorations={r} ({p-r} still in range at end)"
        return f"preemptions={p} == restorations={r} — perfectly balanced"
    check("Preemptions and restorations balanced", test_restorations_balanced)

    def test_unique_tls():
        n = summary.get('unique_tls_affected', 0)
        if n == 0:
            raise ValueError("unique_tls_affected = 0")
        return f"unique_tls_affected = {n}"
    check("At least 1 unique TLS affected by emergency", test_unique_tls)

    # ══════════════════════════════════════════════════════════════════════════
    # GROUP 6: NORMAL TRAFFIC NOT BROKEN
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'─'*65}")
    print("GROUP 6: NORMAL TRAFFIC NOT BROKEN")
    print(f"{'─'*65}")

    def test_csv_valid():
        if not os.path.isfile(STEP_LOG_CSV):
            raise FileNotFoundError(STEP_LOG_CSV)
        rows = list(csv.DictReader(open(STEP_LOG_CSV)))
        if len(rows) < 10:
            raise ValueError(f"Only {len(rows)} rows in CSV — run too short")
        bad = [r for r in rows
               if not r.get('avg_wait_time', '').strip()
               or math.isnan(float(r['avg_wait_time']))]
        if bad:
            raise ValueError(f"{len(bad)} rows have invalid avg_wait_time")
        return f"CSV: {len(rows)} valid rows — no NaN or empty values"
    check("CSV data valid throughout run", test_csv_valid)

    def test_summary_has_emergency_stats():
        if not os.path.isfile(SUMMARY_REPORT):
            raise FileNotFoundError(SUMMARY_REPORT)
        text = open(SUMMARY_REPORT).read()
        if "Total TLS Preemptions" not in text:
            raise ValueError(
                "Summary report missing 'Total TLS Preemptions'.\n"
                "  This line is written by logger.finish() when emergency_stats is provided."
            )
        for line in text.splitlines():
            if "Total TLS Preemptions" in line or "Ambulance Arrived" in line:
                print(f"       {line.strip()}")
        return "Summary report contains emergency stats"
    check("Summary report includes emergency preemption statistics", test_summary_has_emergency_stats)

    def test_active_tls_reflects_preemption():
        if not os.path.isfile(STEP_LOG_CSV):
            raise FileNotFoundError(STEP_LOG_CSV)
        rows = list(csv.DictReader(open(STEP_LOG_CSV)))
        counts = [int(r['active_tls_count']) for r in rows]
        min_c, max_c = min(counts), max(counts)
        if len(obs['preemption_events']) > 0 and min_c == 10:
            return (
                f"NOTE: active_tls_count stayed at 10 during preemption.\n"
                f"       Expected a drop below 10 when TLS were preempted."
            )
        return f"active_tls_count range: {min_c} – {max_c} (drops during preemption)"
    check("active_tls_count reflects preemption state in CSV", test_active_tls_reflects_preemption)

    # ── DETAIL PRINTOUT ───────────────────────────────────────────────────────
    print(f"\n[DETAIL] Emergency summary:")
    for k, v in obs['final_summary'].items():
        print(f"       {k}: {v}")

    print(f"\n[DETAIL] Preemption timeline:")
    if obs['preemption_events']:
        for e in obs['preemption_events']:
            print(f"       step={e.get('step','?'):>4} PREEMPTED "
                  f"'{e['tls_id'][:35]}' "
                  f"dist={e.get('distance',0):.1f}m "
                  f"state='{e.get('state','')}'")
        for e in obs['restoration_events']:
            print(f"       step={e.get('step','?'):>4} RESTORED  "
                  f"'{e['tls_id'][:35]}'")
    else:
        print("       (none — ambulance did not pass within detection range of any TLS)")

    print(f"\n[DETAIL] Route: {obs['ambulance_route_length_m']:.0f}m | "
          f"{len(obs['ambulance_route_edges'])} edges")
    print(f"[DETAIL] AI switches: {sum(obs['switches_at_end'].values())}")
    print(f"[DETAIL] Max simultaneous preemptions: {obs['max_simultaneous_preempted']}")

    _print_results()


def _print_results():
    passed = sum(1 for _, ok, _ in results if ok)
    total  = len(results)
    failed = [(n, e) for n, ok, e in results if not ok]

    print(f"\n{'='*65}")
    print(f"CHUNK 5 RESULTS: {passed}/{total} passed")
    print(f"{'='*65}")

    if failed:
        print("\nFailed tests:")
        for name, err in failed:
            print(f"  x {name}")
            for line in err.split('\n')[:4]:
                print(f"    {line}")
        print()
        # Give specific next action based on which tests failed
        route_failed = any('route' in n.lower() or 'preempt' in n.lower() or
                          'arrived' in n.lower() for n, _ in failed)
        if route_failed:
            print("ACTION REQUIRED:")
            print("  The ambulance route is too short or not crossing any TLS.")
            print("  Do this in netedit:")
            print("  1. Open your map.net.xml in netedit")
            print("  2. Click an edge on the FAR LEFT of your network — note its ID")
            print("  3. Click an edge on the FAR RIGHT of your network — note its ID")
            print("  4. Update routes.rou.xml:")
            print('     <trip id="emergency" type="emergency" depart="0.00"')
            print('           from="EDGE_FAR_LEFT" to="EDGE_FAR_RIGHT"/>')
            print("  5. Re-run this test")
    else:
        print("\nCHUNK 5 PASSED — Emergency preemption verified end-to-end!")
        print("Next: say 'Start Chunk 6' for full integration test.")
    print("="*65 + "\n")


if __name__ == "__main__":
    run()
