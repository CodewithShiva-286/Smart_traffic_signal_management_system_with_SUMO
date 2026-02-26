"""
config.py
=========
Single source of truth for ALL configuration in this project.
Change values HERE only — never hardcode in other files.

Verified against SUMO TraCI 1.x documentation.
"""

import os
import sys

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1: SUMO ENVIRONMENT SETUP
# ─────────────────────────────────────────────────────────────────────────────

def setup_sumo_path():
    """
    Adds SUMO tools to Python path so TraCI can be imported.
    Reads SUMO_HOME environment variable.
    Must be called before 'import traci'.
    """
    sumo_home = os.environ.get("SUMO_HOME")
    if sumo_home is None:
        raise EnvironmentError(
            "\n[CONFIG ERROR] SUMO_HOME environment variable is NOT set.\n"
            "  Windows : set SUMO_HOME=C:\\Program Files (x86)\\Eclipse\\Sumo\n"
            "  Linux   : export SUMO_HOME=/usr/share/sumo\n"
            "  Mac     : export SUMO_HOME=/opt/homebrew/opt/sumo/share/sumo\n"
        )
    tools_path = os.path.join(sumo_home, "tools")
    if tools_path not in sys.path:
        sys.path.append(tools_path)
    return sumo_home


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2: FILE PATHS
# ─────────────────────────────────────────────────────────────────────────────

# Base directory of the project (parent of src/)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# SUMO simulation files — place your files in sumo_files/
SUMO_FILES_DIR  = os.path.join(BASE_DIR, "sumo_files")
SUMO_CONFIG     = os.path.join(SUMO_FILES_DIR, "karvenagarsim.sumocfg")

# Output files
OUTPUT_DIR      = os.path.join(BASE_DIR, "output")
LOGS_DIR        = os.path.join(OUTPUT_DIR, "logs")
STEP_LOG_CSV    = os.path.join(LOGS_DIR, "step_log.csv")
SUMMARY_REPORT  = os.path.join(LOGS_DIR, "summary_report.txt")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3: SUMO LAUNCH OPTIONS
# ─────────────────────────────────────────────────────────────────────────────

# Use "sumo-gui" for visual simulation, "sumo" for headless (faster)
SUMO_BINARY     = "sumo-gui"   # Change to "sumo" for headless

# Extra SUMO command-line options
SUMO_OPTIONS    = [
    "--start",                         # auto-start (no manual play needed for sumo-gui)
    "--quit-on-end",                   # close GUI when sim ends
    "--no-warnings",                   # suppress non-critical warnings
    "--step-length", "1.0",           # 1 second per simulation step
    "--log", os.path.join(LOGS_DIR, "sumo_runtime.log"),  # SUMO's own log
]

# Step length in seconds (must match --step-length above)
STEP_LENGTH     = 1.0


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4: SIGNAL TIMING PARAMETERS
# ─────────────────────────────────────────────────────────────────────────────

# Minimum seconds a green phase must stay green before we can switch
MIN_PHASE_DURATION  = 15    # seconds — gives vehicles time to actually clear the junction

# Minimum green time assigned by AI (never goes below this)
MIN_GREEN_TIME      = 20    # seconds

# Maximum green time assigned by AI (never exceeds this)
MAX_GREEN_TIME      = 90 # seconds

# Default green when we have no data or score is 0
DEFAULT_GREEN_TIME  = 25    # seconds

# Fixed yellow time — NEVER modify yellow via TraCI, let SUMO handle it
# This constant is for reference only (read from network, not set by us)
YELLOW_TIME         = 3     # seconds (informational only)

# How much better a competing phase must score to trigger a switch
# Prevents constant switching when scores are close.
# Lowered from 0.15 → 0.10 after live run showed AI was too conservative:
# with sliding-window normalization, score gaps are now meaningful at 10%.
SWITCH_THRESHOLD    = 0.10  # 10% better score required to switch


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5: AI SCORING WEIGHTS
# ─────────────────────────────────────────────────────────────────────────────
# Weights must sum to 1.0

WEIGHT_DENSITY  = 0.40   # Traffic density (vehicles per meter of lane)
WEIGHT_WAIT     = 0.40   # Average cumulative waiting time
WEIGHT_QUEUE    = 0.20   # Number of halted vehicles

# Fairness: boost score of a phase for each step it has been skipped
# Prevents starvation of low-traffic approaches
FAIRNESS_BONUS_PER_SKIP = 0.08  # added per skip cycle

# After this many skips, force minimum green regardless of score
FAIRNESS_MAX_SKIP       = 8     # steps


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6: EMERGENCY VEHICLE PARAMETERS
# ─────────────────────────────────────────────────────────────────────────────

# Vehicle ID of the ambulance (must match route file or add dynamically)
AMBULANCE_ID            = "emergency"

# Vehicle type ID for ambulance (uses default car type since others failed)
# Change this if you later add ambulance vtype to routes.rou.xml
AMBULANCE_TYPE          = "emergency_type"

# Distance in meters from ambulance to TLS stop line to trigger preemption
AMBULANCE_DETECTION_RANGE = 150  # meters — v6 stop-line edge algorithm works
                                 # correctly at any distance, so 150m is optimal:
                                 # enough warning time (~5-9s at 60-120 km/h) without
                                 # preempting junctions ambulance hasn't reached yet

