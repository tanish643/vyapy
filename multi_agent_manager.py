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
        """Human-style cart total validator.

        Reads the cart top→bottom in small scrolls (mimicking a human),
        extracts items incrementally (deduped by name+price+qty), strictly
        ignores VAT/Tax/% rows, and compares the running sum against the
        displayed Total. Works for carts with 2 to 30+ items.
        """
        import re

        # ── Patterns ─────────────────────────────────────────────────────
        TAX_KEYWORDS = re.compile(
            r'\b(VAT|Tax|CGST|SGST|Service\s*Tax|Excl\.?\s*Tax|Incl\.?\s*Tax|'
            r'ATI|Subtotal|Sub\s*Total|Grand\s*Total|Delivery\s*Fee|'
            r'Service\s*Charge|Charges?|Tip|Gratuity|Discount|Coupon)\b',
            re.IGNORECASE,
        )
        PERCENT_PATTERN = re.compile(r'\d+(?:\.\d+)?\s*%')
        PRICE_PATTERN = re.compile(r'^\s*(?:€|₹|\$)?\s*([\d,]+\.\d{1,2})\s*(?:€|₹|\$)?\s*$')
        QTY_PATTERN = re.compile(r'^(.+?)\s*[x×]\s*(\d+)\s*$', re.IGNORECASE)
        TOTAL_LABEL = re.compile(r'^\s*(?:Total|Grand\s*Total|Order\s*Total)\s*[:€$₹]?\s*$', re.IGNORECASE)
        NODE_PAT_A = re.compile(
            r'<node[^>]*?(?:text|content-desc)="([^"]+)"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
            re.IGNORECASE,
        )
        NODE_PAT_B = re.compile(
            r'<node[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*?(?:text|content-desc)="([^"]+)"',
            re.IGNORECASE,
        )
        Y_TOLERANCE = 60  # pixels: nodes within this Y are "same row"

        # ── Helper: capture first screen (no scroll) ─────────────────────
        def capture_first_screen():
            return self.dump_ui()

        # ── Helper: small controlled scroll (~150 px) ────────────────────
        def small_scroll():
            self.adb("shell", "input", "swipe", "360", "1000", "360", "700", "400")
            time.sleep(1.2)

        # ── Helper: parse all text+bounds nodes from XML ─────────────────
        def parse_nodes(xml):
            nodes = []
            seen = set()
            for m in NODE_PAT_A.finditer(xml):
                text = m.group(1).strip()
                x1, y1, x2, y2 = int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
                if (x1 == 0 and y1 == 0 and x2 == 0 and y2 == 0) or not text:
                    continue
                key = (text, (y1+y2)//2)
                if key in seen:
                    continue
                seen.add(key)
                nodes.append({"text": text, "y": (y1+y2)//2, "x": (x1+x2)//2})
            for m in NODE_PAT_B.finditer(xml):
                x1, y1, x2, y2, text = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), m.group(5).strip()
                if (x1 == 0 and y1 == 0 and x2 == 0 and y2 == 0) or not text:
                    continue
                key = (text, (y1+y2)//2)
                if key in seen:
                    continue
                seen.add(key)
                nodes.append({"text": text, "y": (y1+y2)//2, "x": (x1+x2)//2})
            return nodes

        # ── Helper: strict tax/total filter ──────────────────────────────
        def filter_tax_elements(text):
            """Return True if this text is tax/total/charge — must be skipped."""
            if not text:
                return True
            if TAX_KEYWORDS.search(text):
                return True
            if PERCENT_PATTERN.search(text):
                return True
            return False

        # ── Helper: extract cart items from one XML dump ─────────────────
        def extract_items(xml):
            """Pair each name node with its closest price node in the same row.
            Respects quantity (`x N` / `× N`). Ignores tax/total nodes."""
            nodes = parse_nodes(xml)
            prices, names = [], []
            for n in nodes:
                txt = n["text"]
                if filter_tax_elements(txt):
                    continue
                pm = PRICE_PATTERN.match(txt)
                if pm:
                    try:
                        val = float(pm.group(1).replace(",", ""))
                        if val > 0:
                            prices.append({"y": n["y"], "x": n["x"], "val": val})
                    except ValueError:
                        pass
                else:
                    # Skip pure-numeric text and very short labels
                    stripped = txt.replace(" ", "").replace(".", "").replace(",", "")
                    if len(txt.strip()) >= 2 and not stripped.isdigit():
                        names.append({"y": n["y"], "x": n["x"], "text": txt})

            items, used = [], set()
            for name in names:
                best, best_dist, best_idx = None, float("inf"), None
                for i, p in enumerate(prices):
                    if i in used:
                        continue
                    dist = abs(p["y"] - name["y"])
                    if dist < Y_TOLERANCE and dist < best_dist:
                        best, best_dist, best_idx = p, dist, i
                if best is not None:
                    qty = 1
                    clean_name = name["text"]
                    qm = QTY_PATTERN.match(clean_name)
                    if qm:
                        clean_name = qm.group(1).strip()
                        try:
                            qty = int(qm.group(2))
                        except ValueError:
                            qty = 1
                    items.append({
                        "name": clean_name,
                        "unit_price": best["val"],
                        "qty": qty,
                        "line_total": round(best["val"] * qty, 2),
                    })
                    used.add(best_idx)
            return items

        # ── Helper: find displayed total at end of scrolling ─────────────
        def find_displayed_total(xml):
            nodes = parse_nodes(xml)
            # 1) Look for an explicit "Total" label and a price in the same row
            for n in nodes:
                if TOTAL_LABEL.match(n["text"]):
                    for p in nodes:
                        pm = PRICE_PATTERN.match(p["text"])
                        if pm and abs(p["y"] - n["y"]) < Y_TOLERANCE:
                            try:
                                return float(pm.group(1).replace(",", ""))
                            except ValueError:
                                continue
            # 2) Fallback: bottom-most non-tax price
            candidates = []
            for n in nodes:
                if filter_tax_elements(n["text"]):
                    continue
                m = PRICE_PATTERN.match(n["text"])
                if m:
                    try:
                        candidates.append((float(m.group(1).replace(",", "")), n["y"]))
                    except ValueError:
                        pass
            if not candidates:
                return None
            candidates.sort(key=lambda c: (c[1], c[0]), reverse=True)
            return candidates[0][0]

        # ── Helper: validate total ───────────────────────────────────────
        def validate_total(seen_items, displayed_total):
            calculated = round(sum(v["line_total"] for v in seen_items.values()), 2)
            items_str = " + ".join(f"€{v['line_total']:.2f}" for v in seen_items.values())
            if displayed_total is None:
                return {
                    "pass": False,
                    "displayed_total": None,
                    "calculated_total": calculated,
                    "line_items": [(v["name"], v["line_total"]) for v in seen_items.values()],
                    "diff": 0.0,
                    "reason": f"Cart: could not detect displayed total (calculated=€{calculated:.2f}, items={len(seen_items)})",
                }
            diff = round(abs(displayed_total - calculated), 2)
            if diff <= 0.01:
                return {
                    "pass": True,
                    "displayed_total": displayed_total,
                    "calculated_total": calculated,
                    "line_items": [(v["name"], v["line_total"]) for v in seen_items.values()],
                    "diff": diff,
                    "reason": f"Cart total OK: €{displayed_total:.2f} (Items: {items_str} = €{calculated:.2f})",
                }
            return {
                "pass": False,
                "displayed_total": displayed_total,
                "calculated_total": calculated,
                "line_items": [(v["name"], v["line_total"]) for v in seen_items.values()],
                "diff": diff,
                "reason": f"Cart total mismatch: displayed=€{displayed_total:.2f}, calculated=€{calculated:.2f}, diff=€{diff:.2f}; Items: {items_str}",
            }

        # ── MAIN FLOW ────────────────────────────────────────────────────
        try:
            print(f"[{self.role}] Checking cart total (human-style scroll)...")
            seen_items = {}  # key: (name, unit_price, qty) → item dict

            # Step 1: First screen — extract IMMEDIATELY (fixes "first item missed")
            first_xml = capture_first_screen()
            last_xml = first_xml
            for item in extract_items(first_xml):
                key = (item["name"], item["unit_price"], item["qty"])
                if key not in seen_items:
                    seen_items[key] = item
            print(f"[{self.role}] First screen captured {len(seen_items)} item(s)")

            # Step 2: Iterative small scrolls + incremental dedup
            MAX_SCROLLS = 30  # supports large carts (30+ items)
            STABLE_LIMIT = 2  # stop after 2 scrolls with no new items
            stable_count = 0
            scrolls_done = 0

            for i in range(MAX_SCROLLS):
                small_scroll()
                scrolls_done += 1
                xml = self.dump_ui()
                if xml == last_xml:
                    break  # screen didn't change — reached bottom
                new_count = 0
                for item in extract_items(xml):
                    key = (item["name"], item["unit_price"], item["qty"])
                    if key not in seen_items:
                        seen_items[key] = item
                        new_count += 1
                if new_count == 0:
                    stable_count += 1
                    if stable_count >= STABLE_LIMIT:
                        break
                else:
                    stable_count = 0
                last_xml = xml

            # Step 3: Find displayed total from last (bottom-most) screen
            displayed_total = find_displayed_total(last_xml)

            # Step 4: Scroll back to top so subsequent steps start fresh
            for _ in range(min(scrolls_done + 1, 12)):
                self.adb("shell", "input", "swipe", "360", "700", "360", "1000", "300")
                time.sleep(0.3)

            # Step 5: Validate
            result = validate_total(seen_items, displayed_total)

            # Step 6: Failure handling
            status = "PASS" if result["pass"] else "FAIL"
            shot = None
            if not result["pass"]:
                shot = self.screenshot(f"cart_fail_{int(time.time())}")
                self.last_screenshot = shot
                print(f"[{self.role}] === Cart items captured ({len(seen_items)}) ===")
                for v in seen_items.values():
                    print(f"[{self.role}]   {v['name']} (×{v['qty']}) @ €{v['unit_price']:.2f} = €{v['line_total']:.2f}")
                print(f"[{self.role}] Calculated: €{result['calculated_total']:.2f}")
                disp = result.get("displayed_total")
                print(f"[{self.role}] Displayed:  €{disp:.2f}" if disp is not None else f"[{self.role}] Displayed:  not detected")
                print(f"[{self.role}] Diff:       €{result.get('diff', 0):.2f}")

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


# ═══════════════════════════════════════════════════════════════════════════
# ───── MULTI-AGENT FLOW REFERENCE for PAY9-PAY15 + REV1-REV3 ─────
# ═══════════════════════════════════════════════════════════════════════════
#
# These scenarios run on TWO devices coordinated by run_scenario() below:
#   • Consumer device → runs consumer phase functions
#   • Business iPad   → runs business phase functions
#
# PAY9-PAY15 use order="phased" — they alternate strictly between agents:
#
#   PHASE 1 (consumer) — Person A logs in → NylaiKitchen → counterPlus +
#       guestAdd → contactSearch → invite Person B → bookAppoitment →
#       orderLater → switch_account to Person B → walletTab → wait for
#       InviteCard → eventAccept → orderLater
#       END: ReservedOrderCard now exists in business Orders list
#                                  ↓
#   PHASE 2 (business) — Orders → ReservedOrderCard → T0AssignAnyBtn →
#       AssignTableBtn → addItemsBtn → category → tap items+variants →
#       applyOpt → assignToBtn → selectAll → assignProductsBtn →
#       selectAllItemsBtn → sendItemsBtn → backButton → switch to KITCHEN
#       (kempA) → inProgressOrderCard → tap each kitchen item → orderReadyBtn
#       → orderCloseBtn → switch to SERVE (empA) → Orders → ServeOrderCard →
#       selectAllItemsBtn → serveItemsBtn → notifyPaymentBtn
#       END: consumer wallet shows "NylaiKitchenCard PAYMENT REQUESTED"
#                                  ↓
#   PHASE 3 (consumer) — walletTab → _wait_for_card("NylaiKitchenCard
#       PAYMENT REQUESTED") → swipe → RoopaDfinishedCard → tap a payment
#       option:
#           • "Guest 1pay"   = pay for Guest1's portion (PAY9)
#           • "NooluNagapay" = pay for NooluNaga's portion (PAY10)
#           • "Mepay"        = pay for own portion (PAY11)
#           • "payTotal"     = pay entire bill (PAY12, PAY13, PAY14, PAY15)
#       → proceedPayment → type amount in "0,00 €" field → optional
#       eApplyCoupons → coupon → ePayment / eCash / eFoodVoucher →
#       ePaymentConfirm + waiterNotify (or "Pay € XX.XX" for ePayment)
#       END: business order transitions to PaymentOrderCard (partial pay)
#            or PaymentDoneOrderCard (full pay)
#                                  ↓
#   PHASE 4 (business) — Orders → _wait_for_card("PaymentOrderCard" or
#       "PaymentDoneOrderCard") → if partial: Payment Payment → tap remaining
#       person's Card → cashPaymentBtn → numbers → userInputBtn → optional
#       tipBtn → swipe up → paymentConfirmBtn → Assign/Split → addItemsBtn →
#       eventInvoice or individualInvoice → printNow → swipe → backButton →
#       Overview → closeTableBtn
#       END: event closed, consumer wallet shows
#            "NylaiKitchenCard PAYMENT COMPLETED"
#                                  ↓
#   PHASE 5 (REV1/REV2/REV3 only, consumer-only) — walletTab →
#       _wait_for_card("NylaiKitchenCard PAYMENT COMPLETED") → swipe → starN
#       → category stars (Service/Food/Ambiance) → item stars → comment
#       textbox → submitReview → finishedBlock → homeTab. REV3 runs this
#       twice with switch_account in between for both host and participant.
#
# SPECIAL CASE — PAY14 (Remind Payment + Re-Checkout):
#   Phase 3 is interrupted. Consumer starts payTotal+proceedPayment but
#   stops at the "ePayTip" prompt. Business sees this, sends remindPayment.
#   Consumer re-opens NylaiKitchenCard → payTotal → proceedPayment → types
#   €5.123 → eFoodVoucher → ePaymentConfirm → waiterNotify. Business then
#   does Phase 4 with NooluNagaCard + foodVoucher + epay.
#
# SPECIAL CASE — PAY15 (Whom-to-Pay Check):
#   Phase 3 has multiple account switches: Noolu starts payTotal →
#   walletBackBtn, Roopa checks her screen, Noolu does YES, RE-CHECKOUT →
#   Mepay, finally Roopa does payTotal → ePayment to settle. Phase 4 just
#   closes the table since payment is fully done.
#
# ACCOUNTS:
#   • roopa@xorstack.com / 12345     → "Roopa" (consumer)
#   • noolu@xorstack.com / 12345     → "Noolu" / "NooluNaga" (consumer)
#   • kempA@xorstack.com / Nylaii@09 → kitchen staff (business)
#   • empA@xorstack.com  / Nylaii@06 → serve staff (business)
#
# CARD STATE TRANSITIONS (business Orders screen):
#   ReservedOrderCard → (after assign+sendItems) → inProgressOrderCard
#     → (after kitchen ready+close) → ServeOrderCard
#     → (after notifyPaymentBtn) → PaymentOrderCard
#     → (after partial C-App pay) → still PaymentOrderCard (need B-App cash)
#     → (after full C-App pay) → PaymentDoneOrderCard (just close)
#
# Why _wait_for_card not time.sleep:
#   Consumer's C-App payment can take 5s on fast network, 60s on slow.
#   Hardcoded sleeps either waste time or fail. _wait_for_card polls every
#   ~3s and proceeds the instant the card appears (max_attempts=24 → 72s).
# ═══════════════════════════════════════════════════════════════════════════


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
    # "phased"   = run scenario["phases"] in strict order, alternating agents.
    #              Each phase is a (agent_role, function) tuple. Each function
    #              completes fully before the next phase starts.
    order = scenario.get("order", "consumer_first")
    try:
        if order == "phased":
            phases = scenario.get("phases", [])
            print(f"[{num}] Running {len(phases)} phases in strict order...")
            for i, (agent_role, phase_fn) in enumerate(phases, start=1):
                if scenarios.stop_event.is_set():
                    print(f"[{num}] Stop requested before phase {i} — aborting")
                    break
                target_agent = consumer_agent if agent_role == "consumer" else business_agent
                err_list = consumer_errors if agent_role == "consumer" else business_errors
                print(f"[{num}] Phase {i}/{len(phases)} → {agent_role}: {phase_fn.__name__}")
                try:
                    phase_fn(target_agent)
                except scenarios.BotStopped:
                    err_list.append("Interrupted by user")
                    break
                except Exception as e:
                    err_list.append(str(e))
                    print(f"[{agent_role.title()}] ERROR in phase {i}: "
                          f"{str(e).encode('ascii', errors='replace').decode('ascii')}")
                    break
        elif order == "business_first":
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

    main_keys = list(scenarios.SCENARIO_MAP.keys())
    consumer_only_keys = list(scenarios.PRE_ORDER_CONSUMER_MAP.keys())
    all_keys = main_keys + consumer_only_keys

    # Combined map for lookups
    COMBINED_MAP = {**scenarios.SCENARIO_MAP, **scenarios.PRE_ORDER_CONSUMER_MAP}

    print("\nAvailable Scenarios:")
    for i, (key, s) in enumerate(scenarios.SCENARIO_MAP.items(), 1):
        print(f"  {i:>2}. [{key}] {s['name']}")
    print("\n── Pre-order (Consumer-only) ──")
    for i, (key, s) in enumerate(scenarios.PRE_ORDER_CONSUMER_MAP.items(), len(main_keys) + 1):
        print(f"  {i:>2}. [{key}] {s['name']}")
    print("\nExamples:")
    print(f"  all          → run all {len(all_keys)} scenarios")
    print("  1-10         → run first 10 scenarios by position")
    print("  31           → run scenario #31 by position")
    print("  CW1          → run a single scenario by key")
    print("  CW1,EB1,O1   → run specific scenarios by key")
    print("  POC1         → run a Pre-order consumer-only scenario")

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
        invalid = [k for k in requested if k not in COMBINED_MAP]
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

    elif choice.upper() in COMBINED_MAP:
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
            try:
                import vya_test_report
                vya_test_report.build_report()
            except Exception as _e:
                print(f"[Vya Test Report] Skipped on force-kill: {_e}")
            try:
                import vya_payment_report
                vya_payment_report.build_report()
            except Exception as _e:
                print(f"[Vya Payment Report] Skipped on force-kill: {_e}")
            try:
                import vya_payments_report
                vya_payments_report.build_report()
            except Exception as _e:
                print(f"[Vya Payments Report] Skipped on force-kill: {_e}")
            try:
                import vya_combined_payments_report
                vya_combined_payments_report.build_report()
            except Exception as _e:
                print(f"[Vya Combined Payments Report] Skipped on force-kill: {_e}")
            try:
                import vya_capp_payments_report
                vya_capp_payments_report.build_report()
            except Exception as _e:
                print(f"[Vya C-App Payments Report] Skipped on force-kill: {_e}")
            try:
                import vya_pdf_report
                vya_pdf_report.build_report()
            except Exception as _e:
                print(f"[Vya PDF Report] Skipped on force-kill: {_e}")
            os._exit(1)

    signal.signal(signal.SIGINT, signal_handler)

    try:
        for key in keys_to_run:
            if scenarios.stop_event.is_set():
                print(f"\n[STOPPED] Skipping remaining scenarios.")
                break
            run_scenario(key, COMBINED_MAP[key], consumer_agent, business_agent)
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Stopping...")
        scenarios.request_stop()
    finally:
        scenario_reporter.print_summary()
        scenario_reporter.save_run_to_history()
        try:
            import vya_test_report
            vya_test_report.build_report()
        except Exception as _e:
            print(f"[Vya Test Report] Could not auto-generate report: {_e}")
        try:
            import vya_payment_report
            vya_payment_report.build_report()
        except Exception as _e:
            print(f"[Vya Payment Report] Could not auto-generate report: {_e}")
        try:
            import vya_payments_report
            vya_payments_report.build_report()
        except Exception as _e:
            print(f"[Vya Payments Report] Could not auto-generate report: {_e}")
        try:
            import vya_combined_payments_report
            vya_combined_payments_report.build_report()
        except Exception as _e:
            print(f"[Vya Combined Payments Report] Could not auto-generate report: {_e}")
        try:
            import vya_capp_payments_report
            vya_capp_payments_report.build_report()
        except Exception as _e:
            print(f"[Vya C-App Payments Report] Could not auto-generate report: {_e}")
        try:
            import vya_pdf_report
            vya_pdf_report.build_report()
        except Exception as _e:
            print(f"[Vya PDF Report] Could not auto-generate report: {_e}")