"""
logger.py
=========
Handles all logging for the simulation:
  1. Per-step CSV log (step_log.csv) — used for graphs/analysis
  2. End-of-simulation summary report (summary_report.txt)
  3. Console progress output

No TraCI calls in this module — pure data recording.
"""

import csv
import os
import time
from datetime import datetime
from config import STEP_LOG_CSV, SUMMARY_REPORT, CONSOLE_LOG_INTERVAL, CSV_LOG_INTERVAL


class SimulationLogger:
    """
    Records simulation metrics at each step and produces end-of-run reports.
    
    Usage:
        logger = SimulationLogger()
        logger.start()
        
        # Each step:
        logger.log_step(
            step=100,
            sim_time=100.0,
            network_data={...},
            active_tls_count=12,
            preempted_tls=set(),
            emergency_active=False,
        )
        
        logger.finish(controller_stats, emergency_stats)
    """

    # CSV column definitions — defines order in output file
    CSV_COLUMNS = [
        'step',
        'sim_time',
        'vehicles_in_net',
        'departed',
        'arrived',
        'avg_wait_time',
        'avg_speed',
        'total_wait',
        'active_tls_count',
        'preempted_tls_count',
        'emergency_active',
        'preempted_tls_list',
    ]

    def __init__(self):
        self._csv_file    = None
        self._csv_writer  = None
        self._start_time  = None  # wall clock time

        # Accumulated stats for summary
        self._step_count         = 0
        self._total_vehicle_steps = 0
        self._total_wait_sum     = 0.0
        self._total_speed_sum    = 0.0
        self._max_vehicles       = 0
        self._max_wait_time      = 0.0

        # Emergency-specific stats
        self._emergency_steps       = 0  # steps where emergency was active
        self._emergency_wait_sum    = 0.0
        self._normal_wait_sum       = 0.0
        self._normal_steps          = 0

        # Track if logger has been started
        self._started = False

    def start(self):
        """
        Opens log files and writes CSV header.
        Call once before simulation loop begins.
        """
        os.makedirs(os.path.dirname(STEP_LOG_CSV), exist_ok=True)

        self._csv_file   = open(STEP_LOG_CSV, 'w', newline='', encoding='utf-8')
        self._csv_writer = csv.DictWriter(self._csv_file, fieldnames=self.CSV_COLUMNS)
        self._csv_writer.writeheader()
        self._csv_file.flush()

        self._start_time = time.time()
        self._started    = True

        print(f"[LOGGER] ✓ Logging started")
        print(f"[LOGGER] Step log : {STEP_LOG_CSV}")
        print(f"[LOGGER] Summary  : {SUMMARY_REPORT}")

    def log_step(
        self,
        step: int,
        sim_time: float,
        network_data: dict,
        active_tls_count: int,
        preempted_tls: set,
        emergency_active: bool,
    ):
        """
        Log one simulation step.
        
        Args:
            step: integer step number
            sim_time: simulation time in seconds
            network_data: output from collector.collect_network_summary()
            active_tls_count: number of TLS being managed by AI
            preempted_tls: set of currently preempted TLS IDs
            emergency_active: whether ambulance is currently in network
        """
        if not self._started:
            return

        self._step_count += 1

        vehicles  = network_data.get('vehicles_in_net', 0)
        avg_wait  = network_data.get('avg_wait_time', 0.0)
        avg_speed = network_data.get('avg_speed', 0.0)
        total_wait= network_data.get('total_wait', 0.0)

        # Accumulate for summary
        self._total_vehicle_steps += vehicles
        self._total_wait_sum      += avg_wait
        self._total_speed_sum     += avg_speed
        self._max_vehicles         = max(self._max_vehicles, vehicles)
        self._max_wait_time        = max(self._max_wait_time, avg_wait)

        if emergency_active:
            self._emergency_steps    += 1
            self._emergency_wait_sum += avg_wait
        else:
            self._normal_steps    += 1
            self._normal_wait_sum += avg_wait

        # Write CSV row (respecting interval)
        if step % CSV_LOG_INTERVAL == 0:
            row = {
                'step'                : step,
                'sim_time'            : f"{sim_time:.1f}",
                'vehicles_in_net'     : vehicles,
                'departed'            : network_data.get('departed', 0),
                'arrived'             : network_data.get('arrived', 0),
                'avg_wait_time'       : f"{avg_wait:.2f}",
                'avg_speed'           : f"{avg_speed:.2f}",
                'total_wait'          : f"{total_wait:.1f}",
                'active_tls_count'    : active_tls_count,
                'preempted_tls_count' : len(preempted_tls),
                'emergency_active'    : int(emergency_active),
                'preempted_tls_list'  : "|".join(sorted(preempted_tls)) if preempted_tls else "",
            }
            self._csv_writer.writerow(row)

            # Flush periodically to avoid data loss
            if step % 100 == 0:
                self._csv_file.flush()

        # Console output at interval
        if step % CONSOLE_LOG_INTERVAL == 0:
            emergency_tag = " 🚑 EMERGENCY ACTIVE" if emergency_active else ""
            preempted_tag = f" [{len(preempted_tls)} TLS preempted]" if preempted_tls else ""
            print(
                f"[SIM t={sim_time:7.1f}s | step={step:5d}] "
                f"Vehicles: {vehicles:4d} | "
                f"AvgWait: {avg_wait:6.1f}s | "
                f"AvgSpeed: {avg_speed:.1f}m/s"
                f"{emergency_tag}{preempted_tag}"
            )

    def finish(self, controller_stats: dict = None, emergency_stats: dict = None):
        """
        Close CSV file and write final summary report.
        Call once after simulation loop ends.
        
        Args:
            controller_stats: from ai_controller.get_stats()
            emergency_stats: from emergency_engine.get_summary()
        """
        if not self._started:
            return

        # Close CSV
        if self._csv_file:
            self._csv_file.flush()
            self._csv_file.close()

        wall_time = time.time() - self._start_time

        # Calculate summary stats
        avg_wait_overall  = self._total_wait_sum  / max(self._step_count, 1)
        avg_speed_overall = self._total_speed_sum / max(self._step_count, 1)
        avg_wait_normal   = self._normal_wait_sum / max(self._normal_steps, 1)
        avg_wait_emergency= self._emergency_wait_sum / max(self._emergency_steps, 1)

        # Write summary report
        os.makedirs(os.path.dirname(SUMMARY_REPORT), exist_ok=True)
        with open(SUMMARY_REPORT, 'w', encoding='utf-8') as f:
            f.write("=" * 60 + "\n")
            f.write("AI ADAPTIVE TRAFFIC MANAGEMENT SYSTEM\n")
            f.write("SIMULATION SUMMARY REPORT\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 60 + "\n\n")

            f.write("── SIMULATION INFO ──\n")
            f.write(f"  Total Steps Run      : {self._step_count}\n")
            f.write(f"  Wall Clock Time      : {wall_time:.1f}s\n")
            f.write(f"  Simulation Speed     : {self._step_count / max(wall_time, 1):.1f} steps/sec\n\n")

            f.write("── TRAFFIC PERFORMANCE ──\n")
            f.write(f"  Avg Wait Time Overall : {avg_wait_overall:.2f}s\n")
            f.write(f"  Avg Speed Overall     : {avg_speed_overall:.2f} m/s\n")
            f.write(f"  Peak Vehicles in Net  : {self._max_vehicles}\n")
            f.write(f"  Peak Avg Wait Time    : {self._max_wait_time:.2f}s\n\n")

            f.write("── EMERGENCY VEHICLE PERFORMANCE ──\n")
            if self._emergency_steps > 0:
                f.write(f"  Emergency Steps       : {self._emergency_steps}\n")
                f.write(f"  Avg Wait (emergency)  : {avg_wait_emergency:.2f}s\n")
                f.write(f"  Avg Wait (normal)     : {avg_wait_normal:.2f}s\n")
                f.write(f"  Wait Difference       : {avg_wait_emergency - avg_wait_normal:+.2f}s\n")
            else:
                f.write("  No emergency vehicle events recorded\n")

            if emergency_stats:
                f.write(f"\n  Total TLS Preemptions : {emergency_stats.get('total_preemptions', 0)}\n")
                f.write(f"  Unique TLS Affected   : {emergency_stats.get('unique_tls_affected', 0)}\n")
                f.write(f"  Ambulance Arrived     : {emergency_stats.get('ambulance_arrived', False)}\n")

            if controller_stats:
                f.write("\n── AI CONTROLLER STATS ──\n")
                total_sw = sum(controller_stats.get('total_switches', {}).values())
                f.write(f"  Total Phase Switches  : {total_sw}\n")
                f.write(f"  Preempted TLS Count   : {controller_stats.get('preempted_count', 0)}\n")

            f.write("\n" + "=" * 60 + "\n")
            f.write("Files:\n")
            f.write(f"  Step log : {STEP_LOG_CSV}\n")
            f.write(f"  This file: {SUMMARY_REPORT}\n")

        print(f"\n[LOGGER] ✓ Summary report written: {SUMMARY_REPORT}")
        print(f"[LOGGER] ✓ Step log written: {STEP_LOG_CSV}")
        print(f"\n{'='*50}")
        print(f"SIMULATION COMPLETE")
        print(f"  Steps run        : {self._step_count}")
        print(f"  Wall time        : {wall_time:.1f}s")
        print(f"  Avg wait overall : {avg_wait_overall:.2f}s")
        if self._emergency_steps > 0:
            print(f"  Avg wait (emerg) : {avg_wait_emergency:.2f}s")
        print(f"{'='*50}\n")