# How long to hold the override signal per step (re-applied every step)
EMERGENCY_HOLD_DURATION   = 999  # seconds — effectively infinite, re-set each step

# Whether to spawn ambulance dynamically via TraCI (True)
# or expect it to be defined in routes.rou.xml (False)
SPAWN_AMBULANCE_DYNAMICALLY = False

# Ambulance departure time (simulation seconds) — only if dynamic
AMBULANCE_DEPART_TIME       = 0    # seconds (depart='0.00' in routes.rou.xml)

# Ambulance route ID — must exist in routes.rou.xml OR be added dynamically
AMBULANCE_ROUTE_ID          = "ambulance_route"


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 7: LOGGING & DISPLAY
# ─────────────────────────────────────────────────────────────────────────────

# Print console status every N simulation steps
CONSOLE_LOG_INTERVAL = 50   # steps

# Log to CSV every N simulation steps (1 = every step, higher = less file I/O)
CSV_LOG_INTERVAL     = 1    # steps

# Maximum simulation steps to run (safety cutoff)
# Set to None to run until getMinExpectedNumber() == 0
MAX_SIMULATION_STEPS = 3600  # 1 hour of simulated time at 1s/step


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 8: PHASE STATE CHARACTER REFERENCE
# ─────────────────────────────────────────────────────────────────────────────
# From official SUMO documentation:
#
#  G = Green, vehicle has right-of-way (main green)
#  g = Green, vehicle has to yield (minor green / conditional)
#  r = Red
#  y = Yellow (transition from green to red)
#  Y = Yellow (transition from minor green to red)  [rare]
#  o = Off, blinking (not commonly used)
#  O = Off, no signal (not commonly used)
#  u = Undefined
#  s = Stop (red + stop line)
#
# YELLOW chars: 'y', 'Y'
# GREEN chars:  'G', 'g'
# RED chars:    'r', 's'

GREEN_CHARS  = frozenset({'G', 'g'})
YELLOW_CHARS = frozenset({'y', 'Y'})
RED_CHARS    = frozenset({'r', 's'})


def is_yellow_state(state_string: str) -> bool:
    """
    Returns True if the phase state string represents a yellow transition phase.
    A phase is considered yellow if ANY of its non-red signals are yellow.
    
    Args:
        state_string: e.g. "yyrryyrrr"
    
    Returns:
        True if this is a yellow/transition phase
    """
    non_red = [c for c in state_string if c not in RED_CHARS]
    if not non_red:
        return False  # all-red phase — treat as yellow (don't interrupt)
    return any(c in YELLOW_CHARS for c in non_red)


def is_green_state(state_string: str) -> bool:
    """
    Returns True if this phase gives green to at least one direction.
    
    Args:
        state_string: e.g. "GGrrGGrr"
    
    Returns:
        True if this is a green phase (controllable by AI)
    """
    return any(c in GREEN_CHARS for c in state_string)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 9: VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def validate_config():
    """
    Validates configuration before simulation starts.
    Raises ValueError with clear message if anything is wrong.
    """
    errors = []

    # Check weights sum to ~1.0
    weight_sum = WEIGHT_DENSITY + WEIGHT_WAIT + WEIGHT_QUEUE
    if abs(weight_sum - 1.0) > 0.01:
        errors.append(f"AI weights must sum to 1.0, got {weight_sum:.3f}")

    # Check timing values
    if MIN_GREEN_TIME >= MAX_GREEN_TIME:
        errors.append(f"MIN_GREEN_TIME ({MIN_GREEN_TIME}) must be < MAX_GREEN_TIME ({MAX_GREEN_TIME})")

    if MIN_PHASE_DURATION > MIN_GREEN_TIME:
        errors.append(f"MIN_PHASE_DURATION ({MIN_PHASE_DURATION}) should be <= MIN_GREEN_TIME ({MIN_GREEN_TIME})")

    # Check SUMO config file exists (only if sumo_files are present)
    if not os.path.exists(SUMO_CONFIG):
        errors.append(
            f"SUMO config not found at: {SUMO_CONFIG}\n"
            f"  Copy your .sumocfg and network files into: {SUMO_FILES_DIR}/"
        )

    # Check output dirs exist (create if not)
    for d in [OUTPUT_DIR, LOGS_DIR]:
        os.makedirs(d, exist_ok=True)

    if errors:
        raise ValueError(
            "\n[CONFIG VALIDATION FAILED]\n" +
            "\n".join(f"  ✗ {e}" for e in errors)
        )

    print("[CONFIG] ✓ All configuration validated successfully")
    print(f"[CONFIG] SUMO binary  : {SUMO_BINARY}")
    print(f"[CONFIG] Config file  : {SUMO_CONFIG}")
    print(f"[CONFIG] Output logs  : {LOGS_DIR}")
    print(f"[CONFIG] Step length  : {STEP_LENGTH}s")
    print(f"[CONFIG] Green range  : {MIN_GREEN_TIME}s – {MAX_GREEN_TIME}s")
    print(f"[CONFIG] AI weights   : density={WEIGHT_DENSITY}, wait={WEIGHT_WAIT}, queue={WEIGHT_QUEUE}")


if __name__ == "__main__":
    # Quick self-test when run directly
    try:
        setup_sumo_path()
        validate_config()
    except (EnvironmentError, ValueError) as e:
        print(e)
