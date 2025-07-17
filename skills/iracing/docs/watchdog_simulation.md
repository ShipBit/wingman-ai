# iRacing Watchdog Events Simulation

## Racing Session: Charlotte Motor Speedway - 30 Minute Practice

**Driver:** Starting cold, getting up to speed gradually
**Car:** NASCAR Cup Series
**Track:** Charlotte Motor Speedway (1.5 mile oval)
**Expected Lap Time:** ~28-30 seconds
**Fuel Tank:** 18 gallons
**Fuel Consumption:** ~5 gallons/hour

---

## Session Timeline with Watchdog Events

### **00:00:00** - Session Start

_Watchdog system initializes, all events armed_

### **00:01:15** - First Lap Complete

**Lap Time:** 32.4 seconds (slow first lap)
**Telemetry:** Learning track, no alerts triggered
**Watchdog:** All systems monitoring, no thresholds met

### **00:02:30** - Second Lap Complete

**Lap Time:** 29.8 seconds
**Telemetry:** Getting up to speed
**Watchdog:** Performance delta alert armed but not triggered (within 2s threshold)

### **00:03:45** - Third Lap Complete

**Lap Time:** 28.2 seconds (new personal best)
**📢 WATCHDOG ALERT:** _"Personal best! 28.2 seconds - great improvement!"_
**Event:** `personal_best` triggered
**Cooldown:** 30 seconds until next personal best alert

### **00:05:00** - Fourth Lap Complete

**Lap Time:** 28.0 seconds (new personal best)
**📢 WATCHDOG ALERT:** _"New personal best! 28.0 seconds - you're finding pace!"_
**Event:** `personal_best` triggered again
**Cooldown:** Reset to 30 seconds

### **00:07:30** - Lap 6 In Progress

**Current Delta:** +1.8 seconds behind personal best
**Watchdog:** Performance delta monitoring but within 2s threshold
**No Alert:** Still within acceptable range

### **00:08:45** - Lap 7 Complete

**Lap Time:** 30.2 seconds (+2.2s from personal best)
**📢 WATCHDOG ALERT:** _"Performance check - you're 2.2 seconds off pace"_
**Event:** `performance_drop` triggered
**Cooldown:** 20 seconds (user configured interval)

### **00:12:00** - Lap 9 In Progress

**Incident:** Light contact with wall in Turn 3
**Incident Count:** 0 → 1
**📢 WATCHDOG ALERT:** _"Incident recorded - count now 1x"_
**Event:** `incident_alert` triggered
**Cooldown:** 30 seconds

### **00:12:15** - Damage Assessment

**Engine Warnings:** 0 → 1 (minor damage)
**📢 WATCHDOG ALERT:** _"Engine warning detected - check systems!"_
**Event:** `damage_detection` triggered
**Cooldown:** 30 seconds

### **00:15:30** - Lap 12 Complete

**Lap Time:** 28.1 seconds (back on pace despite damage)
**Tire Temps:** LF: 220°F, RF: 225°F, LR: 210°F, RR: 215°F
**Watchdog:** Tire temperatures within normal range (< 230°F threshold)

### **00:18:00** - Lap 14 In Progress

**Fuel Level:** 16.2 gallons → 15.8 gallons
**Estimated Laps Remaining:** 8 laps
**Watchdog:** Fuel level still above critical threshold

### **00:22:30** - Lap 17 Complete

**Tire Temps:** LF: 235°F, RF: 240°F, LR: 220°F, RR: 225°F
**📢 WATCHDOG ALERT:** _"Tire overheating - right front at 240°F"_
**Event:** `tire_overheat` triggered
**Cooldown:** 8 seconds (user configured)

### **00:22:38** - 8 Seconds Later

**Tire Temps:** LF: 238°F, RF: 242°F, LR: 222°F, RR: 227°F
**📢 WATCHDOG ALERT:** _"Tires still overheating - right front critical at 242°F"_
**Event:** `tire_overheat` triggered again (cooldown expired)

### **00:25:00** - Lap 19 Complete

**Fuel Level:** 14.2 gallons
**Estimated Laps Remaining:** 1.8 laps
**📢 WATCHDOG ALERT:** _"Fuel critical - 1.8 laps remaining"_
**Event:** `fuel_critical` triggered
**Cooldown:** 10 seconds (user configured)

### **00:26:30** - Lap 20 In Progress

**Yellow Flag:** Incident on track
**SessionFlags:** 0x00000008 (Yellow)
**📢 WATCHDOG ALERT:** _"Yellow flag - incident on track"_
**Event:** `flag_change` triggered
**Cooldown:** 3 seconds (user configured)

### **00:27:45** - Green Flag

**SessionFlags:** 0x00000004 (Green)
**📢 WATCHDOG ALERT:** _"Green flag - racing resumed"_
**Event:** `flag_change` triggered
**Cooldown:** 3 seconds

### **00:28:00** - Position Change

**Position:** P12 → P11 (passed car during yellow)
**📢 WATCHDOG ALERT:** _"Position change - P12 to P11!"_
**Event:** `position_change` triggered
**Cooldown:** 15 seconds (user configured)

### **00:30:00** - Session End

**Final Stats:**

- **Total Alerts:** 10 watchdog events triggered
- **Personal Bests:** 2 celebrations
- **Critical Alerts:** 3 (damage, fuel, tire overheating)
- **Informational:** 5 (flags, position, performance)

---

## Alert Frequency Analysis

### **High Priority Events (Critical Safety)**

- **Damage Detection:** 1 alert (5 second interval)
- **Fuel Critical:** 1 alert (10 second interval)
- **Tire Overheating:** 2 alerts (8 second interval)
- **Flag Changes:** 2 alerts (3 second interval)

### **Medium Priority Events (Performance)**

- **Performance Drop:** 1 alert (20 second interval)
- **Position Change:** 1 alert (15 second interval)
- **Personal Best:** 2 alerts (10 second interval)

### **Low Priority Events (Information)**

- **Incident Count:** 1 alert (5 second interval)
- **Pit Window:** 0 alerts (not applicable for practice)
- **Track Conditions:** 0 alerts (stable conditions)

---

## User Experience Summary

### **What the Driver Experiences:**

1. **Encouraging feedback** on personal bests and improvements
2. **Timely warnings** about critical issues (fuel, damage, overheating)
3. **Situational awareness** of flags and position changes
4. **Performance coaching** when consistently off pace

### **Alert Timing:**

- **Total alerts:** 10 over 30 minutes = 1 every 3 minutes average
- **Peak period:** 4 alerts in 2 minutes during tire overheating/fuel critical
- **Quiet periods:** 5+ minute gaps during clean running

### **Cost Implications:**

- **LLM calls:** 10 alerts × brief prompts = minimal token usage
- **Cooldown system:** Prevents spam during extended issues
- **User control:** All intervals configurable to balance responsiveness vs. cost

### **Realistic Feel:**

This simulation shows the watchdog provides **race engineer-like awareness** without being overwhelming. The alerts are:

- **Actionable** (fuel critical, tire overheating, damage)
- **Motivating** (personal bests, position changes)
- **Informative** (flag changes, performance feedback)
- **Well-timed** (cooldowns prevent repetitive alerts)

The system strikes a balance between **proactive assistance** and **cost-effective operation**, giving drivers the critical information they need when they need it most.
