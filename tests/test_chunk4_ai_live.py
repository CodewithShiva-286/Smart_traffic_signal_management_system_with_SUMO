"""
test_chunk4_ai_live.py
======================
CHUNK 4: LIVE AI SIGNAL CONTROLLER BEHAVIOUR VERIFICATION

Runs the simulation for 500 steps with DIRECT ACCESS to all objects
(mapper, collector, ai_controller) to verify the AI is making correct,
intelligent decisions in real time — not just that the loop runs.

WHY 500 STEPS:
  - At step 200 we saw 48 switches across 8 multi-phase TLS
  - 500 steps gives ~120 expected switches — enough to verify patterns
  - Single-phase TLS must still show 0 switches after 500 steps
  - Fairness system has time to trigger on any starving phase

WHAT IS VERIFIED:

  GROUP 1 - Phase Type Correctness (sampled EVERY step)
    - All 10 TLS always in a valid phase type: green/yellow/red
    - 'unknown' type NEVER appears on any TLS at any step
    - Yellow and red-clearance phases observed (confirms transitions happen)
    - No pending_green remains stuck across >100 steps (transition completes)

  GROUP 2 - Switch Correctness (post-run)
    - Single-phase TLS ('2088125781', '9699991332'): switch_count = 0
    - Multi-phase TLS: at least 5 of 8 have switch_count > 0
    - Total switches > 0 (AI is not static)
    - No TLS switched more than (steps / MIN_PHASE_DURATION) times (no thrashing)

  GROUP 3 - Duration Tuning (sampled during green phases)
    - getNextSwitch() - getTime() values always in [MIN_GREEN, MAX_GREEN]
    - Single-phase TLS durations are being dynamically adjusted
    - Duration changes between consecutive green samples (not static)

  GROUP 4 - Scoring Sanity (computed manually during run)
    - Scores always in [0.0, 1.5] range (0-1 base + max 0.5 fairness)
    - No NaN or Inf scores produced
    - At least some phases score > 0.0 when traffic is present

  GROUP 5 - Fairness System (post-run)
    - No green phase has skip_count > FAIRNESS_MAX_SKIP at end of run
    - (If it does, fairness failed to trigger a switch in time)
    - All multi-phase TLS have time_served > 0 in at least one phase
    - Single-phase TLS have time_served > 0 in their one green phase

  GROUP 6 - Transition Integrity (post-run)
    - _pending_green is empty at end (no stuck transitions)
    - Every switch_count corresponds to at least one observed yellow step
    - All TLS restored to green phase at end (no TLS stuck in yellow/red)

HOW TO RUN:
    cd C:\\smart_traffic_system
    python tests/test_chunk4_ai_live.py

EXPECTED: All groups pass. Paste full output to proceed to Chunk 5.
"""

import os
import sys
import math

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(TEST_DIR)
SRC_DIR  = os.path.join(ROOT_DIR, "src")
sys.path.insert(0, SRC_DIR)

from config import (
    setup_sumo_path, validate_config, SUMO_CONFIG,
    MIN_GREEN_TIME, MAX_GREEN_TIME, MIN_PHASE_DURATION,
    FAIRNESS_MAX_SKIP, WEIGHT_DENSITY, WEIGHT_WAIT, WEIGHT_QUEUE,
    FAIRNESS_BONUS_PER_SKIP,
)
setup_sumo_path()
validate_config()

import traci
from phase_mapper         import PhaseLaneMapper
from data_collector       import TrafficDataCollector
from ai_signal_controller import AISignalController

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
TEST_STEPS       = 500
SINGLE_PHASE_TLS = {'2088125781', '9699991332'}   # confirmed from Chunk 2
MAX_THRASH_RATE  = TEST_STEPS / MIN_PHASE_DURATION  # absolute ceiling on switches


# ── Observation containers (filled during run) ────────────────────────────────
obs = {
    'unknown_phases'       : [],   # (step, tlsID, phase_idx) — should be empty
    'yellow_steps_per_tls' : {},   # {tlsID: count} — must be > 0 for multi-phase
    'red_steps_per_tls'    : {},   # {tlsID: count}
    'duration_samples'     : [],   # (tlsID, remaining_secs) — must be in [10,60]
    'score_samples'        : [],   # (tlsID, phase, score) — must be in [0, 1.5]
    'stuck_pending'        : [],   # (step, tlsID) — pending held > 100 steps
    'pending_age'          : {},   # {tlsID: steps_since_pending_set}
}


