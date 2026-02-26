# 🧠 Adaptive Traffic Signal Algorithm

This document explains the complete working logic of the AI-driven adaptive traffic management system.

The goal of the algorithm is to:

- Optimize traffic flow dynamically
- Reduce waiting time
- Prevent lane starvation
- Enable emergency vehicle preemption
- Maintain safe signal transitions

---

## 📌 High-Level Concept

The system uses a **logic-driven AI approach**.

Instead of fixed timers, signal decisions are continuously computed using real-time traffic state data obtained through TraCI.

Core idea:

Traffic State → Priority Calculation → Signal Decision → Execution

---

## 🧩 Algorithm Architecture

The control system is divided into independent modules:


Data Collector
↓
AI Signal Controller
↓
Phase Mapper
↓
Signal Execution
↓
Emergency Preemption (Override Layer)


Each module performs a single responsibility.

---

## 🔄 Main Control Loop

The algorithm runs continuously while the simulation is active.

### Loop Steps


Read traffic data from SUMO (TraCI)

Calculate vehicle density per approach

Compute priority score

Select best signal phase

Apply signal phase

Repeat


---

## 📊 Step 1 — Traffic Data Collection

Handled by:


data_collector.py


Using TraCI, the system reads:

- Vehicle count
- Lane occupancy
- Queue length
- Active signal phase

Example data flow:

SUMO → TraCI → Data Collector → Controller


This creates a live traffic state snapshot.

---

## 📈 Step 2 — Traffic Density Estimation

Traffic density is estimated for each incoming road.

Typical metrics:

- Number of vehicles waiting
- Queue length
- Occupancy percentage

Output example:


North: 12 vehicles
South: 5 vehicles
East : 18 vehicles
West : 7 vehicles


---

## 🧮 Step 3 — Priority Calculation (Core Intelligence)

Handled by:


ai_signal_controller.py


Each direction receives a priority score.

### Conceptual Formula


Priority = Traffic Density + Waiting Influence


Where:

- Higher vehicle count increases priority
- Longer waiting time increases priority
- Recently served directions get reduced priority

This prevents starvation.

---

## ⚖️ Fairness Mechanism

Without fairness, one busy road could remain green forever.

The algorithm includes:

- Minimum green time
- Maximum green cap
- Priority decay after service

Result:


All approaches eventually receive green.


---

## 🚦 Step 4 — Phase Selection

After priorities are calculated:

1. Highest priority direction is selected
2. Valid signal phase is determined

Handled by:


phase_mapper.py


This ensures only legal traffic movements occur.

---

## 🟢 Step 5 — Signal Execution

Signal changes are applied via TraCI:


traci.trafficlight.setPhase(...)


Safety rules:

- No conflicting greens
- Controlled transitions
- Stable switching

---

## 🚑 Emergency Vehicle Preemption

Handled by:


emergency_preemption.py


This module overrides normal logic.

### Workflow


Ambulance detected
↓
Identify approach direction
↓
Force green corridor
↓
Pause normal algorithm
↓
Resume normal control after passage


Emergency priority is absolute.

---

## ⏱️ Timing Logic

Signal decisions are not changed every frame.

The system operates using controlled update intervals:

- Prevents flickering signals
- Maintains realistic behaviour
- Improves stability

---

## 🔗 TraCI Interaction Model

TraCI acts as the communication bridge.

Used for:

### Reading Data


traci.lane.getLastStepVehicleNumber()
traci.lane.getLastStepOccupancy()


### Writing Control


traci.trafficlight.setPhase()


---

## 🧱 Fail-Safe Behaviour

If AI logic fails:

Fallback modes include:

- Fixed countdown cycle
- Safe default phase
- Manual override

Traffic flow never fully stops.

---

## 📊 Algorithm Complexity

Each cycle performs:


O(N) operations


Where N = number of approaches.

This makes the system scalable to multiple junctions.

---

## 🏙️ Real-World Validation

The algorithm has been tested on:

**Pune City Simulation**
(Karvenagar → Paud Phata corridor)

Includes:

- Highways
- Multi-junction intersections
- Realistic traffic behaviour

---

## 🚀 Future Algorithm Extensions

Possible upgrades:

- Reinforcement Learning optimization
- Traffic prediction models
- Multi-junction coordination
- Edge AI deployment

---

## 🧠 Summary

The algorithm combines:

- Real-time traffic observation
- Logic-based AI decision making
- Safe signal execution
- Emergency prioritization

Result:


Adaptive, scalable, and reliable traffic signal coordination.