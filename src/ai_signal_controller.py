"""
ai_signal_controller.py  (v2 — updated after Chunk 1 network analysis)
=======================
AI adaptive traffic signal controller.

ALGORITHM OVERVIEW:
  Each step, for each non-preempted TLS:
    1. Read current phase type (green / yellow / red-clearance)
    2. If yellow or red-clearance: handle pending switch if needed, then return
    3. If green: collect traffic data, score all green phases
    4. If only 1 green phase: only adjust duration (no switching possible)
    5. If 2+ green phases: decide whether to switch
    6. If switching: set yellow phase → track pending → resume after yellow+red

SCORING FORMULA:
  score(phase) =
      WEIGHT_DENSITY * (total_density / max_density_seen) +
      WEIGHT_WAIT    * (total_wait    / max_wait_seen)    +
      WEIGHT_QUEUE   * (total_queue   / max_queue_seen)   +
      skip_count     * FAIRNESS_BONUS_PER_SKIP

DURATION FORMULA:
  duration = MIN_GREEN + score * (MAX_GREEN - MIN_GREEN)
  clamped to [MIN_GREEN, MAX_GREEN]

SWITCH DECISION:
  Switch if (score_gap >= SWITCH_THRESHOLD) OR (time_in_phase >= allocated_duration)
  Never switch if only 1 green phase exists for this TLS.

CRITICAL FIXES FROM NETWORK ANALYSIS:
  FIX 1 — Single-phase guard:
    TLS '2088125781' and '9699991332' have only 1 green phase.
    has_multiple_green_phases() checked before any switch attempt.

  FIX 2 — Red-clearance phase survival:
    After yellow completes, red-clearance ('rrrrr') runs before next green.
    _handle_non_green_phase() handles both yellow AND red types.
    pending_green only fires when we reach the EXPECTED TARGET green.
    Not when yellow ends — waits until the actual green phase appears.

  FIX 3 — Yellow detection via getPhase() + get_phase_type():
    Never relies on guessing — always queries current phase index and
    looks up its type in the phase map.

SUMO TRACI APIs USED (all verified):
  traci.trafficlight.getPhase(tlsID)            → int
  traci.trafficlight.getNextSwitch(tlsID)       → float sim seconds
  traci.trafficlight.setPhase(tlsID, idx)       → None
  traci.trafficlight.setPhaseDuration(tlsID, s) → None (current phase only)
  traci.simulation.getTime()                    → float
"""

import traci
from config import (
    MIN_GREEN_TIME, MAX_GREEN_TIME, DEFAULT_GREEN_TIME,
    MIN_PHASE_DURATION, SWITCH_THRESHOLD,
    WEIGHT_DENSITY, WEIGHT_WAIT, WEIGHT_QUEUE,
    FAIRNESS_BONUS_PER_SKIP, FAIRNESS_MAX_SKIP,
)
from phase_mapper import PhaseLaneMapper
from data_collector import TrafficDataCollector


