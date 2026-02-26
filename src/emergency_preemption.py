"""
emergency_preemption.py  (v6 — correct full-approach green)
=======================
Emergency Vehicle Preemption (EVP) engine.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DESIGN HISTORY — what each version fixed and what it broke
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

v4: Used single link_index from getNextTLS() → 1/12 links green.
    Ambulance stuck behind vehicles in adjacent lanes (India: no lane discipline).

v5: Added getRoadID() to find ambulance's current edge, then matched
    getControlledLinks() from_lanes against it.
    BUG: getRoadID() returns ambulance's CURRENT position edge.
         getControlledLinks() from_lane is the STOP-LINE edge.
         At 150m away: different road segments → different edge IDs → no match.
         FALLBACK fired for approaching vehicles → back to 1 link green.
    ALSO BROKE: detection range raised to 300m → 3 junctions preempted
         simultaneously at spawn point before ambulance even moved.

v6 (THIS VERSION) — Correct algorithm:
    Use getControlledLinks(tls_id)[link_indices[0]] to get the from_lane
    of the ambulance's SPECIFIC confirmed link (from getNextTLS).
    Extract its from_edge (the stop-line edge for this approach).
    Find ALL other links in the junction with the SAME from_edge.
    Those are all the lanes from the same approach direction → all get green.

    WHY THIS WORKS where v5 failed:
      v5 compared: ambulance_current_edge vs controlled_links from_edge
                   (different road segments → mismatch)
      v6 compares: controlled_links[known_index] from_edge vs
                   controlled_links[all] from_edge
                   (both from SAME data source → always match correctly)

    Result: full-approach green at any distance, with or without junction.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FIXES KEPT FROM PREVIOUS VERSIONS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

From v4:
  - getRedYellowGreenState() for state string length (no mismatch crash)
  - setRedYellowGreenState() for instant override (bypasses phase program)
  - Dual detection: by AMBULANCE_ID and by vClass=emergency
  - _maintain_preemption re-applies override every step
  - AI suppression: mark_preempted() / mark_restored()
  - Restoration when ambulance passes each TLS or exits network

From v5:
  - setSpeedMode(23): removes min safe gap → ambulance tailgates queue
  - setProgram() BEFORE setPhase() on restoration (fixes [0,0] crash)
  - getProgram() saved at preemption time (restores exact saved program)
  - Early return after static detection (no same-step fallthrough)

Detection range: 150m (reverted from 300m — correct algorithm makes range irrelevant
  to correctness, and 150m avoids premature multi-junction preemption at spawn)
"""

import traci
from config import (
    AMBULANCE_ID,
    AMBULANCE_TYPE,
    AMBULANCE_ROUTE_ID,
    AMBULANCE_DETECTION_RANGE,
    AMBULANCE_DEPART_TIME,
    SPAWN_AMBULANCE_DYNAMICALLY,
    EMERGENCY_HOLD_DURATION,
)

EMERGENCY_VCLASS = "emergency"


