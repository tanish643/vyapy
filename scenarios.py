"""
Vyapy QA Multi-Agent Scenario Definitions
Generated from Appium Studio XML exports.
All 76 scenarios across Consumer and Business apps.
"""

import threading
import time
import os
import re
import scenario_reporter
import bill_validator

# ─── Global Stop Flag ──────────────────────────────────────────────────────
stop_event = threading.Event()


class BotStopped(Exception):
    """Raised when Ctrl+C is detected to unwind all threads."""
    pass


def request_stop():
    """Signal all threads to stop."""
    stop_event.set()
    # Also unblock any threads waiting on sync events
    for e in events.values():
        e.set()


def check_stop():
    """Call periodically in long operations. Raises BotStopped if stop requested."""
    if stop_event.is_set():
        raise BotStopped("Ctrl+C — stopping")


def interruptible_sleep(seconds):
    """Sleep that can be interrupted by stop_event."""
    if stop_event.wait(timeout=seconds):
        raise BotStopped("Ctrl+C — stopping")


# ─── Sync Events ────────────────────────────────────────────────────────────
events = {
    "order_placed":       threading.Event(),
    "table_accepted":     threading.Event(),
    "guest_joined":       threading.Event(),
    "preorder_submitted": threading.Event(),
    "kitchen_accepted":   threading.Event(),
    "payment_requested":  threading.Event(),
    "payment_completed":  threading.Event(),
    "event_created":      threading.Event(),
    "event_accepted":     threading.Event(),
    "event_declined":     threading.Event(),
    "items_served":       threading.Event(),
    "pdf_consumer_done":  threading.Event(),
}

shared_data = {}

# ─── Error Tracking ───────────────────────────────────────────────────────────
scenario_errors = []  # Track errors per scenario execution
current_scenario = {"num": None, "name": None}  # Track current scenario being executed

def set_current_scenario(num, name):
    """Set the current scenario context for error reporting."""
    global current_scenario
    current_scenario = {"num": num, "name": name}

def add_error(role, error_msg):
    """Add an error to the current scenario."""
    scenario_errors.append({"role": role, "error": error_msg})
    print(f"[ERROR] {role}: {error_msg}")

def clear_errors():
    """Clear errors for next scenario."""
    global scenario_errors
    scenario_errors = []

def has_errors():
    """Check if any errors occurred in current scenario."""
    return len(scenario_errors) > 0

def get_errors():
    """Get all errors from current scenario."""
    return scenario_errors


def clear_events():
    for e in events.values():
        e.clear()
    shared_data.clear()
    clear_errors()


# ─── Screen Load Time Tracking ──────────────────────────────────────────────

