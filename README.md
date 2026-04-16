# Vyapy QA Bot

An automated QA bot that runs test scenarios on the Vyapy apps (iOS and Android) and generates pass/fail reports with detailed explanations.

---

## What This Does

The bot controls two real devices simultaneously:
- **Consumer app** — places orders, makes payments
- **Business app** — accepts orders, manages tables

It runs scripted test scenarios end-to-end across both devices in parallel and outputs a report showing what passed, what failed, and why.

There are two versions of the bot:
- **iOS** (active) — uses XCTest + xcodebuild, runs on Mac with real iPhones
- **Android** (legacy) — uses ADB + uiautomator, runs on Windows with Android devices

---

## Folder Structure

```
vya-agent-testing-main/
├── ios/                        # iOS bot (active)
│   ├── ios_agent_manager.py    # Main entry point for iOS — run this
│   ├── ios_scenarios.py        # All 76 test scenarios
│   └── parallel_xctest_runner.py
├── android/                    # Android bot
│   ├── multi_agent_manager.py  # Main entry point for Android — run this
│   └── scenarios.py            # Android scenario definitions
├── shared/                     # Shared utilities (used by both iOS and Android)
│   ├── bill_validator.py       # Validates bill math on screen
│   └── scenario_reporter.py   # Generates HTML/JSON reports
├── legacy/                     # Old implementations (archived, do not use)
├── docs/                       # Plans and account info
├── Consumer/                   # Output: screenshots + recorded scripts
├── Business/                   # Output: screenshots + recorded scripts
└── groq_key.txt                # Groq AI API key (do not commit)
```

---

---

# iOS Setup & Run Guide

---

## iOS Requirements

- macOS with Xcode 15+ installed
- Python 3.9+
- Groq API key (get one free at console.groq.com)
- Two iPhones with the Vyapy apps installed

```bash
pip3 install groq
```

### iOS Devices
| Role | Device | UDID |
|------|--------|------|
| Consumer | Xorstack's iPhone (iOS 18.6) | `00008030-000E39093C2B402E` |
| Business | iPhone XR (iOS 18.5) | `00008020-000531620150003A` |

---

## iOS Step 1 — Connect Devices

1. Plug both iPhones into the Mac via USB
2. Unlock each device
3. Tap **"Trust This Computer"** on each device if prompted
4. Verify both are detected (no "Connecting" status):

```bash
xcrun xctrace list devices
```

---

## iOS Step 2 — Build the Apps for Testing

Only needed once, or after any code change to the app.

**Consumer:**
```bash
cd /Users/roops/Desktop/Vya/vya-consumer/ios
xcodebuild build-for-testing \
  -workspace vyaconsumer.xcworkspace \
  -scheme vyaconsumer \
  -destination "id=00008030-000E39093C2B402E" \
  -allowProvisioningUpdates
```

**Business:**
```bash
cd /Users/roops/Desktop/Vya/vya-business/ios
xcodebuild build-for-testing \
  -workspace VyaBusinessiPad.xcworkspace \
  -scheme VyaBusinessiPad \
  -destination "id=00008020-000531620150003A" \
  -allowProvisioningUpdates
```

---

## iOS Step 3 — Add Groq API Key

```bash
echo "your_groq_api_key_here" > groq_key.txt
```

---

## iOS Step 4 — Run the Bot

```bash
cd /Users/roops/Desktop/Vya/Vya-agentic-Bot/vya-agent-testing-main/ios
python3 ios_agent_manager.py
```

### How iOS Works

1. Bot sends a JSON action payload to the device via XCTest
2. XCTest on the device reads the payload and performs the action (tap, type, scroll)
3. Both Consumer and Business run in parallel, syncing at key points (e.g. order placed → business accepts)

```
Python Bot → JSON payload → xcodebuild test-without-building → Swift XCTest runner → iPhone
```

---

## iOS Troubleshooting

**Device shows "Connecting" / no Trust dialog:**
- Settings → General → Transfer or Reset iPhone → Reset → Reset Location & Privacy → replug

**xcodebuild RC 70 (can't find device):**
- Make sure device is unlocked and trusted
- Check iOS version matches the build target (18.x)
- Re-run build-for-testing

**XCTest action fails silently:**
- Re-run build-for-testing to refresh the `.xctestrun` file

---

---

# Android Setup & Run Guide

> **Note:** The Android bot runs on Windows and uses ADB to control Android devices. Update the hardcoded paths in `multi_agent_manager.py` to match your machine before running.

---

## Android Requirements

- Windows PC
- Android Studio installed (for ADB)
- Python 3.9+
- Groq API key
- Two Android devices with the Vyapy apps installed and USB debugging enabled

```bash
pip3 install groq
```

---

## Android Step 1 — Enable USB Debugging on Devices

On each Android device:
1. Go to **Settings → About Phone**
2. Tap **Build Number** 7 times to unlock Developer Options
3. Go to **Settings → Developer Options → Enable USB Debugging**
4. Plug in via USB and tap **Allow** on the device when prompted

---

## Android Step 2 — Verify ADB Detects the Devices

```bash
adb devices
```

Both devices should appear with `device` status (not `unauthorized`).

---

## Android Step 3 — Update Paths in multi_agent_manager.py

Open `android/multi_agent_manager.py` and update these lines to match your machine:

```python
ADB = r"C:\path\to\Android\Sdk\platform-tools\adb.exe"
GROQ_KEY_FILE = Path(r"C:\path\to\groq_key.txt")
```

Also update the device serial IDs and package names at the bottom of the file (`__main__` block).

---

## Android Step 4 — Add Groq API Key

Create `groq_key.txt` in the project root with your Groq API key.

---

## Android Step 5 — Run the Bot

```bash
cd /path/to/vya-agent-testing-main/android
python3 multi_agent_manager.py
```

### How Android Works

1. Bot calls ADB to dump the UI hierarchy as XML
2. Parses the XML to find elements by content-desc or text
3. Sends ADB tap/type/swipe commands to interact with the app
4. Groq AI is used as fallback when elements can't be found automatically

```
Python Bot → ADB commands → Android device UI
```

---

## Android Troubleshooting

**`adb devices` shows `unauthorized`:**
- Unlock the device and tap **Allow** on the USB debugging prompt

**Element not found errors:**
- The content-desc values may have changed — check the app's accessibility labels
- Groq AI fallback will attempt to recover automatically

---

---

# Shared: Input Options & Scenario Keys

Both iOS and Android bots use the same scenario key format.

### Input Options at the Prompt

| Input | What it does |
|-------|-------------|
| `EB1` | Run a single scenario by key |
| `CW1,EB1,O1` | Run multiple specific scenarios |
| `1-10` | Run first 10 scenarios by position |
| `all` | Run all scenarios |

### Scenario Key Prefixes

| Prefix | Feature |
|--------|---------|
| `EB` | Event Booking |
| `EC` | Event Cancellation |
| `O` | Ordering |
| `CW` | Consumer Wallet |
| `P` | Payments |
| `R` | Reviews |

To see the full list, run the bot — it prints all available keys before the prompt.

---

## Output (Both Platforms)

After each run:
- **Console** — real-time PASS/FAIL per scenario
- **`Consumer/screenshots/`** and **`Business/screenshots/`** — screenshots taken during the run
- **`Consumer/recorded_script.py`** and **`Business/recorded_script.py`** — logs of every action taken

---

## Groq AI Fallback

Both bots use Groq (free AI API) as a fallback when they can't find an element on screen. Without it the bot still runs, but may fail more often on unexpected screens.

Get a free key at: https://console.groq.com
