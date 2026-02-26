"""
data_collector.py  (v2 — updated after Chunk 1 network analysis)
=================
Collects real-time traffic data from SUMO via TraCI every simulation step.

CRITICAL FIX FROM CHUNK 1 ANALYSIS:
  ISSUE: getLastStepMeanSpeed() returns FREE FLOW SPEED (e.g. 27.8 m/s)
         when a lane has ZERO vehicles — NOT zero.
  FIX:   if vehicle_count == 0 → override speed to 0.0
         This prevents empty lanes from inflating speed and corrupting scores.

  ISSUE: Division by zero in normalization when all values are 0 at sim start.
  FIX:   Running maximums start at 1.0, never go below 1.0.

DATA COLLECTED PER LANE:
  vehicle_count  — traci.lane.getLastStepVehicleNumber()
  halting_count  — traci.lane.getLastStepHaltingNumber()  (speed < 0.1 m/s)
  wait_time      — traci.lane.getWaitingTime()
  mean_speed     — traci.lane.getLastStepMeanSpeed()  ← FIXED
  density        — vehicle_count / lane_length  (veh/meter)

DATA AGGREGATED PER GREEN PHASE:
  All lanes in a green phase are summed together.
  This gives the AI one score per phase, not per lane.

NORMALIZATION:
  Running maximums track the highest value seen so far.
  Each value is divided by its max → [0.0, 1.0] range.
  Prevents one metric from dominating due to different units.

SUMO TRACI APIS USED:
  traci.lane.getLastStepVehicleNumber(laneID)   → int
  traci.lane.getLastStepHaltingNumber(laneID)   → int
  traci.lane.getWaitingTime(laneID)             → float seconds
  traci.lane.getLastStepMeanSpeed(laneID)       → float m/s
  traci.vehicle.getIDList()                     → list[str]
  traci.vehicle.getWaitingTime(vehID)           → float seconds
  traci.vehicle.getSpeed(vehID)                 → float m/s
  traci.simulation.getDepartedNumber()          → int
  traci.simulation.getArrivedNumber()           → int
  traci.simulation.getTime()                    → float
"""

import traci
from phase_mapper import PhaseLaneMapper


