# 🎬 Demo Walkthrough Guide

This document explains how to demonstrate the AI-Driven Adaptive Traffic Signal Coordination System during presentations, evaluations, or testing.

It provides a structured walkthrough so observers can clearly understand:

- What is happening
- Why it is happening
- What makes the system intelligent

---

## 🎯 Demo Objective

Demonstrate:

1. Adaptive traffic signal behaviour
2. Real-time traffic analysis
3. Emergency vehicle preemption
4. AI-driven decision making

---

## 🧰 Pre-Demo Setup

### 1️⃣ Start SUMO in GUI Mode

Open the SUMO simulation configuration file.

---

### 2️⃣ Set Real-Time Simulation Speed (IMPORTANT)

In SUMO GUI:

- Locate simulation delay control
- Set:


1000 ms delay


This ensures real-time behaviour.

If delay is too low:

- Signal changes appear too fast
- Emergency vehicle movement becomes difficult to observe

---

### 3️⃣ Recommended Camera Position

Before starting:

- Zoom to the **southern corridor entry junction**
- This is the Karvenagar-side arterial entry

This is where the emergency vehicle begins.

---

## 🚦 Demo Part 1 — Normal Adaptive Traffic

Run:


python src/main_controller.py --no-emergency


### What Judges Should Observe

- Signals changing dynamically
- Busy directions receiving longer green time
- Traffic flow adjusting automatically
- No fixed timer behaviour

### Explanation to Give

> The system continuously measures traffic density and adapts signal timing in real time instead of using fixed cycles.

---

## 🚑 Demo Part 2 — Emergency Vehicle Scenario

Run:


python src/main_controller.py


### Important Behaviour

- Ambulance spawns at simulation time **t = 0 seconds**
- Origin: southern corridor entry junction
- Moves toward major intersections

If paused early, the ambulance can be seen near the southern section of the map.

---

### What Judges Should Observe

1. Normal traffic operation initially
2. Emergency vehicle appears
3. Signal logic changes automatically
4. Green corridor behaviour
5. Normal traffic resumes after passage

---

### Explanation to Give

> When an emergency vehicle is detected, the system temporarily overrides normal traffic optimization and prioritizes the ambulance path to reduce response time.

---

## 🧠 Key Talking Points During Demo

### Adaptive Intelligence

- Signals are not pre-programmed.
- Decisions are computed continuously.

### Real-Time Data

- Vehicle counts are read live using TraCI.

### Safe Execution

- Phase mapping prevents conflicting greens.

### Emergency Priority

- Emergency logic always overrides normal decisions.

---

## 🔎 Suggested Demo Flow (Timeline)

### Minute 0–1

- Introduce problem
- Show traffic network

### Minute 1–3

- Run normal adaptive mode
- Explain density-based decisions

### Minute 3–5

- Switch to emergency mode
- Highlight ambulance detection
- Show green corridor effect

### Minute 5+

- Explain architecture briefly
- Mention scalability and fail-safe design

---

## 🧩 Common Judge Questions (Quick Answers)

### Q: Is this fixed timing?

No — timing adapts based on live traffic density.

---

### Q: Where is AI used?

AI logic calculates priorities dynamically using real-time traffic data.

---

### Q: What happens if detection fails?

System switches to safe fallback signal logic.

---

### Q: Can this scale to cities?

Yes — architecture supports multi-junction expansion.

---

## ⚠️ Demo Tips

- Always set delay to 1000 ms.
- Keep zoom level medium.
- Focus on signal changes, not vehicle speed.
- Explain what is happening before it happens.

---

## 🏁 Demo Summary Statement

Recommended closing line:

> This system demonstrates how logic-driven AI can transform static traffic signals into adaptive, real-time decision-making agents capable of improving traffic flow and emergency response efficiency.