class EmergencyPreemptionEngine:
    """
    Manages emergency vehicle preemption for all emergency-class vehicles.

    Usage:
        engine = EmergencyPreemptionEngine(ai_controller)
        engine.setup_ambulance_route()       # once after traci.start()

        # Every step, BEFORE ai_controller.step():
        engine.step(current_sim_time, current_step)
        preempted = engine.get_preempted_tls()
    """

    def __init__(self, ai_controller):
        self._ai_ctrl = ai_controller

        self._preempted_tls   = set()
        self._saved_states    = {}   # {tlsID: {'phase':int, 'program':str, 'step':int}}
        self._override_states = {}   # {tlsID: state_string}

        self._ambulance_added   = False
        self._ambulance_arrived = False
        self._ambulance_active  = False

        self._events = []

    # ─────────────────────────────────────────────────────────────────────────
    # SETUP
    # ─────────────────────────────────────────────────────────────────────────

    def setup_ambulance_route(self):
        """Call once after traci.start(). Logs config only."""
        print(f"[EMERGENCY] Ambulance ID       : '{AMBULANCE_ID}'")
        print(f"[EMERGENCY] Detection range    : {AMBULANCE_DETECTION_RANGE}m")
        print(f"[EMERGENCY] Dynamic spawn      : {SPAWN_AMBULANCE_DYNAMICALLY}")
        print(f"[EMERGENCY] Override mode      : FULL APPROACH (v6 — stop-line edge match)")
        print(f"[EMERGENCY] Speed mode         : 23 (tight following, no min gap)")
        if SPAWN_AMBULANCE_DYNAMICALLY:
            print(f"[EMERGENCY] Will spawn at t    : {AMBULANCE_DEPART_TIME}s")
        else:
            print(f"[EMERGENCY] Ambulance defined in routes.rou.xml")

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN UPDATE
    # ─────────────────────────────────────────────────────────────────────────

    def step(self, sim_time: float, current_step: int):
        """Call every simulation step, before ai_controller.step()."""

        # Dynamic spawn
        if SPAWN_AMBULANCE_DYNAMICALLY and not self._ambulance_added:
            if sim_time >= AMBULANCE_DEPART_TIME:
                self._spawn_ambulance()

        # Static mode: detect ambulance entering network.
        # Return immediately after detection — do not fall through into the
        # active-vehicle checks in the same step. getNextTLS() needs one
        # full step to return results for a freshly-spawned vehicle.
        if not SPAWN_AMBULANCE_DYNAMICALLY and not self._ambulance_added:
            self._detect_static_ambulance()
            return

        if not self._ambulance_active:
            return

        # Find all emergency vehicles in network
        all_vehicles   = traci.vehicle.getIDList()
        emergency_vehs = self._find_emergency_vehicles(all_vehicles)

        # Ambulance has left network — restore everything and mark done
        if not emergency_vehs:
            if self._ambulance_added and not self._ambulance_arrived:
                print(f"[EMERGENCY] All emergency vehicles have left the network")
                self._restore_all(current_step)
                self._ambulance_arrived = True
                self._ambulance_active  = False
            return

        # Build the set of TLS within detection range this step
        tls_in_range_this_step = set()
        for veh_id in emergency_vehs:
            self._process_one_vehicle(veh_id, current_step, tls_in_range_this_step)

        # Restore TLS that ambulance has moved past
        passed_tls = self._preempted_tls - tls_in_range_this_step
        for tls_id in list(passed_tls):
            self._restore_tls(tls_id, current_step)

    # ─────────────────────────────────────────────────────────────────────────
    # DETECTION
    # ─────────────────────────────────────────────────────────────────────────

    def _detect_static_ambulance(self):
        """
        Dual detection: by AMBULANCE_ID first, then by vClass=emergency.
        Applies speed override on first detection.
        """
        all_vehicles = traci.vehicle.getIDList()

        if AMBULANCE_ID in all_vehicles:
            self._ambulance_added  = True
            self._ambulance_active = True
            self._apply_ambulance_overrides(AMBULANCE_ID)
            print(f"[EMERGENCY] Ambulance '{AMBULANCE_ID}' detected (by ID)")
            return

        for veh_id in all_vehicles:
            try:
                if traci.vehicle.getTypeID(veh_id) == EMERGENCY_VCLASS:
                    self._ambulance_added  = True
                    self._ambulance_active = True
                    self._apply_ambulance_overrides(veh_id)
                    print(f"[EMERGENCY] Emergency vehicle '{veh_id}' detected (by vClass)")
                    return
            except traci.exceptions.TraCIException:
                continue

    def _find_emergency_vehicles(self, all_vehicles: list) -> list:
        """Returns list of all emergency vehicle IDs currently in network."""
        result = []
        for veh_id in all_vehicles:
            if veh_id == AMBULANCE_ID:
                result.append(veh_id)
                continue
            try:
                if traci.vehicle.getTypeID(veh_id) == EMERGENCY_VCLASS:
                    result.append(veh_id)
            except traci.exceptions.TraCIException:
                continue
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # SPEED OVERRIDE  (applied once at first detection)
    # ─────────────────────────────────────────────────────────────────────────

    def _apply_ambulance_overrides(self, veh_id: str):
        """
        Remove minimum safe following gap so ambulance pushes through queues.

        setSpeedMode(23) = binary 010111:
          bit 0 = 1  obey safe speed             (no suicidal acceleration)
          bit 1 = 1  follow speed on
          bit 2 = 1  apply junction right-of-way
          bit 3 = 0  do NOT keep safe gap to leader  ← key change
                     ambulance drives right up to queued vehicles
          bit 4 = 1  allow emergency deceleration
          bit 5 = 0  keep collision checks        (no overlap/teleport)

        Does NOT use mode 7 — that disables collision, causing teleportation.
        """
        try:
            traci.vehicle.setSpeedMode(veh_id, 23)
            traci.vehicle.setColor(veh_id, (255, 0, 0, 255))
            print(f"[EMERGENCY] Overrides applied to '{veh_id}': "
                  f"mode=23 (no min gap), color=red")
        except traci.exceptions.TraCIException as e:
            print(f"[EMERGENCY] Could not apply overrides to '{veh_id}': {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # PER-VEHICLE PROCESSING
    # ─────────────────────────────────────────────────────────────────────────

    def _process_one_vehicle(self, veh_id: str, current_step: int,
                             tls_in_range: set):
        """
        Find upcoming TLS for one emergency vehicle.
        Collects all link indices per TLS, then calls preempt or maintain.
        """
        try:
            upcoming_tls = traci.vehicle.getNextTLS(veh_id)
        except traci.exceptions.TraCIException:
            return

        tls_links    = {}   # {tlsID: [link_index, ...]}
        tls_distance = {}   # {tlsID: float}

        for (tls_id, tls_index, distance, state) in upcoming_tls:
            if 0 <= distance <= AMBULANCE_DETECTION_RANGE:
                tls_in_range.add(tls_id)
                if tls_id not in tls_links:
                    tls_links[tls_id]    = []
                    tls_distance[tls_id] = distance
                tls_links[tls_id].append(tls_index)

        for tls_id, link_indices in tls_links.items():
            if tls_id not in self._preempted_tls:
                self._preempt_tls(tls_id, link_indices, veh_id,
                                  current_step, tls_distance[tls_id])
            else:
                self._maintain_preemption(tls_id)

    # ─────────────────────────────────────────────────────────────────────────
    # PREEMPTION CORE
    # ─────────────────────────────────────────────────────────────────────────

    def _preempt_tls(self, tls_id: str, link_indices: list, veh_id: str,
                     current_step: int, distance: float):
        """
        Apply emergency override. Saves current program+phase for restoration.
        Builds full-approach green state.
        """
        try:
            current_phase   = traci.trafficlight.getPhase(tls_id)
            current_program = traci.trafficlight.getProgram(tls_id)
            self._saved_states[tls_id] = {
                'phase'  : current_phase,
                'program': current_program,
                'step'   : current_step,
            }

            override_state = self._build_full_approach_state(tls_id, link_indices)
            if override_state is None:
                print(f"[EMERGENCY] Could not build state for '{tls_id}' — skipping")
                return

            traci.trafficlight.setRedYellowGreenState(tls_id, override_state)
            self._override_states[tls_id] = override_state

            self._preempted_tls.add(tls_id)
            self._ai_ctrl.mark_preempted(tls_id)

            green_count = override_state.count('G')
            total_links = len(override_state)
            self._events.append({
                'type'    : 'PREEMPTED',
                'tls_id'  : tls_id,
                'step'    : current_step,
                'distance': distance,
                'state'   : override_state,
                'veh_id'  : veh_id,
            })
            print(
                f"[EMERGENCY] PREEMPTED '{tls_id[:40]}' "
                f"('{veh_id}' at {distance:.1f}m) "
                f"{green_count}/{total_links} links green "
                f"state='{override_state}'"
            )

        except traci.exceptions.TraCIException as e:
            print(f"[EMERGENCY] Preemption failed for '{tls_id}': {e}")

    def _build_full_approach_state(self, tls_id: str, link_indices: list) -> str:
        """
        Build override state that greens ALL signal links from the same
        approach direction as the ambulance — not just the ambulance's lane.

        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        THE CORRECT ALGORITHM (v6):
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

        link_indices comes from getNextTLS() which gives us the EXACT link
        index the ambulance will use at this junction. This is confirmed
        by SUMO — it's the actual connection the ambulance is routed through.

        getControlledLinks(tls_id) returns a list of lists indexed by link
        number. Each entry: [(from_lane, to_lane, via_lane)].
        from_lane is the STOP-LINE lane on the approach road.
        Format: "edgeID_laneNumber"  e.g. "330762152_0" or "-69097264#0_1"

        Step 1: Extract the from_edge of the ambulance's confirmed link:
                ref = getControlledLinks(tls_id)[link_indices[0]][0][0]
                ref_edge = ref.rsplit('_', 1)[0]

        Step 2: Scan ALL links for the same from_edge:
                for i, link_list in enumerate(controlled_links):
                    for (from_lane, _, _) in link_list:
                        if from_lane.rsplit('_',1)[0] == ref_edge:
                            state_chars[i] = 'G'

        WHY THIS WORKS (and why v5's getRoadID approach did not):
          v5 compared:  ambulance_current_road_edge  vs  stop_line_edge
                        These are DIFFERENT road segments → mismatch → fallback
          v6 compares:  stop_line_edge_of_known_link  vs  stop_line_edge_of_all_links
                        Both come from getControlledLinks → always same format → match

          Works at ANY distance (30m or 300m) because we never use the
          ambulance's current position — we use the confirmed link index.
          Works when ambulance is inside junction because link_indices are
          for the NEXT junction (ahead), not the current one being traversed.

        LENGTH SAFETY:
          State string length from getRedYellowGreenState() — always matches
          the online running program. Immune to program-switching crashes.

        FALLBACK:
          If getControlledLinks fails, or link_indices[0] is out of range,
          fall back to greening only the confirmed link_indices. This is
          still better than nothing and never panics.
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        """
        try:
            # Get the current online state — its length is always correct
            current_state = traci.trafficlight.getRedYellowGreenState(tls_id)
            if not current_state:
                return None
            total_links = len(current_state)
            state_chars = ['r'] * total_links

            gave_green  = False
            ref_edge    = None

            # ── PRIMARY: stop-line edge matching ─────────────────────────────
            try:
                controlled_links = traci.trafficlight.getControlledLinks(tls_id)

                # Step 1: get the stop-line from_edge for the ambulance's link
                ref_idx = link_indices[0]
                if (ref_idx < len(controlled_links)
                        and controlled_links[ref_idx]):
                    ref_from_lane = controlled_links[ref_idx][0][0]
                    ref_edge = ref_from_lane.rsplit('_', 1)[0]

                # Step 2: green every link whose from_edge matches
                if ref_edge:
                    for i, link_list in enumerate(controlled_links):
                        if i >= total_links:
                            break
                        for (from_lane, _to, _via) in link_list:
                            from_edge = from_lane.rsplit('_', 1)[0]
                            if from_edge == ref_edge:
                                state_chars[i] = 'G'
                                gave_green = True
                                break   # this index done, move to next

            except (traci.exceptions.TraCIException, IndexError):
                pass   # fall through to fallback

            # ── FALLBACK: use exact link_indices from getNextTLS() ────────────
            if not gave_green:
                for idx in link_indices:
                    if 0 <= idx < total_links:
                        state_chars[idx] = 'G'
                        gave_green = True
                if gave_green:
                    print(f"[EMERGENCY]   Fallback (link-index) for '{tls_id[:35]}'")

            # ── ULTIMATE FALLBACK: index 0 ────────────────────────────────────
            if not gave_green:
                state_chars[0] = 'G'
                print(f"[EMERGENCY]   Ultimate fallback (idx 0) for '{tls_id[:35]}'")

            result = "".join(state_chars)
            green_count = result.count('G')
            approach_info = f"approach='{ref_edge}'" if ref_edge else "approach=unknown"
            print(f"[EMERGENCY]   {green_count}/{total_links} links green | {approach_info}")
            return result

        except traci.exceptions.TraCIException as e:
            print(f"[EMERGENCY] Build state failed for '{tls_id}': {e}")
            return None

    def _maintain_preemption(self, tls_id: str):
        """Re-apply override every step — SUMO resumes its program otherwise."""
        if tls_id in self._override_states:
            try:
                traci.trafficlight.setRedYellowGreenState(
                    tls_id, self._override_states[tls_id]
                )
            except traci.exceptions.TraCIException:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    # RESTORATION
    # ─────────────────────────────────────────────────────────────────────────

    def _restore_tls(self, tls_id: str, current_step: int):
        """
        Restore one TLS to AI control after ambulance passes.

        CRITICAL — TWO-STEP RESTORE (setProgram then setPhase):
          setRedYellowGreenState() creates an anonymous single-phase online
          program in SUMO. After it runs, the TLS only has phase 0 valid.
          Calling setPhase(N) where N > 0 then raises:
            'phase index N is not in allowed range [0,0]'
          and the TLS stays permanently frozen at the override state.

          Fix: setProgram(saved_program) first — this reloads the full
          multi-phase program so all its phases become valid again.
          Then setPhase(saved_phase) succeeds for any valid N.

          We save the program ID (getProgram) at preemption time so we
          always restore the EXACT program that was running before override.
        """
        try:
            saved = self._saved_states.get(tls_id)
            if saved:
                # Step 1: reload the original multi-phase program
                saved_program = saved.get('program', '0')
                traci.trafficlight.setProgram(tls_id, saved_program)
                # Step 2: jump back to the saved phase (now valid again)
                traci.trafficlight.setPhase(tls_id, saved['phase'])

            self._preempted_tls.discard(tls_id)
            self._ai_ctrl.mark_restored(tls_id, current_step)

            self._saved_states.pop(tls_id, None)
            self._override_states.pop(tls_id, None)

            self._events.append({
                'type'  : 'RESTORED',
                'tls_id': tls_id,
                'step'  : current_step,
            })
            print(f"[EMERGENCY] RESTORED '{tls_id[:40]}' to AI control")

        except traci.exceptions.TraCIException as e:
            print(f"[EMERGENCY] Restore failed for '{tls_id}': {e}")
            # Ensure TLS is removed from preempted set even on error
            self._preempted_tls.discard(tls_id)
            self._ai_ctrl.mark_restored(tls_id, current_step)
            self._saved_states.pop(tls_id, None)
            self._override_states.pop(tls_id, None)

    def _restore_all(self, current_step: int):
        """Restore all preempted TLS. Called when ambulance exits network."""
        for tls_id in list(self._preempted_tls):
            self._restore_tls(tls_id, current_step)

    # ─────────────────────────────────────────────────────────────────────────
    # DYNAMIC SPAWN
    # ─────────────────────────────────────────────────────────────────────────

    def _spawn_ambulance(self):
        """Dynamic spawn via TraCI. Route must exist in routes.rou.xml."""
        try:
            traci.vehicle.add(
                vehID       = AMBULANCE_ID,
                routeID     = AMBULANCE_ROUTE_ID,
                typeID      = AMBULANCE_TYPE,
                depart      = "now",
                departLane  = "best",
                departSpeed = "max",
            )
            self._apply_ambulance_overrides(AMBULANCE_ID)
            self._ambulance_added  = True
            self._ambulance_active = True
            print(f"[EMERGENCY] Ambulance '{AMBULANCE_ID}' spawned dynamically")

        except traci.exceptions.TraCIException as e:
            print(f"[EMERGENCY] Failed to spawn ambulance: {e}")
            self._ambulance_added  = True   # don't retry
            self._ambulance_active = False

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC INTERFACE
    # ─────────────────────────────────────────────────────────────────────────

    def get_preempted_tls(self) -> set:
        return self._preempted_tls.copy()

    def is_ambulance_active(self) -> bool:
        return self._ambulance_active

    def get_event_log(self) -> list:
        return self._events.copy()

    def get_summary(self) -> dict:
        preemptions  = [e for e in self._events if e['type'] == 'PREEMPTED']
        restorations = [e for e in self._events if e['type'] == 'RESTORED']
        return {
            'total_preemptions'  : len(preemptions),
            'total_restorations' : len(restorations),
            'unique_tls_affected': len({e['tls_id'] for e in self._events}),
            'ambulance_arrived'  : self._ambulance_arrived,
        }
