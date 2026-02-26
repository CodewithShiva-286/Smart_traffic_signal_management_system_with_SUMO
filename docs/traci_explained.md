# 🔗 TraCI Integration Explained

This document explains how the project communicates with SUMO using **TraCI (Traffic Control Interface)**.

TraCI is the core technology that allows Python code to:

- Read live traffic data
- Observe vehicle behaviour
- Control traffic signals in real time

---

## 🧠 What is TraCI?

TraCI (Traffic Control Interface) is a client-server protocol provided by SUMO.

It allows external programs to:


Read Simulation State
+
Modify Simulation Behaviour


In this project:


Python Controller ↔ TraCI ↔ SUMO Simulation


---

## 🎯 Why TraCI is Used

Without TraCI:

- SUMO runs independently
- Signals follow predefined logic
- No adaptive control possible

With TraCI:

- AI logic can observe traffic
- Signals become programmable
- Real-time adaptation becomes possible

---

## 🏗️ Communication Flow


SUMO Simulation
↓
TraCI Server
↓
Python Controller
↓
Signal Decisions
↓
SUMO Traffic Lights


---

## 🚀 Starting TraCI Connection

When the system starts:


traci.start([...])

This launches SUMO in control mode.

After connection:

Python becomes the controller

SUMO becomes the environment

-----

## 📊 Reading Traffic Data

Handled mainly in:

data_collector.py


The system continuously reads traffic state.

Common TraCI Data Calls

Vehicle Count per Lane


traci.lane.getLastStepVehicleNumber(lane_id)

Returns:

Number of vehicles currently on a lane
Lane Occupancy
traci.lane.getLastStepOccupancy(lane_id)

Used to estimate congestion level.

Vehicle Speed (optional metric)
traci.lane.getLastStepMeanSpeed(lane_id)

Useful for future upgrades.

---

## 🚦 Reading Signal State

The controller can inspect traffic lights:

traci.trafficlight.getPhase(tls_id)

Used for:

Monitoring current phase

Preventing unsafe transitions

---

## 🟢 Controlling Traffic Signals

This is where AI decisions are applied.

Setting Signal Phase
traci.trafficlight.setPhase(tls_id, phase_index)

This command:

Changes active traffic light phase

Directly affects vehicle movement

Setting Phase Duration (optional)
traci.trafficlight.setPhaseDuration(tls_id, duration)

Allows adaptive timing control.

---

## 🔄 Real-Time Control Loop

Every control cycle:

1. Read traffic data
2. Analyze congestion
3. Select best phase
4. Apply phase via TraCI
5. Wait for next update


This loop creates adaptive behaviour.

---

## 🚑 Emergency Vehicle Handling

TraCI enables emergency control by:

- Detecting ambulance position
- Checking route direction
- Forcing green signal phase

Example workflow:


Ambulance detected
↓
Determine approach direction
↓
Force green phase
↓
Resume normal control


---

## ⏱️ Synchronization with Simulation Time

The controller advances simulation using:


traci.simulationStep()

Each step:

Advances simulation time

Updates traffic state

Allows new decisions

## 🧩 Why TraCI Makes This Project AI-Driven

TraCI enables:

Continuous feedback loop

Environment observation

Real-time control

This transforms static signals into:

Adaptive Intelligent Agents


---

## ⚠️ Important Notes

### Simulation Delay

For proper visualization:


SUMO GUI delay = 1000 ms


This keeps behaviour understandable during demos.

---

## Performance Consideration

TraCI calls are lightweight but frequent.

Best practice:

- Avoid unnecessary queries
- Read only required data

---

## 📚 Official Documentation

Full TraCI documentation:

https://sumo.dlr.de/docs/TraCI.html

This project uses only a focused subset relevant to adaptive traffic control.

---

## 🧠 Summary

TraCI acts as:


Eyes → Data Collection
Brain → Decision Logic
Hands → Signal Control


It enables real-time interaction between AI logic and the traffic simulation.

---

## 🚀 Future Extensions Using TraCI

Possible upgrades:

- Multi-junction coordination
- Predictive signal switching
- Reinforcement learning agents
- Live sensor integration