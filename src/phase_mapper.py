"""
phase_mapper.py  (v2 — updated after Chunk 1 network analysis)
===============
Builds the phase → lane mapping for every traffic light in the network.
Called ONCE at startup after traci.start(). Results cached for entire run.

VERIFIED AGAINST YOUR ACTUAL NETWORK (Chunk 1 output):
  TLS '2088125781': 3 phases → GREEN(0), YELLOW(1), RED-CLEARANCE(2)
  TLS '2252147416': 4 phases → GREEN(0), YELLOW(1), GREEN(2), YELLOW(3)
  TLS '9699991332': 3 phases → GREEN(0), YELLOW(1), RED-CLEARANCE(2)
  Mixed state 'yyrrG' exists — yellow transition with residual green

CRITICAL FIXES APPLIED:
  FIX 1 — Red-clearance ('rrrrr') classified as 'red', skipped by AI
  FIX 2 — has_multiple_green_phases() guards AI from switching on 1-phase TLS
  FIX 3 — Transition map correctly skips red-clearance: G→Y→R→G
  FIX 4 — get_raw_controlled_lanes() exposed for emergency preemption
"""

import traci
from config import GREEN_CHARS, YELLOW_CHARS, RED_CHARS, is_yellow_state, is_green_state


class PhaseLaneMapper:
    def __init__(self):
        self._phase_lane_map    = {}   # {tlsID: {phase_idx: [laneID,...]}}
        self._phase_types       = {}   # {tlsID: {phase_idx: 'green'|'yellow'|'red'}}
        self._green_phases      = {}   # {tlsID: [idx,...]}
        self._yellow_phases     = {}   # {tlsID: [idx,...]}
        self._yellow_after_green= {}   # {tlsID: {green_idx: yellow_idx}}
        self._green_after_yellow= {}   # {tlsID: {yellow_idx: green_idx}}
        self._controlled_lanes  = {}   # {tlsID: [laneID,...]} deduplicated
        self._lane_lengths      = {}   # {laneID: float meters}
        self._invalid_tls       = set()
        self._built             = False

    # ── BUILD ─────────────────────────────────────────────────────────────────

    def build_all(self) -> int:
        """
        Build phase-lane maps for every TLS in the network.
        Call ONCE immediately after traci.start().
        Returns number of TLS successfully mapped.
        """
        all_tls = list(traci.trafficlight.getIDList())

        if not all_tls:
            raise RuntimeError(
                "[PHASE_MAPPER] No traffic lights found. "
                "Verify map.net.xml contains TLS junctions."
            )

        print(f"\n[PHASE_MAPPER] Discovered {len(all_tls)} traffic light(s)")
        print(f"[PHASE_MAPPER] Building maps...\n")

        valid = 0
        for tlsID in all_tls:
            if self._build_for_tls(tlsID):
                valid += 1

        print(f"\n[PHASE_MAPPER] ✓ {valid}/{len(all_tls)} TLS mapped")
        if self._invalid_tls:
            print(f"[PHASE_MAPPER] ⚠ Skipped: {self._invalid_tls}")

        self._built = True
        return valid

    def _build_for_tls(self, tlsID: str) -> bool:
        try:
            # Step 1: Controlled lanes (deduplicated)
            raw_lanes    = list(traci.trafficlight.getControlledLanes(tlsID))
            unique_lanes = list(dict.fromkeys(raw_lanes))
            self._controlled_lanes[tlsID] = unique_lanes

            for lane in unique_lanes:
                if lane not in self._lane_lengths:
                    try:
                        self._lane_lengths[lane] = traci.lane.getLength(lane)
                    except traci.exceptions.TraCIException:
                        self._lane_lengths[lane] = 100.0

            # Step 2: Phase definitions
            logics = traci.trafficlight.getAllProgramLogics(tlsID)
            if not logics or not logics[0].phases:
                print(f"  [SKIP] '{tlsID}': no phases found")
                self._invalid_tls.add(tlsID)
                return False

            phases = logics[0].phases
            n      = len(phases)

            # Step 3: Classify each phase + build lane map
            phase_lane_map = {}
            phase_types    = {}

            for idx, phase in enumerate(phases):
                state = phase.state

                # Green lanes: positions where signal char is G or g
                green_lanes = []
                for sig_pos, sig_char in enumerate(state):
                    if sig_pos < len(raw_lanes) and sig_char in GREEN_CHARS:
                        lane = raw_lanes[sig_pos]
                        if lane not in green_lanes:
                            green_lanes.append(lane)

                phase_lane_map[idx] = green_lanes

                # Classify — is_yellow_state correctly handles 'yyrrG' as yellow
                if is_yellow_state(state):
                    phase_types[idx] = 'yellow'
                elif is_green_state(state):
                    phase_types[idx] = 'green'
                else:
                    phase_types[idx] = 'red'   # all-red clearance

            self._phase_lane_map[tlsID] = phase_lane_map
            self._phase_types[tlsID]    = phase_types

            # Step 4: Index green and yellow phases
            greens  = [i for i in range(n) if phase_types[i] == 'green']
            yellows = [i for i in range(n) if phase_types[i] == 'yellow']
            reds    = [i for i in range(n) if phase_types[i] == 'red']

            self._green_phases[tlsID]  = greens
            self._yellow_phases[tlsID] = yellows

            if not greens:
                print(f"  [SKIP] '{tlsID}': no controllable green phases")
                self._invalid_tls.add(tlsID)
                return False

            # Step 5: Build Green→Yellow→Green transition maps
            # Walks forward from each green, finds next yellow, then next green
            # Automatically skips red-clearance phases between yellow and green
            yellow_after_green = {}
            green_after_yellow = {}

            for g_idx in greens:
                # Find next yellow after this green
                y_next = None
                for offset in range(1, n):
                    candidate = (g_idx + offset) % n
                    if phase_types[candidate] == 'yellow':
                        y_next = candidate
                        break

                if y_next is not None:
                    yellow_after_green[g_idx] = y_next

                    # Find next green after that yellow (skips red-clearance)
                    for offset2 in range(1, n):
                        candidate2 = (y_next + offset2) % n
                        if phase_types[candidate2] == 'green':
                            green_after_yellow[y_next] = candidate2
                            break

            self._yellow_after_green[tlsID] = yellow_after_green
            self._green_after_yellow[tlsID] = green_after_yellow

            # Step 6: Print per-TLS summary
            multi_tag = "MULTI-PHASE" if len(greens) > 1 else "SINGLE-PHASE (duration-only)"
            print(
                f"  ✓ '{tlsID[:50]}': "
                f"{n} phases | "
                f"green={greens} | "
                f"yellow={yellows} | "
                f"red={reds} | "
                f"{multi_tag}"
            )
            return True

        except traci.exceptions.TraCIException as e:
            print(f"  ✗ '{tlsID}': TraCI error — {e}")
            self._invalid_tls.add(tlsID)
            return False

    # ── PUBLIC ACCESSORS ──────────────────────────────────────────────────────

    def get_all_tls_ids(self) -> list:
        return list(self._phase_lane_map.keys())

    def get_invalid_tls_ids(self) -> set:
        return self._invalid_tls.copy()

    def get_green_phase_indices(self, tlsID: str) -> list:
        return self._green_phases.get(tlsID, [])

    def get_yellow_phase_indices(self, tlsID: str) -> list:
        return self._yellow_phases.get(tlsID, [])

    def get_green_lanes(self, tlsID: str, phase_idx: int) -> list:
        return self._phase_lane_map.get(tlsID, {}).get(phase_idx, [])

    def get_all_controlled_lanes(self, tlsID: str) -> list:
        return self._controlled_lanes.get(tlsID, [])

    def get_phase_type(self, tlsID: str, phase_idx: int) -> str:
        return self._phase_types.get(tlsID, {}).get(phase_idx, 'unknown')

    def get_yellow_after(self, tlsID: str, green_idx: int):
        """Yellow phase that follows green_idx. Returns None if not found."""
        return self._yellow_after_green.get(tlsID, {}).get(green_idx)

    def get_green_after_yellow(self, tlsID: str, yellow_idx: int):
        """
        Green phase that follows yellow_idx.
        Skips red-clearance phases automatically.
        Returns None if not found.
        """
        return self._green_after_yellow.get(tlsID, {}).get(yellow_idx)

    def has_multiple_green_phases(self, tlsID: str) -> bool:
        """
        True if this TLS has 2+ green phases (AI can switch between them).
        False = AI can only tune duration (e.g. '2088125781', '9699991332').
        """
        return len(self._green_phases.get(tlsID, [])) > 1

    def get_lane_length(self, laneID: str) -> float:
        return self._lane_lengths.get(laneID, 100.0)

    def is_valid_tls(self, tlsID: str) -> bool:
        return tlsID in self._phase_lane_map

    def get_total_phase_count(self, tlsID: str) -> int:
        return len(self._phase_lane_map.get(tlsID, {}))

    def get_raw_controlled_lanes(self, tlsID: str) -> list:
        """
        Raw (non-deduplicated) lane list — one entry per signal link.
        Used by emergency preemption for positional signal indexing.
        MUST NOT be deduplicated for this use case.
        """
        try:
            return list(traci.trafficlight.getControlledLanes(tlsID))
        except traci.exceptions.TraCIException:
            return []

    # ── DEBUG ─────────────────────────────────────────────────────────────────

    def debug_print(self, tlsID: str):
        if not self.is_valid_tls(tlsID):
            print(f"[PHASE_MAPPER] '{tlsID}' not mapped")
            return
        print(f"\n{'='*65}")
        print(f"PHASE MAP DEBUG: TLS '{tlsID}'")
        print(f"{'='*65}")
        print(f"  Unique lanes     : {self._controlled_lanes.get(tlsID)}")
        print(f"  Green phases     : {self._green_phases.get(tlsID)}")
        print(f"  Yellow phases    : {self._yellow_phases.get(tlsID)}")
        print(f"  Multi-phase AI   : {self.has_multiple_green_phases(tlsID)}")
        print()
        for idx, lanes in self._phase_lane_map.get(tlsID, {}).items():
            ptype  = self._phase_types.get(tlsID, {}).get(idx, '?')
            marker = ' ← AI controls' if ptype == 'green' else ''
            print(f"  Phase {idx:2d} [{ptype:10s}]: {lanes}{marker}")
        print(f"\n  Transition map:")
        for g, y in self._yellow_after_green.get(tlsID, {}).items():
            g2 = self._green_after_yellow.get(tlsID, {}).get(y, '?')
            print(f"    Green {g} → Yellow {y} → Green {g2}")
        print(f"{'='*65}\n")

    def print_full_network_summary(self):
        print(f"\n{'='*65}")
        print(f"NETWORK TLS SUMMARY ({len(self._phase_lane_map)} TLS mapped)")
        print(f"{'='*65}")
        print(f"  {'TLS ID':<45} {'Ph':>3} {'Gr':>3} {'Multi'}")
        print(f"  {'-'*58}")
        for tlsID in self._phase_lane_map:
            total  = self.get_total_phase_count(tlsID)
            greens = len(self._green_phases.get(tlsID, []))
            multi  = 'YES' if self.has_multiple_green_phases(tlsID) else 'NO'
            sid    = (tlsID[:43] + '..') if len(tlsID) > 45 else tlsID
            print(f"  {sid:<45} {total:>3} {greens:>3} {multi}")
        print(f"{'='*65}\n")
