# 🏗️ System Architecture

This document explains the complete architecture of the AI-Driven Adaptive Traffic Signal Coordination System.

The system is designed using a **modular, edge-intelligent architecture** to ensure scalability, reliability, and real-world deployability.

---

## 🎯 Design Philosophy

The architecture follows three principles:

1. **Edge Intelligence**
   - Decisions are made locally.
   - No dependency on central servers for real-time control.

2. **Modular Components**
   - Each module has a single responsibility.
   - Easy to debug and extend.

3. **Fail-Operational Design**
   - Traffic never stops even if modules fail.

---

## 🌐 High-Level Architecture


SUMO Simulation Environment
↓
TraCI Interface
↓
Data Collector Layer
↓
AI Signal Controller
↓
Phase Mapper
↓
Traffic Signal Execution
↓
Emergency Preemption Layer


---

## 🧠 Layered Architecture Overview

### 1️⃣ Simulation Layer

**Purpose:** Create realistic traffic environment.

Components:

- SUMO traffic simulator
- Real-world Pune city network
- Vehicles, signals, junctions

Responsibilities:

- Vehicle movement
- Signal state visualization
- Traffic environment generation

---

### 2️⃣ Communication Layer (TraCI)

TraCI acts as a real-time bridge between Python and SUMO.

Responsibilities:

- Read traffic data
- Control traffic signals
- Monitor simulation state

Data flow:


SUMO ↔ TraCI ↔ Python Controller


---

### 3️⃣ Data Collection Layer

Implemented in:


data_collector.py


Responsibilities:

- Collect vehicle counts
- Measure lane occupancy
- Extract queue information
- Provide traffic state snapshot

Output:


Structured traffic data per approach


---

### 4️⃣ Decision Layer (Logic-Based AI)

Implemented in:


ai_signal_controller.py


Responsibilities:

- Analyze traffic density
- Compute priority scores
- Select optimal direction
- Maintain fairness

This layer represents the core intelligence of the system.

---

### 5️⃣ Phase Mapping Layer

Implemented in:


phase_mapper.py


Responsibilities:

- Convert decisions into legal signal phases
- Prevent conflicting movements
- Ensure safe transitions

---

### 6️⃣ Execution Layer

Responsibilities:

- Apply selected phase to SUMO
- Maintain timing stability
- Execute phase transitions safely

Uses:


traci.trafficlight.setPhase()


---

### 7️⃣ Emergency Override Layer

Implemented in:


emergency_preemption.py


Responsibilities:

- Detect emergency vehicle presence
- Override normal signal logic
- Create temporary green corridor
- Restore normal operation after passage

Emergency logic always has highest priority.

---

## 🔁 Runtime Data Flow

Complete execution cycle:


Traffic Movement
↓
TraCI Data Read
↓
Traffic State Analysis
↓
Priority Calculation
↓
Phase Selection
↓
Signal Update
↓
Traffic Responds
↓
Repeat


---

## 🧩 Modular Design Benefits

### Scalability

New features can be added without rewriting the system.

Example:

- Reinforcement learning module
- Prediction engine
- Multi-junction coordination

---

### Maintainability

Each module can be:

- Tested independently
- Debugged separately
- Upgraded without affecting others

---

### Real-World Readiness

Architecture mirrors real intelligent traffic systems:

- Local decision hardware
- Monitoring layer
- Emergency override
- Safe fallback logic

---

## 🧱 Fail-Safe Architecture

The system avoids single points of failure.

### Example fallback cases:

- AI logic failure → fixed countdown mode
- Communication loss → local control continues
- Emergency override → temporary control handover

---

## 🏙️ Deployment Vision (Real World)

Future deployment model:


Edge Device (1–2 junctions)
↓
Local AI Processing
↓
Central Monitoring HQ


HQ role:

- Observation
- Manual override
- Analytics

Real-time decisions remain local.

---

## 📊 Architecture Summary

The system combines:

- Simulation-based validation
- Real-time data acquisition
- Logic-driven AI decision making
- Safe signal execution
- Emergency prioritization

Result:


Adaptive, scalable, and fault-tolerant traffic signal coordination.


---

## 🚀 Future Architectural Extensions

Possible upgrades:

- Multi-junction coordination engine
- Reinforcement learning optimization
- Edge GPU deployment
- Real CCTV integration
- City-wide distributed control