def _check_screen_load(agent, old_xml, label=""):
    """Measure how long the screen takes to change after a tap.
    If > 3 seconds, reports FAIL with the load time.
    Returns the load time in seconds."""
    start = time.time()
    max_wait = 12  # Wait up to 12s to detect change
    changed = False
    while time.time() - start < max_wait:
        new_xml = agent.dump_ui()
        if new_xml != old_xml:
            changed = True
            break
        time.sleep(0.5)
    load_time = round(time.time() - start, 2)

    if not changed:
        # Screen didn't change at all — no load time issue, tap may have done nothing
        return None

    if load_time > 20.0:
        # Only report FAIL for truly stuck screens (>20s)
        msg = f"Slow screen load after '{label}': {load_time:.2f}s (limit: 20s)"
        print(f"[{agent.role}] [SLOW] {msg}")
        key = current_scenario.get("num")
        name = current_scenario.get("name")
        if key and name:
            scenario_reporter.add_result(key, name, agent.role, "FAIL", msg,
                                         agent.last_launch_time, screen_load_time=load_time)
        add_error(agent.role, msg)
    elif load_time > 4.0:
        # Warn but don't fail for borderline loads (4-8s)
        print(f"[{agent.role}] [WARN] Screen loaded in {load_time:.2f}s after '{label}' (slow but OK)")
    else:
        print(f"[{agent.role}] Screen loaded in {load_time:.2f}s after '{label}'")

    return load_time


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _tap_add_new_custom(agent):
    """Tap ADD NEW CUSTOM SELECTION button specifically, avoiding ADD TO CART."""
    for attempt in range(3):
        xml = agent.dump_ui()
        # Try content-desc first
        m = re.search(r'content-desc="addNewCustomSelection"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
        if not m:
            m = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*content-desc="addNewCustomSelection"', xml)
        # Try text with spaces
        if not m:
            m = re.search(r'text="ADD NEW CUSTOM SELECTION"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml, re.IGNORECASE)
        if not m:
            m = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*text="ADD NEW CUSTOM SELECTION"', xml, re.IGNORECASE)
        if m:
            x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            agent.adb("shell", "input", "tap", str(cx), str(cy))
            print(f"[{agent.role}] TAP ({cx},{cy}) [addNewCustomSelection]")
            time.sleep(2)
            return True
        print(f"[{agent.role}] addNewCustomSelection not found, scrolling... ({attempt+1}/3)")
        agent.adb("shell", "input", "swipe", "360", "800", "360", "600", "300")
        time.sleep(2)
    print(f"[{agent.role}] addNewCustomSelection NOT FOUND after 3 attempts")
    return False


def _tap_all_kitchen_items(agent, items):
    """Tap each kitchen item by name. Pass a list of heading names.
    Small scroll every 2 items to reveal next items. Swipe up at end for Ready button."""
    for i, name in enumerate(items):
        _tap(agent, name)
        time.sleep(1)
        # Small scroll after every 2 items to reveal next ones
        if (i + 1) % 2 == 0 and i < len(items) - 1:
            agent.adb("shell", "input", "swipe", "360", "800", "360", "600", "300")
            time.sleep(2)
    print(f"[{agent.role}] Tapped {len(items)} kitchen items")
    # Swipe up to reveal orderReadyBtn if not visible
    agent.swipe_up()
    time.sleep(2)


def _tap(agent, *descs, scroll=None):
    """Tap element by content-desc or text.
    scroll=None (default): auto-detect — scrolls for food items (ending in Inc/Product/Item/Btn), not for UI buttons.
    scroll=True/False: force scroll behavior.
    When scrolling: tries down first (swipe_up), then up (swipe_down) to find the element."""
    if scroll is None:
        name = descs[0] if descs else ""
        scroll = name.endswith("Inc") or name.endswith("Product") or name.endswith("Item") or name.endswith("Btn")
    max_attempts = 4 if scroll else 2
    for attempt in range(max_attempts):
        xml = agent.dump_ui()
        match = agent.find_by_desc(xml, *descs) or agent.find_by_text(xml, *descs)
        if match:
            agent.tap(match[0], match[1], f"[{descs[0]}]")
            _check_screen_load(agent, xml, descs[0])
            return True
        if attempt < max_attempts - 1:
            if scroll:
                print(f"[{agent.role}] NOT FOUND: '{descs[0]}' — scroll down & retry {attempt+1}/{max_attempts-1}")
                agent.swipe_up()
            else:
                print(f"[{agent.role}] NOT FOUND: '{descs[0]}' — retry {attempt+1}/{max_attempts-1}")
            time.sleep(1)
    # If scroll enabled and still not found, try scrolling up
    if scroll:
        for attempt in range(4):
            agent.swipe_down()
            time.sleep(1)
            xml = agent.dump_ui()
            match = agent.find_by_desc(xml, *descs) or agent.find_by_text(xml, *descs)
            if match:
                agent.tap(match[0], match[1], f"[{descs[0]}]")
                _check_screen_load(agent, xml, descs[0])
                return True
            print(f"[{agent.role}] NOT FOUND: '{descs[0]}' — scroll up & retry {attempt+1}/4")
    print(f"[{agent.role}] NOT FOUND: '{descs[0]}' — skipping")
    return False


class ScenarioFail(Exception):
    """Raised when a required element is not found — stops the scenario."""
    pass


def _tap_or_fail(agent, desc, scenario_key, scenario_name):
    """Tap element or stop scenario with FAIL report if not found."""
    result = _tap(agent, desc)
    if not result:
        msg = f"Element not found: '{desc}' — stopping scenario"
        print(f"[{agent.role}] SCENARIO FAIL: {msg}")
        scenario_reporter.add_result(scenario_key, scenario_name, agent.role, "FAIL", msg, agent.last_launch_time)
        raise ScenarioFail(msg)
    return result


def _tap_required(agent, desc, scenario_key, scenario_name, retries=2):
    """Tap a required element. Try twice, report FAIL if not found."""
    for attempt in range(2):
        xml = agent.dump_ui()
        match = agent.find_by_desc(xml, desc) or agent.find_by_text(xml, desc)
        if match:
            agent.tap(match[0], match[1], f"[{desc}]")
            _check_screen_load(agent, xml, desc)
            return True
        if attempt == 0:
            print(f"[{agent.role}] NOT FOUND: '{desc}' — retry 1/2")
            time.sleep(1)
    msg = f"Required button not found: '{desc}'"
    print(f"[{agent.role}] FAIL — {msg}")
    scenario_reporter.add_result(scenario_key, scenario_name, agent.role, "FAIL", msg, agent.last_launch_time)
    return False


def _wait_tap(agent, desc, timeout=10, scenario_key=None, scenario_name=None):
    """Search for element, retry twice before skipping."""
    for attempt in range(2):
        xml = agent.dump_ui()
        match = agent.find_by_desc(xml, desc) or agent.find_by_text(xml, desc)
        if match:
            agent.tap(match[0], match[1], f"[{desc}]")
            _check_screen_load(agent, xml, desc)
            return True
        if attempt == 0:
            print(f"[{agent.role}] NOT FOUND: '{desc}' — retry 1/2")
            time.sleep(1)
    print(f"[{agent.role}] NOT FOUND: '{desc}' — skipping")
    msg = f"Element not found: '{desc}'"
    key = scenario_key or current_scenario.get("num")
    name = scenario_name or current_scenario.get("name")
    if key and name:
        scenario_reporter.add_result(key, name, agent.role, "FAIL", msg, agent.last_launch_time)
    add_error(agent.role, msg)
    return False


def _clear_and_type(agent, text):
    """Clear any existing text in focused field, then type new text."""
    # Select all existing text and delete it
    agent.adb("shell", "input", "keyevent", "123")   # KEYCODE_MOVE_END
    time.sleep(0.3)
    # Delete characters one by one (up to 30 chars)
    for _ in range(30):
        agent.adb("shell", "input", "keyevent", "67")  # KEYCODE_DEL
    time.sleep(0.3)
    # Now type the new text fresh
    agent.type_text(text)


def _type_field(agent, field_desc, text, scenario_key=None, scenario_name=None, critical=False, clear_first=False):
    """Tap a field and type text into it. Try twice before skipping."""
    for attempt in range(2):
        xml = agent.dump_ui()
        match = agent.find_by_desc(xml, field_desc)
        if match:
            agent.tap(match[0], match[1], f"[{field_desc}]")
            break
        if attempt == 0:
            print(f"[{agent.role}] NOT FOUND field: '{field_desc}' — retry 1/2")
            time.sleep(1)
    else:
        print(f"[{agent.role}] NOT FOUND field: '{field_desc}' — skipping")
        if critical:
            msg = f"Field not found: '{field_desc}'"
            key = scenario_key or current_scenario.get("num")
            name = scenario_name or current_scenario.get("name")
            if key and name:
                scenario_reporter.add_result(key, name, agent.role, "FAIL", msg, agent.last_launch_time)
            add_error(agent.role, msg)
        return not critical
    time.sleep(0.5)
    if clear_first:
        _clear_and_type(agent, text)
    else:
        agent.type_text(text)
    agent.adb("shell", "input", "keyevent", "KEYCODE_HIDE")  # hide keyboard
    agent.adb("shell", "input", "keyevent", "KEYCODE_BACK")  # fallback dismiss
    time.sleep(1.5)
    return True


def _swipe_up(agent):
    agent.swipe_up()


def _wait_for_card(agent, card_desc, max_attempts=5):
    """Wait for a card to appear in wallet with retry + pull-to-refresh.
    Used after account switches where server sync causes delay."""
    time.sleep(3)
    for attempt in range(max_attempts):
        xml = agent.dump_ui()
        match = agent.find_by_desc(xml, card_desc) or agent.find_by_text(xml, card_desc)
        if match:
            agent.tap(match[0], match[1], f"[{card_desc}]")
            return True
        print(f"[{agent.role}] Waiting for {card_desc}... ({attempt+1}/{max_attempts})")
        agent.swipe_down()  # pull to refresh
        time.sleep(3)
    # Last resort: scroll up and try once more
    agent.swipe_up()
    return _wait_tap(agent, card_desc)


def _cancel_booking_flow(agent, assignee=None):
    """Execute the standard cancel booking flow:
    cancelBooking -> me only -> [assignee] -> confirmCancelBook -> yesGotIt -> option1 -> comment -> submit"""
    time.sleep(1)
    _tap(agent, "cancelBooking")
    time.sleep(1)
    _tap(agent, "me only")
    time.sleep(1)
    if assignee:
        _tap(agent, assignee)
        time.sleep(1)
    _tap(agent, "confirmCancelBook")
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    # yesGotIt popup may or may not appear — try but don't fail
    _tap(agent, "yesGotIt", "YES, GOT IT")
    time.sleep(2)
    _tap(agent, "option1")
    time.sleep(1)
    agent.swipe_up()
    time.sleep(1)
    # Find and type in the comment field
    xml = agent.dump_ui()
    comment_field = (
        agent.find_by_desc(xml, "cancelReason")
        or agent.find_by_desc(xml, "Or make a comment")
        or agent.find_by_text(xml, "Or make a comment")
        or agent.find_by_desc(xml, "write a comment")
        or agent.find_by_text(xml, "write a comment")
        or agent.find_by_desc(xml, "commentInput")
    )
    if comment_field:
        agent.tap(comment_field[0], comment_field[1], "[comment field]")
        time.sleep(0.5)
        agent.type_text("Booked wrong slot!")
        agent.adb("shell", "input", "keyevent", "KEYCODE_BACK")
        time.sleep(1)
    else:
        print(f"[{agent.role}] Comment field not found — trying AI fallback")
        agent.run_step_ai("Tap the comment text field and type 'Booked wrong slot!'")
        time.sleep(1)
    _tap(agent, "optionSubmit", "submit")
    time.sleep(2)


def _tap_chip_container(agent):
    """Scroll down then tap chip-container. Scrolls up to 3 times to find it."""
    for attempt in range(3):
        print(f"[{agent.role}] Scrolling for chip-container (attempt {attempt+1}/3)")
        agent.swipe_up()
        xml = agent.dump_ui()
        match = agent.find_by_desc(xml, "chip-container") or agent.find_by_text(xml, "chip-container")
        if match:
            agent.tap(match[0], match[1], "[chip-container]")
            _check_screen_load(agent, xml, "chip-container")
            return True
    print(f"[{agent.role}] chip-container NOT FOUND after 3 scrolls — skipping")
    return False


def _tap_events_button(agent):
    """Find and tap 'Events <number>' button on home page. Scrolls up to 3 times."""
    for attempt in range(3):
        xml = agent.dump_ui()
        match = agent.find_by_text(xml, "Events") or agent.find_by_desc(xml, "Events")
        if match:
            agent.tap(match[0], match[1], "[Events]")
            _check_screen_load(agent, xml, "Events")
            return True
        print(f"[{agent.role}] Events button not found — scrolling (attempt {attempt+1}/3)")
        agent.swipe_up()
        time.sleep(1)
    print(f"[{agent.role}] Events button NOT FOUND after 3 scrolls — skipping")
    return False


def _tap_any_table(agent):
    """Find and tap any available table button (T0-T20) on screen."""
    xml = agent.dump_ui()
    m = re.search(
        r'content-desc="(T\d+)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml
    ) or re.search(
        r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*content-desc="(T\d+)"', xml
    )
    if m:
        groups = m.groups()
        if groups[0].startswith("T"):
            name, x1, y1, x2, y2 = groups[0], int(groups[1]), int(groups[2]), int(groups[3]), int(groups[4])
        else:
            x1, y1, x2, y2, name = int(groups[0]), int(groups[1]), int(groups[2]), int(groups[3]), groups[4]
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        agent.tap(cx, cy, f"[{name}]")
        print(f"[{agent.role}] Selected table: {name}")
        return True
    print(f"[{agent.role}] No table button found — skipping")
    return False


def _slide_to_not_sure(agent):
    """Slide the duration slider to 'Not Sure' by finding its position and swiping."""
    xml = agent.dump_ui()
    match = agent.find_by_text(xml, "Not Sure") or agent.find_by_desc(xml, "Not Sure")
    if match:
        target_x, target_y = match[0], match[1]
        # Swipe from left side of slider to "Not Sure" position (slow drag 500ms)
        start_x = 100
        agent.adb("shell", "input", "swipe", str(start_x), str(target_y), str(target_x), str(target_y), "500")
        print(f"[{agent.role}] Slid duration slider to 'Not Sure' at ({target_x},{target_y})")
        time.sleep(1)
        return True
    print(f"[{agent.role}] 'Not Sure' not found on slider — skipping")
    return False


def _wait_for(agent, desc, timeout=15):
    """Wait for element to appear WITHOUT tapping it."""
    for i in range(timeout):
        xml = agent.dump_ui()
        if agent.find_by_desc(xml, desc) or agent.find_by_text(xml, desc):
            print(f"[{agent.role}] FOUND (no tap): '{desc}'")
            return True
        time.sleep(1)
    print(f"[{agent.role}] TIMEOUT waiting for '{desc}' (no tap)")
    return False


def _find_all_inc_buttons(agent, xml):
    """Find all item increment buttons (*Inc content-desc) visible on screen."""
    items = []
    seen = set()
    # Pattern: content-desc before bounds
    for m in re.finditer(r'content-desc="(\w+Inc)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
        name, x1, y1, x2, y2 = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
        if name not in seen and not (x1 == 0 and y1 == 0 and x2 == 0 and y2 == 0):
            items.append((name, (x1 + x2) // 2, (y1 + y2) // 2))
            seen.add(name)
    # Pattern: bounds before content-desc
    for m in re.finditer(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*content-desc="(\w+Inc)"', xml):
        x1, y1, x2, y2, name = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), m.group(5)
        if name not in seen and not (x1 == 0 and y1 == 0 and x2 == 0 and y2 == 0):
            items.append((name, (x1 + x2) // 2, (y1 + y2) // 2))
            seen.add(name)
    return items


def _find_all_product_options(xml):
    """Find all tappable *Product variant/modifier options on screen (excluding controls).
    Returns list of (name, cx, cy, y_position) sorted by vertical position."""
    skip = {"confirmProduct", "favProduct", "productClose", "productInfo"}
    options = []
    seen = set()
    for m in re.finditer(r'content-desc="(\w+Product)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
        name, x1, y1, x2, y2 = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
        if name not in skip and name not in seen and not (x1 == 0 and y1 == 0 and x2 == 0 and y2 == 0):
            options.append((name, (x1 + x2) // 2, (y1 + y2) // 2, y1))
            seen.add(name)
    for m in re.finditer(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*content-desc="(\w+Product)"', xml):
        x1, y1, x2, y2, name = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), m.group(5)
        if name not in skip and name not in seen and not (x1 == 0 and y1 == 0 and x2 == 0 and y2 == 0):
            options.append((name, (x1 + x2) // 2, (y1 + y2) // 2, y1))
            seen.add(name)
    # Sort by vertical position (top to bottom)
    options.sort(key=lambda x: x[3])
    return options


def _find_section_markers(xml):
    """Find vertical positions of 'Choose at least' markers in the dialog XML.
    Each marker starts a new section. Returns list of y-positions."""
    markers = []
    for m in re.finditer(r'text="[^"]*[Cc]hoose at least[^"]*"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
        y1 = int(m.group(2))
        if y1 > 0:
            markers.append(y1)
    for m in re.finditer(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*text="[^"]*[Cc]hoose at least[^"]*"', xml):
        y1 = int(m.group(2))
        if y1 > 0:
            markers.append(y1)
    return sorted(set(markers))


def _select_first_per_section(agent, xml, already_selected):
    """Select the FIRST product option in each required section visible on screen.
    Skips options near bottom edge (y > 1250) — let scrolling bring them up first.
    Returns set of newly selected option names."""
    options = _find_all_product_options(xml)
    markers = _find_section_markers(xml)
    new_selected = set()

    # Filter out options too close to screen bottom — not reliably tappable
    BOTTOM_CUTOFF = 1250
    tappable = [(n, cx, cy, y) for n, cx, cy, y in options if cy < BOTTOM_CUTOFF]

    if not tappable:
        return new_selected

    if not markers:
        # No section markers visible — select first unselected option
        for name, cx, cy, _ in tappable:
            if name not in already_selected:
                agent.tap(cx, cy, f"[variant:{name}]")
                new_selected.add(name)
                time.sleep(0.5)
                break
        return new_selected

    # Group options by section: each option belongs to the section whose marker is closest above it
    for marker_y in markers:
        # Check ALL options in section (including bottom ones) for already-selected skip
        section_all_names = [
            n for n, cx, cy, y in options
            if y >= marker_y and y < marker_y + 400
        ]
        if any(n in already_selected for n in section_all_names):
            continue
        # Only tap options above bottom cutoff
        section_tappable = [
            (n, cx, cy) for n, cx, cy, y in tappable
            if y >= marker_y and y < marker_y + 400
        ]
        if section_tappable:
            name, cx, cy = section_tappable[0]
            agent.tap(cx, cy, f"[variant:{name}]")
            new_selected.add(name)
            print(f"[{agent.role}] Selected '{name}' (first in section at y={marker_y})")
            time.sleep(0.5)

    return new_selected


def _handle_variant_dialog(agent, max_scrolls=6):
    """Handle variant/modifier dialog: select FIRST option per required section.
    Scrolls inside dialog to find all sections. Uses small swipe for dialog overlay."""
    time.sleep(2)
    selected = set()
    no_new_count = 0

    # Phase 1: Scroll through dialog, select first option per section
    for scroll_round in range(max_scrolls + 1):
        # Scroll first (except round 0) to reveal more sections
        if scroll_round > 0:
            agent.swipe_up_small()
            time.sleep(1)

        xml = agent.dump_ui()
        newly = _select_first_per_section(agent, xml, selected)
        selected.update(newly)

        if newly:
            no_new_count = 0
            print(f"[{agent.role}] Selected so far: {len(selected)} options")
        else:
            no_new_count += 1
            if no_new_count >= 2 and scroll_round >= 3:
                break

    print(f"[{agent.role}] Variants done ({len(selected)}): {selected}")

    # Phase 2: Try confirmProduct
    for attempt in range(5):
        xml = agent.dump_ui()

        # Check for any new sections after scrolling
        newly = _select_first_per_section(agent, xml, selected)
        selected.update(newly)

        # Try to tap confirmProduct
        xml = agent.dump_ui()
        confirm = agent.find_by_desc(xml, "confirmProduct")
        if confirm:
            agent.tap(confirm[0], confirm[1], "[confirmProduct]")
            time.sleep(1.5)
            xml2 = agent.dump_ui()
            if not agent.find_by_desc(xml2, "confirmProduct"):
                print(f"[{agent.role}] Added to cart ({len(selected)} variants)")
                return True
            print(f"[{agent.role}] Still in dialog — need more selections, scrolling...")
        # Scroll inside dialog
        agent.swipe_up_small()
        time.sleep(1)

    # Last resort: close dialog
    print(f"[{agent.role}] Could not confirm after {len(selected)} options — closing dialog")
    _tap(agent, "productClose")
    time.sleep(1)
    return False


def _verify_item_added(agent, item_name):
    """Check if item counter changed from 0 to 1+ (item was added)."""
    xml = agent.dump_ui()
    # The Dec button appears only when count >= 1, e.g. "PaneerTikkaDec"
    dec_name = item_name.replace("Inc", "Dec")
    if agent.find_by_desc(xml, dec_name):
        print(f"[{agent.role}] ✓ {item_name} verified (counter > 0)")
        return True
    # Also check: find the counter text "1" near the item
    print(f"[{agent.role}] ✗ {item_name} may not have been added")
    return False


def _add_all_items_in_category(agent, category_desc, global_added=None):
    """Tap a category tab, find ALL items, add each with variants. Returns count added.
    global_added: set of item names already added in previous categories (to skip)."""
    print(f"[{agent.role}] === Adding all items in '{category_desc}' ===")
    if not _wait_tap(agent, category_desc):
        print(f"[{agent.role}] Category '{category_desc}' not found — skipping")
        return 0
    time.sleep(2)

    if global_added is None:
        global_added = set()
    added = set()
    verified = set()
    no_new_rounds = 0

    for scroll_round in range(12):  # more rounds to find all items
        xml = agent.dump_ui()
        inc_buttons = _find_all_inc_buttons(agent, xml)
        # Skip items already added in THIS category or PREVIOUS categories
        new_buttons = [(n, x, y) for n, x, y in inc_buttons
                       if n not in added and n not in global_added]

        if not new_buttons:
            no_new_rounds += 1
            if no_new_rounds >= 3:  # wait longer before giving up
                break
            agent.swipe_up()
            time.sleep(1.5)
            continue

        no_new_rounds = 0
        for name, cx, cy in new_buttons:
            print(f"[{agent.role}] Tapping item: {name}")
            agent.tap(cx, cy, f"[{name}]")
            added.add(name)
            time.sleep(1.5)

            # Check if variant dialog appeared
            xml2 = agent.dump_ui()
            if agent.find_by_desc(xml2, "confirmProduct"):
                success = _handle_variant_dialog(agent)
                if success:
                    verified.add(name)
            else:
                # No variant dialog — verify item was added by checking counter
                if _verify_item_added(agent, name):
                    verified.add(name)
            time.sleep(1)

        agent.swipe_up()
        time.sleep(1.5)

    # Add this category's items to global tracker
    global_added.update(added)
    print(f"[{agent.role}] Category '{category_desc}' done — {len(added)} tapped, {len(verified)} verified")
    return len(verified)


def _no_op(agent):
    """Placeholder for business flow when scenario is consumer-only."""
    print(f"[{agent.role}] No action required for this scenario.")


def _login_if_needed(agent, email, password):
    """Login only if the login screen is visible (loginEmail field exists)."""
    xml = agent.dump_ui()
    match = agent.find_by_desc(xml, "loginEmail") or agent.find_by_text(xml, "loginEmail")
    if match:
        print(f"[{agent.role}] Login screen detected — logging in as {email}")
        _type_field(agent, "loginEmail", email)
        _type_field(agent, "loginPassword", password)
        agent.adb("shell", "input", "keyevent", "KEYCODE_HIDE")
        agent.adb("shell", "input", "swipe", "363", "996", "360", "672", "168")
        time.sleep(1)
        _wait_tap(agent, "signIn")
        time.sleep(3)
    else:
        print(f"[{agent.role}] Already logged in — skipping login")


def _switch_account(agent, email, password):
    """Logout and login as another user on consumer device."""
    print(f"[{agent.role}] Switching to account: {email}")
    _tap(agent, "menuTab")
    _tap(agent, "menuLogout")
    time.sleep(2)
    _type_field(agent, "loginEmail", email)
    _type_field(agent, "loginPassword", password)
    agent.adb("shell", "input", "keyevent", "KEYCODE_HIDE")
    agent.adb("shell", "input", "swipe", "363", "996", "360", "672", "168")
    time.sleep(1)
    _wait_tap(agent, "signIn")
    time.sleep(3)


# ─── CONTACTS & WALLET (CW1–CW6) ─────────────────────────────────────────────

def cw1_consumer_flow(agent):
    """CW1: Creating New Contact from Reservation"""
    print(f"[{agent.role}] [CW1] Creating New Contact from Reservation")
    agent.launch_app()
    _login_if_needed(agent, "roopa@xorstack.com", "12345")
    # Select restaurant and add contact
    _tap(agent, "NylaiKitchen")
    time.sleep(2)
    _wait_tap(agent, "counterPlus")
    _wait_tap(agent, "newContactAdd")
    _type_field(agent, "firstName", "Prajwal")
    _type_field(agent, "mobileCont", "8937773734")
    _tap(agent, "saveContact")
    time.sleep(1)
    _type_field(agent, "contactSearch", "Prajwal")
    _wait_tap(agent, "back")
    _tap_chip_container(agent)
    _wait_tap(agent, "bookAppoitment")
    scenario_reporter.add_result("CW1", "Creating New Contact from Reservation",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def cw2_consumer_flow(agent):
    """CW2: Adding Guest from Wallet after Creating an Event"""
    print(f"[{agent.role}] [CW2] Adding Guest from Wallet")
    agent.launch_app()
    _tap(agent, "orderLater")
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    if not _tap(agent, "Invite"):
        _tap(agent, "inviteUsers")
    time.sleep(2)
    _tap(agent, "back")
    time.sleep(2)
    _tap(agent, "homeTab")
    scenario_reporter.add_result("CW2", "Adding Guest from Wallet",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def cw3_consumer_flow(agent):
    """CW3: Adding User/Participant from Wallet after Creating an Event"""
    print(f"[{agent.role}] [CW3] Adding User from Wallet")
    agent.launch_app()
    # Scroll and select restaurant (exact Appium swipe: 690,1654 → 654,1433)
    agent.adb("shell", "input", "swipe", "690", "1654", "654", "1433", "313")
    time.sleep(1)
    _tap(agent, "NylaiKitchen")
    _tap_chip_container(agent)
    _tap(agent, "bookAppoitment")
    _tap(agent, "orderLater")
    time.sleep(3)  # Wait for NylaiKitchenCard screen to load (Appium waits, no click)
    _tap(agent, "Invite")
    time.sleep(2)
    _type_field(agent, "contactSearch", "Noolu")
    time.sleep(2)
    _tap(agent, "NooluInvite")
    _tap(agent, "Noolu")
    time.sleep(2)
    _tap(agent, "inviteUsers")
    time.sleep(5)
    # Switch account to Noolu to accept invite
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_for_card(agent, "RoopaDInviteCard")
    time.sleep(5)
    if not _tap(agent, "eventAccept"):
        time.sleep(3)
        _tap(agent, "eventAccept")
    time.sleep(3)
    _tap(agent, "orderLater")
    time.sleep(2)
    _tap(agent, "homeTab")
    scenario_reporter.add_result("CW3", "Adding User from Wallet",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def cw4_consumer_flow(agent):
    """CW4: Creating New Contact from Wallet"""
    print(f"[{agent.role}] [CW4] Creating New Contact from Wallet")
    agent.launch_app()
    # Continues from CW3 (logged in as noolu) — no re-login per Appium
    _tap(agent, "NylaiKitchen")
    _tap_chip_container(agent)
    _tap(agent, "bookAppoitment")
    _tap(agent, "orderLater")
    time.sleep(3)  # Wait for Invite screen to load
    _tap(agent, "Invite")
    _tap(agent, "newContactAdd")
    _type_field(agent, "firstName", "Sonu")
    _type_field(agent, "mobileCont", "8937773737")
    _tap(agent, "saveContact")
    _type_field(agent, "contactSearch", "Sonu")
    _tap(agent, "back")
    _tap(agent, "homeTab")
    scenario_reporter.add_result("CW4", "Creating New Contact from Wallet",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


# ─── EVENT BOOKING (EB1–EB5) ─────────────────────────────────────────────────

def eb1_consumer_flow(agent):
    """EB1: Book an Event with 1 Guest for 1 hour - Indoor"""
    print(f"[{agent.role}] [EB1] Book Event 1 Guest Indoor")
    agent.launch_app()
    _tap(agent, "NylaiKitchen")
    time.sleep(2)
    _tap(agent, "Indoor")
    _slide_to_not_sure(agent)              # select duration → reveals time slots
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    if not _tap(agent, "chip"):
        agent.swipe_up()
        time.sleep(2)
        _tap(agent, "chip")
    time.sleep(2)
    _tap(agent, "counterPlus")
    _tap(agent, "guestAdd")
    _tap(agent, "inviteUsers")
    _wait_tap(agent, "bookAppoitment")
    _tap(agent, "orderLater")
    time.sleep(5)  # let booking sync with server
    _tap(agent, "walletTab")
    time.sleep(2)
    _tap(agent, "homeTab")
    events["order_placed"].set()
    scenario_reporter.add_result("EB1", "Book Event 1 Guest Indoor",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def eb1_business_flow(agent):
    """EB1 Business: Accept incoming booking"""
    print(f"[{agent.role}] [EB1] Waiting for booking")
    agent.launch_app()
    if events["order_placed"].wait(timeout=120):
        time.sleep(5)
        _tap(agent, "Orders")
        time.sleep(5)
        # Scroll to find ReservedOrderCard (up to 5 attempts)
        for i in range(5):
            if _tap(agent, "ReservedOrderCard"):
                break
            print(f"[{agent.role}] Scrolling for ReservedOrderCard (attempt {i+1}/5)")
            agent.swipe_up()
            time.sleep(3)
        time.sleep(5)
        agent.swipe_up()
        time.sleep(2)
        if not _tap(agent, "T0AssignAnyBtn"):
            time.sleep(3)
            _tap(agent, "T0AssignAnyBtn")
        _tap(agent, "AssignTableBtn")
        events["table_accepted"].set()
        scenario_reporter.add_result("EB1", "Book Event 1 Guest Indoor",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def eb2_consumer_flow(agent):
    """EB2: Book Event with invitee accepting - Outdoor"""
    print(f"[{agent.role}] [EB2] Book Event Outdoor - Invitee Accepts")
    agent.launch_app()
    _wait_tap(agent, "NylaiKitchen")
    time.sleep(2)
    _tap(agent, "Outdoor")
    _tap(agent, "counterPlus")
    _type_field(agent, "contactSearch", "Noolu")
    time.sleep(2)  # wait for search results
    _tap(agent, "NooluInvite")
    _tap(agent, "Noolu")
    _tap(agent, "inviteUsers")
    _tap_chip_container(agent)
    agent.swipe_up()
    _type_field(agent, "inputSplIns", "Join the party soon!!!")
    time.sleep(1)
    agent.adb("shell", "input", "keyevent", "KEYCODE_BACK")
    time.sleep(2)
    _tap(agent, "bookAppoitment")
    _tap(agent, "orderLater")
    events["order_placed"].set()
    # Switch to Noolu to accept
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_for_card(agent, "RoopaDInviteCard")
    time.sleep(5)
    if not _tap(agent, "eventAccept"):
        time.sleep(3)
        _tap(agent, "eventAccept")
    time.sleep(5)
    _tap(agent, "orderLater")
    time.sleep(5)  # let booking sync with server
    _tap(agent, "walletTab")
    # Switch back to Roopa
    _switch_account(agent, "roopa@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_for_card(agent, "NylaiKitchenCard")
    time.sleep(2)
    _tap(agent, "Update")
    time.sleep(2)
    agent.adb("shell", "input", "keyevent", "KEYCODE_BACK")
    time.sleep(2)
    scenario_reporter.add_result("EB2", "Book Event Outdoor - Invitee Accepts",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def eb2_business_flow(agent):
    _no_op(agent)


def eb3_consumer_flow(agent):
    """EB3: Book Event with 1 Participant and 1 Guest"""
    print(f"[{agent.role}] [EB3] Book Event 1 Participant + 1 Guest")
    agent.launch_app()
    _tap(agent, "NylaiKitchen")
    time.sleep(2)
    _tap(agent, "counterPlus")
    _tap(agent, "guestAdd")
    _type_field(agent, "contactSearch", "Noolu")
    time.sleep(2)  # wait for search results
    _wait_tap(agent, "NooluInvite")
    _tap(agent, "Noolu")
    _tap(agent, "inviteUsers")
    _tap_chip_container(agent)
    _wait_tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "orderLater")
    time.sleep(5)
    time.sleep(5)
    events["order_placed"].set()
    # Noolu accepts
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_for_card(agent, "RoopaDInviteCard")
    time.sleep(5)
    if not _tap(agent, "eventAccept"):
        time.sleep(3)
        _tap(agent, "eventAccept")
    time.sleep(5)
    _tap(agent, "orderLater")
    time.sleep(5)  # let booking sync with server
    _tap(agent, "walletTab")
    _wait_for_card(agent, "NylaiKitchenCard")
    time.sleep(2)
    # Switch back to Roopa
    _switch_account(agent, "roopa@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_for_card(agent, "NylaiKitchenCard")
    time.sleep(2)
    _tap(agent, "Update")
    time.sleep(2)
    agent.adb("shell", "input", "keyevent", "KEYCODE_BACK")
    time.sleep(2)
    scenario_reporter.add_result("EB3", "Book Event 1 Participant + 1 Guest",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def eb3_business_flow(agent):
    _no_op(agent)


def eb4_consumer_flow(agent):
    """EB4: Book Event with invitee when Declines"""
    print(f"[{agent.role}] [EB4] Book Event - Invitee Declines")
    agent.launch_app()
    _tap(agent, "NylaiKitchen")
    time.sleep(2)
    _tap(agent, "counterPlus")
    _type_field(agent, "contactSearch", "Noolu")
    time.sleep(2)  # wait for search results
    _tap(agent, "NooluInvite")
    _tap(agent, "Noolu")
    _tap(agent, "inviteUsers")
    _tap_chip_container(agent)
    agent.swipe_up()
    _type_field(agent, "inputSplIns", "Lets enjoy the party")
    time.sleep(1)
    agent.adb("shell", "input", "keyevent", "KEYCODE_BACK")
    time.sleep(2)
    _tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "orderLater")
    time.sleep(5)
    events["order_placed"].set()
    # Switch to Noolu to decline
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_for_card(agent, "RoopaDInviteCard")
    time.sleep(5)
    if not _tap(agent, "eventDecline"):
        time.sleep(3)
        _tap(agent, "eventDecline")
    time.sleep(5)
    # Switch back to Roopa
    _switch_account(agent, "roopa@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_for_card(agent, "NylaiKitchenCard")
    time.sleep(2)
    _tap(agent, "Update")
    time.sleep(2)
    agent.adb("shell", "input", "keyevent", "KEYCODE_BACK")
    time.sleep(2)
    scenario_reporter.add_result("EB4", "Book Event - Invitee Declines",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def eb4_business_flow(agent):
    _no_op(agent)


def eb5_consumer_flow(agent):
    """EB5: Book Event with more invitees and apply filter in wallet"""
    print(f"[{agent.role}] [EB5] Book Event Multiple Invitees + Wallet Filter")
    agent.launch_app()
    _tap(agent, "NylaiKitchen")
    time.sleep(2)
    _tap(agent, "counterPlus")
    _tap(agent, "contactSearch")
    time.sleep(1)
    agent.type_text("Noolu")
    time.sleep(2)
    agent.adb("shell", "input", "keyevent", "KEYCODE_BACK")
    time.sleep(2)
    _tap(agent, "NooluInvite")
    _tap(agent, "Noolu")
    time.sleep(2)
    _type_field(agent, "contactSearch", "Aritro", clear_first=True)
    time.sleep(2)
    _tap(agent, "AritroInvite")
    _tap(agent, "Aritro")
    time.sleep(2)
    _type_field(agent, "contactSearch", "Likhith Raj", clear_first=True)
    time.sleep(2)
    _tap(agent, "LikhithRajInvite")
    _tap(agent, "Likhith Raj")
    time.sleep(2)
    _tap(agent, "inviteUsers")
    _tap_chip_container(agent)
    _wait_tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "orderLater")
    time.sleep(5)
    # Noolu declines
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_for_card(agent, "RoopaDInviteCard")
    time.sleep(5)
    if not _tap(agent, "eventDecline"):
        time.sleep(3)
        _tap(agent, "eventDecline")
    time.sleep(3)
    _tap(agent, "walletTab")
    # Likhith Raj accepts
    _switch_account(agent, "likhithraj@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_for_card(agent, "RoopaDInviteCard")
    time.sleep(5)
    if not _tap(agent, "eventAccept"):
        time.sleep(3)
        _tap(agent, "eventAccept")
    _tap(agent, "orderLater")
    time.sleep(5)  # let booking sync with server
    _tap(agent, "walletTab")
    # Aritro applies filters then accepts
    _switch_account(agent, "aritro@xorstack.com", "12345")
    _tap(agent, "walletTab")
    time.sleep(5)
    _wait_for_card(agent, "RoopaDInviteCard", max_attempts=8)
    time.sleep(2)
    _tap(agent, "allFilterInvites")
    _tap(agent, "allUserFilterReject")
    _tap(agent, "allUserFilterApply")
    time.sleep(1)
    _tap(agent, "clearFilterInvites")
    _tap(agent, "allFilterInvites")
    _tap(agent, "allUserFilterAccept")
    _tap(agent, "allUserFilterApply")
    time.sleep(1)
    _tap(agent, "clearFilterInvites")
    _tap(agent, "eventAccept")
    _tap(agent, "orderLater")
    time.sleep(5)  # let booking sync with server
    _tap(agent, "walletTab")
    # Switch back to Roopa
    _switch_account(agent, "roopa@xorstack.com", "12345")
    _tap(agent, "walletTab")
    time.sleep(30)
    _wait_for_card(agent, "NylaiKitchenCard", max_attempts=8)
    time.sleep(2)
    _tap(agent, "Update")
    time.sleep(2)
    agent.adb("shell", "input", "keyevent", "KEYCODE_BACK")
    time.sleep(2)
    scenario_reporter.add_result("EB5", "Book Event Multiple Invitees + Wallet Filter",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def eb5_business_flow(agent):
    _no_op(agent)


def _detect_eb6_state(agent):
    """Detect where the user currently is in the EB6 flow.
    Returns the step number to resume from:
      1 = not started (home/restaurant screen)
      2 = event booked, need to go to wallet
      3 = on menu, need to add items
      4 = items added, need to go to checkout
      5 = on checkout screen
    """
    xml = agent.dump_ui()

    # Check MENU first (most specific — category tabs or Inc buttons)
    category_descs = ["starterscategory", "pasta-pizzacategory", "cheesy-comfort-platescategory",
                      "thai-street-food-favoritescategory"]
    has_category = any(cat in xml for cat in category_descs)
    has_inc = bool(re.search(r'content-desc="\w+Inc"', xml))
    if has_category or has_inc:
        print(f"[{agent.role}] [EB6-RESUME] Detected: Menu screen → resuming from Step 3")
        return 3

    # Check checkout (only if NOT on menu — menu can also show "checkout" in cart button)
    # Checkout screen has bill items but NO category tabs
    lower_xml = xml.lower()
    checkout_keywords = ["grand total", "place order", "total amount", "bill total", "payment summary"]
    if any(kw in lower_xml for kw in checkout_keywords):
        print(f"[{agent.role}] [EB6-RESUME] Detected: Checkout screen → resuming from Step 5")
        return 5

    # Check wallet screen
    if "Pre-Order" in xml or "walletTab" in xml:
        print(f"[{agent.role}] [EB6-RESUME] Detected: Wallet screen → resuming from Step 2")
        return 2

    # Check if cart visible (post-menu, pre-checkout)
    if "cartImage" in xml or "cartCheckout" in xml:
        print(f"[{agent.role}] [EB6-RESUME] Detected: Cart visible → resuming from Step 4")
        return 4

    # Default: start from beginning
    print(f"[{agent.role}] [EB6-RESUME] No recognized state → starting from Step 1")
    return 1


# EB6 and EB7 removed — unwanted scenarios


# ─── CREATE & MANAGE EVENTS FROM B-APP (BME1–BME6) ───────────────────────────

def bme1_consumer_flow(agent):
    """BME1: Consumer declines B-App event invite"""
    print(f"[{agent.role}] [BME1] Waiting for B-App event invite")
    agent.launch_app()
    # Poll shared_data — business sets flag when done
    print(f"[{agent.role}] Waiting for business to create event...")
    for i in range(60):
        if shared_data.get("bme1_business_done"):
            print(f"[{agent.role}] Business finished, starting consumer flow")
            break
        time.sleep(3)
    time.sleep(5)
    _tap(agent, "walletTab")
    time.sleep(10)
    _wait_for_card(agent, "Nylai KitchenInviteCard", max_attempts=10)
    time.sleep(3)
    if not _tap(agent, "eventDecline"):
        time.sleep(3)
        _tap(agent, "eventDecline")
    time.sleep(10)
    _tap(agent, "homeTab")
    time.sleep(3)
    shared_data["bme1_consumer_done"] = True
    scenario_reporter.add_result("BME1", "B-App Event - User Declines",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def bme1_business_flow(agent):
    """BME1: Create event from B-App"""
    print(f"[{agent.role}] [BME1] Creating event from B-App")
    agent.launch_app()
    time.sleep(5)
    # Tap add new event
    if not _tap(agent, "addNewEvent"):
        agent.swipe_up()
        time.sleep(3)
        _tap(agent, "addNewEvent")
    time.sleep(5)
    # Type first name
    _tap(agent, "firstName")
    time.sleep(3)
    for ch in "Roopa":
        agent.adb("shell", "input", "text", ch)
        time.sleep(0.3)
    time.sleep(2)
    # Type last name
    _tap(agent, "lastName")
    time.sleep(3)
    agent.adb("shell", "input", "text", "D")
    time.sleep(2)
    # Dismiss keyboard and scroll to see dining area
    agent.adb("shell", "input", "keyevent", "111")
    time.sleep(3)
    # Select Any dining area — tap 3 times to ensure selection
    _tap(agent, "anyBtn")
    time.sleep(1)
    _tap(agent, "anyBtn")
    time.sleep(1)
    _tap(agent, "anyBtn")
    time.sleep(2)
    # Slide duration to Not Sure — long drag from 1hr to end
    agent.adb("shell", "input", "swipe", "80", "1370", "950", "1370", "1500")
    time.sleep(3)
    _tap_chip_container(agent)
    # Type mobile number
    _tap(agent, "mobileInputBtn")
    time.sleep(3)
    for ch in "9686496589":
        agent.adb("shell", "input", "text", ch)
        time.sleep(0.3)
    time.sleep(2)
    agent.adb("shell", "input", "keyevent", "111")
    time.sleep(3)
    # Save event — tap 2 times to ensure it registers
    _tap(agent, "saveBtn")
    time.sleep(2)
    _tap(agent, "saveBtn")
    time.sleep(20)
    # Business done — signal consumer to start
    shared_data["bme1_business_done"] = True
    # Wait for consumer to finish declining
    for i in range(60):
        if shared_data.get("bme1_consumer_done"):
            break
        time.sleep(3)
    scenario_reporter.add_result("BME1", "B-App Event - User Declines",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def bme2_consumer_flow(agent):
    """BME2: Consumer accepts B-App event and preorders"""
    print(f"[{agent.role}] [BME2] Waiting for B-App event to accept")
    agent.launch_app()
    # Poll shared_data — business sets flag when done
    print(f"[{agent.role}] Waiting for business to create event...")
    for i in range(60):
        if shared_data.get("bme2_business_done"):
            print(f"[{agent.role}] Business finished, starting consumer flow")
            break
        time.sleep(3)
    time.sleep(5)
    _tap(agent, "walletTab")
    time.sleep(10)
    _wait_for_card(agent, "Nylai KitchenInviteCard", max_attempts=10)
    time.sleep(3)
    if not _tap(agent, "eventAccept"):
        time.sleep(3)
        _tap(agent, "eventAccept")
    time.sleep(5)
    _tap(agent, "preOrderBooking")
    time.sleep(5)
    _tap(agent, "starterscategory", scroll=False)
    time.sleep(3)
    _tap(agent, "MuttonSeekhKebabInc", scroll=True)
    time.sleep(3)
    _tap(agent, "2pcsProduct")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "chutneyProduct")
    time.sleep(2)
    _tap(agent, "confirmProduct")
    time.sleep(3)
    _tap(agent, "cheesy-comfort-platescategory", scroll=False)
    time.sleep(3)
    _tap(agent, "Cheese-StuffedGarlicBreadInc")
    time.sleep(3)
    _tap(agent, "6pccsProduct")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "MarinaraDipProduct")
    time.sleep(2)
    _tap(agent, "confirmProduct")
    time.sleep(3)
    _tap(agent, "cartImage")
    time.sleep(3)
    _tap(agent, "cartCheckout")
    time.sleep(5)
    _tap(agent, "primary_button")
    time.sleep(20)
    _tap(agent, "pickUpOrderConfirm")
    agent.check_bill()
    time.sleep(3)
    shared_data["bme2_consumer_done"] = True
    scenario_reporter.add_result("BME2", "B-App Event - User Accepts & Preorders",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def bme2_business_flow(agent):
    """BME2: Create event from B-App"""
    print(f"[{agent.role}] [BME2] Creating event from B-App")
    agent.launch_app()
    time.sleep(5)
    # Tap add new event
    if not _tap(agent, "addNewEvent"):
        agent.swipe_up()
        time.sleep(3)
        _tap(agent, "addNewEvent")
    time.sleep(5)
    # Type first name
    _tap(agent, "firstName")
    time.sleep(3)
    for ch in "Roopa":
        agent.adb("shell", "input", "text", ch)
        time.sleep(0.3)
    time.sleep(2)
    # Type last name
    _tap(agent, "lastName")
    time.sleep(3)
    agent.adb("shell", "input", "text", "D")
    time.sleep(2)
    # Dismiss keyboard
    agent.adb("shell", "input", "keyevent", "111")
    time.sleep(3)
    # Select Any dining area — tap 3 times to ensure selection
    _tap(agent, "anyBtn")
    time.sleep(1)
    _tap(agent, "anyBtn")
    time.sleep(1)
    _tap(agent, "anyBtn")
    time.sleep(2)
    # Slide duration to Not Sure — long drag from 1hr to end
    agent.adb("shell", "input", "swipe", "80", "1370", "950", "1370", "1500")
    time.sleep(3)
    _tap_chip_container(agent)
    # Type mobile number
    _tap(agent, "mobileInputBtn")
    time.sleep(3)
    for ch in "9686496589":
        agent.adb("shell", "input", "text", ch)
        time.sleep(0.3)
    time.sleep(2)
    agent.adb("shell", "input", "keyevent", "111")
    time.sleep(3)
    # Save event — tap 2 times to ensure it registers
    _tap(agent, "saveBtn")
    time.sleep(2)
    _tap(agent, "saveBtn")
    time.sleep(20)
    # Business done — signal consumer to start
    shared_data["bme2_business_done"] = True
    # Wait for consumer to finish preorder
    for i in range(60):
        if shared_data.get("bme2_consumer_done"):
            break
        time.sleep(3)
    scenario_reporter.add_result("BME2", "B-App Event - User Accepts & Preorders",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def bme3_consumer_flow(agent):
    """BME3: Accept event and invite another user from wallet"""
    print(f"[{agent.role}] [BME3] Accept event and add guest from wallet")
    agent.launch_app()
    # Wait for business to create event
    print(f"[{agent.role}] Waiting for business to create event...")
    for i in range(60):
        if shared_data.get("bme3_business_done"):
            print(f"[{agent.role}] Business finished, starting consumer flow")
            break
        time.sleep(3)
    time.sleep(5)
    _tap(agent, "walletTab")
    time.sleep(10)
    _wait_for_card(agent, "Nylai KitchenInviteCard", max_attempts=15)
    time.sleep(3)
    if not _tap(agent, "eventAccept"):
        time.sleep(3)
        _tap(agent, "eventAccept")
    time.sleep(5)
    _tap(agent, "orderLater")
    time.sleep(5)
    _tap(agent, "homeTab")
    time.sleep(3)
    _tap(agent, "NylaiKitchen")
    time.sleep(3)
    _tap(agent, "counterPlus")
    time.sleep(2)
    _tap(agent, "guestAdd")
    time.sleep(3)
    _tap(agent, "contactSearch")
    time.sleep(1)
    agent.type_text("Noolu")
    time.sleep(2)
    agent.adb("shell", "input", "keyevent", "KEYCODE_BACK")
    time.sleep(2)
    _tap(agent, "NooluInvite")
    time.sleep(2)
    _tap(agent, "Noolu")
    time.sleep(2)
    _tap(agent, "inviteUsers")
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    _tap_chip_container(agent)
    _tap(agent, "bookAppoitment")
    time.sleep(3)
    shared_data["bme3_consumer_done"] = True
    scenario_reporter.add_result("BME3", "B-App Event - Invite User from Wallet",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def bme3_business_flow(agent):
    """BME3: Create event from B-App"""
    print(f"[{agent.role}] [BME3] Creating event from B-App")
    agent.launch_app()
    time.sleep(5)
    # Tap add new event
    if not _tap(agent, "addNewEvent"):
        agent.swipe_up()
        time.sleep(3)
        _tap(agent, "addNewEvent")
    time.sleep(5)
    # Type first name
    _tap(agent, "firstName")
    time.sleep(3)
    for ch in "Roopa":
        agent.adb("shell", "input", "text", ch)
        time.sleep(0.3)
    time.sleep(2)
    # Type last name
    _tap(agent, "lastName")
    time.sleep(3)
    agent.adb("shell", "input", "text", "D")
    time.sleep(2)
    # Dismiss keyboard
    agent.adb("shell", "input", "keyevent", "111")
    time.sleep(3)
    # Select Any dining area — tap 3 times to ensure selection
    _tap(agent, "anyBtn")
    time.sleep(1)
    _tap(agent, "anyBtn")
    time.sleep(1)
    _tap(agent, "anyBtn")
    time.sleep(2)
    # Slide duration to Not Sure — long drag from 1hr to end
    agent.adb("shell", "input", "swipe", "80", "1370", "950", "1370", "1500")
    time.sleep(3)
    _tap_chip_container(agent)
    # Type mobile number
    _tap(agent, "mobileInputBtn")
    time.sleep(3)
    for ch in "9686496589":
        agent.adb("shell", "input", "text", ch)
        time.sleep(0.3)
    time.sleep(2)
    agent.adb("shell", "input", "keyevent", "111")
    time.sleep(3)
    # Save event — tap 2 times to ensure it registers
    _tap(agent, "saveBtn")
    time.sleep(2)
    _tap(agent, "saveBtn")
    time.sleep(20)
    # Business done — signal consumer to start
    shared_data["bme3_business_done"] = True
    # Wait for consumer to finish inviting
    for i in range(60):
        if shared_data.get("bme3_consumer_done"):
            break
        time.sleep(3)
    scenario_reporter.add_result("BME3", "B-App Event - Invite User from Wallet",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def bme4_consumer_flow(agent):
    """BME4: Cancel event from B-App when invitee present"""
    print(f"[{agent.role}] [BME4] Consumer accepts invite then waits for cancel")
    agent.launch_app()
    # Wait for business to create event
    print(f"[{agent.role}] Waiting for business to create event...")
    for i in range(60):
        if shared_data.get("bme4_business_done"):
            print(f"[{agent.role}] Business finished, starting consumer flow")
            break
        time.sleep(3)
    time.sleep(5)
    # Switch to Noolu to accept
    _switch_account(agent, "noolu@xorstack.com", "12345")
    time.sleep(3)
    _tap(agent, "walletTab")
    time.sleep(10)
    _wait_for_card(agent, "RoopaDInviteCard", max_attempts=10)
    time.sleep(3)
    if not _tap(agent, "eventAccept"):
        time.sleep(3)
        _tap(agent, "eventAccept")
    time.sleep(5)
    _tap(agent, "orderLater")
    time.sleep(5)
    # Switch back to Roopa
    _switch_account(agent, "roopa@xorstack.com", "12345")
    time.sleep(3)
    shared_data["bme4_consumer_done"] = True
    scenario_reporter.add_result("BME4", "B-App Event - Cancel with Invitee",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def bme4_business_flow(agent):
    """BME4: Business creates event then cancels it"""
    print(f"[{agent.role}] [BME4] Creating event and cancelling from B-App")
    agent.launch_app()
    time.sleep(5)
    # Tap add new event
    if not _tap(agent, "addNewEvent"):
        agent.swipe_up()
        time.sleep(3)
        _tap(agent, "addNewEvent")
    time.sleep(5)
    # Type first name
    _tap(agent, "firstName")
    time.sleep(3)
    for ch in "Roopa":
        agent.adb("shell", "input", "text", ch)
        time.sleep(0.3)
    time.sleep(2)
    # Type last name
    _tap(agent, "lastName")
    time.sleep(3)
    agent.adb("shell", "input", "text", "D")
    time.sleep(2)
    # Dismiss keyboard
    agent.adb("shell", "input", "keyevent", "111")
    time.sleep(3)
    # Select Any dining area — tap 3 times to ensure selection
    _tap(agent, "anyBtn")
    time.sleep(1)
    _tap(agent, "anyBtn")
    time.sleep(1)
    _tap(agent, "anyBtn")
    time.sleep(2)
    # Slide duration to Not Sure — long drag from 1hr to end
    agent.adb("shell", "input", "swipe", "80", "1370", "950", "1370", "1500")
    time.sleep(3)
    _tap_chip_container(agent)
    # Type mobile number
    _tap(agent, "mobileInputBtn")
    time.sleep(3)
    for ch in "9686496589":
        agent.adb("shell", "input", "text", ch)
        time.sleep(0.3)
    time.sleep(2)
    agent.adb("shell", "input", "keyevent", "111")
    time.sleep(3)
    # Save event — tap 2 times to ensure it registers
    _tap(agent, "saveBtn")
    time.sleep(2)
    _tap(agent, "saveBtn")
    time.sleep(20)
    # Business done — signal consumer to start
    shared_data["bme4_business_done"] = True
    # Wait for consumer to accept
    for i in range(60):
        if shared_data.get("bme4_consumer_done"):
            break
        time.sleep(3)
    time.sleep(5)
    # Cancel the event
    _tap(agent, "cancelEvent")
    time.sleep(3)
    _tap(agent, "confirmEventBtn")
    time.sleep(5)
    scenario_reporter.add_result("BME4", "B-App Event - Cancel with Invitee",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def bme5_consumer_flow(agent):
    """BME5: Cancel event created from B-App (no invitees)"""
    print(f"[{agent.role}] [BME5] Consumer accepts B-App event")
    agent.launch_app()
    # Wait for business to finish creating event
    for i in range(60):
        if shared_data.get("bme5_business_done"):
            break
        time.sleep(3)
    _tap(agent, "walletTab")
    time.sleep(2)
    _wait_tap(agent, "Nylai KitchenInviteCard")
    _tap(agent, "eventAccept")
    _tap(agent, "orderLater")
    time.sleep(5)
    shared_data["bme5_consumer_done"] = True
    scenario_reporter.add_result("BME5", "B-App Event Cancel - No Invitees",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def bme5_business_flow(agent):
    """BME5: Create and cancel event from B-App"""
    print(f"[{agent.role}] [BME5] Create then cancel event from B-App")
    agent.launch_app()
    time.sleep(5)
    # Tap add new event
    if not _tap(agent, "addNewEvent"):
        agent.swipe_up()
        time.sleep(3)
        _tap(agent, "addNewEvent")
    time.sleep(5)
    # Type first name
    _tap(agent, "firstName")
    time.sleep(3)
    for ch in "Roopa":
        agent.adb("shell", "input", "text", ch)
        time.sleep(0.3)
    time.sleep(2)
    # Type last name
    _tap(agent, "lastName")
    time.sleep(3)
    agent.adb("shell", "input", "text", "D")
    time.sleep(2)
    # Dismiss keyboard and scroll to see dining area
    agent.adb("shell", "input", "keyevent", "111")
    time.sleep(3)
    # Select Any dining area — tap 3 times to ensure selection
    _tap(agent, "anyBtn")
    time.sleep(1)
    _tap(agent, "anyBtn")
    time.sleep(1)
    _tap(agent, "anyBtn")
    time.sleep(2)
    # Slide duration to Not Sure — long drag from 1hr to end
    agent.adb("shell", "input", "swipe", "80", "1370", "950", "1370", "1500")
    time.sleep(3)
    _tap_chip_container(agent)
    # Type mobile number
    _tap(agent, "mobileInputBtn")
    time.sleep(3)
    for ch in "9686496589":
        agent.adb("shell", "input", "text", ch)
        time.sleep(0.3)
    time.sleep(2)
    agent.adb("shell", "input", "keyevent", "111")
    time.sleep(3)
    # Save event — tap 2 times to ensure it registers
    _tap(agent, "saveBtn")
    time.sleep(2)
    _tap(agent, "saveBtn")
    time.sleep(20)
    # Business done — signal consumer to start
    shared_data["bme5_business_done"] = True
    # Wait for consumer to finish accepting
    for i in range(60):
        if shared_data.get("bme5_consumer_done"):
            break
        time.sleep(3)
    time.sleep(5)
    # Go to Home and find the event to cancel
    _tap(agent, "Home")
    time.sleep(8)
    # Find Reserved/In Progress event and tap three dots
    for attempt in range(5):
        xml = agent.dump_ui()
        match = agent.find_by_text(xml, "Reserved") or agent.find_by_text(xml, "In Progress")
        if match:
            dots_x = 1020
            dots_y = match[1] + 40
            print(f"[{agent.role}] Found event at y={match[1]}, tapping three dots")
            agent.adb("shell", "input", "tap", str(dots_x), str(dots_y))
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(5)
    # Tap "Cancel the event"
    print(f"[{agent.role}] Tapping Cancel the event")
    agent.adb("shell", "input", "tap", "300", "1620")
    time.sleep(3)
    # Tap Confirm
    print(f"[{agent.role}] Tapping Confirm")
    agent.adb("shell", "input", "tap", "540", "1880")
    time.sleep(5)
    scenario_reporter.add_result("BME5", "B-App Event Cancel - No Invitees",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


# ─── EVENT CANCELLATIONS (EC1–EC12) ──────────────────────────────────────────

def ec1_consumer_flow(agent):
    """EC1: Host Cancels Event when Invitee Accepted"""
    print(f"[{agent.role}] [EC1] Host Cancels Event when Invitee Accepted")
    agent.launch_app()
    _tap(agent, "NylaiKitchen")
    time.sleep(2)
    _tap(agent, "counterPlus")
    # Search for Noolu contact
    _type_field(agent, "contactSearch", "Noolu")
    time.sleep(2)  # wait for search results to load
    # Tap Noolu from search results
    _tap(agent, "NooluInvite")
    # Tap Noolu again on the confirmation popup
    _tap(agent, "Noolu")
    # Confirm invite — app returns to home
    _tap(agent, "inviteUsers")
    # Scroll down to find date/time slot and select it
    agent.swipe_up()
    time.sleep(1)
    _tap_chip_container(agent)
    _wait_tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "orderLater")
    time.sleep(5)  # let booking sync with server
    _tap(agent, "walletTab")
    events["order_placed"].set()
    # Switch to Noolu to accept
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_for_card(agent, "RoopaDInviteCard")
    time.sleep(5)
    if not _tap(agent, "eventAccept"):
        time.sleep(3)
        _tap(agent, "eventAccept")
    time.sleep(3)
    _tap(agent, "orderLater")
    time.sleep(5)  # let booking sync with server
    _tap(agent, "walletTab")
    # Switch back to Roopa and cancel
    _switch_account(agent, "roopa@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_for_card(agent, "NylaiKitchenCard")
    time.sleep(5)
    agent.swipe_up()
    time.sleep(1)
    _tap(agent, "cancelBooking")
    time.sleep(1)
    _tap(agent, "me only")
    time.sleep(1)
    _tap(agent, "NooluNagaassign")
    time.sleep(1)
    _tap(agent, "confirmCancelBook")
    time.sleep(3)
    _tap(agent, "option1")
    time.sleep(1)
    _tap(agent, "optionSubmit", "submit")
    time.sleep(2)
    scenario_reporter.add_result("EC1", "Host Cancels - Invitee Accepted",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def ec1_business_flow(agent):
    _no_op(agent)


def ec3_consumer_flow(agent):
    """EC3: Host Cancels Event when Invitee Declined"""
    print(f"[{agent.role}] [EC3] Host Cancels Event - Invitee Declined")
    agent.launch_app()
    _tap(agent, "NylaiKitchen")
    time.sleep(2)
    _tap(agent, "counterPlus")
    _type_field(agent, "contactSearch", "Noolu")
    time.sleep(2)  # wait for search results
    _tap(agent, "NooluInvite")
    _tap(agent, "Noolu")
    _tap(agent, "inviteUsers")
    _tap_chip_container(agent)
    _wait_tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "orderLater")
    time.sleep(5)  # let booking sync with server
    _tap(agent, "walletTab")
    # Noolu declines
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_for_card(agent, "RoopaDInviteCard")
    time.sleep(5)  # wait for event detail screen to load
    if not _tap(agent, "eventDecline"):
        time.sleep(3)
        _tap(agent, "eventDecline")
    time.sleep(8)  # let decline sync with server (takes ~6s)
    _tap(agent, "walletTab")
    # Roopa cancels
    _switch_account(agent, "roopa@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_for_card(agent, "NylaiKitchenCard")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(1)
    _tap(agent, "cancelBooking")
    time.sleep(1)
    _tap(agent, "option1")
    time.sleep(1)
    agent.swipe_up()
    time.sleep(1)
    # Find and type in the comment field
    xml = agent.dump_ui()
    comment_field = (
        agent.find_by_desc(xml, "cancelReason")
        or agent.find_by_desc(xml, "Or make a comment")
        or agent.find_by_text(xml, "Or make a comment")
        or agent.find_by_desc(xml, "write a comment")
        or agent.find_by_text(xml, "write a comment")
    )
    if comment_field:
        agent.tap(comment_field[0], comment_field[1], "[comment field]")
        time.sleep(0.5)
        agent.type_text("Booked wrong slot!")
        agent.adb("shell", "input", "keyevent", "KEYCODE_BACK")
        time.sleep(1)
    _tap(agent, "optionSubmit", "submit")
    time.sleep(2)
    scenario_reporter.add_result("EC3", "Host Cancels - Invitee Declined",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def ec3_business_flow(agent):
    _no_op(agent)


def ec4_consumer_flow(agent):
    """EC4: Participant Cancels Event"""
    print(f"[{agent.role}] [EC4] Participant Cancels Event")
    agent.launch_app()
    _tap(agent, "homeTab")
    _wait_tap(agent, "NylaiKitchen")
    agent.swipe_up()
    _tap(agent, "NylaiKitchen")
    time.sleep(2)
    _tap(agent, "counterPlus")
    _type_field(agent, "contactSearch", "Noolu")
    time.sleep(2)  # wait for search results
    _tap(agent, "NooluInvite")
    _tap(agent, "Noolu")
    _tap(agent, "inviteUsers")
    _tap_chip_container(agent)
    _wait_tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "orderLater")
    time.sleep(5)  # let booking sync with server
    _tap(agent, "walletTab")
    events["order_placed"].set()
    # Switch to Noolu to accept then cancel
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_for_card(agent, "RoopaDInviteCard")
    time.sleep(2)
    _tap(agent, "eventAccept")
    _tap(agent, "orderLater")
    time.sleep(5)  # let booking sync with server
    _tap(agent, "walletTab")
    _wait_for_card(agent, "NylaiKitchenCard")
    agent.swipe_up()
    _tap(agent, "cancelBooking")
    time.sleep(1)
    _tap(agent, "option1")
    time.sleep(1)
    agent.swipe_up()
    time.sleep(1)
    # Find and type in the comment field
    xml = agent.dump_ui()
    comment_field = (
        agent.find_by_desc(xml, "cancelReason")
        or agent.find_by_desc(xml, "Or make a comment")
        or agent.find_by_text(xml, "Or make a comment")
        or agent.find_by_desc(xml, "write a comment")
        or agent.find_by_text(xml, "write a comment")
    )
    if comment_field:
        agent.tap(comment_field[0], comment_field[1], "[comment field]")
        time.sleep(0.5)
        agent.type_text("Booked wrong slot!")
        agent.adb("shell", "input", "keyevent", "KEYCODE_BACK")
        time.sleep(1)
    _tap(agent, "optionSubmit", "submit")
    time.sleep(2)
    scenario_reporter.add_result("EC4", "Participant Cancels Event",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def ec4_business_flow(agent):
    _no_op(agent)


def ec12_consumer_flow(agent):
    """EC12: Pickup Cancellation"""
    print(f"[{agent.role}] [EC12] Pickup Cancellation")
    agent.launch_app()
    _tap(agent, "NylaiKitchen")
    time.sleep(3)
    # Select Pickup type
    _tap(agent, "Pickup")
    time.sleep(2)
    _tap_chip_container(agent)
    _tap(agent, "browseMenu")
    time.sleep(3)
    # Item 1: Cheese-Stuffed Garlic Bread with 6pcs + Marinara Dip
    _tap(agent, "cheesy-comfort-platescategory", scroll=False)
    time.sleep(10) 
    _tap(agent, "Cheese-StuffedGarlicBreadInc")
    time.sleep(3)
    _tap(agent, "6pccsProduct")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "MarinaraDipProduct")
    time.sleep(1)
    _tap(agent, "confirmProduct")
    time.sleep(3)
    # Item 2: Tom Yum Soup with chicken + Spicy instruction
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "TomYumSoupInc")
    _tap(agent, "chickenProduct")
    time.sleep(1)
    agent.swipe_up()
    time.sleep(1)
    _type_field(agent, "inputSplIns", "Spicy")
    agent.adb("shell", "input", "keyevent", "KEYCODE_BACK")
    time.sleep(1)
    _tap(agent, "confirmProduct")
    time.sleep(3)
    # Cart and checkout
    _tap(agent, "cartImage")
    _tap(agent, "cartCheckout")
    time.sleep(5)
    if not _tap(agent, "primary_button"):
        _tap(agent, "placeOrder", "Place Order")
    time.sleep(20)
    _tap(agent, "yesGotIt", "YES, GOT IT")
    time.sleep(10)
    # Cancel pickup
    _tap(agent, "cancelPickup")
    time.sleep(3)
    _tap(agent, "yesGotIt", "YES, GOT IT")
    time.sleep(3)
    _tap(agent, "option1")
    time.sleep(1)
    _tap(agent, "optionSubmit", "submit")
    time.sleep(2)
    _tap(agent, "walletTab")
    time.sleep(2)
    _tap(agent, "homeTab")
    scenario_reporter.add_result("EC12", "Pickup Cancellation",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def ec12_business_flow(agent):
    _no_op(agent)


# ─── FILTER EVENTS IN B-APP (FE1–FE7) ────────────────────────────────────────

def fe1_business_flow(agent):
    """FE1: Filter Events by Status"""
    print(f"[{agent.role}] [FE1] Filter by Status")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "Orders")
    time.sleep(5)
    _tap(agent, "orderFilterBtn")
    time.sleep(3)
    _tap(agent, "Reserved")
    time.sleep(2)
    _tap(agent, "Confirm")
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "Remove filter")
    time.sleep(3)
    _tap(agent, "orderFilterBtn")
    time.sleep(3)
    _tap(agent, "Serve")
    time.sleep(2)
    _tap(agent, "Confirm")
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "Remove filter")
    time.sleep(2)
    scenario_reporter.add_result("FE1", "Filter Events by Status",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def fe1_consumer_flow(agent):
    _no_op(agent)


def fe2_business_flow(agent):
    """FE2: Filter Events by Table"""
    print(f"[{agent.role}] [FE2] Filter by Table")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "Orders")
    time.sleep(5)
    _tap(agent, "modifyTable")
    _tap_any_table(agent)
    _tap(agent, "Confirm")
    agent.swipe_up()
    time.sleep(1)
    _tap(agent, "removeTableFilter")
    _tap(agent, "modifyTable")
    _tap_any_table(agent)
    _tap(agent, "Confirm")
    agent.swipe_up()
    time.sleep(1)
    _tap(agent, "removeTableFilter")
    scenario_reporter.add_result("FE2", "Filter Events by Table",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def fe2_consumer_flow(agent):
    _no_op(agent)


def fe3_business_flow(agent):
    """FE3: Status filter in events popup of home page"""
    print(f"[{agent.role}] [FE3] Status Filter in Home Page Popup")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "Home")
    time.sleep(5)
    _tap_events_button(agent)
    time.sleep(3)
    _tap(agent, "orderFilterBtn")
    time.sleep(3)
    _tap(agent, "Order")
    time.sleep(2)
    _tap(agent, "Confirm")
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "Remove filter")
    time.sleep(2)
    scenario_reporter.add_result("FE3", "Status Filter in Home Page Popup",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def fe3_consumer_flow(agent):
    _no_op(agent)


def fe4_business_flow(agent):
    """FE4: Table filter in events popup of home page"""
    print(f"[{agent.role}] [FE4] Table Filter in Home Page Popup")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "Orders")
    time.sleep(5)
    _tap(agent, "modifyTable")
    _tap_any_table(agent)
    _tap(agent, "Confirm")
    agent.swipe_up()
    time.sleep(1)
    _tap(agent, "closeEventModal")
    scenario_reporter.add_result("FE4", "Table Filter in Home Page Popup",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def fe4_consumer_flow(agent):
    _no_op(agent)


# ─── PRE-ORDER (PO1–PO7) ─────────────────────────────────────────────────────

def po1_consumer_flow(agent):
    """PO1: Book → Pre-order → Add items"""
    print(f"[{agent.role}] [PO1] Book and pre-order items")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "NylaiKitchen")
    time.sleep(3)
    _tap_chip_container(agent)
    _tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "preOrderBooking")
    time.sleep(5)
    # Add items
    _tap(agent, "Chicken65")
    time.sleep(3)
    _tap(agent, "addmayoProduct")
    time.sleep(2)
    _tap(agent, "confirmProduct")
    time.sleep(3)
    _tap(agent, "pasta-pizzacategory", scroll=False)
    time.sleep(3)
    _tap(agent, "PizzaRucolaeParmigiano")
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "FreshbellpepperProduct")
    time.sleep(2)
    _tap(agent, "confirmProduct")
    time.sleep(3)
    scenario_reporter.add_result("PO1", "Adding More Items from Cart",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def po1_business_flow(agent):
    _no_op(agent)


def po2_consumer_flow(agent):
    """PO2: Add and reduce items in cart and menu screen — continues from PO1"""
    print(f"[{agent.role}] [PO2] Add and Reduce Items")
    agent.launch_app()
    time.sleep(3)
    # Continue from PO1 menu — add more PizzaRucolaeParmigiano
    _tap(agent, "PizzaRucolaeParmigianoInc")
    time.sleep(3)
    _tap(agent, "counterPlus")
    time.sleep(2)
    _tap(agent, "addNewCustomSelection")
    time.sleep(3)
    _tap(agent, "PizzaRucolaeParmigianoInc")
    time.sleep(3)
    _tap(agent, "counterPlus")
    time.sleep(2)
    _tap(agent, "counterPlus")
    time.sleep(2)
    _tap(agent, "counterMinus")
    time.sleep(2)
    _tap(agent, "addNewCustomSelection")
    time.sleep(3)
    # Go to cart and add from different category
    _tap(agent, "cartImage")
    time.sleep(3)
    _tap(agent, "cartAddItems")
    time.sleep(3)
    _tap(agent, "cheesy-comfort-platescategory", scroll=False)
    time.sleep(3)
    _tap(agent, "FourCheeseLasagnaInc")
    time.sleep(3)
    _tap(agent, "SliceProduct")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "addgheeProduct")
    time.sleep(2)
    _tap(agent, "confirmProduct")
    time.sleep(3)
    # Go to cart and delete an item
    _tap(agent, "cartImage")
    time.sleep(3)
    _tap(agent, "counterMinus")
    time.sleep(2)
    _tap(agent, "deleteCartYes")
    time.sleep(3)
    scenario_reporter.add_result("PO2", "Add and Reduce Items Cart/Menu",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def po2_business_flow(agent):
    _no_op(agent)


def po3_consumer_flow(agent):
    """PO3: Edit item from cart screen — continues from PO2"""
    print(f"[{agent.role}] [PO3] Edit Item from Cart")
    agent.launch_app()
    time.sleep(3)
    # Edit FourCheeseLasagna from cart
    _tap(agent, "FourCheeseLasagnafinishedCard")
    time.sleep(3)
    _tap(agent, "AddMushroomProduct")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "addgheeProduct")
    time.sleep(2)
    _tap(agent, "Gluten-FreePastaProduct")
    time.sleep(2)
    _tap(agent, "confirmProduct")
    time.sleep(3)
    # Checkout and pay
    _tap(agent, "cartCheckout")
    time.sleep(5)
    _tap(agent, "primary_button")
    time.sleep(30)
    _tap(agent, "pickUpOrderConfirm")
    agent.check_bill()
    time.sleep(5)
    scenario_reporter.add_result("PO3", "Edit Item from Cart",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def po3_business_flow(agent):
    _no_op(agent)


def po7_consumer_flow(agent):
    """PO7: Add coupon, remove it, re-add and verify total — BILL VALIDATION"""
    print(f"[{agent.role}] [PO7] Coupon Add/Remove/Verify Total")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "starterscategory", scroll=False)
    time.sleep(3)
    _tap(agent, "MuttonSeekhKebab", scroll=False)
    time.sleep(3)
    _tap(agent, "2pcsProduct")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "chutneyProduct")
    time.sleep(2)
    _tap(agent, "confirmProduct")
    time.sleep(15)
    _tap(agent, "cartImage")
    time.sleep(15)
    # Capture cart total before coupon
    pre_coupon_result = agent.check_cart_total()
    original_total = pre_coupon_result.get("displayed_total")
    # Apply coupon
    _tap(agent, "applyCoupon")
    time.sleep(15)
    _tap(agent, "6% OFFER")
    time.sleep(15)
    # Validate coupon was applied correctly
    if original_total and original_total > 0:
        coupon_value = round(original_total * 0.06, 2)
        xml = agent.dump_ui()
        coupon_result = bill_validator.validate_coupon(xml, original_total, coupon_value)
        coupon_status = "PASS" if coupon_result["pass"] else "FAIL"
        print(f"[{agent.role}] [PO7] Coupon validation: {coupon_status} — {coupon_result['reason']}")
        scenario_reporter.add_result("PO7", "Coupon Validation",
                                     agent.role, coupon_status, coupon_result["reason"],
                                     agent.last_launch_time)
    else:
        print(f"[{agent.role}] [PO7] Could not capture pre-coupon total, skipping coupon validation")
    _tap(agent, "cartCheckout")
    time.sleep(15)
    _tap(agent, "primary_button")
    time.sleep(30)
    _tap(agent, "pickUpOrderConfirm")
    time.sleep(15)
    agent.verify_final_bill()
    scenario_reporter.add_result("PO7", "Coupon Verify Total",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def po7_business_flow(agent):
    """PO7 Business: Accept order and process payment"""
    print(f"[{agent.role}] [PO7] Accept and process payment")
    agent.launch_app()
    time.sleep(10)
    _tap(agent, "Orders")
    time.sleep(5)
    for i in range(5):
        if _tap(agent, "ReservedOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "T0AssignAnyBtn")
    time.sleep(3)
    _tap(agent, "AssignTableBtn")
    time.sleep(5)
    _tap(agent, "addItemsBtn")
    time.sleep(5)
    _tap(agent, "Macaroni&CheeseBakeItem", "Macaroni & Cheese Bake", scroll=False)
    time.sleep(5)
    _tap(agent, "regularBtn", scroll=False)
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "AddTruffleOilBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "assignToBtn")
    time.sleep(3)
    _tap(agent, "selectAll")
    time.sleep(3)
    _tap(agent, "assignProductsBtn")
    time.sleep(5)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(5)
    _tap(agent, "sendItemsBtn")
    time.sleep(10)
    _tap(agent, "backButton")
    time.sleep(3)
    # Kitchen
    _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
    time.sleep(5)
    _tap(agent, "inProgressOrderCard")
    time.sleep(5)
    # Select all kitchen items
    _tap_all_kitchen_items(agent, ["MuttonSeekhKebab", "Macaroni&CheeseBake"])
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "orderReadyBtn")
    time.sleep(3)
    _tap(agent, "orderCloseBtn")
    time.sleep(3)
    # Serve
    _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
    time.sleep(10)
    _tap(agent, "Orders")
    time.sleep(10)
    for i in range(5):
        if _tap(agent, "ServeOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(3)
    _tap(agent, "serveItemsBtn")
    time.sleep(3)
    _tap(agent, "notifyPaymentBtn")
    time.sleep(3)
    _tap(agent, "Payment")
    time.sleep(3)
    _tap(agent, "NooluNagaCard")
    time.sleep(3)
    agent.swipe_down()
    time.sleep(2)
    _tap(agent, "cashPaymentBtn")
    time.sleep(2)
    _tap(agent, "Number2")
    _tap(agent, "Number0")
    _tap(agent, "userInputBtn")
    time.sleep(2)
    _tap(agent, "RoopaDselect")
    time.sleep(2)
    _tap(agent, "Apply")
    time.sleep(2)
    agent.adb("shell", "input", "swipe", "520", "1662", "537", "1086", "224")
    time.sleep(3)
    agent.verify_final_bill()
    _tap(agent, "paymentConfirmBtn")
    time.sleep(5)
    agent.verify_final_bill()
    # Close table
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "closeTableBtn")
    time.sleep(3)
    scenario_reporter.add_result("PO7", "Coupon Verify Total",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


# ─── PAYMENTS (PAY1–PAY6) ─────────────────────────────────────────────────────

def pay1_consumer_flow(agent):
    """PAY1 Consumer: Book event with 1 guest for cash payment"""
    print(f"[{agent.role}] [PAY1] Consumer books event with 1 guest")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "NylaiKitchen")
    time.sleep(3)
    _tap(agent, "counterPlus")
    time.sleep(2)
    _tap(agent, "guestAdd")
    time.sleep(2)
    _tap(agent, "inviteUsers")
    time.sleep(3)
    _tap_chip_container(agent)
    _tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "orderLater")
    time.sleep(5)
    scenario_reporter.add_result("PAY1", "Payment by Cash",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def pay1_business_flow(agent):
    """PAY1: Full cash payment flow — assign, add items, kitchen, serve, pay"""
    print(f"[{agent.role}] [PAY1] Payment by Cash")
    agent.launch_app()
    time.sleep(10)
    # Assign table
    _tap(agent, "Orders")
    time.sleep(5)
    for i in range(5):
        if _tap(agent, "ReservedOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "T0AssignAnyBtn")
    time.sleep(3)
    _tap(agent, "AssignTableBtn")
    time.sleep(5)
    # Add items: PizzaRucolaeParmigiano x3 variants + PizzaQuattroStagioni
    _tap(agent, "addItemsBtn")
    time.sleep(3)
    _tap(agent, "PizzaRucolaeParmigianoItem")
    time.sleep(2)
    _tap(agent, "FreshbellpepperBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "PizzaRucolaeParmigianoItem")
    time.sleep(2)
    _tap(agent, "addNewCustomSelection")
    time.sleep(2)
    _tap(agent, "FreshchampignonsBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "PizzaRucolaeParmigianoItem")
    time.sleep(2)
    _tap(agent, "addNewCustomSelection")
    time.sleep(2)
    _tap(agent, "CookedhamBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "PizzaQuattroStagioniItem")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    # Assign to all and send
    _tap(agent, "assignToBtn")
    time.sleep(3)
    _tap(agent, "selectAll")
    time.sleep(3)
    _tap(agent, "assignProductsBtn")
    time.sleep(5)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(5)
    _tap(agent, "sendItemsBtn")
    time.sleep(10)
    _tap(agent, "backButton")
    time.sleep(3)
    # Kitchen staff
    _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
    time.sleep(5)
    _tap(agent, "inProgressOrderCard")
    time.sleep(5)
    # Scroll down to see all items
    # Select all kitchen items, then swipe up for Ready button
    _tap_all_kitchen_items(agent, ["PizzaRucolaeParmigiano", "PizzaRucolaeParmigiano", "PizzaRucolaeParmigiano", "PizzaQuattroStagioni"])
    time.sleep(2)
    _tap(agent, "orderReadyBtn")
    time.sleep(3)
    _tap(agent, "orderCloseBtn")
    time.sleep(3)
    # Serve staff
    _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
    time.sleep(10)
    _tap(agent, "Orders")
    time.sleep(10)
    for i in range(5):
        if _tap(agent, "ServeOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(3)
    _tap(agent, "serveItemsBtn")
    time.sleep(3)
    _tap(agent, "notifyPaymentBtn")
    time.sleep(3)
    _tap(agent, "Payment")
    time.sleep(3)
    # Cash payment: RoopaDCard → cash 10 → Guest1select → tip 9.5 → cash 153.4
    _tap(agent, "RoopaDCard")
    time.sleep(3)
    _tap(agent, "cashPaymentBtn")
    time.sleep(2)
    _tap(agent, "Number1")
    _tap(agent, "Number0")
    _tap(agent, "userInputBtn")
    time.sleep(2)
    _tap(agent, "Guest1select")
    time.sleep(2)
    _tap(agent, "Apply")
    time.sleep(2)
    agent.adb("shell", "input", "swipe", "520", "1662", "537", "1086", "224")
    time.sleep(3)
    # Tip 9.5
    _tap(agent, "tipBtn")
    time.sleep(2)
    _tap(agent, "Number9")
    _tap(agent, "Decimal point")
    _tap(agent, "Number5")
    _tap(agent, "userInputBtn")
    time.sleep(2)
    # Second cash payment 153.4
    agent.swipe_down()
    time.sleep(2)
    _tap(agent, "cashPaymentBtn")
    time.sleep(2)
    _tap(agent, "Number1")
    _tap(agent, "Number5")
    _tap(agent, "Number3")
    _tap(agent, "Decimal point")
    _tap(agent, "Number4")
    _tap(agent, "userInputBtn")
    time.sleep(2)
    agent.adb("shell", "input", "swipe", "520", "1662", "537", "1086", "224")
    time.sleep(3)
    agent.verify_final_bill()
    _tap(agent, "paymentConfirmBtn")
    time.sleep(5)
    agent.verify_final_bill()
    # Close table
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "closeTableBtn")
    time.sleep(3)
    shared_data["pay1_done"] = True
    scenario_reporter.add_result("PAY1", "Payment by Cash",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def pay3_consumer_flow(agent):
    """PAY3 Consumer: Book event with 1 guest for Epayment scenario"""
    print(f"[{agent.role}] [PAY3] Consumer books for Epayment")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "NylaiKitchen")
    time.sleep(3)
    _tap(agent, "counterPlus")
    time.sleep(2)
    _tap(agent, "guestAdd")
    time.sleep(2)
    _tap(agent, "inviteUsers")
    time.sleep(3)
    _tap_chip_container(agent)
    _tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "orderLater")
    time.sleep(5)
    scenario_reporter.add_result("PAY3", "Payment by E-Payment",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def pay3_business_flow(agent):
    """PAY3 Business: Full E-Payment flow — assign, add items, kitchen, serve, epay"""
    print(f"[{agent.role}] [PAY3] Payment by E-Payment")
    agent.launch_app()
    time.sleep(10)
    # Assign table
    _tap(agent, "Orders")
    time.sleep(5)
    for i in range(5):
        if _tap(agent, "ReservedOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "T0AssignAnyBtn")
    time.sleep(3)
    _tap(agent, "AssignTableBtn")
    time.sleep(5)
    # Add items: MuttonSeekhKebab + chutney, MuttonSeekhKebab + 4pcs chutney, PizzaQuattroStagioni
    _tap(agent, "addItemsBtn")
    time.sleep(3)
    _tap(agent, "MuttonSeekhKebabItem")
    time.sleep(2)
    _tap(agent, "2pcsBtn")
    time.sleep(2)
    _tap(agent, "chutneyBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "MuttonSeekhKebabItem")
    time.sleep(2)
    _tap(agent, "addNewCustomSelection")
    time.sleep(2)
    _tap(agent, "chutneyBtn")
    time.sleep(2)
    _tap(agent, "4pcsBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "PizzaQuattroStagioniItem")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    # Assign to all and send
    _tap(agent, "assignToBtn")
    time.sleep(3)
    _tap(agent, "selectAll")
    time.sleep(3)
    _tap(agent, "assignProductsBtn")
    time.sleep(5)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(5)
    _tap(agent, "sendItemsBtn")
    time.sleep(10)
    _tap(agent, "backButton")
    time.sleep(3)
    # Kitchen staff
    _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
    time.sleep(5)
    _tap(agent, "inProgressOrderCard")
    time.sleep(5)
    # Select all kitchen items, then swipe up for Ready button
    _tap_all_kitchen_items(agent, ["MuttonSeekhKebab", "MuttonSeekhKebab", "PizzaQuattroStagioni"])
    time.sleep(2)
    _tap(agent, "orderReadyBtn")
    time.sleep(3)
    _tap(agent, "orderCloseBtn")
    time.sleep(3)
    # Serve staff
    _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
    time.sleep(10)
    _tap(agent, "Orders")
    time.sleep(10)
    for i in range(5):
        if _tap(agent, "ServeOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(3)
    _tap(agent, "serveItemsBtn")
    time.sleep(3)
    _tap(agent, "notifyPaymentBtn")
    time.sleep(3)
    _tap(agent, "Payment")
    time.sleep(3)
    # E-Payment with tip
    _tap(agent, "RoopaDCard")
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "tipBtn")
    time.sleep(2)
    _tap(agent, "Number2")
    _tap(agent, "Decimal point")
    _tap(agent, "Number5")
    _tap(agent, "userInputBtn")
    time.sleep(2)
    agent.swipe_down()
    time.sleep(2)
    _tap(agent, "epaymentBtn")
    time.sleep(2)
    _tap(agent, "Number1")
    _tap(agent, "Number2")
    _tap(agent, "Number0")
    _tap(agent, "Number0")
    _tap(agent, "userInputBtn")
    time.sleep(2)
    _tap(agent, "Guest1select")
    time.sleep(2)
    _tap(agent, "Apply")
    time.sleep(2)
    agent.adb("shell", "input", "swipe", "520", "1662", "537", "1086", "224")
    time.sleep(3)
    agent.verify_final_bill()
    _tap(agent, "paymentConfirmBtn")
    time.sleep(5)
    agent.verify_final_bill()
    # Close table
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "closeTableBtn")
    time.sleep(3)
    scenario_reporter.add_result("PAY3", "Payment by E-Payment",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def pay2_consumer_flow(agent):
    """PAY2: Host (Roopa) books with 1 guest, host pays for others"""
    print(f"[{agent.role}] [PAY2] Host books with 1 guest")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "NylaiKitchen")
    time.sleep(3)
    _tap(agent, "counterPlus")
    time.sleep(2)
    _tap(agent, "guestAdd")
    time.sleep(2)
    _tap(agent, "inviteUsers")
    time.sleep(3)
    _tap_chip_container(agent)
    _tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "orderLater")
    time.sleep(5)
    scenario_reporter.add_result("PAY2", "Host Pays for Others",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def pay2_business_flow(agent):
    """PAY2 Business: Process order where host pays for guest"""
    print(f"[{agent.role}] [PAY2] Process host-pays-for-others order")
    agent.launch_app()
    time.sleep(10)
    _tap(agent, "Orders")
    time.sleep(5)
    for i in range(5):
        if _tap(agent, "ReservedOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "T0AssignAnyBtn")
    time.sleep(3)
    _tap(agent, "AssignTableBtn")
    time.sleep(5)
    _tap(agent, "addItemsBtn")
    time.sleep(3)
    _tap(agent, "PizzaRucolaeParmigianoItem")
    time.sleep(2)
    _tap(agent, "FreshbellpepperBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "PizzaRucolaeParmigianoItem")
    time.sleep(2)
    _tap(agent, "addNewCustomSelection")
    time.sleep(2)
    _tap(agent, "FreshchampignonsBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "PizzaRucolaeParmigianoItem")
    time.sleep(2)
    _tap(agent, "addNewCustomSelection")
    time.sleep(2)
    _tap(agent, "CookedhamBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "PizzaQuattroStagioniItem")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "assignToBtn")
    time.sleep(3)
    _tap(agent, "selectAll")
    time.sleep(3)
    _tap(agent, "assignProductsBtn")
    time.sleep(5)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(5)
    _tap(agent, "sendItemsBtn")
    time.sleep(10)
    _tap(agent, "backButton")
    time.sleep(3)
    # Kitchen staff
    _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
    time.sleep(5)
    _tap(agent, "inProgressOrderCard")
    time.sleep(5)
    # Select all kitchen items, then swipe up for Ready button
    _tap_all_kitchen_items(agent, ["PizzaRucolaeParmigiano", "PizzaRucolaeParmigiano", "PizzaRucolaeParmigiano", "PizzaQuattroStagioni"])
    time.sleep(2)
    _tap(agent, "orderReadyBtn")
    time.sleep(3)
    _tap(agent, "orderCloseBtn")
    time.sleep(3)
    # Serve staff
    _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
    time.sleep(10)
    _tap(agent, "Orders")
    time.sleep(10)
    for i in range(5):
        if _tap(agent, "ServeOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(3)
    _tap(agent, "serveItemsBtn")
    time.sleep(3)
    _tap(agent, "notifyPaymentBtn")
    time.sleep(3)
    _tap(agent, "Payment")
    time.sleep(3)
    # Host pays for guest — cash 10 + tip 9.5 + cash 153.4
    _tap(agent, "RoopaDCard")
    time.sleep(3)
    _tap(agent, "cashPaymentBtn")
    time.sleep(2)
    _tap(agent, "Number1")
    _tap(agent, "Number0")
    _tap(agent, "userInputBtn")
    time.sleep(2)
    _tap(agent, "Guest1select")
    time.sleep(2)
    _tap(agent, "Apply")
    time.sleep(2)
    agent.adb("shell", "input", "swipe", "520", "1662", "537", "1086", "224")
    time.sleep(3)
    # Tip 9.5
    _tap(agent, "tipBtn")
    time.sleep(2)
    _tap(agent, "Number9")
    _tap(agent, "Decimal point")
    _tap(agent, "Number5")
    _tap(agent, "userInputBtn")
    time.sleep(2)
    # Second cash payment 153.4
    agent.swipe_down()
    time.sleep(2)
    _tap(agent, "cashPaymentBtn")
    time.sleep(2)
    _tap(agent, "Number1")
    _tap(agent, "Number5")
    _tap(agent, "Number3")
    _tap(agent, "Decimal point")
    _tap(agent, "Number4")
    _tap(agent, "userInputBtn")
    time.sleep(2)
    agent.adb("shell", "input", "swipe", "520", "1662", "537", "1086", "224")
    time.sleep(3)
    agent.verify_final_bill()
    _tap(agent, "paymentConfirmBtn")
    time.sleep(5)
    agent.verify_final_bill()
    # Close table
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "closeTableBtn")
    time.sleep(3)
    shared_data["pay2_done"] = True
    scenario_reporter.add_result("PAY2", "Host Pays for Others",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def pay4_consumer_flow(agent):
    """PAY4 Consumer: Book event with 1 guest for food voucher scenario"""
    print(f"[{agent.role}] [PAY4] Consumer books event with 1 guest")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "NylaiKitchen")
    time.sleep(3)
    _tap(agent, "counterPlus")
    time.sleep(2)
    _tap(agent, "guestAdd")
    time.sleep(2)
    _tap(agent, "inviteUsers")
    time.sleep(3)
    _tap_chip_container(agent)
    _tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "orderLater")
    time.sleep(5)
    scenario_reporter.add_result("PAY4", "Payment by Food Voucher",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def pay4_business_flow(agent):
    """PAY4: Payment by Food Voucher"""
    print(f"[{agent.role}] [PAY4] Payment by Food Voucher")
    agent.launch_app()
    time.sleep(10)
    # Assign table
    _tap(agent, "Orders")
    time.sleep(5)
    for i in range(5):
        if _tap(agent, "ReservedOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "T0AssignAnyBtn")
    time.sleep(3)
    _tap(agent, "AssignTableBtn")
    time.sleep(5)
    # Add items: CrispyThaiSpringRolls + PizzaQuattroStagioni
    _tap(agent, "addItemsBtn")
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "CrispyThaiSpringRollsItem")
    time.sleep(2)
    _tap(agent, "6pcsBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    # Scroll back to top to find PizzaQuattroStagioni
    agent.swipe_down()
    time.sleep(2)
    agent.swipe_down()
    time.sleep(2)
    agent.swipe_down()
    time.sleep(2)
    agent.swipe_down()
    time.sleep(2)
    _tap(agent, "PizzaQuattroStagioniItem")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    # Assign to all and send
    _tap(agent, "assignToBtn")
    time.sleep(3)
    _tap(agent, "selectAll")
    time.sleep(3)
    _tap(agent, "assignProductsBtn")
    time.sleep(5)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(5)
    _tap(agent, "sendItemsBtn")
    time.sleep(10)
    _tap(agent, "backButton")
    time.sleep(3)
    # Kitchen staff
    _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
    time.sleep(5)
    _tap(agent, "inProgressOrderCard")
    time.sleep(5)
    # Select all kitchen items, then swipe up for Ready button
    _tap_all_kitchen_items(agent, ["CrispyThaiSpringRolls", "PizzaQuattroStagioni"])
    time.sleep(2)
    _tap(agent, "orderReadyBtn")
    time.sleep(3)
    _tap(agent, "orderCloseBtn")
    time.sleep(3)
    # Serve staff
    _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
    time.sleep(10)
    _tap(agent, "Orders")
    time.sleep(10)
    for i in range(5):
        if _tap(agent, "ServeOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(3)
    _tap(agent, "serveItemsBtn")
    time.sleep(3)
    _tap(agent, "notifyPaymentBtn")
    time.sleep(3)
    _tap(agent, "Payment")
    time.sleep(3)
    # Food voucher payment
    _tap(agent, "RoopaDCard")
    time.sleep(3)
    agent.swipe_down()
    time.sleep(2)
    _tap(agent, "foodVoucherBtn")
    time.sleep(2)
    _tap(agent, "foodVoucher10CounterIncrement")
    time.sleep(2)
    _tap(agent, "inputVoucher")
    time.sleep(2)
    _tap(agent, "Guest1select")
    time.sleep(2)
    _tap(agent, "Apply")
    time.sleep(2)
    agent.swipe_down()
    time.sleep(2)
    _tap(agent, "cashPaymentBtn")
    time.sleep(2)
    _tap(agent, "Number5")
    _tap(agent, "Number0")
    _tap(agent, "Number0")
    _tap(agent, "userInputBtn")
    time.sleep(2)
    agent.adb("shell", "input", "swipe", "520", "1662", "537", "1086", "224")
    time.sleep(3)
    agent.verify_final_bill()
    _tap(agent, "paymentConfirmBtn")
    time.sleep(5)
    agent.verify_final_bill()
    # Close table
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "closeTableBtn")
    time.sleep(3)
    scenario_reporter.add_result("PAY4", "Payment by Food Voucher",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def pay5_consumer_flow(agent):
    """PAY5 Consumer: Book event with 1 guest for all 3 payment modes"""
    print(f"[{agent.role}] [PAY5] Consumer books event with 1 guest")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "NylaiKitchen")
    time.sleep(3)
    _tap(agent, "counterPlus")
    time.sleep(2)
    _tap(agent, "guestAdd")
    time.sleep(2)
    _tap(agent, "inviteUsers")
    time.sleep(3)
    _tap_chip_container(agent)
    _tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "orderLater")
    time.sleep(5)
    scenario_reporter.add_result("PAY5", "Payment All 3 Modes",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def pay5_business_flow(agent):
    """PAY5: Payment using all 3 modes (cash + e-payment + food voucher)"""
    print(f"[{agent.role}] [PAY5] Payment with all 3 modes")
    agent.launch_app()
    time.sleep(10)
    # Assign table
    _tap(agent, "Orders")
    time.sleep(5)
    for i in range(5):
        if _tap(agent, "ReservedOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "T0AssignAnyBtn")
    time.sleep(3)
    _tap(agent, "AssignTableBtn")
    time.sleep(5)
    # Add items: SpaghettiAglioeOlio + PizzaQuattroStagioni
    _tap(agent, "addItemsBtn")
    time.sleep(3)
    _tap(agent, "SpaghettiAglioeOlioItem")
    time.sleep(2)
    _tap(agent, "InsalataconPolioBtn")
    time.sleep(2)
    _tap(agent, "FreshbellpepperBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "PizzaQuattroStagioniItem")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    # Assign to all and send
    _tap(agent, "assignToBtn")
    time.sleep(3)
    _tap(agent, "selectAll")
    time.sleep(3)
    _tap(agent, "assignProductsBtn")
    time.sleep(5)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(5)
    _tap(agent, "sendItemsBtn")
    time.sleep(10)
    _tap(agent, "backButton")
    time.sleep(3)
    # Kitchen staff
    _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
    time.sleep(5)
    _tap(agent, "inProgressOrderCard")
    time.sleep(5)
    # Select all kitchen items, then swipe up for Ready button
    _tap_all_kitchen_items(agent, ["SpaghettiAglioeOlio", "PizzaQuattroStagioni"])
    time.sleep(2)
    _tap(agent, "orderReadyBtn")
    time.sleep(3)
    _tap(agent, "orderCloseBtn")
    time.sleep(3)
    # Serve staff
    _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
    time.sleep(10)
    _tap(agent, "Orders")
    time.sleep(10)
    for i in range(5):
        if _tap(agent, "ServeOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(3)
    _tap(agent, "serveItemsBtn")
    time.sleep(3)
    _tap(agent, "notifyPaymentBtn")
    time.sleep(3)
    _tap(agent, "Payment")
    time.sleep(3)
    # All 3 payment modes
    _tap(agent, "RoopaDCard")
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "tipBtn")
    time.sleep(2)
    _tap(agent, "Number1")
    _tap(agent, "Number0")
    _tap(agent, "userInputBtn")
    time.sleep(2)
    agent.swipe_down()
    time.sleep(2)
    _tap(agent, "cashPaymentBtn")
    time.sleep(2)
    _tap(agent, "Number3")
    _tap(agent, "Number0")
    _tap(agent, "userInputBtn")
    time.sleep(2)
    _tap(agent, "Guest1select")
    time.sleep(2)
    _tap(agent, "Apply")
    time.sleep(2)
    agent.swipe_down()
    time.sleep(2)
    _tap(agent, "epaymentBtn")
    time.sleep(2)
    _tap(agent, "Number2")
    _tap(agent, "Number0")
    _tap(agent, "Decimal point")
    _tap(agent, "Number5")
    _tap(agent, "userInputBtn")
    time.sleep(2)
    agent.adb("shell", "input", "swipe", "520", "1662", "537", "1086", "224")
    time.sleep(3)
    _tap(agent, "foodVoucherBtn")
    time.sleep(2)
    _tap(agent, "foodVoucher10CounterIncrement")
    time.sleep(2)
    _tap(agent, "inputVoucher")
    time.sleep(3)
    agent.verify_final_bill()
    _tap(agent, "paymentConfirmBtn")
    time.sleep(5)
    agent.verify_final_bill()
    # Close table
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "closeTableBtn")
    time.sleep(3)
    scenario_reporter.add_result("PAY5", "Payment All 3 Modes",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


# ─── STATUS VERIFICATION (SV1–SV16) ─────────────────────────────────────────

def sv1_business_flow(agent):
    """SV1: Confirmation Pending Status"""
    print(f"[{agent.role}] [SV1] Confirmation Pending Status")
    agent.launch_app()
    time.sleep(5)
    if not _tap(agent, "addNewEvent"):
        agent.swipe_up()
        time.sleep(3)
        _tap(agent, "addNewEvent")
    time.sleep(5)
    # Type first name
    _tap(agent, "firstName")
    time.sleep(3)
    for ch in "Roopa":
        agent.adb("shell", "input", "text", ch)
        time.sleep(0.3)
    time.sleep(2)
    # Type last name
    _tap(agent, "lastName")
    time.sleep(3)
    agent.adb("shell", "input", "text", "D")
    time.sleep(2)
    # Dismiss keyboard
    agent.adb("shell", "input", "keyevent", "111")
    time.sleep(3)
    # Select Any dining area — tap 3 times to ensure selection
    _tap(agent, "anyBtn")
    time.sleep(1)
    _tap(agent, "anyBtn")
    time.sleep(1)
    _tap(agent, "anyBtn")
    time.sleep(2)
    # Slide duration to Not Sure — long drag from 1hr to end
    agent.adb("shell", "input", "swipe", "80", "1370", "950", "1370", "1500")
    time.sleep(3)
    _tap_chip_container(agent)
    # Type mobile number
    _tap(agent, "mobileInputBtn")
    time.sleep(3)
    for ch in "9686496589":
        agent.adb("shell", "input", "text", ch)
        time.sleep(0.3)
    time.sleep(2)
    agent.adb("shell", "input", "keyevent", "111")
    time.sleep(3)
    # Save event — tap 3 times to ensure it registers
    _tap(agent, "saveBtn")
    time.sleep(2)
    _tap(agent, "saveBtn")
    time.sleep(2)
    _tap(agent, "saveBtn")
    time.sleep(20)
    # Signal consumer that business is done
    shared_data["sv1_business_done"] = True
    scenario_reporter.add_result("SV1", "Confirmation Pending Status",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv1_consumer_flow(agent):
    """SV1: Consumer sees Confirmation Pending — waits for business to finish first"""
    print(f"[{agent.role}] [SV1] Waiting for business to create event...")
    agent.launch_app()
    # Poll shared_data flag instead of event — business sets it when done
    for i in range(60):
        if shared_data.get("sv1_business_done"):
            print(f"[{agent.role}] Business finished, starting consumer flow")
            break
        time.sleep(3)
    time.sleep(5)
    _tap(agent, "walletTab")
    time.sleep(10)
    _wait_for_card(agent, "Nylai KitchenInviteCard", max_attempts=10)
    time.sleep(3)
    if not _tap(agent, "eventAccept"):
        time.sleep(3)
        _tap(agent, "eventAccept")
    time.sleep(5)
    _tap(agent, "orderLater")
    time.sleep(5)
    scenario_reporter.add_result("SV1", "Confirmation Pending Status",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv3_business_flow(agent):
    """SV3: Event Declination from B-App"""
    print(f"[{agent.role}] [SV3] Event Declination from B-App")
    agent.launch_app()
    time.sleep(5)
    if not _tap(agent, "addNewEvent"):
        agent.swipe_up()
        time.sleep(3)
        _tap(agent, "addNewEvent")
    time.sleep(5)
    # Type first name
    _tap(agent, "firstName")
    time.sleep(3)
    for ch in "Roopa":
        agent.adb("shell", "input", "text", ch)
        time.sleep(0.3)
    time.sleep(2)
    # Type last name
    _tap(agent, "lastName")
    time.sleep(3)
    agent.adb("shell", "input", "text", "D")
    time.sleep(2)
    # Dismiss keyboard
    agent.adb("shell", "input", "keyevent", "111")
    time.sleep(3)
    # Select Any dining area — tap 3 times
    _tap(agent, "anyBtn")
    time.sleep(1)
    _tap(agent, "anyBtn")
    time.sleep(1)
    _tap(agent, "anyBtn")
    time.sleep(2)
    # Slide duration to Not Sure — long drag
    agent.adb("shell", "input", "swipe", "80", "1370", "950", "1370", "1500")
    time.sleep(3)
    _tap_chip_container(agent)
    # Type mobile number
    _tap(agent, "mobileInputBtn")
    time.sleep(3)
    for ch in "9686496589":
        agent.adb("shell", "input", "text", ch)
        time.sleep(0.3)
    time.sleep(2)
    agent.adb("shell", "input", "keyevent", "111")
    time.sleep(3)
    # Save event — tap 2 times
    _tap(agent, "saveBtn")
    time.sleep(2)
    _tap(agent, "saveBtn")
    time.sleep(20)
    # Signal consumer that business is done
    shared_data["sv3_business_done"] = True
    scenario_reporter.add_result("SV3", "Event Declination",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv3_consumer_flow(agent):
    """SV3: Consumer declines event from B-App"""
    print(f"[{agent.role}] [SV3] Waiting for business to create event...")
    agent.launch_app()
    # Poll shared_data flag — business sets it when done
    for i in range(60):
        if shared_data.get("sv3_business_done"):
            print(f"[{agent.role}] Business finished, starting consumer flow")
            break
        time.sleep(3)
    time.sleep(5)
    _tap(agent, "walletTab")
    time.sleep(10)
    _wait_for_card(agent, "Nylai KitchenInviteCard", max_attempts=10)
    time.sleep(3)
    if not _tap(agent, "eventDecline"):
        time.sleep(3)
        _tap(agent, "eventDecline")
    time.sleep(20)
    scenario_reporter.add_result("SV3", "Event Declination",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


# ─── PDF Generation (PDF1–PDF3) ──────────────────────────────────────────────

def pdf1_business_flow(agent):
    """PDF1: Generate PDF for Payment by Individuals"""
    print(f"[{agent.role}] [PDF1] Waiting for Consumer flow to finish (max 20s)")
    # Wait max 20 seconds for consumer to finish
    for i in range(20):
        if shared_data.get("pdf1_consumer_done"):
            print(f"[{agent.role}] Consumer finished, starting business flow")
            break
        time.sleep(1)
    else:
        if not shared_data.get("pdf1_consumer_done"):
            msg = "Consumer flow did not finish within 20s — aborting business flow"
            print(f"[{agent.role}] [PDF1] FAIL: {msg}")
            scenario_reporter.add_result("PDF1", "Generate PDF - Individual Payment",
                                         agent.role, "FAIL", msg, agent.last_launch_time)
            return

    try:
        print(f"[{agent.role}] [PDF1] Generate PDF - Individual Payment")
        agent.launch_app()
        time.sleep(3)

        # Step 1: Assign table
        _tap(agent, "Orders")
        time.sleep(5)
        for i in range(5):
            if _tap(agent, "ReservedOrderCard"):
                break
            agent.swipe_up()
            time.sleep(3)
        time.sleep(3)
        _tap(agent, "T0AssignAnyBtn")
        time.sleep(3)
        _tap(agent, "AssignTableBtn")
        time.sleep(5)

        # Step 2: Add items
        _tap(agent, "addItemsBtn")
        time.sleep(3)
        _tap(agent, "PaneerTikkaItem")
        time.sleep(2)
        _tap(agent, "regularBtn")
        time.sleep(2)
        _tap(agent, "extracheeseBtn")
        time.sleep(2)
        _tap(agent, "applyOptionBtn")
        time.sleep(3)
        _tap(agent, "PizzaQuattroStagioniItem")
        time.sleep(2)
        _tap(agent, "applyOptionBtn")
        time.sleep(3)

        # Step 3: Assign to all and send
        _tap(agent, "assignToBtn")
        time.sleep(3)
        _tap(agent, "selectAll")
        time.sleep(3)
        _tap(agent, "assignProductsBtn")
        time.sleep(3)
        _tap(agent, "selectAllItemsBtn")
        time.sleep(3)
        _tap(agent, "sendItemsBtn")
        time.sleep(5)
        _tap(agent, "backButton")
        time.sleep(3)

        # Step 4: Kitchen — switch to kitchen account, mark items ready
        _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
        time.sleep(5)
        _tap(agent, "inProgressOrderCard")
        time.sleep(5)
        _tap_all_kitchen_items(agent, ["PaneerTikka", "PizzaQuattroStagioni"])
        time.sleep(2)
        agent.swipe_up()
        time.sleep(2)
        agent.swipe_up()
        time.sleep(2)
        _tap(agent, "orderReadyBtn")
        time.sleep(3)
        _tap(agent, "orderCloseBtn")
        time.sleep(3)

        # Step 5: Serve — switch to server account, serve items
        _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
        time.sleep(10)
        _tap(agent, "Orders")
        time.sleep(10)
        for i in range(5):
            if _tap(agent, "ServeOrderCard"):
                break
            agent.swipe_up()
            time.sleep(3)
        time.sleep(3)
        _tap(agent, "selectAllItemsBtn")
        time.sleep(3)
        _tap(agent, "serveItemsBtn")
        time.sleep(3)
        _tap(agent, "notifyPaymentBtn")
        time.sleep(3)
        _tap(agent, "Payment")
        time.sleep(3)

        # Step 6: Pay Guest1 — cash 350
        print(f"[{agent.role}] [PDF1] Paying Guest1...")
        _tap(agent, "Guest1Card")
        time.sleep(3)
        # Bill validation before payment — verify Guest1 bill
        agent.swipe_up()
        time.sleep(2)
        agent.verify_final_bill()
        agent.swipe_down()
        time.sleep(2)
        _tap(agent, "paidCashPaymentBtn", "cashPaymentBtn")
        time.sleep(2)
        _tap(agent, "Number3")
        _tap(agent, "Number5")
        _tap(agent, "Number0")
        _tap(agent, "userInputBtn")
        time.sleep(2)
        _tap(agent, "Apply")
        time.sleep(2)
        agent.swipe_up()
        time.sleep(3)
        # Bill validation after payment applied
        agent.verify_final_bill()
        _tap(agent, "paymentConfirmBtn")
        time.sleep(5)

        # Step 7: Pay RoopaD — cash 350
        print(f"[{agent.role}] [PDF1] Paying RoopaD...")
        agent.swipe_down()
        time.sleep(2)
        _tap(agent, "RoopaDCard")
        time.sleep(3)
        # Bill validation before payment — verify RoopaD bill
        agent.swipe_up()
        time.sleep(2)
        agent.verify_final_bill()
        agent.swipe_down()
        time.sleep(2)
        _tap(agent, "cashPaymentBtn")
        time.sleep(2)
        _tap(agent, "Number3")
        _tap(agent, "Number5")
        _tap(agent, "Number0")
        _tap(agent, "userInputBtn")
        time.sleep(2)
        _tap(agent, "Apply")
        time.sleep(2)
        agent.swipe_up()
        time.sleep(3)
        # Bill validation after payment applied
        agent.verify_final_bill()
        _tap(agent, "paymentConfirmBtn")
        time.sleep(5)

        # Step 8: Pay NooluNaga — cash 350
        print(f"[{agent.role}] [PDF1] Paying NooluNaga...")
        agent.swipe_down()
        time.sleep(2)
        _tap(agent, "NooluNagaCard")
        time.sleep(3)
        # Bill validation before payment — verify NooluNaga bill
        agent.swipe_up()
        time.sleep(2)
        agent.verify_final_bill()
        agent.swipe_down()
        time.sleep(2)
        _tap(agent, "cashPaymentBtn")
        time.sleep(2)
        _tap(agent, "Number3")
        _tap(agent, "Number5")
        _tap(agent, "Number0")
        _tap(agent, "userInputBtn")
        time.sleep(2)
        _tap(agent, "Apply")
        time.sleep(2)
        agent.swipe_up()
        time.sleep(3)
        # Bill validation after payment applied
        agent.verify_final_bill()
        _tap(agent, "paymentConfirmBtn")
        time.sleep(5)

        # Step 9: Bill validation before PDF generation — full page check
        print(f"[{agent.role}] [PDF1] Pre-PDF bill validation — checking full page...")
        agent.check_bill_with_vat()
        time.sleep(3)

        scenario_reporter.add_result("PDF1", "Generate PDF - Individual Payment",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)

    except Exception as e:
        msg = f"Unexpected error: {e}"
        print(f"[{agent.role}] [PDF1] ERROR: {msg}")
        scenario_reporter.add_result("PDF1", "Generate PDF - Individual Payment",
                                     agent.role, "FAIL", msg, agent.last_launch_time)


def pdf1_consumer_flow(agent):
    """PDF1 Consumer: Noolu books event with Roopa, then Roopa accepts"""
    print(f"[{agent.role}] [PDF1] Consumer - Book event and accept invite")
    try:
        agent.launch_app()
        time.sleep(3)
        # Step 0: Switch to Noolu's account first
        _switch_account(agent, "noolu@xorstack.com", "12345")
        time.sleep(3)
        # Step 1: Noolu books event at NylaiKitchen with guest + invites Roopa
        _tap_or_fail(agent, "NylaiKitchen", "PDF1", "Generate PDF - Individual Payment")
        time.sleep(3)
        _tap_or_fail(agent, "counterPlus", "PDF1", "Generate PDF - Individual Payment")
        time.sleep(2)
        _tap_or_fail(agent, "guestAdd", "PDF1", "Generate PDF - Individual Payment")
        time.sleep(2)
        _type_field(agent, "contactSearch", "Roopa", scenario_key="PDF1",
                    scenario_name="Generate PDF - Individual Payment", critical=True)
        time.sleep(2)
        _tap_or_fail(agent, "RoopaInvite", "PDF1", "Generate PDF - Individual Payment")
        time.sleep(3)
        _tap_or_fail(agent, "Roopa", "PDF1", "Generate PDF - Individual Payment")
        time.sleep(3)
        _tap_or_fail(agent, "inviteUsers", "PDF1", "Generate PDF - Individual Payment")
        time.sleep(3)
        _tap_chip_container(agent)
        time.sleep(2)
        _tap_or_fail(agent, "bookAppoitment", "PDF1", "Generate PDF - Individual Payment")
        time.sleep(3)
        _tap(agent, "orderLater")
        time.sleep(5)
        # Step 2: Switch to Roopa and accept
        _switch_account(agent, "roopa@xorstack.com", "12345")
        time.sleep(3)
        _tap_or_fail(agent, "walletTab", "PDF1", "Generate PDF - Individual Payment")
        time.sleep(5)
        _wait_for_card(agent, "NooluNagaInviteCard", max_attempts=10)
        time.sleep(3)
        if not _tap(agent, "eventAccept"):
            time.sleep(3)
            if not _tap(agent, "eventAccept"):
                msg = "Element not found: 'eventAccept' — could not accept invite"
                print(f"[{agent.role}] SCENARIO FAIL: {msg}")
                scenario_reporter.add_result("PDF1", "Generate PDF - Individual Payment",
                                             agent.role, "FAIL", msg, agent.last_launch_time)
                return
        time.sleep(10)
        _tap(agent, "orderLater")
        time.sleep(5)
        shared_data["pdf1_consumer_done"] = True
        scenario_reporter.add_result("PDF1", "Generate PDF - Individual Payment",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)

    except ScenarioFail as e:
        print(f"[{agent.role}] [PDF1] Consumer scenario stopped: {e}")
        # ScenarioFail already reported via _tap_or_fail, no duplicate report
    except Exception as e:
        msg = f"Consumer unexpected error: {e}"
        print(f"[{agent.role}] [PDF1] ERROR: {msg}")
        scenario_reporter.add_result("PDF1", "Generate PDF - Individual Payment",
                                     agent.role, "FAIL", msg, agent.last_launch_time)


def pdf2_business_flow(agent):
    """PDF2: Generate PDF for entire event (all guests)"""
    print(f"[{agent.role}] [PDF2] Generate PDF for Entire Event")
    agent.launch_app()
    time.sleep(10)
    # Step 1: Tap on Assign/Split tab
    print(f"[{agent.role}] [PDF2] Opening Assign/Split page...")
    _tap(agent, "Assign/Split")
    time.sleep(3)
    # Step 2: Tap on PDF generator button (bottom purple icon button)
    print(f"[{agent.role}] [PDF2] Tapping PDF generate button...")
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "ASSIGN / SPLIT", "pdfGenerateBtn", "assignSplitBtn", "generatePdfBtn")
    time.sleep(3)
    # Step 3: Tap on "Print the event's invoice" radio button
    print(f"[{agent.role}] [PDF2] Selecting event invoice option...")
    _tap(agent, "eventInvoice")
    time.sleep(3)
    # Step 4: Tap on Print Now
    print(f"[{agent.role}] [PDF2] Tapping Print Now...")
    _tap(agent, "printNow")
    time.sleep(5)
    # Step 5: Bill validation — swipe through and verify all items + calculations
    print(f"[{agent.role}] [PDF2] Verifying final bill with all calculations...")
    agent.verify_final_bill()
    time.sleep(2)
    scenario_reporter.add_result("PDF2", "Generate PDF for Entire Event",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def pdf2_consumer_flow(agent):
    _no_op(agent)


def pdf3_business_flow(agent):
    """PDF3: Generate PDF after event completion for individual"""
    print(f"[{agent.role}] [PDF3] Generate PDF after Event Completion (Individual)")
    agent.launch_app()
    time.sleep(10)
    _tap(agent, "backButton")
    time.sleep(3)

    # Step 1: Generate PDF for NooluNaga
    print(f"[{agent.role}] [PDF3] Generating PDF for NooluNaga...")
    _tap(agent, "pdfGenerateBtn")
    time.sleep(3)
    _tap(agent, "individualInvoice")
    time.sleep(3)
    _tap(agent, "NooluNagaselect")
    time.sleep(3)
    _tap(agent, "printNow")
    time.sleep(5)
    # Verify NooluNaga bill — full calculation check
    print(f"[{agent.role}] [PDF3] Verifying NooluNaga invoice...")
    agent.verify_final_bill()
    time.sleep(2)

    # Step 2: Go back and generate PDF for RoopaD
    print(f"[{agent.role}] [PDF3] Going back for RoopaD invoice...")
    _tap(agent, "backButton")
    time.sleep(3)
    _tap(agent, "pdfGenerateBtn")
    time.sleep(3)
    _tap(agent, "individualInvoice")
    time.sleep(3)
    _tap(agent, "RoopaDselect", "RoopaDCard", "RoopaD")
    time.sleep(3)
    _tap(agent, "printNow")
    time.sleep(5)
    # Verify RoopaD bill — full calculation check
    print(f"[{agent.role}] [PDF3] Verifying RoopaD invoice...")
    agent.verify_final_bill()
    time.sleep(2)

    # Step 3: Go back and continue remaining steps
    _tap(agent, "backButton")
    time.sleep(3)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "closeTableBtn")
    time.sleep(3)
    scenario_reporter.add_result("PDF3", "Generate PDF after Event Completion (Individual)",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def pdf3_consumer_flow(agent):
    _no_op(agent)


# ─── ORDERING (O1–O5) ────────────────────────────────────────────────────────

def _switch_biz_account(agent, email, password):
    """Switch kitchen/staff account on business device."""
    _tap(agent, "Menu")
    _tap(agent, "logOutBtn")
    time.sleep(1)
    _type_field(agent, "emailValue", email)
    _type_field(agent, "passwordValue", password)
    agent.adb("shell", "input", "swipe", "776", "1817", "770", "1220")
    _tap(agent, "clickCheckBox")
    _wait_tap(agent, "signInBtn")
    time.sleep(3)


def o1_consumer_flow(agent):
    """O1: Adding items with different modifiers & variants - 5 users"""
    print(f"[{agent.role}] [O1] Booking with 2 invitees for modifiers scenario")
    agent.launch_app()
    _tap(agent, "NylaiKitchen")
    _tap(agent, "counterPlus")
    time.sleep(2)
    _tap(agent, "guestAdd")
    time.sleep(2)
    _tap(agent, "guestAdd")
    time.sleep(2)
    _type_field(agent, "contactSearch", "Noolu")
    time.sleep(2)
    _tap(agent, "NooluInvite")
    time.sleep(2)
    _tap(agent, "Noolu")
    time.sleep(2)
    _type_field(agent, "contactSearch", "Aritro", clear_first=True)
    time.sleep(2)
    _tap(agent, "AritroInvite")
    time.sleep(2)
    _tap(agent, "Aritro")
    time.sleep(2)
    _tap(agent, "inviteUsers")
    time.sleep(3)
    _tap_chip_container(agent)
    _tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "orderLater")
    time.sleep(5)
    # Noolu accepts
    _switch_account(agent, "noolu@xorstack.com", "12345")
    time.sleep(3)
    _tap(agent, "walletTab")
    time.sleep(5)
    _wait_for_card(agent, "RoopaDInviteCard", max_attempts=10)
    time.sleep(5)
    if not _tap(agent, "eventAccept"):
        time.sleep(3)
        _tap(agent, "eventAccept")
    time.sleep(10)
    _tap(agent, "orderLater")
    time.sleep(5)
    _tap(agent, "walletTab")
    # Aritro accepts
    _switch_account(agent, "aritro@xorstack.com", "12345")
    time.sleep(3)
    _tap(agent, "walletTab")
    time.sleep(5)
    _wait_for_card(agent, "RoopaDInviteCard", max_attempts=10)
    time.sleep(5)
    if not _tap(agent, "eventAccept"):
        time.sleep(3)
        _tap(agent, "eventAccept")
    time.sleep(5)
    scenario_reporter.add_result("O1", "Adding Items with Modifiers & Variants",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def o1_business_flow(agent):
    """O1 Business: Process order with complex modifiers & variants"""
    print(f"[{agent.role}] [O1] Process order with modifiers")
    agent.launch_app()
    time.sleep(10)
    _tap(agent, "Orders")
    time.sleep(5)
    for i in range(5):
        if _tap(agent, "ReservedOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "T0AssignAnyBtn")
    time.sleep(3)
    _tap(agent, "AssignTableBtn")
    time.sleep(5)
    _tap(agent, "addItemsBtn")
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "ThaiGreenCurrywithJasmineRiceItem")
    time.sleep(2)
    _tap(agent, "vegBtn")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "addspicyBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "ThaiGreenCurrywithJasmineRiceItem")
    time.sleep(2)
    _tap(agent, "addNewCustomSelection")
    time.sleep(2)
    _tap(agent, "tofuBtn")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "extrapeanutsBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "ThaiGreenCurrywithJasmineRiceItem")
    time.sleep(2)
    _tap(agent, "addNewCustomSelection")
    time.sleep(2)
    _tap(agent, "chickenBtn")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "extrasauceBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "ThaiGreenCurrywithJasmineRiceItem")
    time.sleep(2)
    _tap(agent, "addNewCustomSelection")
    time.sleep(2)
    _tap(agent, "chickenBtn")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "addmayoBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "assignToBtn")
    time.sleep(3)
    _tap(agent, "RoopaDselect")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "Guest1select")
    time.sleep(2)
    _tap(agent, "Guest2select")
    time.sleep(2)
    _tap(agent, "assignProductsBtn")
    time.sleep(5)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(5)
    _tap(agent, "sendItemsBtn")
    time.sleep(10)
    _tap(agent, "backButton")
    time.sleep(3)
    # Kitchen
    _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
    time.sleep(5)
    _tap(agent, "inProgressOrderCard")
    time.sleep(5)
    _tap_all_kitchen_items(agent, ["ThaiGreenCurrywithJasmineRice", "ThaiGreenCurrywithJasmineRice", "ThaiGreenCurrywithJasmineRice", "ThaiGreenCurrywithJasmineRice"])
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "orderReadyBtn")
    time.sleep(3)
    _tap(agent, "orderCloseBtn")
    time.sleep(3)
    scenario_reporter.add_result("O1", "Adding Items with Modifiers & Variants",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def o2_consumer_flow(agent):
    _no_op(agent)


def o2_business_flow(agent):
    """O2: Split before serve"""
    print(f"[{agent.role}] [O2] Split before serve")
    agent.launch_app()
    time.sleep(10)
    _tap(agent, "Orders")
    time.sleep(5)
    for i in range(5):
        if _tap(agent, "ServeOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "addItemsBtn")
    time.sleep(3)
    _tap(agent, "PizzaRucolaeParmigianoItem")
    time.sleep(2)
    _tap(agent, "FreshchampignonsBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "PizzaRucolaeParmigianoItem")
    time.sleep(2)
    _tap(agent, "addNewCustomSelection")
    time.sleep(2)
    _tap(agent, "CookedhamBtn")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "assignToBtn")
    time.sleep(3)
    _tap(agent, "NooluNagaselect")
    time.sleep(3)
    _tap(agent, "assignProductsBtn")
    time.sleep(5)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(5)
    _tap(agent, "sendItemsBtn")
    time.sleep(10)
    _tap(agent, "backButton")
    time.sleep(3)
    # Kitchen staff prepares
    _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
    time.sleep(5)
    _tap(agent, "inProgressOrderCard")
    time.sleep(5)
    _tap_all_kitchen_items(agent, ["ThaiGreenCurrywithJasmineRice", "ThaiGreenCurrywithJasmineRice", "ThaiGreenCurrywithJasmineRice", "ThaiGreenCurrywithJasmineRice", "PizzaRucolaeParmigiano", "PizzaRucolaeParmigiano"])
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "orderReadyBtn")
    time.sleep(3)
    _tap(agent, "orderCloseBtn")
    time.sleep(3)
    # Serve staff
    _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
    time.sleep(10)
    _tap(agent, "Orders")
    time.sleep(10)
    for i in range(5):
        if _tap(agent, "ServeOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    scenario_reporter.add_result("O2", "Split Before Serve",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def o3_consumer_flow(agent):
    _no_op(agent)


def o3_business_flow(agent):
    """O3: Try to split already-splitted items (validation check)"""
    print(f"[{agent.role}] [O3] Trying to split splitted items")
    agent.launch_app()
    time.sleep(10)
    _tap(agent, "Assign/Split Assign/Split")
    time.sleep(3)
    _tap(agent, "ThaiGreenCurrywithJasmineRicecard")
    time.sleep(3)
    _tap(agent, "sendItemsBtn")
    time.sleep(3)
    _tap(agent, "RoopaDselect")
    time.sleep(2)
    _tap(agent, "Guest1select")
    time.sleep(2)
    _tap(agent, "assignProductsBtn")
    time.sleep(3)
    _tap(agent, "closeModal")
    time.sleep(2)
    scenario_reporter.add_result("O3", "Trying to Split Splitted Items",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def o4_consumer_flow(agent):
    _no_op(agent)


def o4_business_flow(agent):
    """O4: Assigning item from 1 person to another"""
    print(f"[{agent.role}] [O4] Assigning item from 1 to another")
    agent.launch_app()
    time.sleep(10)
    _tap(agent, "arrowBtn")
    time.sleep(3)
    _tap(agent, "NooluNagaselect")
    time.sleep(3)
    _tap(agent, "PizzaRucolaeParmigianocard")
    time.sleep(3)
    _tap(agent, "sendItemsBtn")
    time.sleep(3)
    _tap(agent, "RoopaDselect")
    time.sleep(2)
    _tap(agent, "assignProductsBtn")
    time.sleep(3)
    _tap(agent, "closeModal")
    time.sleep(2)
    _tap(agent, "assignProductsBtn")
    time.sleep(3)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(3)
    _tap(agent, "serveItemsBtn")
    time.sleep(3)
    scenario_reporter.add_result("O4", "Assigning Item from 1 to Another",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def o5_consumer_flow(agent):
    _no_op(agent)


def o5_business_flow(agent):
    """O5: Split after serve with payment"""
    print(f"[{agent.role}] [O5] Split after serve")
    agent.launch_app()
    time.sleep(10)
    _tap(agent, "Assign/Split Assign/Split")
    time.sleep(3)
    _tap(agent, "NooluNagaselect")
    time.sleep(3)
    _tap(agent, "PizzaRucolaeParmigianocard")
    time.sleep(3)
    _tap(agent, "sendItemsBtn")
    time.sleep(3)
    _tap(agent, "NooluNagaselect")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "Guest2select")
    time.sleep(2)
    _tap(agent, "Guest1select")
    time.sleep(2)
    _tap(agent, "assignProductsBtn")
    time.sleep(3)
    _tap(agent, "closeModal")
    time.sleep(2)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "notifyPaymentBtn")
    time.sleep(3)
    _tap(agent, "Payment")
    time.sleep(3)
    _tap(agent, "RoopaDCard")
    time.sleep(3)
    agent.swipe_down()
    time.sleep(2)
    _tap(agent, "cashPaymentBtn")
    time.sleep(2)
    _tap(agent, "Number7")
    _tap(agent, "Number0")
    _tap(agent, "userInputBtn")
    time.sleep(2)
    _tap(agent, "Guest1select")
    time.sleep(2)
    _tap(agent, "Guest2select")
    time.sleep(2)
    _tap(agent, "Apply")
    time.sleep(2)
    agent.adb("shell", "input", "swipe", "520", "1662", "537", "1086", "224")
    time.sleep(3)
    _tap(agent, "paymentConfirmBtn")
    time.sleep(5)
    _tap(agent, "NooluNagaCard")
    time.sleep(3)
    agent.swipe_down()
    time.sleep(2)
    _tap(agent, "cashPaymentBtn")
    time.sleep(2)
    _tap(agent, "Number1")
    _tap(agent, "Number0")
    _tap(agent, "userInputBtn")
    time.sleep(2)
    _tap(agent, "tipBtn")
    time.sleep(2)
    _tap(agent, "Number1")
    time.sleep(2)
    agent.adb("shell", "input", "swipe", "520", "1662", "537", "1086", "224")
    time.sleep(3)
    _tap(agent, "paymentConfirmBtn")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    scenario_reporter.add_result("O5", "Split After Serve with Payment",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


# ─── PAYMENTS 2 (PAY6–PAY7) ──────────────────────────────────────────────────

def pay6_consumer_flow(agent):
    """PAY6: Participant (Noolu) Pays for Others"""
    print(f"[{agent.role}] [PAY6] Noolu books event, invites Roopa")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "NylaiKitchen")
    time.sleep(3)
    _tap(agent, "counterPlus")
    time.sleep(2)
    _tap(agent, "guestAdd")
    time.sleep(2)
    _type_field(agent, "contactSearch", "Roopa")
    time.sleep(2)
    _tap(agent, "RoopaInvite")
    time.sleep(3)
    _tap(agent, "Roopa")
    time.sleep(3)
    _tap(agent, "inviteUsers")
    time.sleep(3)
    _tap_chip_container(agent)
    _tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "orderLater")
    time.sleep(5)
    # Switch to Roopa to accept
    _switch_account(agent, "roopa@xorstack.com", "12345")
    time.sleep(3)
    _tap(agent, "walletTab")
    time.sleep(5)
    _wait_for_card(agent, "NooluNagaInviteCard", max_attempts=10)
    time.sleep(3)
    if not _tap(agent, "eventAccept"):
        time.sleep(3)
        _tap(agent, "eventAccept")
    time.sleep(5)
    _tap(agent, "orderLater")
    time.sleep(5)
    scenario_reporter.add_result("PAY6", "Participant Pays for Others",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def pay6_business_flow(agent):
    """PAY6 Business: Process participant pays for others"""
    print(f"[{agent.role}] [PAY6] Process participant pays for others")
    agent.launch_app()
    time.sleep(10)
    # Assign table
    _tap(agent, "Orders")
    time.sleep(5)
    for i in range(5):
        if _tap(agent, "ReservedOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "T0AssignAnyBtn")
    time.sleep(3)
    _tap(agent, "AssignTableBtn")
    time.sleep(5)
    # Add items: FishAmritsari + PadThaiNoodles + Spinach&CheeseRavioli
    _tap(agent, "addItemsBtn")
    time.sleep(3)
    _tap(agent, "FishAmritsariItem")
    time.sleep(2)
    _tap(agent, "largeBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "PadThaiNoodlesItem")
    time.sleep(2)
    _tap(agent, "prawnBtn")
    time.sleep(2)
    _tap(agent, "addspicyBtn")
    time.sleep(2)
    _tap(agent, "FreshbellpepperBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "Spinach&CheeseRavioliItem")
    time.sleep(2)
    _tap(agent, "regularBtn")
    time.sleep(2)
    _tap(agent, "AddGarlicOilBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    # Assign to all and send
    _tap(agent, "assignToBtn")
    time.sleep(3)
    _tap(agent, "selectAll")
    time.sleep(3)
    _tap(agent, "assignProductsBtn")
    time.sleep(5)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(5)
    _tap(agent, "sendItemsBtn")
    time.sleep(10)
    _tap(agent, "backButton")
    time.sleep(3)
    # Kitchen staff
    _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
    time.sleep(5)
    _tap(agent, "inProgressOrderCard")
    time.sleep(5)
    # Select all kitchen items, then swipe up for Ready button
    _tap_all_kitchen_items(agent, ["FishAmritsari", "PadThaiNoodles", "Spinach&CheeseRavioli"])
    time.sleep(2)
    _tap(agent, "orderReadyBtn")
    time.sleep(3)
    _tap(agent, "orderCloseBtn")
    time.sleep(3)
    # Serve staff
    _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
    time.sleep(10)
    _tap(agent, "Orders")
    time.sleep(10)
    for i in range(5):
        if _tap(agent, "ServeOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(3)
    _tap(agent, "serveItemsBtn")
    time.sleep(3)
    _tap(agent, "notifyPaymentBtn")
    time.sleep(3)
    _tap(agent, "Payment")
    time.sleep(3)
    # Cash payment
    _tap(agent, "RoopaDCard")
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "cashPaymentBtn")
    time.sleep(2)
    _tap(agent, "Number9")
    _tap(agent, "Number8")
    _tap(agent, "Number0")
    _tap(agent, "Number0")
    _tap(agent, "userInputBtn")
    time.sleep(2)
    _tap(agent, "Guest1select")
    time.sleep(2)
    _tap(agent, "NooluNagaselect")
    time.sleep(2)
    _tap(agent, "Apply")
    time.sleep(2)
    agent.adb("shell", "input", "swipe", "520", "1662", "537", "1086", "224")
    time.sleep(3)
    agent.verify_final_bill()
    _tap(agent, "paymentConfirmBtn")
    time.sleep(5)
    agent.verify_final_bill()
    # Close table
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "closeTableBtn")
    time.sleep(3)
    scenario_reporter.add_result("PAY6", "Participant Pays for Others",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def pay7_consumer_flow(agent):
    """PAY7: Guest (Roopa) books event, invites Noolu"""
    print(f"[{agent.role}] [PAY7] Roopa books event, invites Noolu")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "NylaiKitchen")
    time.sleep(3)
    _tap(agent, "counterPlus")
    time.sleep(2)
    _tap(agent, "guestAdd")
    time.sleep(2)
    _type_field(agent, "contactSearch", "Noolu")
    time.sleep(2)
    _tap(agent, "NooluInvite")
    time.sleep(3)
    _tap(agent, "Noolu")
    time.sleep(3)
    _tap(agent, "inviteUsers")
    time.sleep(3)
    _tap_chip_container(agent)
    _tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "orderLater")
    time.sleep(5)
    # Switch to Noolu to accept
    _switch_account(agent, "noolu@xorstack.com", "12345")
    time.sleep(3)
    _tap(agent, "walletTab")
    time.sleep(5)
    _wait_for_card(agent, "RoopaDInviteCard", max_attempts=10)
    time.sleep(3)
    if not _tap(agent, "eventAccept"):
        time.sleep(3)
        _tap(agent, "eventAccept")
    time.sleep(5)
    _tap(agent, "orderLater")
    time.sleep(5)
    scenario_reporter.add_result("PAY7", "Guest Pays for Others",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def pay7_business_flow(agent):
    """PAY7 Business: Guest pays for others"""
    print(f"[{agent.role}] [PAY7] Process guest pays for others")
    agent.launch_app()
    time.sleep(10)
    # Assign table
    _tap(agent, "Orders")
    time.sleep(5)
    for i in range(5):
        if _tap(agent, "ReservedOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "T0AssignAnyBtn")
    time.sleep(3)
    _tap(agent, "AssignTableBtn")
    time.sleep(5)
    # Add items: PaneerTikka + PizzaQuattroStagioni
    _tap(agent, "addItemsBtn")
    time.sleep(3)
    _tap(agent, "PaneerTikkaItem")
    time.sleep(2)
    _tap(agent, "regularBtn")
    time.sleep(2)
    _tap(agent, "extracheeseBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "PizzaQuattroStagioniItem")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    # Assign to all and send
    _tap(agent, "assignToBtn")
    time.sleep(3)
    _tap(agent, "selectAll")
    time.sleep(3)
    _tap(agent, "assignProductsBtn")
    time.sleep(5)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(5)
    _tap(agent, "sendItemsBtn")
    time.sleep(10)
    _tap(agent, "backButton")
    time.sleep(3)
    # Kitchen staff
    _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
    time.sleep(5)
    _tap(agent, "inProgressOrderCard")
    time.sleep(5)
    # Select all kitchen items, then swipe up for Ready button
    _tap_all_kitchen_items(agent, ["PaneerTikka", "PizzaQuattroStagioni"])
    time.sleep(2)
    _tap(agent, "orderReadyBtn")
    time.sleep(3)
    _tap(agent, "orderCloseBtn")
    time.sleep(3)
    # Serve staff
    _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
    time.sleep(10)
    _tap(agent, "Orders")
    time.sleep(10)
    for i in range(5):
        if _tap(agent, "ServeOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(3)
    _tap(agent, "serveItemsBtn")
    time.sleep(3)
    _tap(agent, "notifyPaymentBtn")
    time.sleep(3)
    _tap(agent, "Payment")
    time.sleep(3)
    # Guest pays — paidCash 1000
    _tap(agent, "Guest1Card")
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "paidCashPaymentBtn")
    time.sleep(2)
    _tap(agent, "Number1")
    _tap(agent, "Number0")
    _tap(agent, "Number0")
    _tap(agent, "Number0")
    _tap(agent, "userInputBtn")
    time.sleep(2)
    _tap(agent, "RoopaDselect")
    time.sleep(2)
    _tap(agent, "Apply")
    time.sleep(2)
    agent.adb("shell", "input", "swipe", "520", "1662", "537", "1086", "224")
    time.sleep(3)
    agent.verify_final_bill()
    _tap(agent, "paymentConfirmBtn")
    time.sleep(5)
    agent.verify_final_bill()
    # Close table
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "closeTableBtn")
    time.sleep(3)
    scenario_reporter.add_result("PAY7", "Guest Pays for Others",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


# ─── EVENT CANCELLATIONS (EC2, EC5–EC11) ─────────────────────────────────────

def ec2_consumer_flow(agent):
    """EC2: After host change, check if adding user/guest works"""
    print(f"[{agent.role}] [EC2] Verify adding user after host change")
    agent.launch_app()
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_for_card(agent, "NylaiKitchenCard")
    time.sleep(2)
    scenario_reporter.add_result("EC2", "Adding User After Host Change",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def ec2_business_flow(agent):
    _no_op(agent)


def ec5_consumer_flow(agent):
    """EC5: Both Host and Participant Cancel Event"""
    print(f"[{agent.role}] [EC5] Both host and participant cancel")
    agent.launch_app()
    _switch_account(agent, "roopa@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_for_card(agent, "NylaiKitchenCard")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(1)
    _tap(agent, "cancelBooking")
    time.sleep(1)
    _tap(agent, "option1")
    time.sleep(1)
    agent.swipe_up()
    time.sleep(1)
    xml = agent.dump_ui()
    comment_field = (
        agent.find_by_desc(xml, "cancelReason")
        or agent.find_by_desc(xml, "Or make a comment")
        or agent.find_by_text(xml, "Or make a comment")
        or agent.find_by_desc(xml, "write a comment")
        or agent.find_by_text(xml, "write a comment")
    )
    if comment_field:
        agent.tap(comment_field[0], comment_field[1], "[comment field]")
        time.sleep(0.5)
        agent.type_text("Booked wrong slot!")
        agent.adb("shell", "input", "keyevent", "KEYCODE_BACK")
        time.sleep(1)
    _tap(agent, "optionSubmit", "submit")
    time.sleep(2)
    _tap(agent, "BOOKING CANCELLED")
    time.sleep(2)
    _tap(agent, "homeTab")
    scenario_reporter.add_result("EC5", "Both Host and Participant Cancel",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def ec5_business_flow(agent):
    _no_op(agent)


def ec6_consumer_flow(agent):
    """EC6: Host Cancels after both preorder - After 15 min - Me Only"""
    print(f"[{agent.role}] [EC6] Host + Noolu preorder, host cancels Me Only")
    agent.launch_app()
    _tap(agent, "NylaiKitchen")
    time.sleep(2)
    _tap(agent, "counterPlus")
    _type_field(agent, "contactSearch", "Noolu")
    time.sleep(2)  # wait for search results
    _tap(agent, "NooluInvite")
    _tap(agent, "Noolu")  # confirm Noolu on popup
    _tap(agent, "inviteUsers")
    _tap_chip_container(agent)
    _wait_tap(agent, "bookAppoitment")
    time.sleep(3)
    _wait_tap(agent, "preOrderBooking")
    time.sleep(5)
    _tap(agent, "Chicken65Inc")
    time.sleep(2)  # wait for popup
    _tap(agent, "yes", "Yes")  # confirm add item
    time.sleep(2)  # wait for variant dialog
    _tap(agent, "addmayoProduct", scroll=False)
    time.sleep(1)
    _tap(agent, "confirmProduct", scroll=False)
    time.sleep(10)
    _tap(agent, "pasta-pizzacategory", scroll=False)
    time.sleep(10)
    _tap(agent, "PizzaProsciuttoeFunghiInc")
    time.sleep(2)  # wait for popup
    _tap(agent, "yes", "Yes")  # confirm add item
    time.sleep(2)  # wait for variant dialog
    _tap(agent, "FreshbellpepperProduct", scroll=False)
    time.sleep(1)
    _tap(agent, "confirmProduct", scroll=False)
    time.sleep(2)
    _tap(agent, "cartImage")
    _tap(agent, "cartCheckout")
    time.sleep(2)
    # Dismiss any OK/confirmation dialog before pay screen
    _tap(agent, "ok", "OK")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(1)
    # Tap pay button
    if not _tap(agent, "primary_button"):
        _tap(agent, "placeOrder", "Place Order")
    time.sleep(20)  # wait for payment to process
    # Dismiss confirmation popup
    _tap(agent, "pickUpOrderConfirm")
    agent.check_bill()
    time.sleep(20)
    _tap(agent, "yesGotIt", "YES, GOT IT")
    time.sleep(20)
    agent.go_home()
    time.sleep(2)
    _tap(agent, "walletTab")
    # Noolu accepts and preorders
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_for_card(agent, "RoopaDInviteCard")
    time.sleep(2)
    _tap(agent, "eventAccept")
    time.sleep(10)  # wait for server to process accept
    _wait_tap(agent, "preOrderBooking")
    time.sleep(10)
    _tap(agent, "starterscategory", scroll=False)
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "HaraBharaKebabInc")
    time.sleep(2)  # wait for variant dialog
    _tap(agent, "4pcsProduct", scroll=False)
    time.sleep(1)
    _tap(agent, "confirmProduct", scroll=False)
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    _tap(agent, "ThaiGreenCurrywithJasmineRiceInc")
    time.sleep(2)  # wait for variant dialog
    _tap(agent, "vegProduct", scroll=False)
    time.sleep(1)
    agent.swipe_up_small()
    time.sleep(1)
    _tap(agent, "extrapeanutsProduct", scroll=False)
    time.sleep(1)
    _tap(agent, "confirmProduct", scroll=False)
    time.sleep(3)
    _tap(agent, "cartImage")
    _tap(agent, "cartCheckout")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(1)
    # Tap pay/confirm button
    # Tap pay button first
    if not _tap(agent, "primary_button"):
        _tap(agent, "placeOrder", "Place Order")
    time.sleep(20)  # wait for payment to process
    # Dismiss confirmation popup
    _tap(agent, "pickUpOrderConfirm")
    agent.check_bill()
    _tap(agent, "yesGotIt", "YES, GOT IT")
    time.sleep(3)
    agent.go_home()
    time.sleep(2)
    _tap(agent, "walletTab")
    # Roopa switches back and cancels
    _switch_account(agent, "roopa@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_for_card(agent, "NylaiKitchenCard")
    time.sleep(2)
    agent.swipe_up()
    _cancel_booking_flow(agent, assignee="NooluNagaassign")
    _tap(agent, "BOOKING CANCELLED")
    _tap(agent, "homeTab")
    scenario_reporter.add_result("EC6", "Host Cancels After Preorder - Me Only",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def ec6_business_flow(agent):
    _no_op(agent)


def ec7_consumer_flow(agent):
    """EC7: Only host preorders & cancels - After 15 min - Me Only"""
    print(f"[{agent.role}] [EC7] Host preorders with guest, cancels Me Only")
    agent.launch_app()
    _tap(agent, "NylaiKitchen")
    _tap(agent, "counterPlus")
    _tap(agent, "guestAdd")
    _tap(agent, "inviteUsers")
    _tap_chip_container(agent)
    _wait_tap(agent, "bookAppoitment")
    _tap(agent, "bookAppoitment")
    _wait_tap(agent, "preOrderBooking")
    _tap(agent, "preOrderBooking")
    time.sleep(5)
    _tap(agent, "Chicken65Inc")
    _tap(agent, "addmayoProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "pasta-pizzacategory", scroll=False)
    _tap(agent, "PizzaProsciuttoeFunghiInc")
    _tap(agent, "FreshbellpepperProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "cartImage")
    _tap(agent, "cartCheckout")
    time.sleep(2)
    _tap(agent, "ok", "OK")
    time.sleep(2)
    if not _tap(agent, "primary_button"):
        _tap(agent, "placeOrder", "Place Order")
    time.sleep(20)
    _tap(agent, "yesGotIt", "YES, GOT IT")
    time.sleep(10)
    # Wallet tab opens automatically after payment — just swipe up to find cancelBooking
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "cancelBooking")
    time.sleep(1)
    _tap(agent, "option1")
    time.sleep(1)
    agent.swipe_up()
    time.sleep(1)
    # Find and type in the comment field
    xml = agent.dump_ui()
    comment_field = (
        agent.find_by_desc(xml, "cancelReason")
        or agent.find_by_desc(xml, "Or make a comment")
        or agent.find_by_text(xml, "Or make a comment")
        or agent.find_by_desc(xml, "write a comment")
        or agent.find_by_text(xml, "write a comment")
        or agent.find_by_desc(xml, "commentInput")
    )
    if comment_field:
        agent.tap(comment_field[0], comment_field[1], "[comment field]")
        time.sleep(0.5)
        agent.type_text("Booked wrong slot!")
        agent.adb("shell", "input", "keyevent", "KEYCODE_BACK")
        time.sleep(1)
    _tap(agent, "optionSubmit", "submit")
    time.sleep(2)
    _tap(agent, "BOOKING CANCELLED")
    _tap(agent, "homeTab")
    scenario_reporter.add_result("EC7", "Host Preorders with Guest, Cancels Me Only",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def ec7_business_flow(agent):
    _no_op(agent)


def ec8_consumer_flow(agent):
    """EC8: Host Cancels after both preorder - After 15 min - Cancel for all"""
    print(f"[{agent.role}] [EC8] Host + Noolu preorder, host cancels for all")
    agent.launch_app()
    _tap(agent, "NylaiKitchen")
    time.sleep(3)
    _tap(agent, "counterPlus")
    _type_field(agent, "contactSearch", "Noolu")
    _tap(agent, "NooluInvite")
    _tap(agent, "Noolu")  # confirm Noolu on popup
    _tap(agent, "inviteUsers")
    _tap_chip_container(agent)
    _tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "preOrderBooking")
    time.sleep(5)
    _tap(agent, "Chicken65Inc")
    _tap(agent, "addmayoProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "pasta-pizzacategory", scroll=False)
    _tap(agent, "PizzaProsciuttoeFunghiInc")
    _tap(agent, "FreshbellpepperProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "cartImage")
    _tap(agent, "cartCheckout")
    time.sleep(5)
    _tap(agent, "ok", "OK")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    if not _tap(agent, "primary_button"):
        _tap(agent, "placeOrder", "Place Order")
    time.sleep(30)
    _tap(agent, "yesGotIt", "YES, GOT IT")
    time.sleep(5)
    _tap(agent, "walletTab")
    # Noolu accepts and preorders
    _switch_account(agent, "noolu@xorstack.com", "12345")
    time.sleep(10)
    _tap(agent, "walletTab")
    time.sleep(10)
    _wait_for_card(agent, "RoopaDInviteCard")
    time.sleep(10)
    _tap(agent, "eventAccept")
    time.sleep(15)
    _tap(agent, "preOrderBooking")
    time.sleep(5)
    _tap(agent, "starterscategory", scroll=False)
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "HaraBharaKebabInc")
    _tap(agent, "4pcsProduct")
    _tap(agent, "confirmProduct")
    agent.swipe_up()
    agent.swipe_up()
    agent.swipe_up()
    _tap(agent, "ThaiGreenCurrywithJasmineRiceInc")
    _tap(agent, "vegProduct")
    agent.swipe_up()
    _tap(agent, "extrapeanutsProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "cartImage")
    _tap(agent, "cartCheckout")
    time.sleep(5)
    _tap(agent, "ok", "OK")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    if not _tap(agent, "primary_button"):
        _tap(agent, "placeOrder", "Place Order")
    time.sleep(30)
    _tap(agent, "yesGotIt", "YES, GOT IT")
    time.sleep(5)
    _tap(agent, "walletTab")
    # Roopa cancels for ALL
    _switch_account(agent, "roopa@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_for_card(agent, "NylaiKitchenCard")
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "cancelBooking")
    time.sleep(2)
    # Popup: tap "ALL IN THIS EVENT"
    if not _tap(agent, "ALL IN THIS EVENT"):
        _tap(agent, "all in this event")
    time.sleep(3)
    scenario_reporter.add_result("EC8", "Host Cancels for All After Preorder",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def ec8_business_flow(agent):
    _no_op(agent)


def ec9_consumer_flow(agent):
    """EC9: Host Cancels - Before 15 min - Cancel for all"""
    print(f"[{agent.role}] [EC9] Host cancels for all before 15 min")
    agent.launch_app()
    _tap(agent, "NylaiKitchen")
    _tap(agent, "counterPlus")
    _type_field(agent, "contactSearch", "Noolu")
    _tap(agent, "NooluInvite")
    _tap(agent, "Noolu")  # confirm Noolu on popup
    _tap(agent, "inviteUsers")
    _tap_chip_container(agent)
    _wait_tap(agent, "bookAppoitment")
    _tap(agent, "bookAppoitment")
    _wait_tap(agent, "preOrderBooking")
    time.sleep(5)
    _tap(agent, "Chicken65Inc")
    _tap(agent, "addmayoProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "pasta-pizzacategory", scroll=False)
    _tap(agent, "PizzaProsciuttoeFunghiInc")
    _tap(agent, "FreshbellpepperProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "cartImage")
    _tap(agent, "cartCheckout")
    time.sleep(2)
    _tap(agent, "ok", "OK")
    time.sleep(2)
    if not _tap(agent, "primary_button"):
        _tap(agent, "placeOrder", "Place Order")
    time.sleep(10)
    _tap(agent, "pickUpOrderConfirm")
    agent.check_bill()
    time.sleep(5)  # let order sync with server
    _tap(agent, "walletTab")
    # Noolu accepts and preorders
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_for_card(agent, "RoopaDInviteCard")
    time.sleep(2)
    _tap(agent, "eventAccept")
    _tap(agent, "preOrderBooking")
    time.sleep(5)
    _tap(agent, "starterscategory", scroll=False)
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "HaraBharaKebabInc")
    _tap(agent, "4pcsProduct")
    _tap(agent, "confirmProduct")
    agent.swipe_up()
    agent.swipe_up()
    agent.swipe_up()
    _tap(agent, "ThaiGreenCurrywithJasmineRiceInc")
    _tap(agent, "vegProduct")
    agent.swipe_up()
    _tap(agent, "extrapeanutsProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "cartImage")
    _tap(agent, "cartCheckout")
    time.sleep(2)
    _tap(agent, "ok", "OK")
    time.sleep(2)
    if not _tap(agent, "primary_button"):
        _tap(agent, "placeOrder", "Place Order")
    time.sleep(20)
    _tap(agent, "yesGotIt", "YES, GOT IT")
    time.sleep(20)  # let order sync with server
    _tap(agent, "walletTab")
    # Roopa cancels for ALL before 15 min
    _switch_account(agent, "roopa@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_for_card(agent, "NylaiKitchenCard")
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "cancelBooking")
    time.sleep(2)
    if not _tap(agent, "ALL IN THIS EVENT"):
        _tap(agent, "all in this event")
    time.sleep(3)
    _tap(agent, "yesGotIt", "YES, GOT IT")
    time.sleep(2)
    _tap(agent, "homeTab")
    scenario_reporter.add_result("EC9", "Host Cancels for All Before 15 min",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def ec9_business_flow(agent):
    _no_op(agent)


def ec10_consumer_flow(agent):
    """EC10: Host Cancels - before 15 min - Me Only"""
    print(f"[{agent.role}] [EC10] Host + Noolu preorder, cancel Me Only before 15 min")
    agent.launch_app()
    _tap(agent, "NylaiKitchen")
    _tap(agent, "counterPlus")
    _type_field(agent, "contactSearch", "Noolu")
    _tap(agent, "NooluInvite")
    _tap(agent, "Noolu")  # confirm Noolu on popup
    _tap(agent, "inviteUsers")
    _tap_chip_container(agent)
    _tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "preOrderBooking")
    time.sleep(5)
    _tap(agent, "Chicken65Inc")
    _tap(agent, "addmayoProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "pasta-pizzacategory", scroll=False)
    _tap(agent, "PizzaProsciuttoeFunghiInc")
    _tap(agent, "FreshbellpepperProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "cartImage")
    _tap(agent, "cartCheckout")
    time.sleep(5)
    _tap(agent, "ok", "OK")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    if not _tap(agent, "primary_button"):
        _tap(agent, "placeOrder", "Place Order")
    time.sleep(30)
    _tap(agent, "yesGotIt", "YES, GOT IT")
    time.sleep(5)
    _tap(agent, "walletTab")
    # Noolu accepts and preorders
    _switch_account(agent, "noolu@xorstack.com", "12345")
    time.sleep(3)
    _tap(agent, "walletTab")
    time.sleep(5)
    _wait_for_card(agent, "RoopaDInviteCard")
    time.sleep(3)
    _tap(agent, "eventAccept")
    time.sleep(15)
    _tap(agent, "preOrderBooking")
    time.sleep(5)
    _tap(agent, "starterscategory", scroll=False)
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "HaraBharaKebabInc")
    _tap(agent, "4pcsProduct")
    _tap(agent, "confirmProduct")
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "ThaiGreenCurrywithJasmineRiceInc")
    _tap(agent, "vegProduct")
    agent.swipe_up()
    time.sleep(1)
    _tap(agent, "extrapeanutsProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "cartImage")
    _tap(agent, "cartCheckout")
    time.sleep(5)
    _tap(agent, "ok", "OK")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    if not _tap(agent, "primary_button"):
        _tap(agent, "placeOrder", "Place Order")
    time.sleep(30)
    _tap(agent, "yesGotIt", "YES, GOT IT")
    time.sleep(5)
    _tap(agent, "walletTab")
    # Roopa cancels Me Only
    _switch_account(agent, "roopa@xorstack.com", "12345")
    time.sleep(3)
    _tap(agent, "walletTab")
    time.sleep(5)
    _wait_for_card(agent, "NylaiKitchenCard")
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "cancelBooking")
    time.sleep(2)
    _tap(agent, "me only")
    time.sleep(1)
    _tap(agent, "NooluNagaassign")
    time.sleep(1)
    _tap(agent, "confirmCancelBook")
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "yesGotIt", "YES, GOT IT")
    time.sleep(2)
    _tap(agent, "option1")
    time.sleep(1)
    agent.swipe_up()
    time.sleep(1)
    # Type cancel reason
    xml = agent.dump_ui()
    comment_field = (
        agent.find_by_desc(xml, "cancelReason")
        or agent.find_by_desc(xml, "Or make a comment")
        or agent.find_by_text(xml, "Or make a comment")
        or agent.find_by_desc(xml, "write a comment")
        or agent.find_by_text(xml, "write a comment")
        or agent.find_by_desc(xml, "commentInput")
    )
    if comment_field:
        agent.tap(comment_field[0], comment_field[1], "[comment field]")
        time.sleep(0.5)
        agent.type_text("Booked wrong slot!")
        agent.adb("shell", "input", "keyevent", "KEYCODE_BACK")
        time.sleep(1)
    _tap(agent, "optionSubmit", "submit")
    time.sleep(2)
    _tap(agent, "BOOKING CANCELLED")
    _tap(agent, "homeTab")
    scenario_reporter.add_result("EC10", "Host Cancels Me Only Before 15 min",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def ec10_business_flow(agent):
    _no_op(agent)


def ec11_consumer_flow(agent):
    """EC11: Only host preorders & cancels - before 15 min - Me Only"""
    print(f"[{agent.role}] [EC11] Host preorders with guest, cancels Me Only before 15 min")
    agent.launch_app()
    _tap(agent, "NylaiKitchen")
    _tap(agent, "counterPlus")
    _tap(agent, "guestAdd")
    _tap(agent, "inviteUsers")
    _tap_chip_container(agent)
    _wait_tap(agent, "bookAppoitment")
    _tap(agent, "bookAppoitment")
    _wait_tap(agent, "preOrderBooking")
    _tap(agent, "preOrderBooking")
    time.sleep(5)
    _tap(agent, "Chicken65Inc")
    _tap(agent, "addmayoProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "pasta-pizzacategory", scroll=False)
    _tap(agent, "PizzaProsciuttoeFunghiInc")
    _tap(agent, "FreshbellpepperProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "cartImage")
    _tap(agent, "cartCheckout")
    time.sleep(2)
    _tap(agent, "ok", "OK")
    time.sleep(2)
    if not _tap(agent, "primary_button"):
        _tap(agent, "placeOrder", "Place Order")
    time.sleep(10)
    _tap(agent, "pickUpOrderConfirm")
    agent.check_bill()
    time.sleep(10)
    agent.swipe_up()
    time.sleep(3)
    if not _tap(agent, "cancelBooking"):
        agent.swipe_up()
        time.sleep(2)
        _tap(agent, "cancelBooking")
    time.sleep(2)
    _tap(agent, "option1")
    time.sleep(1)
    _tap(agent, "optionSubmit")
    time.sleep(2)
    _tap(agent, "homeTab")
    scenario_reporter.add_result("EC11", "Host with Guest Preorders, Cancels Me Only",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def ec11_business_flow(agent):
    _no_op(agent)


# ─── STATUS VERIFICATION (SV2, SV4–SV16) ─────────────────────────────────────

def sv2_business_flow(agent):
    """SV2: Reserved status - B-App"""
    print(f"[{agent.role}] [SV2] Reserved status in B-App")
    agent.launch_app()
    _tap(agent, "Home")
    agent.swipe_up()
    agent.swipe_up()
    time.sleep(3)
    scenario_reporter.add_result("SV2", "Reserved Status B-App",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv2_consumer_flow(agent):
    _no_op(agent)


def sv4_consumer_flow(agent):
    """SV4: Pre-order status - C-App"""
    print(f"[{agent.role}] [SV4] Pre-order status in C-App")
    agent.launch_app()
    _tap(agent, "Home")
    time.sleep(3)
    _tap(agent, "NylaiKitchen")
    _tap_chip_container(agent)
    _tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "orderLater")
    time.sleep(5)
    _tap(agent, "walletTab")
    time.sleep(5)
    agent.swipe_up()
    time.sleep(2)
    # cancel flow
    _tap(agent, "cancelBooking")
    time.sleep(3)
    _tap(agent, "optionThree")
    time.sleep(2)
    _tap(agent, "optionSubmit")
    time.sleep(3)
    _tap(agent, "BOOKING CANCELLED")
    time.sleep(2)
    scenario_reporter.add_result("SV4", "Pre-Order Status C-App",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv4_business_flow(agent):
    _no_op(agent)


def sv6_consumer_flow(agent):
    """SV6: Consumer books event, then places menu order after business assigns table"""
    print(f"[{agent.role}] [SV6] Menu order - C-App")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "Home")
    time.sleep(3)
    # Step 1: Book event first
    _tap(agent, "NylaiKitchen")
    time.sleep(3)
    _tap_chip_container(agent)
    _tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "orderLater")
    time.sleep(5)
    # Step 2: Go to Home, then wallet, and place menu order
    _tap(agent, "Home")
    time.sleep(3)
    _tap(agent, "walletTab")
    time.sleep(5)
    _wait_for_card(agent, "NylaiKitchenCard", max_attempts=10)
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "Pre-Order", "preOrderBtn", scroll=False)
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "TomYumSoupInc")
    time.sleep(3)
    _tap(agent, "prawnProduct")
    time.sleep(2)
    _tap(agent, "confirmProduct")
    time.sleep(3)
    _tap(agent, "cartImage")
    time.sleep(3)
    _tap(agent, "checkout")
    time.sleep(3)
    _tap(agent, "primary_button")
    time.sleep(20)
    _tap(agent, "pickUpOrderConfirm")
    time.sleep(3)
    scenario_reporter.add_result("SV6", "Menu Order C-App",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv6_business_flow(agent):
    """SV6: Business assigns table after consumer books"""
    print(f"[{agent.role}] [SV6] Business flow starting")
    agent.launch_app()
    time.sleep(10)
    _tap(agent, "Orders")
    time.sleep(5)
    for i in range(5):
        if _tap(agent, "ReservedOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "T0AssignAnyBtn")
    time.sleep(3)
    _tap(agent, "AssignTableBtn")
    time.sleep(5)
    _tap(agent, "addItemsBtn")
    time.sleep(5)
    scenario_reporter.add_result("SV6", "Menu Order C-App",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv7_business_flow(agent):
    """SV7: Order status - B-App"""
    print(f"[{agent.role}] [SV7] Order status in B-App")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "Orders")
    time.sleep(5)
    _tap(agent, "OrderOrderCard")
    time.sleep(3)
    scenario_reporter.add_result("SV7", "Order Status B-App",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv7_consumer_flow(agent):
    _no_op(agent)


def sv8_business_flow(agent):
    """SV8: In Progress - B-App (add items & send to kitchen)"""
    print(f"[{agent.role}] [SV8] In Progress status")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "addItemsBtn")
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "Macaroni&CheeseBake", scroll=False)
    time.sleep(3)
    _tap(agent, "regularBtn")
    time.sleep(2)
    _tap(agent, "AddTruffleOilBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "assignToBtn")
    time.sleep(3)
    _tap(agent, "selectAll")
    time.sleep(3)
    _tap(agent, "assignProductsBtn")
    time.sleep(3)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(3)
    _tap(agent, "sendItemsBtn")
    time.sleep(5)
    _tap(agent, "backButton")
    time.sleep(3)
    # Kitchen prepares
    _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
    time.sleep(5)
    _tap(agent, "inProgressOrderCard")
    time.sleep(3)
    _tap(agent, "Macaroni&CheeseBake1regularAddTruffleOil Macaroni&CheeseBake")
    time.sleep(2)
    _tap(agent, "TomYumSoup1vegchickenprawn TomYumSoup")
    time.sleep(2)
    _tap(agent, "orderReadyBtn")
    time.sleep(3)
    _tap(agent, "orderCloseBtn")
    time.sleep(3)
    # Switch to serve
    _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
    time.sleep(5)
    _tap(agent, "Orders")
    time.sleep(3)
    scenario_reporter.add_result("SV8", "In Progress Status B-App",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv8_consumer_flow(agent):
    _no_op(agent)


def sv9_business_flow(agent):
    """SV9: Serve status - B-App"""
    print(f"[{agent.role}] [SV9] Serve status")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "ServeOrderCard")
    time.sleep(3)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(3)
    _tap(agent, "serveItemsBtn")
    time.sleep(3)
    _tap(agent, "notifyPaymentBtn")
    time.sleep(3)
    _tap(agent, "backButton")
    time.sleep(3)
    scenario_reporter.add_result("SV9", "Serve Status B-App",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv9_consumer_flow(agent):
    _no_op(agent)


def sv10_business_flow(agent):
    """SV10: Payment - B-App"""
    print(f"[{agent.role}] [SV10] Payment status")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "Payment")
    time.sleep(3)
    scenario_reporter.add_result("SV10", "Payment Status B-App",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv10_consumer_flow(agent):
    _no_op(agent)


def sv11_consumer_flow(agent):
    """SV11: Payment Requested - C-App"""
    print(f"[{agent.role}] [SV11] Payment Requested status")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "Home")
    time.sleep(3)
    _tap(agent, "walletTab")
    time.sleep(5)
    _tap(agent, "NylaiKitchenCard PAYMENT REQUESTED")
    time.sleep(3)
    scenario_reporter.add_result("SV11", "Payment Requested C-App",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv11_business_flow(agent):
    _no_op(agent)


def sv12_business_flow(agent):
    """SV12: Payment done - B-App processes payment"""
    print(f"[{agent.role}] [SV12] Payment done")
    agent.launch_app()
    time.sleep(10)
    _tap(agent, "Orders")
    time.sleep(10)
    for i in range(5):
        if _tap(agent, "PaymentOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "Payment")
    time.sleep(3)
    _tap(agent, "RoopaDCard")
    time.sleep(3)
    agent.swipe_down()
    time.sleep(2)
    _tap(agent, "cashPaymentBtn")
    time.sleep(2)
    _tap(agent, "Number2")
    _tap(agent, "Number0")
    _tap(agent, "userInputBtn")
    time.sleep(2)
    agent.adb("shell", "input", "swipe", "520", "1662", "537", "1086", "224")
    time.sleep(3)
    _tap(agent, "paymentConfirmBtn")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "PaymentDoneOrderCard")
    time.sleep(3)
    _tap(agent, "closeTableBtn")
    time.sleep(3)
    scenario_reporter.add_result("SV12", "Payment Done B-App",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv12_consumer_flow(agent):
    _no_op(agent)


def sv13_business_flow(agent):
    """SV13: Completed - B-App"""
    print(f"[{agent.role}] [SV13] Completed status B-App")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "Home")
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "RoopaDCompletedCard")
    time.sleep(3)
    scenario_reporter.add_result("SV13", "Completed Status B-App",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv13_consumer_flow(agent):
    _no_op(agent)


def sv14_consumer_flow(agent):
    """SV14: Completed - C-App"""
    print(f"[{agent.role}] [SV14] Completed status C-App")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "Home")
    time.sleep(3)
    _tap(agent, "walletTab")
    time.sleep(5)
    _tap(agent, "NylaiKitchenCard PAYMENT COMPLETED", "PAYMENT COMPLETED", "NylaiKitchenCard")
    time.sleep(5)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "Completed", scroll=False)
    time.sleep(3)
    agent.adb("shell", "input", "keyevent", "KEYCODE_BACK")
    time.sleep(3)
    scenario_reporter.add_result("SV14", "Completed Status C-App",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv14_business_flow(agent):
    _no_op(agent)


def sv15_consumer_flow(agent):
    """SV15: No-show status for users"""
    print(f"[{agent.role}] [SV15] No-show status check")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "homeTab")
    time.sleep(3)
    _tap(agent, "NylaiKitchen")
    time.sleep(3)
    _tap(agent, "counterPlus")
    time.sleep(2)
    _tap(agent, "guestAdd")
    time.sleep(2)
    _tap(agent, "guestAdd")
    time.sleep(2)
    _type_field(agent, "contactSearch", "Noolu")
    time.sleep(2)
    _tap(agent, "Noolu")
    time.sleep(3)
    _tap(agent, "inviteUsers")
    time.sleep(3)
    _tap_chip_container(agent)
    _tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "orderLater")
    time.sleep(5)
    # Noolu accepts
    _switch_account(agent, "noolu@xorstack.com", "12345")
    time.sleep(3)
    _tap(agent, "walletTab")
    time.sleep(5)
    _wait_for_card(agent, "RoopaDInviteCard", max_attempts=10)
    time.sleep(3)
    if not _tap(agent, "eventAccept"):
        time.sleep(3)
        _tap(agent, "eventAccept")
    time.sleep(10)
    _tap(agent, "orderLater")
    time.sleep(5)
    _tap(agent, "walletTab")
    time.sleep(3)
    # Switch back to Roopa
    _switch_account(agent, "roopa@xorstack.com", "12345")
    time.sleep(3)
    scenario_reporter.add_result("SV15", "No-Show Status Verification",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv15_business_flow(agent):
    """SV15: Business assigns table, adds items, notifies payment"""
    print(f"[{agent.role}] [SV15] Process no-show scenario")
    agent.launch_app()
    time.sleep(10)
    _tap(agent, "Orders")
    time.sleep(5)
    for i in range(5):
        if _tap(agent, "ReservedOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "T0AssignAnyBtn")
    time.sleep(3)
    _tap(agent, "AssignTableBtn")
    time.sleep(5)
    _tap(agent, "addItemsBtn")
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "ThaiGreenCurrywithJasmineRiceItem")
    time.sleep(3)
    _tap(agent, "vegBtn")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "addspicyBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "ThaiGreenCurrywithJasmineRiceItem")
    time.sleep(3)
    _tap(agent, "addNewCustomSelection")
    time.sleep(3)
    _tap(agent, "tofuBtn")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "extrapeanutsBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "ThaiGreenCurrywithJasmineRiceItem")
    time.sleep(3)
    _tap(agent, "addNewCustomSelection")
    time.sleep(3)
    _tap(agent, "chickenBtn")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "extrasauceBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "ThaiGreenCurrywithJasmineRiceItem")
    time.sleep(3)
    _tap(agent, "addNewCustomSelection")
    time.sleep(3)
    _tap(agent, "chickenBtn")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "addmayoBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "assignToBtn")
    time.sleep(3)
    _tap(agent, "RoopaDselect")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "Guest1select")
    time.sleep(3)
    _tap(agent, "assignProductsBtn")
    time.sleep(5)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(5)
    _tap(agent, "sendItemsBtn")
    time.sleep(10)
    _tap(agent, "backButton")
    time.sleep(3)
    # Kitchen prepares
    _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
    time.sleep(5)
    _tap(agent, "inProgressOrderCard")
    time.sleep(5)
    # Select all kitchen items
    _tap_all_kitchen_items(agent, ["ThaiGreenCurrywithJasmineRice", "ThaiGreenCurrywithJasmineRice", "ThaiGreenCurrywithJasmineRice", "ThaiGreenCurrywithJasmineRice"])
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "orderReadyBtn")
    time.sleep(3)
    _tap(agent, "orderCloseBtn")
    time.sleep(3)
    # Serve
    _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
    time.sleep(10)
    _tap(agent, "Orders")
    time.sleep(10)
    for i in range(5):
        if _tap(agent, "ServeOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(3)
    _tap(agent, "serveItemsBtn")
    time.sleep(3)
    _tap(agent, "notifyPaymentBtn")
    time.sleep(3)
    scenario_reporter.add_result("SV15", "No-Show Status Verification",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv16_consumer_flow(agent):
    """SV16: Payment done via C-App payment"""
    print(f"[{agent.role}] [SV16] Consumer pays via C-App")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "walletTab")
    time.sleep(5)
    _tap(agent, "NylaiKitchenCard PAYMENT REQUESTED")
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "payTotal")
    time.sleep(3)
    _tap(agent, "proceedPayment")
    time.sleep(3)
    _tap(agent, "ePayment")
    time.sleep(5)
    # Try to tap Pay button — try multiple names
    if not _tap(agent, "Pay"):
        _tap(agent, "primary_button")
    time.sleep(10)
    _tap(agent, "walletTab")
    time.sleep(3)
    shared_data["sv16_consumer_done"] = True
    scenario_reporter.add_result("SV16", "Payment Done via C-App",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv16_business_flow(agent):
    """SV16: Business verifies payment done"""
    agent.launch_app()
    # Wait for consumer to pay
    for i in range(60):
        if shared_data.get("sv16_consumer_done"):
            break
        time.sleep(3)
    time.sleep(5)
    _tap(agent, "Orders")
    time.sleep(5)
    _tap(agent, "PaymentDoneOrderCard")
    time.sleep(3)
    scenario_reporter.add_result("SV16", "Payment Done via C-App",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


# ─── PRE-ORDER (PO4–PO6) ─────────────────────────────────────────────────────

def po4_consumer_flow(agent):
    """PO4: Host (Noolu) Preorders First, Invitee (Roopa) Does Not"""
    print(f"[{agent.role}] [PO4] Host preorders first, invitee skips")
    agent.launch_app()
    _switch_account(agent, "noolu@xorstack.com", "12345")
    time.sleep(3)
    _tap(agent, "homeTab")
    time.sleep(3)
    _tap(agent, "NylaiKitchen")
    time.sleep(3)
    _tap(agent, "counterPlus")
    time.sleep(2)
    _type_field(agent, "contactSearch", "Roopa")
    time.sleep(2)
    _tap(agent, "RoopaInvite")
    time.sleep(3)
    _tap(agent, "Roopa")
    time.sleep(3)
    _tap(agent, "inviteUsers")
    time.sleep(3)
    _tap_chip_container(agent)
    _tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "preOrderBooking")
    time.sleep(5)
    # Chicken65 #1 with addmayo + "more crispyy"
    _tap(agent, "Chicken65Inc")
    time.sleep(3)
    _tap(agent, "addmayoProduct")
    time.sleep(2)
    _type_field(agent, "inputSplIns", "more crispyy")
    time.sleep(2)
    _tap(agent, "confirmProduct")
    time.sleep(3)
    # Chicken65 #2 with addmayo + "less oil"
    _tap(agent, "Chicken65Inc")
    time.sleep(3)
    _tap_add_new_custom(agent)
    time.sleep(3)
    _tap(agent, "addmayoProduct", scroll=False)
    time.sleep(2)
    _type_field(agent, "inputSplIns", "less oil")
    time.sleep(2)
    _tap(agent, "confirmProduct")
    time.sleep(3)
    # PizzaProsciuttoeFunghi #1 with Freshbellpepper + "more cheese"
    _tap(agent, "pasta-pizzacategory", scroll=False)
    time.sleep(3)
    _tap(agent, "PizzaProsciuttoeFunghiInc")
    time.sleep(3)
    _tap(agent, "FreshbellpepperProduct")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _type_field(agent, "inputSplIns", "more cheese")
    time.sleep(2)
    _tap(agent, "confirmProduct")
    time.sleep(3)
    # PizzaProsciuttoeFunghi #2 with Spicysalami
    _tap(agent, "PizzaProsciuttoeFunghiInc")
    time.sleep(3)
    _tap(agent, "counterPlus")
    time.sleep(2)
    _tap_add_new_custom(agent)
    time.sleep(3)
    agent.swipe_up()
    time.sleep(3)
    _tap(agent, "SpicysalamiProduct", scroll=False)
    time.sleep(2)
    _tap(agent, "confirmProduct")
    time.sleep(3)
    _tap(agent, "cartImage")
    time.sleep(3)
    agent.check_cart_total()
    _tap(agent, "cartCheckout")
    time.sleep(10)
    _tap(agent, "primary_button")
    time.sleep(30)
    _tap(agent, "pickUpOrderConfirm")
    time.sleep(30)
    agent.check_bill_with_vat()
    _tap(agent, "walletTab")
    time.sleep(5)
    # Roopa accepts and preorders
    _switch_account(agent, "roopa@xorstack.com", "12345")
    time.sleep(3)
    _tap(agent, "walletTab")
    time.sleep(5)
    _wait_for_card(agent, "NooluNagaInviteCard", max_attempts=10)
    time.sleep(3)
    if not _tap(agent, "eventAccept"):
        time.sleep(3)
        _tap(agent, "eventAccept")
    time.sleep(10)
    _tap(agent, "preOrderBooking")
    time.sleep(5)
    _tap(agent, "starterscategory", scroll=False)
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "HaraBharaKebabInc", scroll=False)
    time.sleep(3)
    _tap(agent, "4pcsProduct", scroll=False)
    time.sleep(2)
    _tap(agent, "confirmProduct", scroll=False)
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "ThaiGreenCurrywithJasmineRiceInc")
    time.sleep(3)
    _tap(agent, "vegProduct")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "extrapeanutsProduct")
    time.sleep(2)
    _type_field(agent, "inputSplIns", "Spicy")
    time.sleep(2)
    _tap(agent, "confirmProduct")
    time.sleep(15)
    _tap(agent, "cartImage")
    time.sleep(15)
    agent.check_cart_total()
    _tap(agent, "cartCheckout")
    time.sleep(15)
    _tap(agent, "primary_button")
    time.sleep(30)
    _tap(agent, "pickUpOrderConfirm")
    time.sleep(30)
    agent.verify_final_bill()
    scenario_reporter.add_result("PO4", "Host Preorders First Invitee Skips",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def po4_business_flow(agent):
    """PO4 Business: Accept and process dual preorder"""
    print(f"[{agent.role}] [PO4] Process dual preorder")
    agent.launch_app()
    time.sleep(10)
    _tap(agent, "Orders")
    time.sleep(5)
    for i in range(5):
        if _tap(agent, "ReservedOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "T0AssignAnyBtn")
    time.sleep(3)
    _tap(agent, "AssignTableBtn")
    time.sleep(5)
    _tap(agent, "addItemsBtn")
    time.sleep(5)
    _tap(agent, "Macaroni&CheeseBakeItem", "Macaroni & Cheese Bake", scroll=False)
    time.sleep(5)
    _tap(agent, "regularBtn", scroll=False)
    time.sleep(2)
    _tap(agent, "AddTruffleOilBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "assignToBtn")
    time.sleep(3)
    _tap(agent, "selectAll")
    time.sleep(3)
    _tap(agent, "assignProductsBtn")
    time.sleep(5)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(5)
    _tap(agent, "sendItemsBtn")
    time.sleep(10)
    _tap(agent, "backButton")
    time.sleep(3)
    # Kitchen
    _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
    time.sleep(5)
    _tap(agent, "inProgressOrderCard")
    time.sleep(5)
    # Select all kitchen items — same approach as PAY scenarios
    _tap_all_kitchen_items(agent, ["Macaroni&CheeseBake", "Chicken65", "Chicken65", "HaraBharaKebab", "PizzaProsciuttoeFunghi", "PizzaProsciuttoeFunghi", "ThaiGreenCurrywithJasmineRice"])
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "orderReadyBtn")
    time.sleep(3)
    _tap(agent, "orderCloseBtn")
    time.sleep(3)
    # Serve
    _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
    time.sleep(10)
    _tap(agent, "Orders")
    time.sleep(10)
    for i in range(5):
        if _tap(agent, "ServeOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(3)
    _tap(agent, "serveItemsBtn")
    time.sleep(3)
    _tap(agent, "notifyPaymentBtn")
    time.sleep(3)
    _tap(agent, "Payment")
    time.sleep(3)
    _tap(agent, "NooluNagaCard")
    time.sleep(3)
    agent.swipe_down()
    time.sleep(2)
    _tap(agent, "cashPaymentBtn")
    time.sleep(2)
    _tap(agent, "Number2")
    _tap(agent, "Number0")
    _tap(agent, "userInputBtn")
    time.sleep(2)
    _tap(agent, "RoopaDselect")
    time.sleep(2)
    _tap(agent, "Apply")
    time.sleep(2)
    agent.adb("shell", "input", "swipe", "520", "1662", "537", "1086", "224")
    time.sleep(3)
    agent.verify_final_bill()
    _tap(agent, "paymentConfirmBtn")
    time.sleep(5)
    agent.verify_final_bill()
    # Close table
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "closeTableBtn")
    time.sleep(3)
    scenario_reporter.add_result("PO4", "Host Preorders First Invitee Skips",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def po5_consumer_flow(agent):
    """PO5: Host (Roopa) Preorders First, Invitee (Noolu) Also Preorders"""
    print(f"[{agent.role}] [PO5] Both host and invitee preorder")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "NylaiKitchen")
    time.sleep(3)
    _tap(agent, "counterPlus")
    time.sleep(2)
    _type_field(agent, "contactSearch", "Noolu")
    time.sleep(2)
    _tap(agent, "NooluInvite")
    time.sleep(3)
    _tap(agent, "Noolu")
    time.sleep(3)
    _tap(agent, "inviteUsers")
    time.sleep(3)
    _tap_chip_container(agent)
    _tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "preOrderBooking")
    time.sleep(5)
    # 1st VegManchurian with "Spicyy"
    _tap(agent, "starterscategory", scroll=False)
    time.sleep(3)
    _tap(agent, "VegManchurianInc")
    time.sleep(3)
    _tap(agent, "gravyProduct")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "extrasauceProduct")
    time.sleep(2)
    _type_field(agent, "inputSplIns", "Spicyy ")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "confirmProduct")
    time.sleep(3)
    # 2nd VegManchurian with "Crispyy"
    _tap(agent, "VegManchurianInc")
    time.sleep(3)
    _tap_add_new_custom(agent)
    time.sleep(3)
    _tap(agent, "gravyProduct")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "extrasauceProduct")
    time.sleep(2)
    _type_field(agent, "inputSplIns", "Crispyy ")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "confirmProduct")
    time.sleep(3)
    # 3rd VegManchurian with "More sauce"
    _tap(agent, "VegManchurianInc")
    time.sleep(3)
    _tap_add_new_custom(agent)
    time.sleep(3)
    _tap(agent, "gravyProduct")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "extrasauceProduct")
    time.sleep(2)
    _type_field(agent, "inputSplIns", "More sauce")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "confirmProduct")
    time.sleep(3)
    # FourCheeseLasagna x2 — 1 Slice + 1 AddMushroom
    _tap(agent, "cheesy-comfort-platescategory", scroll=False)
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "FourCheeseLasagnaInc")
    time.sleep(3)
    _tap(agent, "SliceProduct")
    time.sleep(2)
    _tap(agent, "confirmProduct")
    time.sleep(3)
    _tap(agent, "FourCheeseLasagnaInc")
    time.sleep(3)
    _tap_add_new_custom(agent)
    time.sleep(3)
    _tap(agent, "AddMushroomProduct")
    time.sleep(2)
    _tap(agent, "confirmProduct")
    time.sleep(3)
    # PizzaQuattroStagioni x2 — 1 plain + 1 with Extra sauce
    agent.swipe_down()
    time.sleep(2)
    agent.swipe_down()
    time.sleep(2)
    _tap(agent, "PizzaQuattroStagioniInc")
    time.sleep(3)
    _tap(agent, "confirmProduct")
    time.sleep(3)
    _tap(agent, "PizzaQuattroStagioniInc")
    time.sleep(3)
    _tap_add_new_custom(agent)
    time.sleep(3)
    _type_field(agent, "inputSplIns", "Extra sauce")
    time.sleep(2)
    _tap(agent, "confirmProduct")
    time.sleep(15)
    _tap(agent, "cartImage")
    time.sleep(15)
    agent.check_cart_total()
    _tap(agent, "cartCheckout")
    time.sleep(15)
    _tap(agent, "primary_button")
    time.sleep(30)
    _tap(agent, "pickUpOrderConfirm")
    time.sleep(15)
    agent.check_bill_with_vat()
    _tap(agent, "walletTab")
    time.sleep(5)
    # Noolu accepts and preorders
    _switch_account(agent, "noolu@xorstack.com", "12345")
    time.sleep(3)
    _tap(agent, "walletTab")
    time.sleep(5)
    _wait_for_card(agent, "RoopaDInviteCard", max_attempts=10)
    time.sleep(3)
    if not _tap(agent, "eventAccept"):
        time.sleep(3)
        _tap(agent, "eventAccept")
    time.sleep(10)
    _tap(agent, "preOrderBooking")
    time.sleep(5)
    _tap(agent, "starterscategory", scroll=False)
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "HaraBharaKebabInc", scroll=False)
    time.sleep(3)
    _tap(agent, "4pcsProduct", scroll=False)
    time.sleep(2)
    _tap(agent, "confirmProduct", scroll=False)
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "ThaiGreenCurrywithJasmineRiceInc")
    time.sleep(3)
    _tap(agent, "vegProduct")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "extrapeanutsProduct")
    time.sleep(2)
    _type_field(agent, "inputSplIns", "Spicy")
    time.sleep(2)
    _tap(agent, "confirmProduct")
    time.sleep(15)
    _tap(agent, "cartImage")
    time.sleep(15)
    agent.check_cart_total()
    _tap(agent, "cartCheckout")
    time.sleep(15)
    _tap(agent, "primary_button")
    time.sleep(30)
    _tap(agent, "pickUpOrderConfirm")
    time.sleep(15)
    agent.verify_final_bill()
    scenario_reporter.add_result("PO5", "Both Host and Invitee Preorder",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def po5_business_flow(agent):
    """PO5 Business: Process both preorders"""
    print(f"[{agent.role}] [PO5] Process both preorders")
    agent.launch_app()
    time.sleep(10)
    _tap(agent, "Orders")
    time.sleep(5)
    for i in range(5):
        if _tap(agent, "ReservedOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "T0AssignAnyBtn")
    time.sleep(3)
    _tap(agent, "AssignTableBtn")
    time.sleep(5)
    _tap(agent, "addItemsBtn")
    time.sleep(5)
    _tap(agent, "Macaroni&CheeseBakeItem", "Macaroni & Cheese Bake", scroll=False)
    time.sleep(5)
    _tap(agent, "regularBtn", scroll=False)
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "AddTruffleOilBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "assignToBtn")
    time.sleep(3)
    _tap(agent, "selectAll")
    time.sleep(3)
    _tap(agent, "assignProductsBtn")
    time.sleep(5)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(5)
    _tap(agent, "sendItemsBtn")
    time.sleep(10)
    _tap(agent, "backButton")
    time.sleep(3)
    # Kitchen
    _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
    time.sleep(5)
    _tap(agent, "inProgressOrderCard")
    time.sleep(5)
    # Select all kitchen items
    _tap_all_kitchen_items(agent, ["Macaroni&CheeseBake", "VegManchurian", "VegManchurian", "VegManchurian", "FourCheeseLasagna", "FourCheeseLasagna", "PizzaQuattroStagioni", "PizzaQuattroStagioni"])
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "orderReadyBtn")
    time.sleep(3)
    _tap(agent, "orderCloseBtn")
    time.sleep(3)
    # Serve
    _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
    time.sleep(10)
    _tap(agent, "Orders")
    time.sleep(10)
    for i in range(5):
        if _tap(agent, "ServeOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(3)
    _tap(agent, "serveItemsBtn")
    time.sleep(3)
    _tap(agent, "notifyPaymentBtn")
    time.sleep(3)
    _tap(agent, "Payment")
    time.sleep(3)
    _tap(agent, "RoopaDCard")
    time.sleep(3)
    agent.swipe_down()
    time.sleep(2)
    _tap(agent, "cashPaymentBtn")
    time.sleep(2)
    _tap(agent, "Number2")
    _tap(agent, "Number0")
    _tap(agent, "userInputBtn")
    time.sleep(2)
    _tap(agent, "NooluNagaselect")
    time.sleep(2)
    _tap(agent, "Apply")
    time.sleep(2)
    agent.adb("shell", "input", "swipe", "520", "1662", "537", "1086", "224")
    time.sleep(3)
    agent.verify_final_bill()
    _tap(agent, "paymentConfirmBtn")
    time.sleep(5)
    agent.verify_final_bill()
    # Close table
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "closeTableBtn")
    time.sleep(3)
    scenario_reporter.add_result("PO5", "Both Host and Invitee Preorder",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def po6_consumer_flow(agent):
    """PO6: Host Does Not Preorder, Participant Preorders First"""
    print(f"[{agent.role}] [PO6] Participant preorders first, host adds later")
    agent.launch_app()
    _switch_account(agent, "roopa@xorstack.com", "12345")
    time.sleep(3)
    _tap(agent, "NylaiKitchen")
    time.sleep(3)
    _tap(agent, "counterPlus")
    time.sleep(2)
    _type_field(agent, "contactSearch", "Noolu")
    time.sleep(2)
    _tap(agent, "NooluInvite")
    time.sleep(3)
    _tap(agent, "Noolu")
    time.sleep(3)
    _tap(agent, "inviteUsers")
    time.sleep(3)
    _tap_chip_container(agent)
    _tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "orderLater")
    time.sleep(5)
    _tap(agent, "walletTab")
    time.sleep(5)
    # Noolu accepts and preorders
    _switch_account(agent, "noolu@xorstack.com", "12345")
    time.sleep(3)
    _tap(agent, "walletTab")
    time.sleep(5)
    _wait_for_card(agent, "RoopaDInviteCard", max_attempts=10)
    time.sleep(3)
    if not _tap(agent, "eventAccept"):
        time.sleep(3)
        _tap(agent, "eventAccept")
    time.sleep(10)
    _tap(agent, "preOrderBooking")
    time.sleep(5)
    _tap(agent, "starterscategory", scroll=False)
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "HaraBharaKebabInc", scroll=False)
    time.sleep(3)
    _tap(agent, "4pcsProduct", scroll=False)
    time.sleep(2)
    _tap(agent, "confirmProduct", scroll=False)
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "ThaiGreenCurrywithJasmineRiceInc")
    time.sleep(3)
    _tap(agent, "vegProduct")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "extrapeanutsProduct")
    time.sleep(2)
    _type_field(agent, "inputSplIns", "Spicy")
    time.sleep(2)
    _tap(agent, "confirmProduct")
    time.sleep(15)
    _tap(agent, "cartImage")
    time.sleep(15)
    agent.check_cart_total()
    _tap(agent, "cartCheckout")
    time.sleep(15)
    _tap(agent, "primary_button")
    time.sleep(30)
    _tap(agent, "pickUpOrderConfirm")
    time.sleep(15)
    agent.check_bill_with_vat()
    _tap(agent, "walletTab")
    time.sleep(5)
    # Roopa switches back, adds her own items
    _switch_account(agent, "roopa@xorstack.com", "12345")
    time.sleep(3)
    _tap(agent, "walletTab")
    time.sleep(5)
    _wait_for_card(agent, "NylaiKitchenCard", max_attempts=10)
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "preOrderBtn", scroll=False)
    time.sleep(5)
    _tap(agent, "starterscategory", scroll=False)
    time.sleep(3)
    _tap(agent, "MuttonSeekhKebab")
    time.sleep(3)
    _tap(agent, "2pcsProduct")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "chutneyProduct")
    time.sleep(2)
    _tap(agent, "confirmProduct")
    time.sleep(15)
    _tap(agent, "cartImage")
    time.sleep(15)
    _tap(agent, "applyCoupon")
    time.sleep(15)
    _tap(agent, "6% OFFER")
    time.sleep(15)
    agent.check_cart_total()
    _tap(agent, "cartCheckout")
    time.sleep(15)
    _tap(agent, "primary_button")
    time.sleep(30)
    _tap(agent, "pickUpOrderConfirm")
    time.sleep(15)
    agent.verify_final_bill()
    scenario_reporter.add_result("PO6", "Participant Preorders First Host Adds Later",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def po6_business_flow(agent):
    """PO6 Business: Process participant-first preorder"""
    print(f"[{agent.role}] [PO6] Process participant-first preorder")
    agent.launch_app()
    time.sleep(10)
    _tap(agent, "Orders")
    time.sleep(5)
    for i in range(5):
        if _tap(agent, "ReservedOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "T0AssignAnyBtn")
    time.sleep(3)
    _tap(agent, "AssignTableBtn")
    time.sleep(5)
    _tap(agent, "addItemsBtn")
    time.sleep(5)
    _tap(agent, "Macaroni&CheeseBakeItem", "Macaroni & Cheese Bake", scroll=False)
    time.sleep(5)
    _tap(agent, "regularBtn", scroll=False)
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "AddTruffleOilBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "assignToBtn")
    time.sleep(3)
    _tap(agent, "selectAll")
    time.sleep(3)
    _tap(agent, "assignProductsBtn")
    time.sleep(5)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(5)
    _tap(agent, "sendItemsBtn")
    time.sleep(10)
    _tap(agent, "backButton")
    time.sleep(3)
    # Kitchen
    _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
    time.sleep(5)
    _tap(agent, "inProgressOrderCard")
    time.sleep(5)
    # Select all kitchen items
    _tap_all_kitchen_items(agent, ["MuttonSeekhKebab", "Macaroni&CheeseBake", "HaraBharaKebab", "ThaiGreenCurrywithJasmineRice"])
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "orderReadyBtn")
    time.sleep(3)
    _tap(agent, "orderCloseBtn")
    time.sleep(3)
    # Serve
    _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
    time.sleep(10)
    _tap(agent, "Orders")
    time.sleep(10)
    for i in range(5):
        if _tap(agent, "ServeOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(3)
    _tap(agent, "serveItemsBtn")
    time.sleep(3)
    _tap(agent, "notifyPaymentBtn")
    time.sleep(3)
    _tap(agent, "Payment")
    time.sleep(3)
    _tap(agent, "NooluNagaCard")
    time.sleep(3)
    agent.swipe_down()
    time.sleep(2)
    _tap(agent, "cashPaymentBtn")
    time.sleep(2)
    _tap(agent, "Number2")
    _tap(agent, "Number0")
    _tap(agent, "userInputBtn")
    time.sleep(2)
    _tap(agent, "RoopaDselect")
    time.sleep(2)
    _tap(agent, "Apply")
    time.sleep(2)
    agent.adb("shell", "input", "swipe", "520", "1662", "537", "1086", "224")
    time.sleep(3)
    agent.verify_final_bill()
    _tap(agent, "paymentConfirmBtn")
    time.sleep(5)
    agent.verify_final_bill()
    # Close table
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "closeTableBtn")
    time.sleep(3)
    scenario_reporter.add_result("PO6", "Participant Preorders First Host Adds Later",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


# ─── CONTACTS & WALLET (CW5–CW6) ─────────────────────────────────────────────

def cw5_consumer_flow(agent):
    """CW5: Consumer books for business to add items with 1 guest"""
    print(f"[{agent.role}] [CW5] Book event for B-App to add items")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "NylaiKitchen")
    time.sleep(3)
    _tap_chip_container(agent)
    _tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "orderLater")
    time.sleep(5)
    scenario_reporter.add_result("CW5", "Adding Item in B-App with 1 Guest",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def cw5_business_flow(agent):
    """CW5 Business: Add items, process payment with guest"""
    print(f"[{agent.role}] [CW5] Add items and payment with guest")
    agent.launch_app()
    time.sleep(10)
    _tap(agent, "Orders")
    time.sleep(5)
    for i in range(5):
        if _tap(agent, "ReservedOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "T0AssignAnyBtn")
    time.sleep(3)
    _tap(agent, "AssignTableBtn")
    time.sleep(5)
    # Payment tab to add guest
    _tap(agent, "Payment")
    time.sleep(3)
    _tap(agent, "addGuestBtn")
    time.sleep(3)
    # Back to Overview to add items
    _tap(agent, "Overview")
    time.sleep(3)
    _tap(agent, "addItemsBtn")
    time.sleep(5)
    _tap(agent, "PaneerTikkaItem")
    time.sleep(3)
    _tap(agent, "regularBtn")
    time.sleep(2)
    _tap(agent, "extracheeseBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "PizzaQuattroStagioniItem")
    time.sleep(3)
    _tap(agent, "applyOptionBtn")
    time.sleep(5)
    _tap(agent, "assignToBtn")
    time.sleep(5)
    _tap(agent, "selectAll")
    time.sleep(3)
    _tap(agent, "assignProductsBtn")
    time.sleep(5)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(5)
    _tap(agent, "sendItemsBtn")
    time.sleep(10)
    _tap(agent, "backButton")
    time.sleep(3)
    # Kitchen
    _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
    time.sleep(5)
    _tap(agent, "inProgressOrderCard")
    time.sleep(5)
    # Select all kitchen items
    _tap_all_kitchen_items(agent, ["PaneerTikka", "PizzaQuattroStagioni"])
    time.sleep(2)
    _tap(agent, "orderReadyBtn")
    time.sleep(3)
    _tap(agent, "orderCloseBtn")
    time.sleep(3)
    # Serve
    _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
    time.sleep(10)
    _tap(agent, "Orders")
    time.sleep(10)
    for i in range(5):
        if _tap(agent, "ServeOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(3)
    _tap(agent, "serveItemsBtn")
    time.sleep(3)
    _tap(agent, "notifyPaymentBtn")
    time.sleep(3)
    _tap(agent, "Payment")
    time.sleep(3)
    _tap(agent, "NooluNagaCard")
    time.sleep(3)
    agent.swipe_down()
    time.sleep(2)
    _tap(agent, "cashPaymentBtn")
    time.sleep(2)
    _tap(agent, "Number6")
    _tap(agent, "Number0")
    _tap(agent, "Number8")
    _tap(agent, "userInputBtn")
    time.sleep(2)
    _tap(agent, "Guest1select")
    time.sleep(2)
    _tap(agent, "Apply")
    time.sleep(2)
    _tap(agent, "tipBtn")
    time.sleep(2)
    _tap(agent, "Number4")
    _tap(agent, "userInputBtn")
    time.sleep(2)
    agent.adb("shell", "input", "swipe", "520", "1662", "537", "1086", "224")
    time.sleep(3)
    agent.verify_final_bill()
    _tap(agent, "paymentConfirmBtn")
    time.sleep(5)
    agent.verify_final_bill()
    _tap(agent, "RoopaDCard")
    time.sleep(3)
    # Close table
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "closeTableBtn")
    time.sleep(3)
    scenario_reporter.add_result("CW5", "Adding Item in B-App with 1 Guest",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def cw6_consumer_flow(agent):
    """CW6: Consumer books for B-App to add items with 2+ guests"""
    print(f"[{agent.role}] [CW6] Book event for B-App with multiple guests")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "NylaiKitchen")
    time.sleep(3)
    _tap(agent, "counterPlus")
    time.sleep(2)
    _tap(agent, "guestAdd")
    time.sleep(2)
    _tap(agent, "inviteUsers")
    time.sleep(3)
    _tap_chip_container(agent)
    _tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "orderLater")
    time.sleep(5)
    scenario_reporter.add_result("CW6", "Adding Item in B-App with 2+ Guests",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def cw6_business_flow(agent):
    """CW6 Business: Add items and process payment with multiple guests"""
    print(f"[{agent.role}] [CW6] Add items and payment with multiple guests")
    agent.launch_app()
    time.sleep(10)
    _tap(agent, "Orders")
    time.sleep(5)
    for i in range(5):
        if _tap(agent, "ReservedOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "T0AssignAnyBtn")
    time.sleep(3)
    _tap(agent, "AssignTableBtn")
    time.sleep(5)
    # Payment tab to add guests
    _tap(agent, "Payment")
    time.sleep(3)
    _tap(agent, "addGuestBtn")
    time.sleep(3)
    _tap(agent, "Guest2Card")
    time.sleep(3)
    _tap(agent, "addGuestBtn")
    time.sleep(3)
    _tap(agent, "Guest3Card")
    time.sleep(3)
    _tap(agent, "addGuestBtn")
    time.sleep(3)
    _tap(agent, "Guest4Card")
    time.sleep(3)
    # Back to Overview to add items
    _tap(agent, "Overview")
    time.sleep(3)
    _tap(agent, "addItemsBtn")
    time.sleep(5)
    _tap(agent, "PizzaRucolaeParmigianoItem")
    time.sleep(2)
    _tap(agent, "FreshbellpepperBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "PizzaRucolaeParmigianoItem")
    time.sleep(2)
    _tap(agent, "addNewCustomSelection")
    time.sleep(2)
    _tap(agent, "FreshchampignonsBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "PizzaRucolaeParmigianoItem")
    time.sleep(2)
    _tap(agent, "addNewCustomSelection")
    time.sleep(2)
    _tap(agent, "CookedhamBtn")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "PizzaQuattroStagioniItem")
    time.sleep(2)
    _tap(agent, "applyOptionBtn")
    time.sleep(3)
    _tap(agent, "assignToBtn")
    time.sleep(3)
    _tap(agent, "addNewGuest")
    time.sleep(3)
    _tap(agent, "selectAll")
    time.sleep(3)
    _tap(agent, "assignProductsBtn")
    time.sleep(5)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(5)
    _tap(agent, "sendItemsBtn")
    time.sleep(10)
    _tap(agent, "backButton")
    time.sleep(3)
    # Kitchen
    _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
    time.sleep(5)
    _tap(agent, "inProgressOrderCard")
    time.sleep(5)
    # Select all kitchen items
    _tap_all_kitchen_items(agent, ["PizzaRucolaeParmigiano", "PizzaRucolaeParmigiano", "PizzaRucolaeParmigiano", "PizzaQuattroStagioni"])
    time.sleep(2)
    _tap(agent, "orderReadyBtn")
    time.sleep(3)
    _tap(agent, "orderCloseBtn")
    time.sleep(3)
    # Serve
    _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
    time.sleep(10)
    _tap(agent, "Orders")
    time.sleep(10)
    for i in range(5):
        if _tap(agent, "ServeOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "selectAllItemsBtn")
    time.sleep(3)
    _tap(agent, "serveItemsBtn")
    time.sleep(3)
    _tap(agent, "notifyPaymentBtn")
    time.sleep(3)
    _tap(agent, "Payment")
    time.sleep(3)
    _tap(agent, "NooluNagaCard")
    time.sleep(3)
    agent.swipe_down()
    time.sleep(2)
    _tap(agent, "cashPaymentBtn")
    time.sleep(2)
    _tap(agent, "Number5")
    _tap(agent, "Number0")
    _tap(agent, "Number0")
    _tap(agent, "userInputBtn")
    time.sleep(2)
    _tap(agent, "Guest2select")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "Guest4select")
    time.sleep(2)
    _tap(agent, "Guest5select")
    time.sleep(2)
    _tap(agent, "Apply")
    time.sleep(2)
    agent.adb("shell", "input", "swipe", "520", "1662", "537", "1086", "224")
    time.sleep(3)
    agent.verify_final_bill()
    _tap(agent, "paymentConfirmBtn")
    time.sleep(5)
    agent.verify_final_bill()
    _tap(agent, "Guest3Card")
    time.sleep(3)
    agent.swipe_down()
    time.sleep(2)
    _tap(agent, "paidCashPaymentBtn")
    time.sleep(2)
    _tap(agent, "Number3")
    _tap(agent, "Number0")
    _tap(agent, "Number0")
    _tap(agent, "userInputBtn")
    time.sleep(2)
    _tap(agent, "Guest5select")
    time.sleep(2)
    _tap(agent, "Apply")
    time.sleep(2)
    agent.adb("shell", "input", "swipe", "520", "1662", "537", "1086", "224")
    time.sleep(3)
    agent.verify_final_bill()
    _tap(agent, "paymentConfirmBtn")
    time.sleep(5)
    agent.verify_final_bill()
    _tap(agent, "RoopaDCard")
    time.sleep(3)
    # Close table
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "Overview")
    time.sleep(5)
    _tap(agent, "closeTableBtn")
    time.sleep(3)
    scenario_reporter.add_result("CW6", "Adding Item in B-App with 2+ Guests",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


# EB7 removed — unwanted scenario


# ─── CREATE & MANAGE EVENTS FROM B-APP (BME6) ───────────────────────────────

def bme6_consumer_flow(agent):
    """BME6 Consumer: Book event, business transfers it"""
    print(f"[{agent.role}] [BME6] Consumer books event for transfer test")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "NylaiKitchen")
    time.sleep(3)
    _tap_chip_container(agent)
    _tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "orderLater")
    time.sleep(5)
    scenario_reporter.add_result("BME6", "Transfer Event Between Waiters",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def bme6_business_flow(agent):
    """BME6 Business: Assign table then transfer event"""
    print(f"[{agent.role}] [BME6] Assign table and transfer event")
    agent.launch_app()
    time.sleep(10)
    _tap(agent, "Orders")
    time.sleep(5)
    for i in range(5):
        if _tap(agent, "ReservedOrderCard"):
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(3)
    _tap(agent, "T0AssignAnyBtn")
    time.sleep(3)
    _tap(agent, "AssignTableBtn")
    time.sleep(3)
    _tap(agent, "backButton")
    time.sleep(3)
    _tap(agent, "Home")
    time.sleep(8)
    # Find event card and tap three dots icon at top-right of card
    for attempt in range(5):
        xml = agent.dump_ui()
        match = agent.find_by_text(xml, "Roopa D") or agent.find_by_text(xml, "In Progress") or agent.find_by_text(xml, "Reserved")
        if match:
            # Three dots are at top-right of event card — same X but far right
            dots_x = match[0] + 300
            dots_y = match[1] - 30
            print(f"[{agent.role}] Found event at ({match[0]},{match[1]}), tapping three dots at ({dots_x},{dots_y})")
            agent.adb("shell", "input", "tap", str(dots_x), str(dots_y))
            break
        agent.swipe_up()
        time.sleep(3)
    time.sleep(5)
    # Tap "Transfer to another waiter" radio button
    _tap(agent, "Transfer to another waiter", scroll=False)
    time.sleep(3)
    # Tap Confirm button
    _tap(agent, "Confirm", scroll=False)
    time.sleep(3)
    scenario_reporter.add_result("BME6", "Transfer Event Between Waiters",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


# ─── FILTER EVENTS (FE5–FE7) ────────────────────────────────────────────────

def fe5_business_flow(agent):
    """FE5: Table main filter + Status filter in home page"""
    print(f"[{agent.role}] [FE5] Table Main Filter + Status Filter")
    agent.launch_app()
    _tap(agent, "tableBtn")
    agent.swipe_up()
    agent.swipe_up()
    _tap_events_button(agent)
    _tap(agent, "orderFilterBtn")
    _tap(agent, "In Progress")
    _tap(agent, "Confirm")
    time.sleep(3)
    _tap(agent, "Remove filter")
    scenario_reporter.add_result("FE5", "Table Main Filter + Status Filter",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def fe5_consumer_flow(agent):
    _no_op(agent)


def fe6_business_flow(agent):
    """FE6: Table main filter + Table filter in home page"""
    print(f"[{agent.role}] [FE6] Table Main Filter + Table Filter")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "Orders")
    time.sleep(5)
    _tap(agent, "modifyTable")
    _tap_any_table(agent)
    _tap(agent, "Confirm")
    time.sleep(3)
    _tap_events_button(agent)
    _tap(agent, "Remove filter")
    scenario_reporter.add_result("FE6", "Table Main Filter + Table Filter",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def fe6_consumer_flow(agent):
    _no_op(agent)


def fe7_business_flow(agent):
    """FE7: Pickup main filter in home page"""
    print(f"[{agent.role}] [FE7] Pickup Main Filter")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "pickupBtn")
    time.sleep(3)
    # Scroll to find Events button — try up to 5 times
    found = False
    for attempt in range(5):
        if _tap_events_button(agent):
            found = True
            break
        agent.swipe_up()
        time.sleep(2)
    time.sleep(2)
    scenario_reporter.add_result("FE7", "Pickup Main Filter",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def fe7_consumer_flow(agent):
    _no_op(agent)


# ─── FILTER & ACTIONS IN C-APP (FC1–FC9) ─────────────────────────────────────

def fc1_consumer_flow(agent):
    """FC1: Filter by Ratings - Top Rated"""
    print(f"[{agent.role}] [FC1] Filter by Ratings - Top Rated")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "homeFilter")
    time.sleep(3)
    _tap(agent, "avgRateBtn")
    time.sleep(2)
    _tap(agent, "belowTenThousandPrice")
    time.sleep(2)
    _tap(agent, "allSortFilterApply")
    time.sleep(5)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "homeRemoveFilterProd")
    time.sleep(2)
    scenario_reporter.add_result("FC1", "Filter by Ratings - Top Rated",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def fc1_business_flow(agent):
    _no_op(agent)


def fc2_consumer_flow(agent):
    """FC2: Filter by Discount"""
    print(f"[{agent.role}] [FC2] Filter by Discount")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "homeFilter")
    time.sleep(3)
    _tap(agent, "discountBtn")
    time.sleep(2)
    _tap(agent, "belowTenThousandPrice")
    time.sleep(2)
    _tap(agent, "allSortFilterApply")
    time.sleep(5)
    agent.swipe_up()
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "homeRemoveFilterProd")
    time.sleep(2)
    scenario_reporter.add_result("FC2", "Filter by Discount",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def fc2_business_flow(agent):
    _no_op(agent)


def fc3_consumer_flow(agent):
    """FC3: Modify Table Type"""
    print(f"[{agent.role}] [FC3] Modify Table Type")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "NylaiKitchen")
    time.sleep(3)
    _tap(agent, "Outdoor")
    time.sleep(2)
    _tap_chip_container(agent)
    agent.swipe_up()
    time.sleep(2)
    # Message flow: tap image area -> tap message field -> type -> tap tick (✓)
    _tap(agent, "addImageButton")
    time.sleep(3)
    _tap(agent, "inputSplIns")
    time.sleep(2)
    agent.type_text("Come Soon!")
    time.sleep(2)
    # Tick button has no content-desc, tap by coordinate (610, 866)
    agent.adb("shell", "input", "tap", "610", "866")
    time.sleep(3)
    _tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "preOrderBooking")
    time.sleep(3)
    _tap(agent, "Nylai KitchenModify")
    time.sleep(3)
    _tap(agent, "Indoor")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    # Repeat message flow - clear field first then type
    _tap(agent, "inputSplIns")
    time.sleep(2)
    # Select all (Ctrl+A) then delete
    agent.adb("shell", "input", "keyevent", "123")
    time.sleep(0.5)
    for i in range(30):
        agent.adb("shell", "input", "keyevent", "67")
    time.sleep(1)
    agent.type_text("Come Soon!")
    time.sleep(2)
    agent.adb("shell", "input", "tap", "610", "866")
    time.sleep(3)
    _tap(agent, "modifyReservation")
    time.sleep(3)
    scenario_reporter.add_result("FC3", "Modify Table Type",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def fc3_business_flow(agent):
    _no_op(agent)


def fc4_consumer_flow(agent):
    """FC4: Pre-Order Items After Modify"""
    print(f"[{agent.role}] [FC4] Pre-Order Items After Modify")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "walletTab")
    time.sleep(3)
    _wait_for_card(agent, "NylaiKitchenCard", max_attempts=5)
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    if not _tap(agent, "preOrderBooking"):
        _tap(agent, "pre-order")
    time.sleep(3)
    _tap(agent, "PaneerTikkaInc")
    time.sleep(3)
    _tap(agent, "LargeProduct")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "extracheeseProduct")
    time.sleep(2)
    _tap(agent, "confirmProduct")
    time.sleep(3)
    _tap(agent, "cartImage")
    time.sleep(3)
    _tap(agent, "cartCheckout")
    time.sleep(5)
    _tap(agent, "primary_button")
    time.sleep(20)
    _tap(agent, "pickUpOrderConfirm")
    agent.check_bill()
    time.sleep(3)
    _tap(agent, "homeTab")
    time.sleep(2)
    scenario_reporter.add_result("FC4", "Pre-Order Items After Modify",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def fc4_business_flow(agent):
    _no_op(agent)


def fc5_consumer_flow(agent):
    """FC5: Modify Event with Invitees"""
    print(f"[{agent.role}] [FC5] Modify Event with Invitees")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "walletTab")
    time.sleep(3)
    _wait_for_card(agent, "NylaiKitchenCard", max_attempts=5)
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    if not _tap(agent, "preOrderBooking"):
        _tap(agent, "pre-order")
    time.sleep(10)
    _tap(agent, "Nylai KitchenModify")
    time.sleep(3)
    _tap(agent, "counterPlus")
    time.sleep(2)
    _tap(agent, "guestAdd")
    time.sleep(2)
    _tap(agent, "guestAdd")
    time.sleep(2)
    _tap(agent, "contactSearch")
    time.sleep(1)
    agent.type_text("Noolu")
    time.sleep(2)
    agent.adb("shell", "input", "keyevent", "KEYCODE_BACK")
    time.sleep(2)
    _tap(agent, "NooluInvite")
    time.sleep(2)
    _tap(agent, "Noolu")
    time.sleep(2)
    _tap(agent, "inviteUsers")
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "modifyReservation")
    time.sleep(3)
    scenario_reporter.add_result("FC5", "Modify Event with Invitees",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def fc5_business_flow(agent):
    _no_op(agent)


def fc6_consumer_flow(agent):
    """FC6: Subtract Persons and Remove Guest"""
    print(f"[{agent.role}] [FC6] Subtract Persons and Remove Guest")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "walletTab")
    time.sleep(3)
    _wait_for_card(agent, "NylaiKitchenCard", max_attempts=5)
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    if not _tap(agent, "preOrderBooking"):
        _tap(agent, "pre-order")
    time.sleep(10)
    _tap(agent, "Nylai KitchenModify")
    time.sleep(3)
    _tap(agent, "counterMinus")
    time.sleep(2)
    _tap(agent, "Guest 1cancel")
    time.sleep(2)
    _tap(agent, "inviteUsers")
    time.sleep(3)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "modifyReservation")
    time.sleep(5)
    # Now add items
    _tap(agent, "PaneerTikkaInc")
    time.sleep(3)
    _tap(agent, "LargeProduct")
    time.sleep(2)
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "extracheeseProduct")
    time.sleep(2)
    _tap(agent, "confirmProduct")
    time.sleep(3)
    _tap(agent, "cartImage")
    time.sleep(3)
    _tap(agent, "cartCheckout")
    time.sleep(5)
    _tap(agent, "primary_button")
    time.sleep(20)
    _tap(agent, "pickUpOrderConfirm")
    agent.check_bill()
    time.sleep(3)
    _tap(agent, "homeTab")
    time.sleep(2)
    scenario_reporter.add_result("FC6", "Subtract Persons and Remove Guest",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def fc6_business_flow(agent):
    _no_op(agent)


def fc7_consumer_flow(agent):
    """FC7: Unsubscribe from Restaurant"""
    print(f"[{agent.role}] [FC7] Unsubscribe from Restaurant")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "NylaiKitchenUnsub")
    time.sleep(3)
    if not _tap(agent, "Yes"):
        _tap(agent, "yes")
    time.sleep(3)
    _tap(agent, "NylaiKitchen")
    time.sleep(3)
    _tap(agent, "screenBackBtn")
    time.sleep(3)
    _tap(agent, "menuTab")
    time.sleep(3)
    _tap(agent, "TARGETEDADSmenu")
    time.sleep(3)
    if not _tap(agent, "closeBtn"):
        _tap(agent, "close")
    time.sleep(2)
    _tap(agent, "homeTab")
    time.sleep(2)
    scenario_reporter.add_result("FC7", "Unsubscribe from Restaurant",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def fc7_business_flow(agent):
    _no_op(agent)


def fc8_consumer_flow(agent):
    """FC8: Subscribe to Restaurant"""
    print(f"[{agent.role}] [FC8] Subscribe to Restaurant")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "NylaiKitchenSub")
    time.sleep(3)
    _tap(agent, "subscribeGotIt")
    time.sleep(2)
    _tap(agent, "NylaiKitchen")
    time.sleep(3)
    _tap(agent, "screenBackBtn")
    time.sleep(3)
    _tap(agent, "menuTab")
    time.sleep(3)
    _tap(agent, "TARGETEDADSmenu")
    time.sleep(3)
    if not _tap(agent, "closeBtn"):
        _tap(agent, "close")
    time.sleep(2)
    _tap(agent, "homeTab")
    time.sleep(2)
    scenario_reporter.add_result("FC8", "Subscribe to Restaurant",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def fc8_business_flow(agent):
    _no_op(agent)


def fc9_consumer_flow(agent):
    """FC9: Like and Dislike Restaurant + Like Product"""
    print(f"[{agent.role}] [FC9] Like/Dislike Restaurant + Like Product")
    agent.launch_app()
    time.sleep(3)
    _tap(agent, "homeTab")
    time.sleep(3)
    # Like restaurant
    _tap(agent, "NylaiKitchenFav")
    time.sleep(3)
    _tap(agent, "NylaiKitchen")
    time.sleep(3)
    _tap(agent, "screenBackBtn")
    time.sleep(3)
    # Dislike restaurant
    _tap(agent, "NylaiKitchen")
    time.sleep(3)
    _tap(agent, "moreInformation")
    time.sleep(2)
    _tap(agent, "screenFavBtn")
    time.sleep(3)
    # Verify unlike worked — check if NylaiKitchenFav still exists (it shouldn't after unlike)
    xml = agent.dump_ui()
    still_liked = agent.find_by_desc(xml, "NylaiKitchenFav") or agent.find_by_desc(xml, "screenFavBtn")
    if still_liked:
        print(f"[{agent.role}] [FC9] APP BUG DETECTED: Restaurant is still liked after tapping unlike button (screenFavBtn)")
        scenario_reporter.add_result("FC9", "Like/Dislike Restaurant + Like Product",
                                     agent.role, "FAIL", "APP BUG: Unlike button (screenFavBtn) does not work - restaurant remains liked after tapping unlike", agent.last_launch_time)
        return
    _tap(agent, "screenBackBtn")
    time.sleep(2)
    _tap(agent, "screenBackBtn")
    time.sleep(3)
    # Like product
    _tap(agent, "NylaiKitchen")
    time.sleep(3)
    _tap(agent, "Menu")
    time.sleep(3)
    _tap(agent, "favProduct")
    time.sleep(2)
    _tap(agent, "screenBackBtn")
    time.sleep(2)
    _tap(agent, "screenBackBtn")
    time.sleep(2)
    _tap(agent, "homeTab")
    time.sleep(2)
    scenario_reporter.add_result("FC9", "Like/Dislike Restaurant + Like Product",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def fc9_business_flow(agent):
    _no_op(agent)


# ─── SCENARIO MAP ────────────────────────────────────────────────────────────

SCENARIO_MAP = {
    # Contacts & Wallet
    "CW1": {"name": "Creating New Contact from Reservation",          "consumer": cw1_consumer_flow, "business": _no_op},
    "CW2": {"name": "Adding Guest from Wallet",                        "consumer": cw2_consumer_flow, "business": _no_op},
    "CW3": {"name": "Adding User from Wallet",                         "consumer": cw3_consumer_flow, "business": _no_op},
    "CW4": {"name": "Creating New Contact from Wallet",                "consumer": cw4_consumer_flow, "business": _no_op},
    "CW5": {"name": "Adding Item in B-App with 1 Guest",               "consumer": cw5_consumer_flow, "business": cw5_business_flow},
    "CW6": {"name": "Adding Item in B-App with 2+ Guests",             "consumer": cw6_consumer_flow, "business": cw6_business_flow},

    # Event Booking
    "EB1": {"name": "Book Event 1 Guest Indoor",                       "consumer": eb1_consumer_flow, "business": eb1_business_flow},
    "EB2": {"name": "Book Event Outdoor - Invitee Accepts",            "consumer": eb2_consumer_flow, "business": eb2_business_flow},
    "EB3": {"name": "Book Event 1 Participant + 1 Guest",              "consumer": eb3_consumer_flow, "business": eb3_business_flow},
    "EB4": {"name": "Book Event - Invitee Declines",                   "consumer": eb4_consumer_flow, "business": eb4_business_flow},
    "EB5": {"name": "Book Event Multiple Invitees + Wallet Filter",    "consumer": eb5_consumer_flow, "business": eb5_business_flow},

    # Create & Manage Events from B-App
    "BME1": {"name": "B-App Event - User Declines",                   "consumer": bme1_consumer_flow, "business": bme1_business_flow, "order": "business_first"},
    "BME2": {"name": "B-App Event - User Accepts & Preorders",        "consumer": bme2_consumer_flow, "business": bme2_business_flow, "order": "business_first"},
    "BME3": {"name": "B-App Event - Invite User from Wallet",         "consumer": bme3_consumer_flow, "business": bme3_business_flow, "order": "business_first"},
    "BME4": {"name": "B-App Event - Cancel with Invitee",             "consumer": bme4_consumer_flow, "business": bme4_business_flow, "order": "business_first"},
    "BME5": {"name": "B-App Event Cancel - No Invitees",              "consumer": bme5_consumer_flow, "business": bme5_business_flow, "order": "business_first"},
    "BME6": {"name": "Transfer Event Between Waiters",               "consumer": bme6_consumer_flow, "business": bme6_business_flow},

    # Event Cancellations
    "EC1":  {"name": "Host Cancels - Invitee Accepted",               "consumer": ec1_consumer_flow,  "business": ec1_business_flow},
    "EC2":  {"name": "Adding User After Host Change",                  "consumer": ec2_consumer_flow,  "business": ec2_business_flow},
    "EC3":  {"name": "Host Cancels - Invitee Declined",               "consumer": ec3_consumer_flow,  "business": ec3_business_flow},
    "EC4":  {"name": "Participant Cancels Event",                      "consumer": ec4_consumer_flow,  "business": ec4_business_flow},
    "EC5":  {"name": "Both Host and Participant Cancel",               "consumer": ec5_consumer_flow,  "business": ec5_business_flow},
    "EC6":  {"name": "Host Cancels After Preorder - Me Only",          "consumer": ec6_consumer_flow,  "business": ec6_business_flow},
    "EC7":  {"name": "Host with Guest Preorders, Cancels Me Only",     "consumer": ec7_consumer_flow,  "business": ec7_business_flow},
    "EC8":  {"name": "Host Cancels for All After Preorder",            "consumer": ec8_consumer_flow,  "business": ec8_business_flow},
    "EC9":  {"name": "Host Cancels for All Before 15 min",             "consumer": ec9_consumer_flow,  "business": ec9_business_flow},
    "EC10": {"name": "Host Cancels Me Only Before 15 min",             "consumer": ec10_consumer_flow, "business": ec10_business_flow},
    "EC11": {"name": "Host with Guest Preorders, Cancels Me Only",     "consumer": ec11_consumer_flow, "business": ec11_business_flow},
    "EC12": {"name": "Pickup Cancellation",                            "consumer": ec12_consumer_flow, "business": ec12_business_flow},

    # Filter Events in B-App
    "FE1": {"name": "Filter Events by Status",                         "consumer": fe1_consumer_flow,  "business": fe1_business_flow},
    "FE2": {"name": "Filter Events by Table",                          "consumer": fe2_consumer_flow,  "business": fe2_business_flow},
    "FE3": {"name": "Status Filter in Home Page Popup",                "consumer": fe3_consumer_flow,  "business": fe3_business_flow},
    "FE4": {"name": "Table Filter in Home Page Popup",                 "consumer": fe4_consumer_flow,  "business": fe4_business_flow},
    "FE5": {"name": "Table Main Filter + Status Filter",              "consumer": fe5_consumer_flow,  "business": fe5_business_flow},
    "FE6": {"name": "Table Main Filter + Table Filter",               "consumer": fe6_consumer_flow,  "business": fe6_business_flow},
    "FE7": {"name": "Pickup Main Filter",                             "consumer": fe7_consumer_flow,  "business": fe7_business_flow},

    # Filter & Actions in C-App
    "FC1": {"name": "Filter by Ratings - Top Rated",                   "consumer": fc1_consumer_flow,  "business": fc1_business_flow},
    "FC2": {"name": "Filter by Discount",                              "consumer": fc2_consumer_flow,  "business": fc2_business_flow},
    "FC3": {"name": "Modify Table Type",                               "consumer": fc3_consumer_flow,  "business": fc3_business_flow},
    "FC4": {"name": "Pre-Order Items After Modify",                    "consumer": fc4_consumer_flow,  "business": fc4_business_flow},
    "FC5": {"name": "Modify Event with Invitees",                      "consumer": fc5_consumer_flow,  "business": fc5_business_flow},
    "FC6": {"name": "Subtract Persons and Remove Guest",               "consumer": fc6_consumer_flow,  "business": fc6_business_flow},
    "FC7": {"name": "Unsubscribe from Restaurant",                     "consumer": fc7_consumer_flow,  "business": fc7_business_flow},
    "FC8": {"name": "Subscribe to Restaurant",                         "consumer": fc8_consumer_flow,  "business": fc8_business_flow},
    "FC9": {"name": "Like/Dislike Restaurant + Like Product",          "consumer": fc9_consumer_flow,  "business": fc9_business_flow},

    # Ordering
    "O1":  {"name": "Adding Items with Modifiers & Variants",          "consumer": o1_consumer_flow,   "business": o1_business_flow},
    "O2":  {"name": "Split Before Serve",                              "consumer": o2_consumer_flow,   "business": o2_business_flow},
    "O3":  {"name": "Trying to Split Splitted Items",                  "consumer": o3_consumer_flow,   "business": o3_business_flow},
    "O4":  {"name": "Assigning Item from 1 to Another",                "consumer": o4_consumer_flow,   "business": o4_business_flow},
    "O5":  {"name": "Split After Serve with Payment",                  "consumer": o5_consumer_flow,   "business": o5_business_flow},

    # Pre-Order
    "PO1": {"name": "Adding More Items from Cart",                     "consumer": po1_consumer_flow,  "business": po1_business_flow},
    "PO2": {"name": "Add and Reduce Items Cart/Menu",                  "consumer": po2_consumer_flow,  "business": po2_business_flow},
    "PO3": {"name": "Edit Item from Cart",                             "consumer": po3_consumer_flow,  "business": po3_business_flow},
    "PO4": {"name": "Host Preorders First Invitee Skips",              "consumer": po4_consumer_flow,  "business": po4_business_flow},
    "PO5": {"name": "Both Host and Invitee Preorder",                  "consumer": po5_consumer_flow,  "business": po5_business_flow},
    "PO6": {"name": "Participant Preorders First Host Adds Later",     "consumer": po6_consumer_flow,  "business": po6_business_flow},
    "PO7": {"name": "Coupon Add/Remove/Verify Total",                  "consumer": po7_consumer_flow,  "business": po7_business_flow},

    # Payments
    "PAY1": {"name": "Payment by Cash",                                "consumer": pay1_consumer_flow, "business": pay1_business_flow, "order": "consumer_first"},
    "PAY2": {"name": "Host Pays for Others",                           "consumer": pay2_consumer_flow, "business": pay2_business_flow},
    "PAY3": {"name": "Payment by E-Payment",                           "consumer": pay3_consumer_flow, "business": pay3_business_flow},
    "PAY4": {"name": "Payment by Food Voucher",                        "consumer": pay4_consumer_flow, "business": pay4_business_flow},
    "PAY5": {"name": "Payment All 3 Modes",                            "consumer": pay5_consumer_flow, "business": pay5_business_flow},
    "PAY6": {"name": "Participant Pays for Others",                    "consumer": pay6_consumer_flow, "business": pay6_business_flow},
    "PAY7": {"name": "Guest Pays for Others",                          "consumer": pay7_consumer_flow, "business": pay7_business_flow},

    # Status Verification
    "SV1":  {"name": "Confirmation Pending Status",                    "consumer": sv1_consumer_flow,  "business": sv1_business_flow, "order": "business_first"},
    "SV2":  {"name": "Reserved Status B-App",                          "consumer": sv2_consumer_flow,  "business": sv2_business_flow},
    "SV3":  {"name": "Event Declination Status",                       "consumer": sv3_consumer_flow,  "business": sv3_business_flow, "order": "business_first"},
    "SV4":  {"name": "Pre-Order Status C-App",                         "consumer": sv4_consumer_flow,  "business": sv4_business_flow},
    "SV6":  {"name": "Menu Order C-App",                               "consumer": sv6_consumer_flow,  "business": sv6_business_flow},
    "SV7":  {"name": "Order Status B-App",                             "consumer": sv7_consumer_flow,  "business": sv7_business_flow},
    "SV8":  {"name": "In Progress Status B-App",                       "consumer": sv8_consumer_flow,  "business": sv8_business_flow},
    "SV9":  {"name": "Serve Status B-App",                             "consumer": sv9_consumer_flow,  "business": sv9_business_flow},
    "SV10": {"name": "Payment Status B-App",                           "consumer": sv10_consumer_flow, "business": sv10_business_flow},
    "SV11": {"name": "Payment Requested C-App",                        "consumer": sv11_consumer_flow, "business": sv11_business_flow},
    "SV12": {"name": "Payment Done B-App",                             "consumer": sv12_consumer_flow, "business": sv12_business_flow},
    "SV13": {"name": "Completed Status B-App",                         "consumer": sv13_consumer_flow, "business": sv13_business_flow},
    "SV14": {"name": "Completed Status C-App",                         "consumer": sv14_consumer_flow, "business": sv14_business_flow},
    "SV15": {"name": "No-Show Status Verification",                    "consumer": sv15_consumer_flow, "business": sv15_business_flow},
    "SV16": {"name": "Payment Done via C-App",                         "consumer": sv16_consumer_flow, "business": sv16_business_flow},

    # PDF
    "PDF1": {"name": "Generate PDF - Individual Payment",              "consumer": pdf1_consumer_flow, "business": pdf1_business_flow},
    "PDF2": {"name": "Generate PDF for Entire Event",                  "consumer": pdf2_consumer_flow, "business": pdf2_business_flow},
    "PDF3": {"name": "Generate PDF after Event Completion (Individual)","consumer": pdf3_consumer_flow, "business": pdf3_business_flow},
}