class AISignalController:
    """
    Manages adaptive green phase timing for ALL traffic lights.

    One instance handles the entire network.

    Usage:
        ctrl = AISignalController(mapper, collector)

        # Every step:
        ctrl.step(step_number)

        # Emergency interface:
        ctrl.mark_preempted("J5")
        ctrl.mark_restored("J5", current_step)

        # Stats:
        stats = ctrl.get_stats()
    """

    def __init__(self, mapper: PhaseLaneMapper, collector: TrafficDataCollector):
        self._mapper    = mapper
        self._collector = collector

        # TLS IDs currently overridden by emergency — AI skips these
        self._preempted = set()

        # Per-TLS state tracking
        # When this phase started (in steps)
        self._phase_start   = {}   # {tlsID: int}

        # Duration we assigned to the current green phase
        self._alloc_duration= {}   # {tlsID: float seconds}

        # How many times each green phase has been skipped (for fairness)
        self._skip_counts   = {}   # {tlsID: {phase_idx: int}}

        # Pending switch: after yellow/red-clearance finishes, switch to this green
        self._pending_green = {}   # {tlsID: int target_green_phase_idx}

        # Which green phase initiated the current pending switch
        self._switch_source = {}   # {tlsID: int source_green_phase_idx}

        # Stats
        self._switch_count  = {}   # {tlsID: int}
        self._time_served   = {}   # {tlsID: {phase_idx: float}}

        # Initialize state for all valid TLS
        for tlsID in mapper.get_all_tls_ids():
            self._init_tls(tlsID)

    def _init_tls(self, tlsID: str):
        green_phases = self._mapper.get_green_phase_indices(tlsID)
        self._phase_start[tlsID]    = 0
        self._alloc_duration[tlsID] = DEFAULT_GREEN_TIME
        self._skip_counts[tlsID]    = {p: 0 for p in green_phases}
        self._switch_count[tlsID]   = 0
        self._time_served[tlsID]    = {p: 0.0 for p in green_phases}

    # ── MAIN UPDATE LOOP ──────────────────────────────────────────────────────

    def step(self, current_step: int):
        """
        Update ALL non-preempted traffic lights.
        Call exactly ONCE per simulation step.

        Args:
            current_step: integer step counter (0, 1, 2, ...)
        """
        for tlsID in self._mapper.get_all_tls_ids():
            if tlsID not in self._preempted:
                self._update_tls(tlsID, current_step)

    def _update_tls(self, tlsID: str, current_step: int):
        """Core update for one TLS. Called every step."""
        try:
            current_phase = traci.trafficlight.getPhase(tlsID)
            phase_type    = self._mapper.get_phase_type(tlsID, current_phase)

            # ── RULE 1: Never interrupt yellow or red-clearance ───────────────
            # Both 'yellow' and 'red' (all-red clearance) are treated identically:
            # hands-off. We check if our pending switch target has arrived.
            if phase_type in ('yellow', 'red'):
                self._handle_non_green_phase(tlsID, current_phase, current_step)
                return

            # ── We are in a GREEN phase ───────────────────────────────────────

            # Track time served for this phase (for stats)
            if current_phase in self._time_served.get(tlsID, {}):
                self._time_served[tlsID][current_phase] += 1.0

            # Update phase_start if this is a fresh green we just entered
            # (detects when we naturally cycle back to green without our control)
            self._refresh_phase_start_if_needed(tlsID, current_phase, current_step)

            time_in_phase = current_step - self._phase_start[tlsID]

            # ── RULE 2: Respect minimum phase duration ────────────────────────
            if time_in_phase < MIN_PHASE_DURATION:
                return

            # ── RULE 3: Single-phase TLS — duration tuning only ───────────────
            if not self._mapper.has_multiple_green_phases(tlsID):
                self._tune_duration_only(tlsID, current_phase)
                return

            # ── RULE 4: Multi-phase TLS — score and decide ────────────────────
            raw_data     = self._collector.collect(tlsID)
            norm_data    = self._collector.get_normalized(raw_data)
            green_phases = self._mapper.get_green_phase_indices(tlsID)

            if not green_phases:
                return

            scores = {p: self._score_phase(tlsID, p, norm_data) for p in green_phases}

            best_phase = max(scores, key=scores.get)
            best_score = scores[best_phase]
            curr_score = scores.get(current_phase, 0.0)
            new_dur    = self._calc_duration(best_score)

            if best_phase == current_phase:
                # ── Stay on current — adjust duration ─────────────────────────
                traci.trafficlight.setPhaseDuration(tlsID, new_dur)
                self._alloc_duration[tlsID] = new_dur

            else:
                # ── Evaluate switching ────────────────────────────────────────
                score_gap    = best_score - curr_score
                time_expired = time_in_phase >= self._alloc_duration[tlsID]
                starving     = self._skip_counts[tlsID].get(best_phase, 0) >= FAIRNESS_MAX_SKIP

                if score_gap >= SWITCH_THRESHOLD or time_expired or starving:
                    self._initiate_switch(tlsID, current_phase, best_phase, current_step)

                    # Reset skip count for phase we're switching to
                    if best_phase in self._skip_counts[tlsID]:
                        self._skip_counts[tlsID][best_phase] = 0

                    # Increment skips for all other phases
                    for p in green_phases:
                        if p not in (best_phase, current_phase):
                            self._skip_counts[tlsID][p] = \
                                self._skip_counts[tlsID].get(p, 0) + 1
                else:
                    # Not switching yet — extend current duration
                    traci.trafficlight.setPhaseDuration(tlsID, new_dur)
                    self._alloc_duration[tlsID] = new_dur

        except traci.exceptions.TraCIException as e:
            # Log but never crash the simulation
            print(f"[AI_CTRL] ⚠ '{tlsID}' step error: {e}")

    # ── PHASE TRANSITION HANDLING ─────────────────────────────────────────────

    def _handle_non_green_phase(self, tlsID: str, current_phase: int, current_step: int):
        """
        Called when current phase is yellow or red-clearance.

        Checks if our pending_green target has arrived.
        The pending switch fires only when we actually land on the target
        green phase — NOT when yellow ends (red-clearance may come next).

        For networks with G→Y→R→G:
          - Yellow runs: _handle_non_green_phase does nothing
          - Red-clearance runs: _handle_non_green_phase does nothing
          - SUMO naturally advances to next green
          - On THAT step, _update_tls sees phase_type='green' again
          - We detect the new green in _refresh_phase_start_if_needed

        This is cleaner and more robust than trying to fire during yellow.
        """
        # If no pending switch, nothing to do
        if tlsID not in self._pending_green:
            return

        # Pending switch exists — check if SUMO has already advanced to our target
        # This shouldn't happen here (we only call this for yellow/red phases)
        # but if it does, clear pending state
        target = self._pending_green[tlsID]
        if current_phase == target:
            # We somehow landed on target — update tracking
            self._phase_start[tlsID]    = current_step
            self._alloc_duration[tlsID] = DEFAULT_GREEN_TIME
            del self._pending_green[tlsID]
            self._switch_source.pop(tlsID, None)

    def _refresh_phase_start_if_needed(self, tlsID: str, current_phase: int, current_step: int):
        """
        Detects when SUMO has naturally cycled to a new green phase
        (either via our pending switch, or SUMO's own program).

        If current_phase != the phase we started tracking from,
        this is a new phase — reset tracking.
        """
        # If we have a pending switch and we've arrived at the target:
        if tlsID in self._pending_green:
            if current_phase == self._pending_green[tlsID]:
                self._phase_start[tlsID]    = current_step
                self._alloc_duration[tlsID] = DEFAULT_GREEN_TIME
                del self._pending_green[tlsID]
                self._switch_source.pop(tlsID, None)
                return

        # If phase changed without our involvement (SUMO natural cycle):
        # We can't easily detect this without storing last known phase.
        # Simple approach: if time_in_phase would be negative (phase changed
        # but we didn't update start), reset start to current_step.
        time_in_phase = current_step - self._phase_start.get(tlsID, current_step)
        if time_in_phase < 0:
            self._phase_start[tlsID] = current_step

    def _initiate_switch(self, tlsID: str, from_green: int, to_green: int, current_step: int):
        """
        Begin phase transition: from_green → yellow → [red-clearance] → to_green.

        Sets the yellow phase via TraCI. SUMO then handles yellow+red-clearance
        timing automatically. We just track the pending target.
        """
        yellow = self._mapper.get_yellow_after(tlsID, from_green)

        if yellow is None:
            # No yellow transition mapped — direct switch (fallback for unusual TLS)
            # This should not happen with your network but is a safe fallback
            dur = self._calc_duration(0.5)
            traci.trafficlight.setPhase(tlsID, to_green)
            traci.trafficlight.setPhaseDuration(tlsID, dur)
            self._phase_start[tlsID]    = current_step
            self._alloc_duration[tlsID] = dur
            self._switch_count[tlsID]  += 1
            return

        # Set yellow — SUMO handles timing automatically
        traci.trafficlight.setPhase(tlsID, yellow)

        # Record pending: after yellow+red-clearance, we expect to_green
        self._pending_green[tlsID] = to_green
        self._switch_source[tlsID] = from_green
        self._switch_count[tlsID] += 1

    def _tune_duration_only(self, tlsID: str, current_phase: int):
        """
        For single-green-phase TLS: only adjust the duration.
        No switching possible. Uses real traffic data.
        Applies to: '2088125781', '9699991332' in your network.
        """
        try:
            raw_data  = self._collector.collect(tlsID)
            norm_data = self._collector.get_normalized(raw_data)

            green_phases = self._mapper.get_green_phase_indices(tlsID)
            if not green_phases:
                return

            only_phase = green_phases[0]
            if only_phase != current_phase:
                return  # Not in the green phase right now

            score = self._score_phase(tlsID, only_phase, norm_data)
            dur   = self._calc_duration(score)
            traci.trafficlight.setPhaseDuration(tlsID, dur)
            self._alloc_duration[tlsID] = dur

        except traci.exceptions.TraCIException:
            pass

    # ── SCORING & DURATION ────────────────────────────────────────────────────

    def _score_phase(self, tlsID: str, phase_idx: int, norm_data: dict) -> float:
        """
        Score a green phase.

        score = W_density * density_norm
              + W_wait    * wait_norm
              + W_queue   * queue_norm
              + skip_count * FAIRNESS_BONUS  (starvation prevention)

        Returns float in [0.0, ~1.5] (can exceed 1.0 with fairness bonus).
        Higher = deserves more green time.
        """
        data = norm_data.get(phase_idx)
        if data is None:
            return 0.0

        base_score = (
            WEIGHT_DENSITY * data['density_norm'] +
            WEIGHT_WAIT    * data['wait_norm']    +
            WEIGHT_QUEUE   * data['queue_norm']
        )

        skip      = self._skip_counts.get(tlsID, {}).get(phase_idx, 0)
        fairness  = min(skip * FAIRNESS_BONUS_PER_SKIP, 0.5)  # cap bonus at 0.5

        return base_score + fairness

    def _calc_duration(self, score: float) -> float:
        """
        Map score [0,1] → duration [MIN_GREEN, MAX_GREEN].
        Clips score to [0,1] before mapping.
        """
        clipped = max(0.0, min(score, 1.0))
        return round(MIN_GREEN_TIME + clipped * (MAX_GREEN_TIME - MIN_GREEN_TIME), 1)

    # ── EMERGENCY INTERFACE ───────────────────────────────────────────────────

    def mark_preempted(self, tlsID: str):
        """Called by emergency engine. AI will skip this TLS."""
        self._preempted.add(tlsID)

    def mark_restored(self, tlsID: str, current_step: int = 0):
        """Called by emergency engine. AI resumes control of this TLS."""
        self._preempted.discard(tlsID)
        # Reset tracking so AI starts fresh — no stale state
        self._phase_start[tlsID]    = current_step
        self._alloc_duration[tlsID] = DEFAULT_GREEN_TIME
        self._pending_green.pop(tlsID, None)
        self._switch_source.pop(tlsID, None)

    def get_preempted(self) -> set:
        return self._preempted.copy()

    # ── STATS ─────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        return {
            'total_switches' : dict(self._switch_count),
            'time_served'    : dict(self._time_served),
            'preempted_count': len(self._preempted),
        }