class TrafficDataCollector:
    """
    Collects and structures traffic data per TLS per step.

    Usage:
        collector = TrafficDataCollector(mapper)

        # Each step, for each TLS:
        raw    = collector.collect(tlsID)
        normed = collector.get_normalized(raw)

        # Once per step for logging:
        summary = collector.collect_network_summary()

    Output of collect(tlsID):
        {
          phase_idx: {
            'count'    : int,      total vehicles in all green lanes
            'queue'    : int,      halted vehicles (speed < 0.1 m/s)
            'wait'     : float,    cumulative waiting time (seconds)
            'speed'    : float,    average speed (0.0 if no vehicles)
            'density'  : float,    vehicles per meter of lane
            'lanes'    : list[str]
          },
          ...
        }

    Output of get_normalized(raw):
        {
          phase_idx: {
            'density_norm': float [0,1],
            'wait_norm'   : float [0,1],
            'queue_norm'  : float [0,1],
            'count'       : int,
            'speed'       : float,
            'lanes'       : list[str]
          },
          ...
        }
    """

    def __init__(self, mapper: PhaseLaneMapper):
        self._mapper = mapper

        # Sliding-window maximums — anchored to RECENT traffic, not all-time peak.
        # Without this, a high-peak early in the run (e.g. wait=65s) normalises
        # all later moderate waits (8-15s) to near-zero, collapsing score gaps
        # and causing the AI to stop switching phases correctly.
        #
        # Strategy: exponential decay.
        #   each step: max = max(new_value, max * DECAY_FACTOR)
        #   DECAY_FACTOR = 0.995 → after 200 steps of no traffic, max drops ~63%
        #   floor = 1.0 always (prevents div/zero)
        self._max_density  = 1.0
        self._max_wait     = 1.0
        self._max_queue    = 1.0
        self._DECAY        = 0.995   # per-step decay toward recent reality

        # Step counter for internal use
        self._step_count = 0

    # ── PER-TLS DATA COLLECTION ───────────────────────────────────────────────

    def collect(self, tlsID: str) -> dict:
        """
        Collect and aggregate traffic data for all green phases of a TLS.

        Args:
            tlsID: Traffic light ID (must be valid per phase_mapper)

        Returns:
            dict keyed by green phase index.
            Returns empty dict if TLS is invalid.
        """
        if not self._mapper.is_valid_tls(tlsID):
            return {}

        green_phases = self._mapper.get_green_phase_indices(tlsID)
        result       = {}

        for phase_idx in green_phases:
            lanes = self._mapper.get_green_lanes(tlsID, phase_idx)

            if not lanes:
                result[phase_idx] = self._zero_data(phase_idx)
                continue

            total_count   = 0
            total_halting = 0
            total_wait    = 0.0
            total_density = 0.0
            speed_sum     = 0.0
            lanes_with_vehicles = 0

            for lane in lanes:
                try:
                    count   = traci.lane.getLastStepVehicleNumber(lane)
                    halting = traci.lane.getLastStepHaltingNumber(lane)
                    wait    = traci.lane.getWaitingTime(lane)
                    speed   = traci.lane.getLastStepMeanSpeed(lane)
                    length  = self._mapper.get_lane_length(lane)

                    # ── CRITICAL FIX: free-flow speed when empty ──────────────
                    # SUMO returns road speed limit (e.g. 27.8 m/s) when
                    # no vehicles are present. This is NOT useful for scoring.
                    # We only count speed when vehicles are actually present.
                    if count > 0:
                        speed_sum           += speed
                        lanes_with_vehicles += 1

                    total_count   += count
                    total_halting += halting
                    total_wait    += wait
                    total_density += count / max(length, 1.0)

                except traci.exceptions.TraCIException:
                    # Internal lanes or temporarily inaccessible — skip silently
                    continue

            # Average speed across lanes that actually have vehicles
            avg_speed = speed_sum / lanes_with_vehicles if lanes_with_vehicles > 0 else 0.0

            result[phase_idx] = {
                'count'  : total_count,
                'queue'  : total_halting,
                'wait'   : total_wait,
                'speed'  : avg_speed,
                'density': total_density,
                'lanes'  : lanes,
            }

            # Sliding-window update: decay toward recent data each step.
            # This prevents a one-time peak from permanently suppressing all
            # future scores by over-inflating the normalization denominator.
            self._max_density = max(total_density,        self._max_density * self._DECAY, 1.0)
            self._max_wait    = max(total_wait,           self._max_wait    * self._DECAY, 1.0)
            self._max_queue   = max(float(total_halting), self._max_queue   * self._DECAY, 1.0)

        return result

    def get_normalized(self, raw: dict) -> dict:
        """
        Normalize raw phase data to [0.0, 1.0] range.
        Uses running maximums as denominators.

        Args:
            raw: output from collect()

        Returns:
            dict with _norm suffix values, plus raw count/speed/lanes
        """
        normed = {}
        for phase_idx, data in raw.items():
            normed[phase_idx] = {
                'density_norm': min(data['density'] / self._max_density, 1.0),
                'wait_norm'   : min(data['wait']    / self._max_wait,    1.0),
                'queue_norm'  : min(data['queue']   / self._max_queue,   1.0),
                'count'       : data['count'],
                'speed'       : data['speed'],
                'lanes'       : data['lanes'],
            }
        return normed

    # ── NETWORK-WIDE SUMMARY (once per step, for logging) ─────────────────────

    def collect_network_summary(self) -> dict:
        """
        Collect network-wide aggregate statistics.
        Call ONCE per step — used exclusively by logger.

        Returns:
            dict with keys: sim_time, vehicles_in_net, departed, arrived,
                            avg_wait_time, avg_speed, total_wait
        """
        self._step_count += 1

        try:
            sim_time = traci.simulation.getTime()
            departed = traci.simulation.getDepartedNumber()
            arrived  = traci.simulation.getArrivedNumber()

            all_vehs = traci.vehicle.getIDList()
            count    = len(all_vehs)

            total_wait  = 0.0
            total_speed = 0.0

            for veh_id in all_vehs:
                try:
                    total_wait  += traci.vehicle.getWaitingTime(veh_id)
                    total_speed += traci.vehicle.getSpeed(veh_id)
                except traci.exceptions.TraCIException:
                    continue

            avg_wait  = total_wait  / count if count > 0 else 0.0
            avg_speed = total_speed / count if count > 0 else 0.0

            return {
                'sim_time'       : sim_time,
                'vehicles_in_net': count,
                'departed'       : departed,
                'arrived'        : arrived,
                'avg_wait_time'  : avg_wait,
                'avg_speed'      : avg_speed,
                'total_wait'     : total_wait,
            }

        except traci.exceptions.TraCIException as e:
            return {
                'sim_time'       : 0.0,
                'vehicles_in_net': 0,
                'departed'       : 0,
                'arrived'        : 0,
                'avg_wait_time'  : 0.0,
                'avg_speed'      : 0.0,
                'total_wait'     : 0.0,
                'error'          : str(e),
            }

    # ── HELPERS ───────────────────────────────────────────────────────────────

    def _zero_data(self, phase_idx: int) -> dict:
        return {
            'count'  : 0,
            'queue'  : 0,
            'wait'   : 0.0,
            'speed'  : 0.0,
            'density': 0.0,
            'lanes'  : [],
        }

    def get_max_observed(self) -> dict:
        """Current running maximums — used by test scripts for verification."""
        return {
            'max_density': self._max_density,
            'max_wait'   : self._max_wait,
            'max_queue'  : self._max_queue,
        }

    def debug_print(self, tlsID: str, raw: dict):
        """Human-readable data snapshot for a TLS. Use in debug mode."""
        print(f"\n[DATA] TLS '{tlsID}' @ step {self._step_count}:")
        if not raw:
            print("  (no data — TLS invalid or no green phases)")
            return
        for phase_idx, d in raw.items():
            print(
                f"  Phase {phase_idx:2d}: "
                f"count={d['count']:3d} | "
                f"queue={d['queue']:3d} | "
                f"wait={d['wait']:8.2f}s | "
                f"density={d['density']:.5f} v/m | "
                f"speed={d['speed']:5.1f} m/s"
            )
        print(f"  Running maxes: density={self._max_density:.4f}, wait={self._max_wait:.1f}s, queue={self._max_queue:.0f}")
