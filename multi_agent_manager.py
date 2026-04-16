import threading
import subprocess
import time
import sys
import signal
import os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path
import json
import urllib.request
import re
import bill_validator
import scenario_reporter

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

ADB = r"C:\platform-tools\adb.exe"
GROQ_KEY_FILE = Path(r"C:\Users\Tanish\Downloads\Vya-agentic-BOT (1)\Vya-agentic-BOT\groq_key.txt")
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
- Use exact content-desc values
- When task is complete use step_done
- If stuck after 3 scrolls use step_done"""

class VyapyAgent:
    def __init__(self, serial_id, package_name, role_name, base_dir=r"C:\Users\Tanish\Downloads\Vya-agentic-BOT (1)\Vya-agentic-BOT\output"):
        self.serial = serial_id
        self.app_package = package_name
        self.role = role_name # Consumer or Business
        # Separate output directories for each agent to prevent screenshot/xml clashes
        self.out_dir = Path(base_dir) / self.role
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.screenshot_dir = self.out_dir / "screenshots"
        self.screenshot_dir.mkdir(exist_ok=True)
        self.ui_xml_path = self.out_dir / "ui.xml"

        # Tracking state for reporting
        self.last_launch_time = None
        self.last_screenshot = None
        self.current_scenario_num = "?"
        self.current_scenario_name = "Unknown"

        # Setup auto-recording script file to save tokens later
        self.record_file = self.out_dir / "recorded_script.py"
        with open(self.record_file, "a") as f:
            f.write(f"\n# --- New Recorded Session for {self.role} ---\n")

    def _check_stop(self):
        """Check if stop was requested. Import here to avoid circular import at module level."""
        import scenarios as _sc
        if _sc.stop_event.is_set():
            raise _sc.BotStopped("Ctrl+C — stopping")

    def adb(self, *args):
        """Run ADB commands specific to this agent's device."""
        self._check_stop()
        return subprocess.run(
            [ADB, "-s", self.serial] + list(args),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=30,
        )

    def dump_ui(self):
        """Dump UI hierarchy to the agent's specific directory."""
        self._check_stop()
        self.adb("shell", "uiautomator", "dump", "//sdcard/ui.xml")
        self.adb("pull", "//sdcard/ui.xml", str(self.ui_xml_path))
        try:
            return self.ui_xml_path.read_text(encoding="utf-8", errors="ignore")
        except FileNotFoundError:
            return ""

    def screenshot(self, name):
        """Take a screenshot and save it to the agent's specific directory."""
        if not name.lower().endswith(".png"):
            name += ".png"
        try:
            r = subprocess.run([ADB, "-s", self.serial, "exec-out", "screencap", "-p"],
                               capture_output=True, timeout=15)
            path = self.screenshot_dir / name
            path.write_bytes(r.stdout)
            return str(path)
        except subprocess.TimeoutExpired:
            return ""

    def record_action(self, code):
        """Append a hardcoded action to the record file."""
        with open(self.record_file, "a") as f:
            f.write(f"{code}\n")

    def tap(self, x, y, label=""):
        """Tap at specific coordinates."""
        self._check_stop()
        print(f"[{self.role}] TAP ({x},{y}) {label}")
        self.adb("shell", "input", "tap", str(x), str(y))
        self.record_action(f'agent.tap({x}, {y}, "{label}")')
        import scenarios as _sc
        _sc.stop_event.wait(timeout=1.2)  # interruptible sleep

    def _screen_size(self):
        """Return (width, height) of the device screen."""
        r = self.adb("shell", "wm", "size")
        m = re.search(r"(\d+)x(\d+)", r.stdout)
        if m:
            return int(m.group(1)), int(m.group(2))
        return 1080, 1920  # safe default

    def swipe_up(self):
        """Swipe up (Scrolls page down)."""
        self._check_stop()
        w, h = self._screen_size()
        cx = w // 2
        self.adb("shell", "input", "swipe", str(cx), str(int(h * 0.70)), str(cx), str(int(h * 0.25)), "400")
        self.record_action("agent.swipe_up()")
        import scenarios as _sc
        _sc.stop_event.wait(timeout=0.8)

    def swipe_down(self):
        """Swipe down (Scrolls page up)."""
        self._check_stop()
        w, h = self._screen_size()
        cx = w // 2
        self.adb("shell", "input", "swipe", str(cx), str(int(h * 0.25)), str(cx), str(int(h * 0.70)), "400")
        self.record_action("agent.swipe_down()")
        import scenarios as _sc
        _sc.stop_event.wait(timeout=0.8)

    def swipe_up_small(self):
        """Small swipe up inside a dialog/popup (scrolls content down a bit)."""
        self._check_stop()
        w, h = self._screen_size()
        cx = w // 2
        self.adb("shell", "input", "swipe", str(cx), str(int(h * 0.60)), str(cx), str(int(h * 0.35)), "300")
        import scenarios as _sc
        _sc.stop_event.wait(timeout=0.5)

    def type_text(self, text):
        """Type text."""
        self._check_stop()
        self.adb("shell", "input", "text", text.replace(" ", "%s"))
        self.record_action(f'agent.type_text("{text}")')
        import scenarios as _sc
        _sc.stop_event.wait(timeout=0.5)

    def launch_app(self):
        """Launch the assigned application and measure launch time. FAIL if >4s."""
        self._check_stop()
        print(f"[{self.role}] Launching: {self.app_package}")
        start = time.time()
        self.adb("shell", "am", "start", "-W", "-n", f"{self.app_package}/.MainActivity")
        self.last_launch_time = round(time.time() - start, 2)

        if self.last_launch_time > 4.0:
            msg = f"Slow launch: {self.last_launch_time:.2f}s (limit: 4s)"
            print(f"[{self.role}] [FAIL] {msg}")
            shot = self.screenshot(f"slow_launch_{int(time.time())}")
            self.last_screenshot = shot
            scenario_reporter.add_result(
                scenario_num=self.current_scenario_num,
                scenario_name=self.current_scenario_name,
                role=self.role,
                status="FAIL",
                reason=msg,
                launch_time=self.last_launch_time,
                screenshot_path=shot,
                screen_load_time=self.last_launch_time,
            )
        else:
            print(f"[{self.role}] App ready in {self.last_launch_time:.2f}s")

    def go_home(self):
         """Press back repeatedly to go home."""
         self._check_stop()
         print(f"[{self.role}] Going Home")
         import scenarios as _sc
         for _ in range(6):
             self.adb("shell", "input", "keyevent", "KEYCODE_BACK")
             _sc.stop_event.wait(timeout=1)
             if _sc.stop_event.is_set():
                 raise _sc.BotStopped("Ctrl+C — stopping")
         self.launch_app()
         return True


    def check_bill(self):
        """
        Validate bill math on the current checkout screen.
        Scrolls through the entire bill to collect all items before validating.
        Automatically adds a PASS/FAIL result to the report.
        Returns the validation result dict.
        """
        print(f"[{self.role}] Validating bill math (scrolling to collect all items)...")
        xml_dumps = []

        # First dump — check if this is even a bill screen
        xml = self.dump_ui()
        if not bill_validator.is_bill_screen(xml):
            print(f"[{self.role}] Not a bill screen — skipping validation")
            return {"is_bill_screen": False, "pass": True, "reason": "Not a bill screen"}

        xml_dumps.append(xml)

        # Scroll down to collect all items (up to 5 scrolls)
        for i in range(5):
            self.adb("shell", "input", "swipe", "360", "800", "360", "400", "300")
            time.sleep(1)
            new_xml = self.dump_ui()
            # Stop if screen didn't change (reached bottom)
            if new_xml == xml_dumps[-1]:
                break
            xml_dumps.append(new_xml)

        print(f"[{self.role}] Collected {len(xml_dumps)} screen dumps for bill validation")

        # Validate using all collected dumps
        result = bill_validator.validate_bill_from_dumps(xml_dumps)

        # Scroll back to top
        for i in range(len(xml_dumps)):
            self.adb("shell", "input", "swipe", "360", "400", "360", "800", "300")
            time.sleep(0.5)

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
        if result.get("line_items"):
            for name, price in result["line_items"]:
                print(f"[{self.role}]   {name}: €{price:.2f}")
        if result.get("vat_percent") is not None:
            print(f"[{self.role}]   VAT: {result['vat_percent']}% = €{result.get('vat_amount', 0):.2f}")
        if result.get("vat_check"):
            print(f"[{self.role}]   {result['vat_check']['reason']}")
        return result

    def _collect_dumps_by_scrolling(self, max_scrolls=5):
        """Collect UI dumps while scrolling down the screen."""
        xml_dumps = []
        xml = self.dump_ui()
        xml_dumps.append(xml)
        for i in range(max_scrolls):
            self.adb("shell", "input", "swipe", "360", "800", "360", "400", "300")
            time.sleep(1)
            new_xml = self.dump_ui()
            if new_xml == xml_dumps[-1]:
                break
            xml_dumps.append(new_xml)
        # Scroll back to top
        for i in range(len(xml_dumps)):
            self.adb("shell", "input", "swipe", "360", "400", "360", "800", "300")
            time.sleep(0.5)
        return xml_dumps

    def check_cart_total(self):
        """Simple cart check: verify sum of item prices = cart total.
        Use after cartImage, before cartCheckout. No VAT check.
        Scrolls through entire cart to collect all items.
        - Ensures first screen items are always captured
        - Strips VAT/Tax/CGST/SGST/Service Tax lines from item extraction"""
        try:
            print(f"[{self.role}] Checking cart total (scrolling through entire cart)...")

            # Step 1: Capture first screen BEFORE any scrolling
            first_xml = self.dump_ui()
            time.sleep(1)

            # Step 2: Scroll and collect remaining dumps
            xml_dumps = self._collect_dumps_by_scrolling(max_scrolls=10)

            # Step 3: Ensure first screen is always included at position 0
            if not xml_dumps or xml_dumps[0] != first_xml:
                xml_dumps.insert(0, first_xml)

            # Step 4: Strip VAT/Tax related nodes from all dumps before validation
            import re
            vat_keywords = re.compile(
                r'\b(VAT|Tax|CGST|SGST|Service\s*Tax|Excl\.?\s*Tax|ATI|Incl\.?)\b',
                re.IGNORECASE
            )
            pct_pattern = re.compile(r'\d+(\.\d+)?\s*%')

            cleaned_dumps = []
            for xml in xml_dumps:
                # Remove entire <node> elements whose text/content-desc contains VAT/tax keywords or percentage patterns
                cleaned = re.sub(
                    r'<node\b[^>]*?(?:text|content-desc)="([^"]*)"[^>]*/?>',
                    lambda m: '' if (vat_keywords.search(m.group(1)) or pct_pattern.search(m.group(1))) else m.group(0),
                    xml
                )
                cleaned_dumps.append(cleaned)

            result = bill_validator.validate_cart_total_only(cleaned_dumps)

            status = "PASS" if result["pass"] else "FAIL"
            shot = None
            if not result["pass"]:
                shot = self.screenshot(f"cart_fail_{int(time.time())}")
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
            print(f"[{self.role}] Cart check: {status} — {result['reason']}")
            return result
        except Exception as e:
            print(f"[{self.role}] Cart check error (continuing): {e}")
            return {"pass": False, "reason": f"Cart check error: {e}"}

    def check_bill_with_vat(self):
        """Full bill check: items + VAT calculation + grand total.
        Use after pickUpOrderConfirm."""
        try:
            return self._check_bill_with_vat_impl()
        except Exception as e:
            print(f"[{self.role}] Bill+VAT check error (continuing): {e}")
            return {"pass": False, "reason": f"Bill+VAT error: {e}"}

    def _check_items_sum_impl(self):
        print(f"[{self.role}] Checking items sum = Total...")
        xml_dumps = self._collect_dumps_by_scrolling(max_scrolls=5)
        result = bill_validator.validate_items_sum_only(xml_dumps)

        status = "PASS" if result["pass"] else "FAIL"
        shot = None
        if not result["pass"]:
            shot = self.screenshot(f"bill_items_fail_{int(time.time())}")
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
        try:
            print(f"[{self.role}] Items check: {status} — {result['reason']}")
            if result.get("line_items"):
                for name, price in result["line_items"]:
                    if price is not None:
                        print(f"[{self.role}]   {name}: €{price:.2f}")
            if result.get("grand_total") is not None:
                print(f"[{self.role}]   Total: €{result['grand_total']:.2f}")
        except Exception as e:
            print(f"[{self.role}] Error formatting result: {e}")
        return result

    def _check_bill_with_vat_impl(self):
        print(f"[{self.role}] Checking bill with VAT calculation...")
        xml_dumps = self._collect_dumps_by_scrolling(max_scrolls=5)
        result = bill_validator.validate_bill_with_vat(xml_dumps)

        status = "PASS" if result["pass"] else "FAIL"
        shot = None
        if not result["pass"]:
            shot = self.screenshot(f"bill_vat_fail_{int(time.time())}")
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
        try:
            print(f"[{self.role}] Bill+VAT check: {status} — {result['reason']}")
            if result.get("line_items"):
                for name, price in result["line_items"]:
                    if price is not None:
                        print(f"[{self.role}]   {name}: €{price:.2f}")
            if result.get("grand_total") is not None:
                print(f"[{self.role}]   Total: €{result['grand_total']:.2f}")
            if result.get("vat_rows"):
                for row in result["vat_rows"]:
                    pct = row.get("vat_percent")
                    excl = row.get("excl_tax")
                    amt = row.get("vat_amount")
                    ati = row.get("ati")
                    pct_str = f"{pct}%" if pct is not None else "?"
                    excl_str = f"€{excl:.2f}" if excl is not None else "?"
                    amt_str = f"€{amt:.2f}" if amt is not None else "?"
                    ati_str = f"€{ati:.2f}" if ati is not None else "?"
                    print(f"[{self.role}]   VAT {pct_str}: Excl.Tax={excl_str}, VAT={amt_str}, ATI={ati_str}")
        except Exception as e:
            print(f"[{self.role}] Error formatting bill result: {e}")
        return result

    def verify_final_bill(self):
        """Final bill verification — full VAT check + items sum + Excl.Tax + VAT formula.
        Use at the LAST step of consumer flow."""
        try:
            return self._check_bill_with_vat_impl()
        except Exception as e:
            print(f"[{self.role}] Final bill check error (continuing): {e}")
            return {"pass": False, "reason": f"Final bill error: {e}"}

    # --- Methods from hybrid_bot.py ported to use agent specific ADB ---
    def find_by_desc(self, xml, *desc_options):
        for desc in desc_options:
            # Search by content-desc (exact, then partial)
            exact1 = rf'content-desc="{re.escape(desc)}"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
            exact2 = rf'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*content-desc="{re.escape(desc)}"'
            m = re.search(exact1, xml, re.IGNORECASE) or re.search(exact2, xml, re.IGNORECASE)
            if not m:
                pattern = rf'content-desc="[^"]*{re.escape(desc)}[^"]*"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
                m = re.search(pattern, xml, re.IGNORECASE)
            if not m:
                pattern = rf'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*content-desc="[^"]*{re.escape(desc)}[^"]*"'
                m = re.search(pattern, xml, re.IGNORECASE)
            # Also search by resource-id (for elements like chip-container that use resource-id instead of content-desc)
            if not m:
                rid1 = rf'resource-id="[^"]*{re.escape(desc)}"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
                rid2 = rf'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*resource-id="[^"]*{re.escape(desc)}"'
                m = re.search(rid1, xml) or re.search(rid2, xml)
            if m:
                x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                if x1 == 0 and y1 == 0 and x2 == 0 and y2 == 0:
                    return None  # element exists but has zero bounds (invisible/off-screen)
                return (x1 + x2) // 2, (y1 + y2) // 2, desc
        return None

    def find_by_text(self, xml, *text_options):
        for txt in text_options:
            exact1 = rf'text="{re.escape(txt)}"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
            exact2 = rf'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*text="{re.escape(txt)}"'
            m = re.search(exact1, xml, re.IGNORECASE) or re.search(exact2, xml, re.IGNORECASE)
            if not m:
                pattern = rf'text="[^"]*{re.escape(txt)}[^"]*"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
                m = re.search(pattern, xml, re.IGNORECASE)
            if not m:
                pattern = rf'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*text="[^"]*{re.escape(txt)}[^"]*"'
                m = re.search(pattern, xml, re.IGNORECASE)
            if m:
                x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                return (x1 + x2) // 2, (y1 + y2) // 2, txt
        return None

    def get_screen_name(self):
        r = self.adb("shell", "dumpsys", "window")
        m = re.search(r"mCurrentFocus=Window\{[^}]+ \S+ ([^\s}]+)\}", r.stdout)
        return m.group(1) if m else "unknown"

    def parse_elements(self, xml):
        elements = []
        for m in re.finditer(r"<node[^>]+>", xml):
            node = m.group(0)
            desc = re.search(r'content-desc="([^"]+)"', node)
            text = re.search(r'text="([^"]+)"', node)
            bounds = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
            clickable = "clickable=\"true\"" in node
            if (desc or text) and bounds:
                x1, y1, x2, y2 = int(bounds.group(1)), int(bounds.group(2)), int(bounds.group(3)), int(bounds.group(4))
                elements.append(
                    {
                        "desc": desc.group(1) if desc else "",
                        "text": text.group(1) if text else "",
                        "center": [(x1 + x2) // 2, (y1 + y2) // 2],
                        "clickable": clickable,
                    }
                )
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
        # Contextualize prompt for the specific app/role
        prompt = f"""{SYSTEM_PROMPT} You are currently acting as the {self.role} using {self.app_package}.

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
        import scenarios as _sc
        print(f"[{self.role}] AI Step: {task_desc}")
        for attempt in range(max_retries):
            self._check_stop()
            xml = self.dump_ui()
            elements = self.parse_elements(xml)
            old_elements_str = self.build_elements_str(elements)
            screen = self.get_screen_name()

            action = self.call_groq(task_desc, elements, screen)
            if not action:
                _sc.stop_event.wait(timeout=2)
                if _sc.stop_event.is_set():
                    raise _sc.BotStopped("Ctrl+C — stopping")
                continue

            print(f"[{self.role}] AI decided: {action}")
            if action.get("action") == "step_done":
                print(f"[{self.role}] AI Step Complete.")
                return True

            self.execute_action(action, elements)

            # Smart Wait: If we tapped or scrolled, wait for the UI to actually change.
            if action.get("action") in ["tap", "scroll_down", "scroll_up", "type"]:
                wait_start = time.time()
                changed = False
                while time.time() - wait_start < 10:
                    self._check_stop()
                    new_xml = self.dump_ui()
                    new_elems = self.parse_elements(new_xml)
                    new_elements_str = self.build_elements_str(new_elems)

                    if new_elements_str != old_elements_str:
                        _sc.stop_event.wait(timeout=1.0)
                        changed = True
                        break

                    _sc.stop_event.wait(timeout=1.5)

                if not changed:
                    print(f"[{self.role}] AI Step Complete (tap executed, UI unchanged).")
                    return True
                else:
                    if action.get("action") in ["tap", "type"]:
                        print(f"[{self.role}] AI Step Complete (UI changed).")
                        return True
            else:
                _sc.stop_event.wait(timeout=2)

        print(f"[{self.role}] AI Step Failed after {max_retries} retries.")
        return False

import scenarios


def run_scenario(num, scenario, consumer_agent, business_agent):
    """Run one scenario with both agents in parallel and record results."""
    name = scenario["name"]
    print(f"\n{'='*60}")
    print(f"  [{num}] {name}")
    print(f"{'='*60}")

    # Set context on agents so launch_app/check_bill know which scenario we're in
    for agent in (consumer_agent, business_agent):
        agent.current_scenario_num = num
        agent.current_scenario_name = name
        agent.last_screenshot = None

    scenarios.clear_events()
    scenarios.set_current_scenario(num, name)  # Set scenario context for error reporting

    consumer_errors = []
    business_errors = []

    def run_consumer():
        try:
            scenario["consumer"](consumer_agent)
        except scenarios.BotStopped:
            consumer_errors.append("Interrupted by user")
        except Exception as e:
            consumer_errors.append(str(e))
            print(f"[Consumer] ERROR: {str(e).encode('ascii', errors='replace').decode('ascii')}")

    def run_business():
        try:
            scenario["business"](business_agent)
        except scenarios.BotStopped:
            business_errors.append("Interrupted by user")
        except Exception as e:
            business_errors.append(str(e))
            print(f"[Business] ERROR: {str(e).encode('ascii', errors='replace').decode('ascii')}")

    t1 = threading.Thread(target=run_consumer)
    t2 = threading.Thread(target=run_business)
    t1.daemon = True
    t2.daemon = True
    # Check scenario order preference: "order" key in scenario dict
    # "consumer_first" (default) = consumer runs first, then business
    # "business_first" = business runs first, then consumer
    # "parallel" = both run simultaneously (old behavior)
    order = scenario.get("order", "consumer_first")
    try:
        if order == "business_first":
            print(f"[{num}] Running business first, then consumer...")
            t2.start()
            while t2.is_alive():
                t2.join(timeout=1)
                if scenarios.stop_event.is_set():
                    t2.join(timeout=5)
                    break
            print(f"[{num}] Business finished, starting consumer...")
            t1.start()
            while t1.is_alive():
                t1.join(timeout=1)
                if scenarios.stop_event.is_set():
                    t1.join(timeout=5)
                    break
        elif order == "parallel":
            t1.start()
            t2.start()
            while t1.is_alive() or t2.is_alive():
                t1.join(timeout=1)
                t2.join(timeout=1)
        else:  # consumer_first (default)
            print(f"[{num}] Running consumer first, then business...")
            t1.start()
            while t1.is_alive():
                t1.join(timeout=1)
                if scenarios.stop_event.is_set():
                    t1.join(timeout=5)
                    break
            print(f"[{num}] Consumer finished, starting business...")
            t2.start()
            while t2.is_alive():
                t2.join(timeout=1)
                if scenarios.stop_event.is_set():
                    t2.join(timeout=5)
                    break
    except KeyboardInterrupt:
        print(f"\n[{num}] Interrupted by user")
        scenarios.request_stop()
        t1.join(timeout=5)
        t2.join(timeout=5)
        return

    # Merge errors from scenarios module (where helper functions report failures)
    scenario_module_errors = scenarios.get_errors()
    for error_dict in scenario_module_errors:
        role = error_dict.get("role")
        error_msg = error_dict.get("error")
        if role == "Consumer":
            consumer_errors.append(error_msg)
        elif role == "Business":
            business_errors.append(error_msg)

    # Record scenario-level PASS/FAIL for each role
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
    CONSUMER_SERIAL = "112243141G051943"  # Infinix X6528 (Consumer phone)
    BUSINESS_SERIAL = "80e7953a0521"   # New Business phone
    CONSUMER_APP_PACKAGE = "com.vyaconsumer"
    BUSINESS_APP_PACKAGE = "com.vya_business"  # Matches installed APK

    print("Initializing Agents...")
    consumer_agent = VyapyAgent(serial_id=CONSUMER_SERIAL, package_name=CONSUMER_APP_PACKAGE, role_name="Consumer")
    business_agent = VyapyAgent(serial_id=BUSINESS_SERIAL, package_name=BUSINESS_APP_PACKAGE, role_name="Business")

    all_keys = list(scenarios.SCENARIO_MAP.keys())

    print("\nAvailable Scenarios:")
    for i, (key, s) in enumerate(scenarios.SCENARIO_MAP.items(), 1):
        print(f"  {i:>2}. [{key}] {s['name']}")
    print("\nExamples:")
    print(f"  all          → run all {len(all_keys)} scenarios")
    print("  1-10         → run first 10 scenarios by position")
    print("  31           → run scenario #31 by position")
    print("  CW1          → run a single scenario by key")
    print("  CW1,EB1,O1   → run specific scenarios by key")

    import sys
    if len(sys.argv) > 1:
        choice = sys.argv[1]
        print(f"\nAuto-selected choice: {choice}")
    else:
        choice = input("\nEnter choice: ").strip()

    # Determine which keys to run
    keys_to_run = []

    if choice.lower() == "all":
        keys_to_run = all_keys

    elif "-" in choice and not choice.upper().startswith(tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ")):
        # Numeric range like "1-10"
        try:
            start, end = choice.split("-")
            start, end = int(start.strip()) - 1, int(end.strip()) - 1
            keys_to_run = all_keys[max(0, start): end + 1]
        except ValueError:
            print("Invalid range. Use format like '1-10'.")
            exit(1)

    elif "," in choice:
        # Comma-separated keys like "CW1,EB1,O1"
        requested = [k.strip().upper() for k in choice.split(",")]
        invalid = [k for k in requested if k not in scenarios.SCENARIO_MAP]
        if invalid:
            print(f"Unknown scenario keys: {invalid}")
            exit(1)
        keys_to_run = requested

    elif choice.isdigit():
        # Single number like "31" → run scenario at that position
        idx = int(choice) - 1
        if 0 <= idx < len(all_keys):
            keys_to_run = [all_keys[idx]]
        else:
            print(f"Invalid position: {choice}. Must be 1-{len(all_keys)}.")
            exit(1)

    elif choice.upper() in scenarios.SCENARIO_MAP:
        keys_to_run = [choice.upper()]

    else:
        print("Invalid choice. Exiting.")
        exit(1)

    print(f"\nRunning {len(keys_to_run)} scenario(s): {', '.join(keys_to_run)}\n")
    
    _stop_count = [0]  # mutable container for signal handler access

    def signal_handler(sig, frame):
        _stop_count[0] += 1
        if _stop_count[0] == 1:
            print("\n[INTERRUPTED] Ctrl+C detected. Stopping after current step...")
            scenarios.request_stop()
        else:
            # Second Ctrl+C = hard kill
            print("\n[FORCE KILL] Second Ctrl+C — terminating immediately.")
            scenario_reporter.print_summary()
            scenario_reporter.save_run_to_history()
            os._exit(1)

    signal.signal(signal.SIGINT, signal_handler)

    try:
        for key in keys_to_run:
            if scenarios.stop_event.is_set():
                print(f"\n[STOPPED] Skipping remaining scenarios.")
                break
            run_scenario(key, scenarios.SCENARIO_MAP[key], consumer_agent, business_agent)
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Stopping...")
        scenarios.request_stop()
    finally:
        scenario_reporter.print_summary()
        scenario_reporter.save_run_to_history()