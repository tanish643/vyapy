"""
iOS Multi-Agent Manager for Vyapy QA Bot
Uses Meta's idb (iOS Device Bridge) instead of Appium for ADB-like performance.

Setup (Mac):
  brew tap facebook/idb
  brew install idb-companion
  pip3 install groq

Usage:
  # No background servers required. Just run:
  python3 ios_agent_manager.py
"""

import threading
import time
import sys
import json
import urllib.request
import re
import os
import subprocess
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
import bill_validator
import scenario_reporter

# --- Configuration ---
BASE_DIR = Path(__file__).parent
GROQ_KEY_FILE = BASE_DIR.parent / "groq_key.txt"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.1-8b-instant"

SYSTEM_PROMPT = """You are a mobile QA agent for Vyapy food ordering app.
Given ONE task and current screen elements, output the next single action as JSON only.
Actions:
{"action":"tap","target":"element_name"}
{"action":"scroll_down"}
{"action":"scroll_up"}
{"action":"type","text":"value"}
{"action":"wait","seconds":2}
{"action":"step_done"}
Rules:
- ONE action per response
- Use exact accessibility label values
- When task is complete use step_done
- If stuck after 3 scrolls use step_done"""


class VyapyAgent:
    def __init__(self, udid, bundle_id, role_name, device_name=None, is_simulator=True):
        self.udid = udid
        self.bundle_id = bundle_id
        self.role = role_name  # Consumer or Business
        self.is_simulator = is_simulator
        self._screen_w = None
        self._screen_h = None

        # Boot simulator if needed
        if self.is_simulator:
            self._boot_simulator()

        # Output directories
        self.out_dir = BASE_DIR / self.role
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.screenshot_dir = self.out_dir / "screenshots"
        self.screenshot_dir.mkdir(exist_ok=True)

        # Tracking state for reporting
        self.last_launch_time = None
        self.last_screenshot = None
        self.last_action_error = None
        self.current_scenario_num = "?"
        self.current_scenario_name = "Unknown"

        # Recording
        self.record_file = self.out_dir / "recorded_script.py"
        with open(self.record_file, "a") as f:
            f.write(f"\n# --- New Recorded Session for {self.role} (idb) ---\n")

    def _boot_simulator(self):
        """Boot the simulator if it's not already running."""
        try:
            result = subprocess.run(
                ["xcrun", "simctl", "list", "devices", "-j"],
                capture_output=True, text=True
            )
            import json as _json
            devices = _json.loads(result.stdout)
            for runtime, devs in devices.get("devices", {}).items():
                for d in devs:
                    if d["udid"] == self.udid:
                        if d["state"] == "Booted":
                            print(f"[{self.role}] Simulator already booted: {d['name']}")
                            return
                        print(f"[{self.role}] Booting simulator: {d['name']}...")
                        subprocess.run(["xcrun", "simctl", "boot", self.udid], check=True)
                        time.sleep(5)
                        print(f"[{self.role}] Simulator booted.")
                        return
        except Exception as e:
            print(f"[{self.role}] Simulator boot error: {e}")

    def _run_idb(self, cmd_args, capture_output=True):
        """Run an idb command via subprocess."""
        full_cmd = ["idb"] + cmd_args + ["--udid", self.udid]
        if capture_output:
            try:
                result = subprocess.run(full_cmd, capture_output=True, text=True, check=True)
                return result.stdout
            except subprocess.CalledProcessError as e:
                print(f"[{self.role}] idb error: {e.stderr}")
                return ""
        else:
            subprocess.run(full_cmd)
            return ""

    def dump_ui(self):
        """Get UI hierarchy from idb. idb returns JSON; we convert to normalized XML for bot compatibility."""
        try:
            raw_json = self._run_idb(["ui", "describe-all"])
            if not raw_json:
                return ""
            data = json.loads(raw_json)

            # idb describe-all returns a flat list of elements (no nested children)
            # Convert to pseudo-XML for find_by_desc/regex compatibility
            return self._json_to_pseudo_xml(data)
        except Exception as e:
            print(f"[{self.role}] dump_ui error: {e}")
            return ""

    def _json_to_pseudo_xml(self, nodes):
        """Recursively flatten idb JSON tree into Android-like XML nodes."""
        lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<hierarchy rotation="0">']

        def process_node(node):
            # Extract frame/bounds — idb returns both "frame" dict and "AXFrame" string
            frame_dict = node.get("frame")
            if frame_dict and isinstance(frame_dict, dict):
                x = int(round(frame_dict.get("x", 0)))
                y = int(round(frame_dict.get("y", 0)))
                w = int(round(frame_dict.get("width", 0)))
                h = int(round(frame_dict.get("height", 0)))
            else:
                # Fallback: parse AXFrame string "{{x, y}, {w, h}}" with float support
                frame_str = node.get("AXFrame", "{{0,0},{0,0}}")
                m = re.findall(r"[\d.]+", frame_str)
                if len(m) >= 4:
                    x, y, w, h = int(float(m[0])), int(float(m[1])), int(float(m[2])), int(float(m[3]))
                else:
                    x, y, w, h = 0, 0, 0, 0

            bounds = f'bounds="[{x},{y}][{x+w},{y+h}]"'

            # Extract identifier/label as content-desc/text
            desc = node.get("AXIdentifier") or node.get("AXLabel") or node.get("AXValue") or ""
            text = node.get("AXLabel") or ""

            # Escape XML special characters
            desc = str(desc).replace('"', '&quot;').replace('&', '&amp;').replace('<', '&lt;')
            text = str(text).replace('"', '&quot;').replace('&', '&amp;').replace('<', '&lt;')

            # idb marks interactable elements
            role = node.get("role") or node.get("AXRole") or ""
            clickable = "true" if role in ["AXButton", "AXTextField", "AXStaticText", "AXCell", "AXLink", "AXImage"] else "false"

            xml_line = f'  <node content-desc="{desc}" text="{text}" {bounds} clickable="{clickable}" />'
            lines.append(xml_line)

            # Recurse into children if present
            for child in node.get("children", []):
                process_node(child)

        if isinstance(nodes, list):
            for n in nodes:
                process_node(n)
        else:
            process_node(nodes)

        lines.append('</hierarchy>')
        return '\n'.join(lines)

    def screenshot(self, name):
        """Take a screenshot via idb."""
        if not name.lower().endswith(".png"):
            name += ".png"
        path = self.screenshot_dir / name
        try:
            self._run_idb(["screenshot", str(path)])
        except Exception as e:
            print(f"[{self.role}] Screenshot error: {e}")
        return str(path)

    def record_action(self, code):
        """Append a hardcoded action to the record file."""
        with open(self.record_file, "a") as f:
            f.write(f"{code}\n")

    # Screen loading timeout (seconds) — if element lookup takes longer, it's reported
    SCREEN_LOAD_TIMEOUT = 4

    def _find_element(self, label, xml=None):
        """Find element by label/desc in current UI. Returns (x, y, matched_label) or None."""
        if xml is None:
            xml = self.dump_ui()
        result = self.find_by_desc(xml, label) or self.find_by_text(xml, label)
        return result

    def wait_for_element(self, label, timeout=None, scroll_retries=3):
        """Wait for element to appear on screen. Auto-scrolls if not found.
        Returns (x, y, label) or None. Reports slow screen loads (>4s)."""
        if timeout is None:
            timeout = self.SCREEN_LOAD_TIMEOUT
        start = time.time()

        # First attempt — check current screen
        result = self._find_element(label)
        if result:
            return result

        # Poll until timeout
        deadline = start + timeout
        while time.time() < deadline:
            time.sleep(0.5)
            result = self._find_element(label)
            if result:
                elapsed = time.time() - start
                if elapsed > self.SCREEN_LOAD_TIMEOUT:
                    print(f"[{self.role}] SLOW SCREEN: '{label}' took {elapsed:.1f}s (>{self.SCREEN_LOAD_TIMEOUT}s)")
                    scenario_reporter.add_result(
                        scenario_num=self.current_scenario_num,
                        scenario_name=self.current_scenario_name,
                        role=self.role,
                        status="WARN",
                        reason=f"Screen load slow: '{label}' found after {elapsed:.1f}s (limit {self.SCREEN_LOAD_TIMEOUT}s)",
                        launch_time=None,
                        screenshot_path=None,
                    )
                return result

        # Not found after timeout — auto-scroll and retry
        for attempt in range(1, scroll_retries + 1):
            print(f"[{self.role}] Element '{label}' not found — scrolling down (attempt {attempt}/{scroll_retries})")
            self.swipe_up()
            time.sleep(0.8)
            result = self._find_element(label)
            if result:
                elapsed = time.time() - start
                if elapsed > self.SCREEN_LOAD_TIMEOUT:
                    print(f"[{self.role}] SLOW SCREEN: '{label}' took {elapsed:.1f}s (>{self.SCREEN_LOAD_TIMEOUT}s)")
                    scenario_reporter.add_result(
                        scenario_num=self.current_scenario_num,
                        scenario_name=self.current_scenario_name,
                        role=self.role,
                        status="WARN",
                        reason=f"Screen load slow: '{label}' found after {elapsed:.1f}s (needed scroll x{attempt})",
                        launch_time=None,
                        screenshot_path=None,
                    )
                return result

        elapsed = time.time() - start
        print(f"[{self.role}] Element '{label}' NOT FOUND after {elapsed:.1f}s + {scroll_retries} scrolls")
        return None

    def xctest_wait_for(self, label, timeout=15):
        """Wait for element to appear (compatibility method). Returns True/False."""
        result = self.wait_for_element(label, timeout=timeout, scroll_retries=3)
        return result is not None

    def tap(self, x, y, label=""):
        """Tap element. If x=0,y=0 and label is given, find element by label first (with auto-scroll)."""
        if x == 0 and y == 0 and label:
            # Label-based tap: find element, scroll if needed
            result = self.wait_for_element(label)
            if result:
                tx, ty, matched = result
                print(f"[{self.role}] TAP ({tx},{ty}) '{matched}'")
                try:
                    self._run_idb(["ui", "tap", str(tx), str(ty)])
                except Exception as e:
                    print(f"[{self.role}] Tap error: {e}")
                    self.last_action_error = str(e)
                    return False
                self.record_action(f'agent.tap({tx}, {ty}, "{matched}")')
                time.sleep(1.2)
                return True
            else:
                print(f"[{self.role}] TAP FAILED — element '{label}' not found")
                self.last_action_error = f"Element '{label}' not found on screen"
                return False
        else:
            # Coordinate-based tap
            print(f"[{self.role}] TAP ({x},{y}) {label}")
            try:
                self._run_idb(["ui", "tap", str(x), str(y)])
            except Exception as e:
                print(f"[{self.role}] Tap error: {e}")
                return False
            self.record_action(f'agent.tap({x}, {y}, "{label}")')
            time.sleep(1.2)
            return True

    def _swipe(self, start_x, start_y, end_x, end_y, duration_ms=400):
        """Perform a swipe gesture via idb."""
        try:
            self._run_idb(["ui", "swipe", str(start_x), str(start_y), str(end_x), str(end_y)])
        except Exception as e:
            print(f"[{self.role}] Swipe error: {e}")

    def _get_screen_size(self):
        """Get screen size in points from the first element (Application frame)."""
        if self._screen_w and self._screen_h:
            return self._screen_w, self._screen_h
        try:
            raw = self._run_idb(["ui", "describe-all"])
            if raw:
                data = json.loads(raw)
                if data and isinstance(data, list):
                    frame = data[0].get("frame", {})
                    self._screen_w = int(frame.get("width", 402))
                    self._screen_h = int(frame.get("height", 874))
                    return self._screen_w, self._screen_h
        except Exception:
            pass
        # Fallback: iPhone 16 Pro simulator points
        return 402, 874

    def swipe_up(self):
        """Swipe up (scrolls page down)."""
        w, h = self._get_screen_size()
        cx = w // 2
        self._swipe(cx, int(h * 0.70), cx, int(h * 0.25), 400)
        self.record_action("agent.swipe_up()")
        time.sleep(0.8)

    def swipe_down(self):
        """Swipe down (scrolls page up)."""
        w, h = self._get_screen_size()
        cx = w // 2
        self._swipe(cx, int(h * 0.25), cx, int(h * 0.70), 400)
        self.record_action("agent.swipe_down()")
        time.sleep(0.8)

    def swipe_up_small(self):
        """Small swipe up inside a dialog/popup (scrolls content down a bit)."""
        w, h = self._get_screen_size()
        cx = w // 2
        self._swipe(cx, int(h * 0.60), cx, int(h * 0.35), 300)
        time.sleep(0.5)

    def type_text(self, text, target=None):
        """Type text into a field. Uses simctl pasteboard paste for reliability.
        If target label is given, tap it first to focus.
        Dismisses keyboard after typing."""
        if target:
            tap_ok = self.tap(0, 0, target)
            if not tap_ok:
                self.last_action_error = f"Cannot type — field '{target}' not found"
                return False
            time.sleep(0.8)

        print(f"[{self.role}] TYPING: '{text}'")
        try:
            # Method 1: simctl pasteboard + paste (most reliable for simulators)
            subprocess.run(
                ["xcrun", "simctl", "pbcopy", self.udid],
                input=text, text=True, check=True
            )
            time.sleep(0.2)
            # Cmd+V to paste (key-sequence: 55=Cmd, 9=V)
            self._run_idb(["ui", "key-sequence", "55", "9"])
            time.sleep(0.3)
        except Exception as e1:
            print(f"[{self.role}] Paste method failed ({e1}), trying idb ui text...")
            try:
                self._run_idb(["ui", "text", text])
            except Exception as e2:
                print(f"[{self.role}] Type error: {e2}")
                self.last_action_error = str(e2)
                return False

        self.record_action(f'agent.type_text("{text}")')
        time.sleep(0.3)
        self.dismiss_keyboard()
        return True

    def dismiss_keyboard(self):
        """Dismiss the on-screen keyboard."""
        print(f"[{self.role}] Dismissing keyboard...")
        try:
            # Press Return/Done key to dismiss (key code 40)
            self._run_idb(["ui", "key", "40"])
            time.sleep(0.5)
        except Exception:
            pass
        # Fallback: tap an empty area at the top of the screen
        try:
            self._run_idb(["ui", "tap", "10", "50"])
            time.sleep(0.3)
        except Exception:
            pass

    def launch_app(self):
        """Launch the assigned application via idb."""
        print(f"[{self.role}] Launching: {self.bundle_id}")
        start = time.time()
        try:
            # idb launch takes bundle id
            self._run_idb(["launch", self.bundle_id])
        except Exception as e:
            print(f"[{self.role}] Launch error: {e}")
        self.last_launch_time = round(time.time() - start, 2)
        print(f"[{self.role}] App ready in {self.last_launch_time:.2f}s")

    def go_home(self):
        """Press home via idb."""
        print(f"[{self.role}] Going Home")
        try:
            self._run_idb(["ui", "button", "HOME"])
            time.sleep(1)
        except Exception:
            pass
        self.launch_app()
        return True

    def check_bill(self):
        """Validate bill math on the current checkout screen."""
        print(f"[{self.role}] Validating bill math...")
        xml = self.dump_ui()
        result = bill_validator.validate_bill(xml)

        if not result["is_bill_screen"]:
            print(f"[{self.role}] Not a bill screen — skipping validation")
            return result

        status = "PASS" if result["pass"] else "FAIL"
        shot = None
        if not result["pass"]:
            shot = self.screenshot(f"bill_fail_{int(time.time())}")
            self.last_screenshot = shot

        scenario_reporter.add_result(
            scenario_num=self.current_scenario_num,
            scenario_name=self.current_scenario_name,
            role=self.role,
            status=status,
            reason=result["reason"],
            launch_time=None,
            screenshot_path=shot,
        )
        print(f"[{self.role}] Bill check: {status} — {result['reason']}")
        return result

    # --- Element finding (same regex as Android — works because we normalize XML) ---
    def find_by_desc(self, xml, *desc_options):
        for desc in desc_options:
            exact1 = rf'content-desc="{re.escape(desc)}"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
            exact2 = rf'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*content-desc="{re.escape(desc)}"'
            m = re.search(exact1, xml) or re.search(exact2, xml)
            if not m:
                pattern = rf'content-desc="[^"]*{re.escape(desc)}[^"]*"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
                m = re.search(pattern, xml)
            if not m:
                pattern = rf'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*content-desc="[^"]*{re.escape(desc)}[^"]*"'
                m = re.search(pattern, xml)
            if not m:
                rid1 = rf'resource-id="[^"]*{re.escape(desc)}"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
                rid2 = rf'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*resource-id="[^"]*{re.escape(desc)}"'
                m = re.search(rid1, xml) or re.search(rid2, xml)
            if m:
                x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                if x1 == 0 and y1 == 0 and x2 == 0 and y2 == 0:
                    return None
                return (x1 + x2) // 2, (y1 + y2) // 2, desc
        return None

    def find_by_text(self, xml, *text_options):
        for txt in text_options:
            exact1 = rf'text="{re.escape(txt)}"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
            exact2 = rf'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*text="{re.escape(txt)}"'
            m = re.search(exact1, xml) or re.search(exact2, xml)
            if not m:
                pattern = rf'text="[^"]*{re.escape(txt)}[^"]*"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
                m = re.search(pattern, xml)
            if not m:
                pattern = rf'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*text="[^"]*{re.escape(txt)}[^"]*"'
                m = re.search(pattern, xml)
            if m:
                x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                return (x1 + x2) // 2, (y1 + y2) // 2, txt
        return None

    def get_screen_name(self):
        """Get current screen/activity name (iOS doesn't have this natively)."""
        return "iOS_Screen"

    def parse_elements(self, xml):
        elements = []
        for m in re.finditer(r"<[^>]+>", xml):
            node = m.group(0)
            desc = re.search(r'content-desc="([^"]+)"', node)
            text = re.search(r'text="([^"]+)"', node)
            bounds = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
            clickable = "clickable=\"true\"" in node or "enabled=\"true\"" in node
            if (desc or text) and bounds:
                x1, y1, x2, y2 = int(bounds.group(1)), int(bounds.group(2)), int(bounds.group(3)), int(bounds.group(4))
                elements.append({
                    "desc": desc.group(1) if desc else "",
                    "text": text.group(1) if text else "",
                    "center": [(x1 + x2) // 2, (y1 + y2) // 2],
                    "clickable": clickable,
                })
        return elements

    def build_elements_str(self, elements):
        relevant = [e for e in elements if e["clickable"]] + [e for e in elements if not e["clickable"]]
        relevant = relevant[:20]
        lines = []
        for e in relevant:
            label = e["desc"] or e["text"]
            prefix = "?" if e["clickable"] else "-"
            lines.append(f"{prefix} {label}")
        return "\n".join(lines)

    def call_groq(self, task_desc, elements, screen_name):
        if not GROQ_KEY_FILE.exists():
            print(f"[{self.role}] Groq Key missing")
            return None
        api_key = GROQ_KEY_FILE.read_text(encoding="utf-8").strip()
        if not api_key:
            return None

        elements_str = self.build_elements_str(elements)
        prompt = f"""{SYSTEM_PROMPT} You are currently acting as the {self.role} using {self.bundle_id}.

TASK: {task_desc}
SCREEN: {screen_name}
ELEMENTS:
{elements_str}

JSON?"""
        body = {
            "model": GROQ_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 100,
        }
        req = urllib.request.Request(
            GROQ_URL,
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "Mozilla/5.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            raw = data["choices"][0]["message"]["content"]
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            return json.loads(m.group(0)) if m else None
        except Exception as e:
            print(f"[{self.role}] Groq error: {e}")
            return None

    def execute_action(self, action, elements):
        a = action.get("action")
        if a == "tap":
            target = action.get("target", "").split(",")[0].strip()
            found = False
            for e in elements:
                if e["desc"] == target or e["text"] == target:
                    self.tap(e["center"][0], e["center"][1], f"[{target}]")
                    found = True
                    break
            if not found:
                xml = self.dump_ui()
                result = self.find_by_desc(xml, target) or self.find_by_text(xml, target)
                if result:
                    self.tap(result[0], result[1], f"[{target}]")
        elif a == "scroll_down":
            self.swipe_up()
        elif a == "scroll_up":
            self.swipe_down()
        elif a == "type":
            text = action.get("text", "")
            self.type_text(text)
        elif a == "wait":
            secs = int(action.get("seconds", 2))
            time.sleep(secs)
            self.record_action(f'time.sleep({secs})')

    def run_step_ai(self, task_desc, max_retries=6):
        """Pure AI driven step execution for the agent."""
        print(f"[{self.role}] AI Step: {task_desc}")
        for attempt in range(max_retries):
            xml = self.dump_ui()
            elements = self.parse_elements(xml)
            old_elements_str = self.build_elements_str(elements)
            screen = self.get_screen_name()

            action = self.call_groq(task_desc, elements, screen)
            if not action:
                time.sleep(2)
                continue

            print(f"[{self.role}] AI decided: {action}")
            if action.get("action") == "step_done":
                print(f"[{self.role}] AI Step Complete.")
                return True

            self.execute_action(action, elements)

            if action.get("action") in ["tap", "scroll_down", "scroll_up", "type"]:
                wait_start = time.time()
                changed = False
                while time.time() - wait_start < 45:
                    new_xml = self.dump_ui()
                    new_elems = self.parse_elements(new_xml)
                    new_elements_str = self.build_elements_str(new_elems)
                    if new_elements_str != old_elements_str:
                        time.sleep(1.0)
                        changed = True
                        break
                    time.sleep(1.5)
                if not changed:
                    print(f"[{self.role}] UI did not change after 45s wait. Retrying AI step...")
                else:
                    if action.get("action") in ["tap", "type"]:
                        print(f"[{self.role}] AI Step Complete (UI changed).")
                        return True
            else:
                time.sleep(2)

        print(f"[{self.role}] AI Step Failed after {max_retries} retries.")
        return False

    def cleanup(self):
        """Cleanup (no-op for idb)."""
        pass


# --- adb compatibility stub (handles Android adb calls on iOS) ---
def _adb_stub(self, *args):
    """Handle adb-style calls by mapping to iOS equivalents."""
    args_str = " ".join(str(a) for a in args)
    if "KEYCODE_HIDE" in args_str or "KEYCODE_BACK" in args_str:
        # Keyboard dismiss — use iOS dismiss_keyboard
        self.dismiss_keyboard()
    else:
        print(f"[{self.role}] Ignored adb call: {args}")
    return type('Result', (), {'stdout': '', 'stderr': '', 'returncode': 0})()

VyapyAgent.adb = _adb_stub


import ios_scenarios as scenarios


def run_scenario(num, scenario, consumer_agent, business_agent):
    """Run one scenario with both agents in parallel and record results."""
    name = scenario["name"]
    print(f"\n{'='*60}")
    print(f"  [{num}] {name}")
    print(f"{'='*60}")

    for agent in (consumer_agent, business_agent):
        agent.current_scenario_num = num
        agent.current_scenario_name = name
        agent.last_screenshot = None

    scenarios.clear_events()

    consumer_errors = []
    business_errors = []

    def run_consumer():
        try:
            scenario["consumer"](consumer_agent)
        except Exception as e:
            consumer_errors.append(str(e))
            print(f"[Consumer] ERROR: {str(e).encode('ascii', errors='replace').decode('ascii')}")

    def run_business():
        try:
            scenario["business"](business_agent)
        except Exception as e:
            business_errors.append(str(e))
            print(f"[Business] ERROR: {str(e).encode('ascii', errors='replace').decode('ascii')}")

    t1 = threading.Thread(target=run_consumer)
    t2 = threading.Thread(target=run_business)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    for agent, errors in [(consumer_agent, consumer_errors), (business_agent, business_errors)]:
        if errors:
            scenario_reporter.add_result(
                scenario_num=num,
                scenario_name=name,
                role=agent.role,
                status="FAIL",
                reason=errors[0],
                launch_time=agent.last_launch_time,
                screenshot_path=agent.last_screenshot,
            )
        else:
            scenario_reporter.add_result(
                scenario_num=num,
                scenario_name=name,
                role=agent.role,
                status="PASS",
                reason="Completed",
                launch_time=agent.last_launch_time,
                screenshot_path=None,
            )

    print(f"  [{num}] Done — Consumer: {'FAIL' if consumer_errors else 'PASS'} | Business: {'FAIL' if business_errors else 'PASS'}")


if __name__ == "__main__":
    # ╔══════════════════════════════════════════════════════════════╗
    # ║  UPDATE THESE VALUES HERE                                    ║
    # ╚══════════════════════════════════════════════════════════════╝
    # Simulator UDIDs (from `xcrun simctl list devices`)
    CONSUMER_UDID = "A8C31FA6-AE36-41E8-897A-F628B15A980D"  # iPhone 16 Pro Simulator
    BUSINESS_UDID = "F7661759-D7EE-4A7E-9357-0EF0CCE03DEF"  # iPad Air 11-inch (M3) Simulator

    # Bundle IDs
    CONSUMER_BUNDLE = "org.vyapy.sarls.vyaconsumer"
    BUSINESS_BUNDLE = "org.vyapy.sarls.vyabusinessipad"

    print("=" * 60)
    print("  VYAPY QA Bot — iOS Mode (Simulators via idb)")
    print("=" * 60)
    print(f"  Consumer: {CONSUMER_UDID} → {CONSUMER_BUNDLE} (iPhone 16 Pro Simulator)")
    print(f"  Business: {BUSINESS_UDID} → {BUSINESS_BUNDLE} (iPad Air 11\" Simulator)")
    print()

    print("Initializing iOS Agents via idb (simulators)...")
    consumer_agent = VyapyAgent(
        udid=CONSUMER_UDID,
        bundle_id=CONSUMER_BUNDLE,
        role_name="Consumer",
        is_simulator=True,
    )
    business_agent = VyapyAgent(
        udid=BUSINESS_UDID,
        bundle_id=BUSINESS_BUNDLE,
        role_name="Business",
        is_simulator=True,
    )

    all_keys = list(scenarios.SCENARIO_MAP.keys())

    print("\nAvailable Scenarios:")
    for i, (key, s) in enumerate(scenarios.SCENARIO_MAP.items(), 1):
        print(f"  {i:>2}. [{key}] {s['name']}")
    print("\nExamples:")
    print("  all          → run all scenarios")
    print("  1-10         → run first 10 scenarios by position")
    print("  CW1          → run a single scenario by key")
    print("  CW1,EB1,O1   → run specific scenarios by key")

    if len(sys.argv) > 1:
        choice = sys.argv[1]
        print(f"\nAuto-selected choice: {choice}")
    else:
        choice = input("\nEnter choice: ").strip()

    keys_to_run = []

    if choice.lower() == "all":
        keys_to_run = all_keys
    elif "-" in choice and not choice.upper().startswith(tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ")):
        try:
            start, end = choice.split("-")
            start, end = int(start.strip()) - 1, int(end.strip()) - 1
            keys_to_run = all_keys[max(0, start): end + 1]
        except ValueError:
            print("Invalid range. Use format like '1-10'.")
            exit(1)
    elif "," in choice:
        requested = [k.strip().upper() for k in choice.split(",")]
        invalid = [k for k in requested if k not in scenarios.SCENARIO_MAP]
        if invalid:
            print(f"Unknown scenario keys: {invalid}")
            exit(1)
        keys_to_run = requested
    elif choice.upper() in scenarios.SCENARIO_MAP:
        keys_to_run = [choice.upper()]
    else:
        print("Invalid choice. Exiting.")
        exit(1)

    print(f"\nRunning {len(keys_to_run)} scenario(s): {', '.join(keys_to_run)}\n")
    try:
        for key in keys_to_run:
            run_scenario(key, scenarios.SCENARIO_MAP[key], consumer_agent, business_agent)
    finally:
        # Clean up
        consumer_agent.cleanup()
        business_agent.cleanup()

    scenario_reporter.save_run_to_history()
    scenario_reporter.print_summary()
