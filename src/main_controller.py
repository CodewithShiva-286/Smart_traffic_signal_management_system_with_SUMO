"""
main_controller.py
==================
The main orchestration script. Single entry point for the entire system.

Run this file to start the simulation:
    python main_controller.py
    python main_controller.py --headless       (no GUI, faster)
    python main_controller.py --no-emergency   (AI only, no ambulance)
    python main_controller.py --steps 1000     (limit to N steps)

Execution order each step:
1. traci.simulationStep()           — advance simulation
2. emergency_engine.step()          — emergency check FIRST (highest priority)
3. ai_controller.step()            — AI skips preempted TLS automatically
4. logger.log_step()               — record metrics
5. Check termination

All modules are loosely coupled through this orchestrator.
"""

import os
import sys
import argparse
import traci

# ── Setup: must happen before ANY other project imports ──────────────────────
# Add src/ to path so imports work regardless of working directory
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from config import (
    setup_sumo_path,
    validate_config,
    SUMO_BINARY,
    SUMO_CONFIG,
    SUMO_OPTIONS,
    MAX_SIMULATION_STEPS,
    STEP_LENGTH,
)

# Setup SUMO path (must happen before traci is used)
setup_sumo_path()

from phase_mapper import PhaseLaneMapper
from data_collector import TrafficDataCollector
from ai_signal_controller import AISignalController
from emergency_preemption import EmergencyPreemptionEngine
from logger import SimulationLogger


def parse_args():
    parser = argparse.ArgumentParser(
        description="AI Adaptive Traffic Management System with Emergency Preemption"
    )
    parser.add_argument(
        "--headless", action="store_true",
        help="Run without SUMO GUI (faster, uses 'sumo' binary)"
    )
    parser.add_argument(
        "--no-emergency", action="store_true",
        help="Disable emergency vehicle — run AI-only mode"
    )
    parser.add_argument(
        "--steps", type=int, default=None,
        help="Limit simulation to N steps (overrides config)"
    )
    parser.add_argument(
        "--debug-tls", type=str, default=None,
        help="Print detailed debug info for a specific TLS ID each step"
    )
    return parser.parse_args()


