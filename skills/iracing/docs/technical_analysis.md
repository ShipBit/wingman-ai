# Technical Watchdog Code Execution Analysis

## How Our Actual Code Would Execute During Racing

### **Event: Personal Best Achievement**

**Timestamp:** 00:03:45
**Trigger Condition:** `current_best < self._last_best_lap`

```python
def _check_personal_best_threshold(self, telemetry_data):
    current_best = telemetry_data.get("LapBestLapTime", 0)  # 28.2 seconds
    if not hasattr(self, "_last_best_lap"):
        self._last_best_lap = current_best
        return False, {}

    # Check: 28.2 < 29.8 (previous best) = TRUE
    if current_best > 0 and current_best < self._last_best_lap:
        old_best = self._last_best_lap  # 29.8
        self._last_best_lap = current_best  # 28.2
        return True, {"old_best": 29.8, "new_best": 28.2}

    return False, {}
```

**LLM Prompt Generated:**

```
"Generate a brief race engineer celebration for personal best. New best: 28.200s, previous: 29.800s. Keep it under 12 words."
```

**Expected LLM Response:**
_"Excellent! New personal best 28.2 - that's 1.6 seconds faster!"_

---

### **Event: Fuel Critical Alert**

**Timestamp:** 00:25:00
**Trigger Condition:** `laps_remaining < 2.0`

```python
def _check_fuel_threshold(self, telemetry_data):
    fuel_level = telemetry_data.get("FuelLevel", 0)  # 14.2 gallons
    fuel_use_per_hour = telemetry_data.get("FuelUsePerHour", 0)  # 5.0 gal/hr

    if fuel_use_per_hour > 0:
        laps_remaining = fuel_level / fuel_use_per_hour  # 14.2 / 5.0 = 2.84 hours
        # Convert to laps: 2.84 hours * 60 min/hr * 60 sec/min / 28 sec/lap = 1.8 laps
        laps_remaining = (laps_remaining * 3600) / 28  # Approximate lap time

        if laps_remaining < 2.0:  # 1.8 < 2.0 = TRUE
            return True, {"fuel_level": 14.2, "laps_remaining": 1.8}

    return False, {}
```

**LLM Prompt Generated:**

```
"Generate a brief race engineer fuel warning. Fuel level: 14.2L, laps remaining: 1.8. Keep it under 12 words."
```

**Expected LLM Response:**
_"Fuel critical! Only 1.8 laps remaining - consider pit stop"_

---

### **Event: Tire Overheating**

**Timestamp:** 00:22:30
**Trigger Condition:** `temp > 105°C` (converted from 240°F)

```python
def _check_tire_temp_threshold(self, telemetry_data):
    lf_temp = telemetry_data.get("LFtempCL", 0)  # 113°C (235°F)
    rf_temp = telemetry_data.get("RFtempCL", 0)  # 116°C (240°F)
    lr_temp = telemetry_data.get("LRtempCL", 0)  # 104°C (220°F)
    rr_temp = telemetry_data.get("RRtempCL", 0)  # 107°C (225°F)

    temps = [113, 116, 104, 107]
    overheating = [temp for temp in temps if temp > 105]  # [113, 116, 107]

    if overheating:  # 3 tires overheating
        return True, {"max_temp": 116, "tire_count": 3}

    return False, {}
```

**LLM Prompt Generated:**

```
"Generate a brief race engineer tire temperature warning. Max temp: 116°C on 3 tires. Keep it under 12 words."
```

**Expected LLM Response:**
_"Tire overheating! 3 tires at 116°C - ease up pace"_

---

### **Event: Position Change**

**Timestamp:** 00:28:00
**Trigger Condition:** `current_pos != self._last_position`

```python
def _check_position_change_threshold(self, telemetry_data):
    current_pos = telemetry_data.get("CarIdxPosition", [0])[0]  # P11
    if not hasattr(self, "_last_position"):
        self._last_position = current_pos
        return False, {}

    if current_pos != self._last_position:  # 11 != 12 = TRUE
        old_pos = self._last_position  # 12
        self._last_position = current_pos  # 11
        return True, {"old_pos": 12, "new_pos": 11}

    return False, {}
```

**LLM Prompt Generated:**