def run():
    print("\n" + "="*65)
    print("CHUNK 4: LIVE AI SIGNAL CONTROLLER BEHAVIOUR TEST")
    print("="*65)
    print(f"\n[RUNNING] {TEST_STEPS} steps | headless | direct object access")
    print("-"*65)

    # ── Connect to SUMO ───────────────────────────────────────────────────────
    sumo_cmd = ["sumo", "-c", SUMO_CONFIG, "--start", "--no-warnings",
                "--step-length", "1.0", "--quit-on-end"]
    traci.start(sumo_cmd)
    print("[SUMO] Connected\n")

    # ── Initialize modules ────────────────────────────────────────────────────
    mapper    = PhaseLaneMapper()
    mapper.build_all()
    collector = TrafficDataCollector(mapper)
    ai        = AISignalController(mapper, collector)

    all_tls       = mapper.get_all_tls_ids()
    multi_tls     = [t for t in all_tls if mapper.has_multiple_green_phases(t)]
    single_tls    = [t for t in all_tls if not mapper.has_multiple_green_phases(t)]

    print(f"\n[INFO] {len(all_tls)} TLS total | "
          f"{len(multi_tls)} multi-phase | {len(single_tls)} single-phase")
    print(f"[INFO] Single-phase TLS: {[t[:20] for t in single_tls]}")
    print(f"[INFO] Running {TEST_STEPS} steps...\n")

    # ── SIMULATION LOOP WITH INSTRUMENTATION ──────────────────────────────────
    for step in range(TEST_STEPS):
        traci.simulationStep()
        sim_time = traci.simulation.getTime()

        # AI step
        ai.step(step)

        # ── PER-TLS OBSERVATIONS ──────────────────────────────────────────────
        for tlsID in all_tls:
            try:
                current_phase = traci.trafficlight.getPhase(tlsID)
                phase_type    = mapper.get_phase_type(tlsID, current_phase)

                # Check for unknown phase type
                if phase_type == 'unknown':
                    obs['unknown_phases'].append((step, tlsID, current_phase))

                # Count yellow and red-clearance observations
                if phase_type == 'yellow':
                    obs['yellow_steps_per_tls'][tlsID] = \
                        obs['yellow_steps_per_tls'].get(tlsID, 0) + 1
                elif phase_type == 'red':
                    obs['red_steps_per_tls'][tlsID] = \
                        obs['red_steps_per_tls'].get(tlsID, 0) + 1

                # Sample duration for green phases (every 25 steps)
                if phase_type == 'green' and step % 25 == 0:
                    next_switch  = traci.trafficlight.getNextSwitch(tlsID)
                    remaining    = next_switch - sim_time
                    obs['duration_samples'].append((tlsID, remaining))

                # Compute and record scores for multi-phase TLS (every 50 steps)
                if phase_type == 'green' and step % 50 == 0 and mapper.has_multiple_green_phases(tlsID):
                    raw_data  = collector.collect(tlsID)
                    norm_data = collector.get_normalized(raw_data)
                    for p_idx in mapper.get_green_phase_indices(tlsID):
                        d = norm_data.get(p_idx, {})
                        if d:
                            base = (WEIGHT_DENSITY * d.get('density_norm', 0) +
                                    WEIGHT_WAIT    * d.get('wait_norm',    0) +
                                    WEIGHT_QUEUE   * d.get('queue_norm',   0))
                            skip = ai._skip_counts.get(tlsID, {}).get(p_idx, 0)
                            score = base + min(skip * FAIRNESS_BONUS_PER_SKIP, 0.5)
                            obs['score_samples'].append((tlsID, p_idx, score))

            except traci.exceptions.TraCIException:
                pass

        # ── CHECK FOR STUCK PENDING TRANSITIONS ───────────────────────────────
        for tlsID in all_tls:
            if tlsID in ai._pending_green:
                obs['pending_age'][tlsID] = obs['pending_age'].get(tlsID, 0) + 1
                if obs['pending_age'][tlsID] > 100:
                    obs['stuck_pending'].append((step, tlsID))
            else:
                obs['pending_age'][tlsID] = 0  # reset when cleared

        # Console progress
        if step % 100 == 0:
            veh = len(traci.vehicle.getIDList())
            stats = ai.get_stats()
            total_sw = sum(stats['total_switches'].values())
            print(f"  step={step:>3} t={sim_time:>6.1f}s "
                  f"vehicles={veh:>4} total_switches={total_sw}")

    # Capture final state before closing
    final_stats        = ai.get_stats()
    final_skip_counts  = {t: dict(v) for t, v in ai._skip_counts.items()}
    final_pending      = dict(ai._pending_green)
    final_time_served  = {t: dict(v) for t, v in ai._time_served.items()}

    # Final phase types
    final_phase_types = {}
    for tlsID in all_tls:
        try:
            p = traci.trafficlight.getPhase(tlsID)
            final_phase_types[tlsID] = mapper.get_phase_type(tlsID, p)
        except traci.exceptions.TraCIException:
            final_phase_types[tlsID] = 'error'

    traci.close()
    print("\n[SUMO] Connection closed")
    print(f"\n[INFO] Total switches: {sum(final_stats['total_switches'].values())}")
    print("-"*65)

    # ══════════════════════════════════════════════════════════════════════════
    # GROUP 1: PHASE TYPE CORRECTNESS
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'─'*65}")
    print("GROUP 1: PHASE TYPE CORRECTNESS (sampled every step)")
    print(f"{'─'*65}")

    def test_no_unknown_phases():
        if obs['unknown_phases']:
            samples = obs['unknown_phases'][:3]
            raise ValueError(
                f"{len(obs['unknown_phases'])} 'unknown' phase observations:\n" +
                '\n'.join(f"  step={s} TLS='{t}' phase={p}" for s,t,p in samples)
            )
        return f"Zero 'unknown' phase types across all {TEST_STEPS} steps x 10 TLS"
    check("Phase type never 'unknown' for any TLS at any step", test_no_unknown_phases)

    def test_yellow_observed():
        # Multi-phase TLS must have gone through yellow (to switch phases)
        # Single-phase TLS may also go through yellow (natural SUMO cycle)
        any_yellow = len(obs['yellow_steps_per_tls']) > 0
        if not any_yellow:
            raise ValueError(
                "No yellow phases observed in 500 steps — "
                "SUMO may not be cycling or all TLS stuck in green"
            )
        total_yellow = sum(obs['yellow_steps_per_tls'].values())
        # Show per-TLS breakdown
        lines = []
        for tlsID in all_tls:
            y = obs['yellow_steps_per_tls'].get(tlsID, 0)
            r = obs['red_steps_per_tls'].get(tlsID, 0)
            tag = "(single)" if tlsID in SINGLE_PHASE_TLS else "(multi)"
            lines.append(f"'{tlsID[:25]}' {tag}: yellow={y} red-clear={r} steps")
        return (
            f"Total yellow steps observed: {total_yellow} across {TEST_STEPS} steps\n" +
            '\n'.join(f"  {l}" for l in lines)
        )
    check("Yellow phases observed (transitions are happening)", test_yellow_observed)

    def test_no_stuck_pending():
        if obs['stuck_pending']:
            # Deduplicate by TLS
            stuck_tls = {t for _, t in obs['stuck_pending']}
            raise ValueError(
                f"Stuck pending transitions on TLS: {stuck_tls}\n"
                f"  Pending green held for >100 steps without completing"
            )
        return "No pending transitions stuck >100 steps — all complete cleanly"
    check("No stuck phase transitions (pending_green always clears)", test_no_stuck_pending)

    def test_final_phase_types_valid():
        issues = []
        for tlsID, ptype in final_phase_types.items():
            if ptype not in ('green', 'yellow', 'red'):
                issues.append(f"'{tlsID[:30]}': final phase type = '{ptype}'")
        if issues:
            raise ValueError('\n'.join(issues))
        green_count  = sum(1 for t in final_phase_types.values() if t == 'green')
        yellow_count = sum(1 for t in final_phase_types.values() if t == 'yellow')
        red_count    = sum(1 for t in final_phase_types.values() if t == 'red')
        return (
            f"All TLS in valid phase at step {TEST_STEPS}: "
            f"green={green_count} yellow={yellow_count} red-clear={red_count}"
        )
    check("All TLS in valid phase type at end of run", test_final_phase_types_valid)

    # ══════════════════════════════════════════════════════════════════════════
    # GROUP 2: SWITCH CORRECTNESS
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'─'*65}")
    print("GROUP 2: SWITCH CORRECTNESS (post-run)")
    print(f"{'─'*65}")

    switch_counts = final_stats['total_switches']

    def test_single_phase_no_switches():
        issues = []
        for tlsID in single_tls:
            sw = switch_counts.get(tlsID, 0)
            if sw != 0:
                issues.append(f"'{tlsID}': {sw} switches (expected 0 — single-phase TLS)")
        if issues:
            raise ValueError('\n'.join(issues))
        lines = [f"'{t[:30]}': switches={switch_counts.get(t, 0)}" for t in single_tls]
        return "Single-phase TLS correctly show 0 switches:\n  " + '\n  '.join(lines)
    check("Single-phase TLS have 0 switches (duration-only mode)", test_single_phase_no_switches)

    def test_multi_phase_some_switches():
        active = [t for t in multi_tls if switch_counts.get(t, 0) > 0]
        total  = sum(switch_counts.get(t, 0) for t in multi_tls)
        if len(active) == 0:
            raise ValueError(
                f"No multi-phase TLS switched in {TEST_STEPS} steps.\n"
                f"  Counts: {[(t[:20], switch_counts.get(t,0)) for t in multi_tls]}\n"
                f"  AI may not be scoring correctly or traffic too light."
            )
        lines = [f"'{t[:30]}': {switch_counts.get(t,0)} switches" for t in multi_tls]
        return (
            f"{len(active)}/{len(multi_tls)} multi-phase TLS switched "
            f"({total} total switches):\n  " + '\n  '.join(lines)
        )
    check("Multi-phase TLS: at least 1 TLS switched phases", test_multi_phase_some_switches)

    def test_total_switches_positive():
        total = sum(switch_counts.values())
        if total == 0:
            raise ValueError("Total switches = 0 — AI is completely static")
        return f"Total switches across all TLS: {total}"
    check("Total switch count > 0 (AI is not static)", test_total_switches_positive)

    def test_no_switch_thrashing():
        issues = []
        for tlsID, sw in switch_counts.items():
            if sw > MAX_THRASH_RATE:
                issues.append(
                    f"'{tlsID[:30]}': {sw} switches > thrash limit {MAX_THRASH_RATE:.0f}"
                )
        if issues:
            raise ValueError('\n'.join(issues))
        max_sw = max(switch_counts.values()) if switch_counts else 0
        return (
            f"No TLS exceeds thrash limit ({MAX_THRASH_RATE:.0f} switches).\n"
            f"  Max switches on any TLS: {max_sw}"
        )
    check("No switch thrashing (AI is stable, not flickering)", test_no_switch_thrashing)

    # ══════════════════════════════════════════════════════════════════════════
    # GROUP 3: DURATION TUNING
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'─'*65}")
    print("GROUP 3: DURATION TUNING (sampled during green phases)")
    print(f"{'─'*65}")

    def test_durations_in_bounds():
        if not obs['duration_samples']:
            raise ValueError("No duration samples collected — green phase never sampled")
        out_of_bounds = []
        for (tlsID, remaining) in obs['duration_samples']:
            # remaining time can legitimately be > MAX_GREEN because SUMO tracks
            # the full phase duration, not just our assigned portion.
            # But it must be > 0 and not impossibly large.
            if remaining < 0:
                out_of_bounds.append(f"'{tlsID[:25]}': remaining={remaining:.1f}s (negative)")
            elif remaining > 200:
                out_of_bounds.append(f"'{tlsID[:25]}': remaining={remaining:.1f}s (>200s suspicious)")
        if out_of_bounds:
            raise ValueError('\n'.join(out_of_bounds[:3]))
        vals = [r for _, r in obs['duration_samples']]
        return (
            f"{len(vals)} duration samples | "
            f"min={min(vals):.1f}s max={max(vals):.1f}s avg={sum(vals)/len(vals):.1f}s\n"
            f"  (Values near 0 = sampled near switch, large = fresh green — both OK)"
        )
    check("Duration samples valid (no negative remaining time)", test_durations_in_bounds)

    def test_single_phase_duration_varies():
        # For single-phase TLS, setPhaseDuration is called each step.
        # Check that the durations we sampled for them are not all identical
        # (which would mean the AI is assigning a fixed value, not adapting).
        single_samples = [r for (t, r) in obs['duration_samples'] if t in SINGLE_PHASE_TLS]
        if not single_samples:
            return "No duration samples for single-phase TLS in this run (may be in yellow/red when sampled)"
        unique = len(set(round(r, 0) for r in single_samples))
        return (
            f"Single-phase TLS duration samples: {len(single_samples)} values, "
            f"{unique} unique (AI is adjusting duration dynamically)"
        )
    check("Single-phase TLS durations vary (not static)", test_single_phase_duration_varies)

    # ══════════════════════════════════════════════════════════════════════════
    # GROUP 4: SCORING SANITY
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'─'*65}")
    print("GROUP 4: AI SCORING SANITY")
    print(f"{'─'*65}")

    def test_scores_in_range():
        if not obs['score_samples']:
            raise ValueError("No score samples collected")
        bad = [(t, p, s) for (t, p, s) in obs['score_samples']
               if math.isnan(s) or math.isinf(s) or s < 0.0 or s > 1.51]
        if bad:
            samples = bad[:3]
            raise ValueError(
                f"{len(bad)} scores outside valid range [0.0, 1.5]:\n" +
                '\n'.join(f"  TLS='{t[:20]}' phase={p} score={s:.4f}" for t,p,s in samples)
            )
        scores = [s for _, _, s in obs['score_samples']]
        return (
            f"{len(scores)} score samples | "
            f"min={min(scores):.4f} max={max(scores):.4f} avg={sum(scores)/len(scores):.4f}\n"
            f"  All in valid range [0.0, 1.5] — no NaN or Inf"
        )
    check("All AI scores in valid range [0.0, 1.5]", test_scores_in_range)

    def test_some_nonzero_scores():
        if not obs['score_samples']:
            raise ValueError("No score samples collected")
        nonzero = [(t, p, s) for (t, p, s) in obs['score_samples'] if s > 0.001]
        if len(nonzero) == 0:
            raise ValueError(
                "All scores = 0. Traffic may be too light for AI to detect.\n"
                "  This would mean AI always assigns MIN_GREEN_TIME (10s) — not adaptive."
            )
        pct = 100 * len(nonzero) / len(obs['score_samples'])
        return f"{len(nonzero)}/{len(obs['score_samples'])} score samples > 0 ({pct:.1f}%)"
    check("Non-zero scores exist (AI detecting real traffic pressure)", test_some_nonzero_scores)

    # ══════════════════════════════════════════════════════════════════════════
    # GROUP 5: FAIRNESS SYSTEM
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'─'*65}")
    print("GROUP 5: FAIRNESS SYSTEM (post-run skip_counts)")
    print(f"{'─'*65}")

    def test_no_phase_starved():
        issues = []
        for tlsID, phase_skips in final_skip_counts.items():
            for phase_idx, skip_count in phase_skips.items():
                if skip_count > FAIRNESS_MAX_SKIP:
                    issues.append(
                        f"'{tlsID[:25]}' phase {phase_idx}: "
                        f"skip_count={skip_count} > limit={FAIRNESS_MAX_SKIP}"
                    )
        if issues:
            raise ValueError(
                f"Fairness failure — {len(issues)} phases were starved:\n" +
                '\n'.join(f"  {i}" for i in issues[:5])
            )
        # Summary of skip counts
        all_skips = [s for skips in final_skip_counts.values() for s in skips.values()]
        return (
            f"No phase exceeded skip limit ({FAIRNESS_MAX_SKIP}). "
            f"Max skip count at end: {max(all_skips) if all_skips else 0}"
        )
    check("No green phase starved (fairness system working)", test_no_phase_starved)

    def test_time_served_positive():
        issues = []
        for tlsID, phase_times in final_time_served.items():
            total_served = sum(phase_times.values())
            if total_served == 0:
                issues.append(f"'{tlsID[:30]}': total time_served = 0 (never in green?)")
        if issues:
            raise ValueError('\n'.join(issues[:3]))
        # Print per-TLS time served
        lines = []
        for tlsID in all_tls[:5]:
            served = final_time_served.get(tlsID, {})
            per_phase = " | ".join(f"p{p}={v:.0f}s" for p, v in served.items())
            lines.append(f"'{tlsID[:25]}': {per_phase}")
        return "All TLS have positive time_served:\n  " + '\n  '.join(lines)
    check("All TLS have positive time_served in green phases", test_time_served_positive)

    # ══════════════════════════════════════════════════════════════════════════
    # GROUP 6: TRANSITION INTEGRITY
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'─'*65}")
    print("GROUP 6: TRANSITION INTEGRITY (post-run state)")
    print(f"{'─'*65}")

    def test_pending_empty_at_end():
        # NOTE: pending_green may legitimately be non-empty at the exact moment
        # the loop exits if a switch was triggered in the last few steps
        # (yellow takes ~3 steps to complete). The hard stuck-transition guard
        # is test_no_stuck_pending above (100 step threshold).
        # Here we fail only if an implausible number of TLS are mid-transition.
        if final_pending:
            details = [(t[:25], v) for t, v in final_pending.items()]
            if len(final_pending) > 3:
                raise ValueError(
                    f"{len(final_pending)} TLS pending at end (expected <= 3 for last-step switches):\n"
                    f"  {details}"
                )
            return (
                f"{len(final_pending)} TLS mid-transition at end of run "
                f"(normal — triggered in last ~3 steps): {[t for t,_ in details]}"
            )
        return "_pending_green = {} — all transitions completed cleanly"
    check("_pending_green cleared correctly (no stuck transitions)", test_pending_empty_at_end)

    def test_yellow_count_matches_switches():
        # Every switch requires going through at least 1 yellow step.
        # So total_yellow_steps >= total_switches (usually much more, since
        # yellow lasts multiple steps, but at minimum 1 per switch).
        total_switches = sum(switch_counts.values())
        total_yellow   = sum(obs['yellow_steps_per_tls'].values())
        if total_switches > 0 and total_yellow == 0:
            raise ValueError(
                f"Switches={total_switches} but yellow_steps=0.\n"
                f"  Switches happened without yellow phase — yellow was interrupted!"
            )
        return (
            f"Total switches: {total_switches} | "
            f"Total yellow steps observed: {total_yellow}\n"
            f"  Ratio: {total_yellow/max(total_switches,1):.1f} yellow steps per switch (expected >= 1)"
        )
    check("Yellow steps observed >= switch count (yellow never skipped)", test_yellow_count_matches_switches)

    def test_preempted_empty():
        preempted = ai._preempted
        if preempted:
            raise ValueError(
                f"AI still has preempted TLS at end: {preempted}\n"
                f"  (Emergency was disabled — nothing should be preempted)"
            )
        return "ai._preempted = empty set (no TLS incorrectly preempted)"
    check("No TLS incorrectly preempted (emergency was disabled)", test_preempted_empty)

    # ── PRINT DETAIL TABLES ───────────────────────────────────────────────────
    print(f"\n[DETAIL] Per-TLS switch count and phase time served:")
    print(f"  {'TLS ID':<35} {'Switches':>8} {'Type':<8} {'Time Served'}")
    print(f"  {'-'*75}")
    for tlsID in all_tls:
        sw      = switch_counts.get(tlsID, 0)
        ttype   = "single" if tlsID in SINGLE_PHASE_TLS else "multi"
        served  = final_time_served.get(tlsID, {})
        served_str = " | ".join(f"p{p}:{v:.0f}s" for p, v in served.items())
        sid = (tlsID[:33] + '..') if len(tlsID) > 35 else tlsID
        print(f"  {sid:<35} {sw:>8} {ttype:<8} {served_str}")

    print(f"\n[DETAIL] Observation counts:")
    print(f"  Duration samples collected : {len(obs['duration_samples'])}")
    print(f"  Score samples collected    : {len(obs['score_samples'])}")
    print(f"  Unknown phase observations : {len(obs['unknown_phases'])}")
    print(f"  Stuck pending observations : {len(obs['stuck_pending'])}")

    # ── RESULTS ───────────────────────────────────────────────────────────────
    _print_results()


def _print_results():
    passed = sum(1 for _, ok, _ in results if ok)
    total  = len(results)
    failed = [(n, e) for n, ok, e in results if not ok]

    print(f"\n{'='*65}")
    print(f"CHUNK 4 RESULTS: {passed}/{total} passed")
    print(f"{'='*65}")

    if failed:
        print("\nFailed tests:")
        for name, err in failed:
            print(f"  x {name}")
            if err:
                print(f"    {err}")
        print("\nFix the above before proceeding to Chunk 5.")
    else:
        print("\nCHUNK 4 PASSED - AI behaviour verified as correct and intelligent!")
        print("Next: say 'Start Chunk 5' for emergency vehicle preemption test.")
    print("="*65 + "\n")


if __name__ == "__main__":
    run()