def run_simulation(
    headless: bool = False,
    enable_emergency: bool = True,
    max_steps: int = None,
    debug_tls: str = None,
):
    """
    Main simulation function.
    
    Args:
        headless       : use 'sumo' instead of 'sumo-gui'
        enable_emergency: spawn and track ambulance
        max_steps      : override MAX_SIMULATION_STEPS from config
        debug_tls      : if set, print detailed data for this TLS each step
    """

    # ── Pre-flight validation ─────────────────────────────────────────────────
    print("\n" + "="*60)
    print("AI ADAPTIVE TRAFFIC MANAGEMENT SYSTEM")
    print("Karvena Nagar Simulation")
    print("="*60 + "\n")

    validate_config()

    # Determine binary
    binary = "sumo" if headless else SUMO_BINARY
    step_limit = max_steps or MAX_SIMULATION_STEPS

    print(f"\n[MAIN] Starting SUMO: {binary}")
    print(f"[MAIN] Config: {SUMO_CONFIG}")
    print(f"[MAIN] Emergency vehicle: {'ENABLED' if enable_emergency else 'DISABLED'}")
    print(f"[MAIN] Step limit: {step_limit}")
    print()

    # ── Start SUMO via TraCI ──────────────────────────────────────────────────
    sumo_cmd = [binary, "-c", SUMO_CONFIG] + SUMO_OPTIONS
    traci.start(sumo_cmd)
    print(f"[MAIN] ✓ SUMO connected via TraCI")

    # ── Initialize all modules ────────────────────────────────────────────────

    # 1. Phase mapper — builds lane maps for all TLS (one-time)
    mapper = PhaseLaneMapper()
    valid_tls_count = mapper.build_all()
    all_tls_ids = mapper.get_all_tls_ids()

    if valid_tls_count == 0:
        print("[MAIN] ✗ FATAL: No valid traffic lights found. Check network file.")
        traci.close()
        return

    # 2. Data collector
    collector = TrafficDataCollector(mapper)

    # 3. AI signal controller
    ai_controller = AISignalController(mapper, collector)
    print(f"[MAIN] ✓ AI controller initialized for {len(all_tls_ids)} TLS")

    # 4. Emergency engine
    emergency_engine = None
    if enable_emergency:
        emergency_engine = EmergencyPreemptionEngine(ai_controller)
        emergency_engine.setup_ambulance_route()
        print(f"[MAIN] ✓ Emergency preemption engine ready")

    # 5. Logger
    logger = SimulationLogger()
    logger.start()

    print(f"\n[MAIN] ✓ All modules initialized. Entering simulation loop...\n")
    print("-" * 60)

    # ── MAIN SIMULATION LOOP ──────────────────────────────────────────────────
    step = 0
    try:
        while True:
            # Termination condition: all vehicles done OR step limit reached
            min_expected = traci.simulation.getMinExpectedNumber()
            if min_expected == 0:
                print(f"\n[MAIN] All vehicles have left the network. Ending.")
                break
            if step_limit is not None and step >= step_limit:
                print(f"\n[MAIN] Step limit ({step_limit}) reached. Ending.")
                break

            # ── Step 1: Advance simulation ────────────────────────────────────
            traci.simulationStep()
            sim_time = traci.simulation.getTime()

            # ── Step 2: Emergency check (HIGHEST PRIORITY) ────────────────────
            emergency_active = False
            preempted_tls    = set()

            if emergency_engine is not None:
                emergency_engine.step(sim_time, step)
                preempted_tls    = emergency_engine.get_preempted_tls()
                emergency_active = emergency_engine.is_ambulance_active()

            # ── Step 3: AI signal control (skips preempted TLS automatically) ─
            ai_controller.step(step)

            # ── Step 4: Collect network summary for logging ───────────────────
            network_data = collector.collect_network_summary()

            # ── Step 5: Debug output for specific TLS ────────────────────────
            if debug_tls and step % 10 == 0:
                if mapper.is_valid_tls(debug_tls):
                    data = collector.collect(debug_tls)
                    collector.debug_print(debug_tls, data)
                    current_phase = traci.trafficlight.getPhase(debug_tls)
                    phase_type    = mapper.get_phase_type(debug_tls, current_phase)
                    print(f"  [DEBUG] Current phase: {current_phase} ({phase_type})")

            # ── Step 6: Log step ─────────────────────────────────────────────
            logger.log_step(
                step             = step,
                sim_time         = sim_time,
                network_data     = network_data,
                active_tls_count = len(all_tls_ids) - len(preempted_tls),
                preempted_tls    = preempted_tls,
                emergency_active = emergency_active,
            )

            step += 1

    except KeyboardInterrupt:
        print(f"\n[MAIN] Interrupted by user at step {step}")
    except traci.exceptions.TraCIException as e:
        print(f"\n[MAIN] ✗ TraCI error at step {step}: {e}")
        raise
    finally:
        # ── Cleanup ───────────────────────────────────────────────────────────
        print(f"\n[MAIN] Shutting down...")

        controller_stats = ai_controller.get_stats()
        emergency_stats  = emergency_engine.get_summary() if emergency_engine else {}

        logger.finish(controller_stats, emergency_stats)

        try:
            traci.close()
            print("[MAIN] ✓ TraCI connection closed cleanly")
        except Exception:
            pass


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = parse_args()

    try:
        run_simulation(
            headless         = args.headless,
            enable_emergency = not args.no_emergency,
            max_steps        = args.steps,
            debug_tls        = args.debug_tls,
        )
    except traci.exceptions.FatalTraCIError:
        # User closed SUMO-GUI window — simulation already shut down cleanly
        # in the finally block. This exception is cosmetic; suppress it.
        pass
    except KeyboardInterrupt:
        pass