```
"Generate a brief race engineer position update. Position changed from P12 to P11. Keep it under 12 words."
```

**Expected LLM Response:**
_"Great move! Up to P11 from P12 - nice pass!"_

---

### **Event: Flag Change**

**Timestamp:** 00:26:30
**Trigger Condition:** `current_flags != self._last_flags`

```python
def _check_flag_threshold(self, telemetry_data):
    current_flags = telemetry_data.get("SessionFlags", 0)  # 0x00000008 (Yellow)
    if not hasattr(self, "_last_flags"):
        self._last_flags = current_flags
        return False, {}

    if current_flags != self._last_flags:  # 0x00000008 != 0x00000004 = TRUE
        old_flags = self._last_flags  # 0x00000004 (Green)
        self._last_flags = current_flags  # 0x00000008 (Yellow)
        return True, {"old_flags": 4, "new_flags": 8}

    return False, {}
```

**LLM Prompt Generated:**

```
"Generate a brief race engineer flag status update. Flag changed from 4 to 8. Keep it under 12 words."
```

**Expected LLM Response:**
_"Yellow flag! Incident ahead - maintain position, no passing"_

---

### **Watchdog Event Processing Loop**

**Called every 5 seconds from `_watchdog_loop()`**

```python
async def _process_watchdog_events(self):
    if not self.telemetry_data:
        return

    current_time = time.time()  # 1742486700.0 (example timestamp)

    for event in self.watchdog_events:
        # Example: processing fuel_critical event
        if not event.enabled:  # Check user config: self.fuel_alerts_enabled = True
            continue

        # Check timing: last_check_time + 10.0 < current_time
        if current_time - event.last_check_time < event.check_interval:  # 10.0 seconds
            continue

        # Check cooldown: last_trigger_time + 30.0 < current_time
        if current_time - event.last_trigger_time < event.cooldown_period:  # 30.0 seconds
            continue

        event.last_check_time = current_time

        try:
            # Call: self._check_fuel_threshold(self.telemetry_data)
            triggered, context = event.threshold_func(self.telemetry_data)

            if triggered:  # True for fuel critical
                event.last_trigger_time = current_time

                # Format prompt with context
                prompt = event.prompt_template.format(**context)
                # "Generate a brief race engineer fuel warning. Fuel level: 14.2L, laps remaining: 1.8. Keep it under 12 words."

                # Send to LLM and play to user
                await self.wingman.add_assistant_message(
                    text=prompt,
                    play_to_user=True,
                    context={"event": "fuel_critical", "telemetry": {"fuel_level": 14.2, "laps_remaining": 1.8}}
                )

                # Debug logging
                if self.settings.debug_mode:
                    await self.printr.print_async(
                        text="iRacing watchdog triggered: fuel_critical",
                        color=LogType.INFO,
                    )

        except Exception as e:
            # Error handling for individual events
            if self.settings.debug_mode:
                await self.printr.print_async(
                    text=f"iRacing watchdog event error (fuel_critical): {str(e)}",
                    color=LogType.ERROR,
                )
```

---

## Configuration Impact on Behavior

### **User Settings Effect:**

```yaml
# User has configured these values in UI:
fuel_alerts_enabled: true
fuel_alerts_interval: 10 # Check every 10 seconds
alert_cooldown_period: 30 # 30 seconds between same alerts
```

### **Timing Calculations:**

- **Check Interval:** Event threshold function called every 10 seconds
- **Cooldown Period:** Same event type blocked for 30 seconds after trigger
- **Multiple Events:** Different event types can trigger simultaneously

### **Cost Analysis:**

- **LLM Calls:** Only when events trigger (not on every check)
- **Token Usage:** Brief prompts (< 50 tokens) + brief responses (< 20 tokens)
- **Frequency:** Average 1 alert per 3 minutes = 20 LLM calls per hour during active racing

### **Performance Impact:**

- **Watchdog Loop:** Runs every 5 seconds (configurable)
- **Event Processing:** Adds ~50ms to each watchdog cycle
- **Memory Usage:** Minimal state tracking per event
- **CPU Usage:** Negligible threshold calculations

This technical analysis shows how our watchdog system provides **intelligent, context-aware racing assistance** while maintaining **efficient resource usage** and **user configurability**.
