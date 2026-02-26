# 🚦 AI-Driven Adaptive Traffic Signal Coordination System

An edge-intelligent, logic-driven AI traffic management system designed to optimize traffic flow, prioritize emergency vehicles, and improve intersection coordination using real-time traffic state estimation.

This project has been validated on a real-world scale SUMO simulation of **Pune city (Karvenagar → Paud Phata corridor)** including highways, multi-junction intersections, and signalized road networks.

---

## ⚠️ IMPORTANT NOTICE

🚦 This project contains multiple advanced components and a non-trivial system architecture.

Before running or modifying the project, please read:

➡️ **📚 [`docs/`](./docs) — Full Technical Documentation**

The docs include:

✔ Architecture explanation  
✔ Full algorithm breakdown  
✔ TraCI integration guide  
✔ Simulation walkthrough  
✔ Demo instructions  

Skipping documentation may lead to incorrect setup.

## 🌍 Problem Statement

Traditional traffic signal systems operate on fixed timing cycles, leading to:

- Unnecessary waiting time
- Traffic congestion
- Poor emergency vehicle response
- Inefficient intersection utilization

Modern cities require adaptive, data-driven traffic control capable of reacting to real-time traffic conditions.

---

## 💡 Solution Overview

This project introduces an **AI-driven adaptive traffic signal system** that:

- Collects live traffic data from simulation
- Dynamically adjusts signal timing
- Prioritizes emergency vehicles (ambulance preemption)
- Uses edge-local decision logic for reliability
- Supports fail-safe operation and manual override

---

## 🧠 Core Features

- 🚦 Adaptive signal timing based on traffic density
- 🚑 Emergency vehicle preemption system
- 🧩 Phase mapping & intelligent signal switching
- 🖥️ Edge-local processing (no central dependency)
- 🏙️ Real-world map simulation (Pune city network)
- 🔁 Fail-safe fallback logic
- 📊 Real-time TraCI data integration

---

## 🏗️ System Architecture

SUMO Simulation
↓
TraCI Data Collector
↓
Traffic Density Analysis
↓
AI Signal Controller (Logic-Based AI)
↓
Phase Mapper
↓
Traffic Signal Execution


### High-Level Design

- **SUMO** → Traffic environment simulation  
- **TraCI** → Real-time data interface  
- **Controller** → Decision engine  
- **Emergency Module** → Ambulance prioritization  
- **Phase Mapper** → Converts decisions into valid signal phases  

---

## 🧩 Project Structure

smart_traffic_system/
│
├── src/
│ ├── main_controller.py # Main execution controller
│ ├── ai_signal_controller.py # Adaptive signal decision logic
│ ├── emergency_preemption.py # Ambulance handling logic
│ ├── data_collector.py # TraCI traffic data extraction
│ ├── phase_mapper.py # Signal phase mapping
│ ├── config.py # System configuration
│ └── logger.py # Logging utilities
│
├── sumo_files/ # SUMO network + route files
├── docs/ # Detailed documentation
└── README.md


---

## ⚙️ Requirements

### Software

- Python 3.9+
- SUMO (Simulation of Urban Mobility)
- TraCI (included with SUMO)

### Python Dependencies

```bash
pip install -r requirements.txt
▶️ Running the Project
1️⃣ Normal Traffic Simulation

Run adaptive traffic system without emergency vehicle:

python src/main_controller.py --no-emergency
2️⃣ Traffic + Ambulance Emergency Simulation
python src/main_controller.py

This activates emergency vehicle preemption logic.

⏱️ Simulation Timing (IMPORTANT)

    SUMO runs faster than real time by default.

    For correct visualization and realistic behaviour:

    Set SUMO GUI delay to:
    1000 ms  (Real-Time Mode)

    This ensures:

    Realistic signal timing

    Proper emergency vehicle visualization

    Accurate demonstration behaviour

🚑 Emergency Scenario Behavior

In emergency mode:

The ambulance is injected at t = 0 seconds

Spawn location:

Southern corridor entry junction
(Karvenagar-side arterial entry)

If the simulation is paused early, the ambulance can be observed near the southern section of the map at the initial junction.

⚠️ If simulation delay is too low, the ambulance may appear to move too quickly.

🧠 Algorithm Overview

The system operates in a continuous control loop:

1. Collect live traffic data via TraCI
2. Estimate traffic density per approach
3. Compute priority score
4. Select optimal signal phase
5. Apply phase using TraCI
6. Repeat
Emergency Handling

    When an ambulance is detected:

    Normal priority logic pauses

    Signal phases create a green corridor

    Traffic resumes normal operation after passage

🔗 TraCI Integration

    TraCI is used to:

    Read vehicle counts

    Monitor lane density

    Observe signal states

    Apply signal phase changes

    Official TraCI Documentation:

https://sumo.dlr.de/docs/TraCI.html

🧱 Fail-Safe Design

    The system is designed to never fully fail.

    Fallback behaviours include:

    Fixed countdown signal cycle

    Local autonomous logic

    Manual override capability

    Safe default phase switching

📍 Simulation Environment

Tested on:

Pune City — Karvenagar → Paud Phata corridor

Includes:

    1. Highways

    2. Signalized intersections

    3. Multi-junction network

    4. Realistic urban traffic behaviour

🚀 Future Improvements

    Reinforcement learning signal optimization

    Multi-junction coordination

    Edge AI deployment

    Real CCTV integration

    Predictive traffic modeling

🤝 Open Source Contribution

    Contributions are welcome.

    If you wish to improve the system:

    Fork the repository

    Create a feature branch

    Submit a pull request

📜 License

MIT License