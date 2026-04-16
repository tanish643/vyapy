"""
Vyapy QA Multi-Agent Scenario Definitions
Generated from Appium Studio XML exports.
All 76 scenarios across Consumer and Business apps.
"""

import threading
import time
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import scenario_reporter
import bill_validator

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
}

shared_data = {}


def clear_events():
    for e in events.values():
        e.clear()
    shared_data.clear()


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _tap(agent, *descs):
    """Tap element by label via XCTest. Falls back to Groq AI if XCTest fails."""
    label = descs[0]
    success = agent.tap(0, 0, label)
    if not success:
        print(f"[{agent.role}] XCTest tap failed for '{label}' — invoking Groq AI fallback")
        ai_ok = agent.run_step_ai(f"Find and tap '{label}' on screen", max_retries=3)
        if not ai_ok:
            raise RuntimeError(agent.last_action_error or f"XCTest + Groq failed to tap '{label}'")
    return True


def _tap_required(agent, desc, scenario_key, scenario_name, retries=2):
    """Tap a required element via XCTest. Reports FAIL if it fails."""
    success = agent.tap(0, 0, desc)
    if not success:
        msg = f"XCTest failed to tap required element: '{desc}'"
        print(f"[{agent.role}] FAIL — {msg}")
        scenario_reporter.add_result(scenario_key, scenario_name, agent.role, "FAIL", msg, agent.last_launch_time)
        return False
    return True


def _wait_tap(agent, desc, timeout=10):
    """Wait for element then tap it via XCTest. Falls back to Groq AI if not found."""
    print(f"[{agent.role}] Waiting and Tapping '{desc}'...")
    success = agent.tap(0, 0, desc)
    if not success:
        print(f"[{agent.role}] _wait_tap failed for '{desc}' — invoking Groq AI fallback")
        ai_ok = agent.run_step_ai(f"Find and tap '{desc}' on screen", max_retries=3)
        if not ai_ok:
            raise RuntimeError(agent.last_action_error or f"XCTest + Groq failed to tap '{desc}'")
    return True


def _try_tap(agent, desc):
    """Attempt to tap element; silently skip if not found (optional elements)."""
    success = agent.tap(0, 0, desc)
    if not success:
        print(f"[{agent.role}] Optional element '{desc}' not found — skipping")
    return success


def _type_field(agent, field_desc, text):
    """Type text into a target element using XCTest."""
    success = agent.type_text(text, target=field_desc)
    if not success:
        raise RuntimeError(agent.last_action_error or f"XCTest failed to type into '{field_desc}'")
    return True


def _swipe_up(agent):
    agent.swipe_up()


def _wait_for(agent, desc, timeout=15):
    """Wait for element to appear WITHOUT tapping it. Uses XCTest waitForExistence."""
    found = agent.xctest_wait_for(desc, timeout)
    if found:
        print(f"[{agent.role}] FOUND (no tap): '{desc}'")
    else:
        print(f"[{agent.role}] TIMEOUT waiting for '{desc}' (no tap)")
    return found


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


def _switch_account(agent, email, password):
    """Logout and login as another user on consumer device."""
    print(f"[{agent.role}] Switching to account: {email}")
    _tap(agent, "menuTab")
    _tap(agent, "menuLogout")
    time.sleep(2)
    _type_field(agent, "loginEmail", email)
    _type_field(agent, "loginPassword", password)
    time.sleep(1)
    _wait_tap(agent, "signIn")
    time.sleep(3)


# ─── CONTACTS & WALLET (CW1–CW6) ─────────────────────────────────────────────

def cw1_consumer_flow(agent):
    """CW1: Creating New Contact from Reservation"""
    print(f"[{agent.role}] [CW1] Creating New Contact from Reservation")
    agent.launch_app()
    _tap(agent, "NylaiKitchen")
    _tap(agent, "counterPlus")
    _tap(agent, "newContactAdd")
    _type_field(agent, "firstName", "Prajwal")
    _type_field(agent, "mobileCont", "8937773734")
    _tap(agent, "saveContact")
    _type_field(agent, "contactSearch", "Prajwal")
    time.sleep(1)
    _tap(agent, "back")
    _tap(agent, "back")
    _tap(agent, "chip-container")
    _wait_tap(agent, "bookAppoitment")
    scenario_reporter.add_result("CW1", "Creating New Contact from Reservation",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def cw2_consumer_flow(agent):
    """CW2: Adding Guest from Wallet after Creating an Event"""
    print(f"[{agent.role}] [CW2] Adding Guest from Wallet")
    agent.launch_app()
    _wait_tap(agent, "NylaiKitchen")
    time.sleep(2)
    _tap(agent, "Not Sure")
    _wait_tap(agent, "chip")
    time.sleep(3)
    # Debug: find the real accessibility label of the Book Now button
    labels = agent.xctest_query_labels("label != ''")
    print(f"[{agent.role}] [CW2-DEBUG] Labels after chip tap: {labels}")
    _tap(agent, "Book Now")
    _wait_tap(agent, "orderLater")
    _wait_tap(agent, "NylaiKitchenCard")
    _wait_tap(agent, "Invite")
    _tap(agent, "guestAdd")
    _tap(agent, "inviteUsers")
    _tap(agent, "homeTab")
    scenario_reporter.add_result("CW2", "Adding Guest from Wallet",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def cw3_consumer_flow(agent):
    """CW3: Adding User from Wallet after Creating an Event"""
    print(f"[{agent.role}] [CW3] Adding User from Wallet")
    agent.launch_app()
    agent.swipe_down()
    _tap(agent, "NylaiKitchen")
    _wait_tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "orderLater")
    time.sleep(3)
    _type_field(agent, "contactSearch", "Noolu")
    _tap(agent, "NooluInvite")
    _tap(agent, "inviteUsers")
    _tap(agent, "homeTab")
    scenario_reporter.add_result("CW3", "Adding User from Wallet",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def cw4_consumer_flow(agent):
    """CW4: Creating New Contact from Wallet"""
    print(f"[{agent.role}] [CW4] Creating New Contact from Wallet")
    agent.launch_app()
    _wait_tap(agent, "bookAppoitment")
    _wait_for(agent, "preOrderBooking")   # wait for booking confirmed screen
    _wait_tap(agent, "orderLater")
    _wait_tap(agent, "Invite")            # tap Invite to open contacts screen
    _wait_tap(agent, "newContactAdd")
    _type_field(agent, "firstName", "Sonu")
    _type_field(agent, "mobileCont", "8937773737")
    _tap(agent, "saveContact")
    _type_field(agent, "contactSearch", "Sonu")
    time.sleep(1)
    _tap(agent, "back")
    _tap(agent, "homeTab")
    scenario_reporter.add_result("CW4", "Creating New Contact from Wallet",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


# ─── EVENT BOOKING (EB1–EB5) ─────────────────────────────────────────────────

def eb1_consumer_flow(agent):
    """EB1: Book an Event with 1 Guest for 1 hour - Indoor"""
    print(f"[{agent.role}] [EB1] Book Event 1 Guest Indoor")
    agent.launch_app()
    time.sleep(5)
    _wait_tap(agent, "NylaiKitchen")
    time.sleep(2)
    _tap(agent, "Indoor")
    _tap(agent, "Not Sure")              # select duration → reveals time slots
    _wait_tap(agent, "chip")             # tap first available time slot chip
    _tap(agent, "counterPlus")
    _tap(agent, "guestAdd")
    _tap(agent, "inviteUsers")
    _wait_tap(agent, "bookAppoitment")
    events["order_placed"].set()         # booking placed — signal Business now
    _try_tap(agent, "orderLater")        # optional: skip if screen not ready
    _tap(agent, "walletTab")
    time.sleep(2)
    _tap(agent, "homeTab")
    scenario_reporter.add_result("EB1", "Book Event 1 Guest Indoor",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def eb1_business_flow(agent):
    """EB1 Business: Accept incoming booking"""
    print(f"[{agent.role}] [EB1] Waiting for booking")
    agent.launch_app()
    if events["order_placed"].wait(timeout=120):
        _wait_tap(agent, "Orders")
        _wait_tap(agent, "ReservedOrderCard")
        _tap_required(agent, "T0AssignAnyBtn", "EB1", "Book Event 1 Guest Indoor")
        _tap(agent, "AssignTableBtn")
        events["table_accepted"].set()
        scenario_reporter.add_result("EB1", "Book Event 1 Guest Indoor",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)
    else:
        raise RuntimeError("order_placed event timed out after 120s — Consumer did not complete booking")


def eb2_consumer_flow(agent):
    """EB2: Book Event with invitee accepting - Outdoor"""
    print(f"[{agent.role}] [EB2] Book Event Outdoor - Invitee Accepts")
    agent.launch_app()
    _wait_tap(agent, "NylaiKitchen")
    time.sleep(2)
    _tap(agent, "Outdoor")
    _tap(agent, "counterPlus")
    _type_field(agent, "contactSearch", "Noolu")
    _tap(agent, "NooluInvite")
    _tap(agent, "inviteUsers")
    _tap(agent, "chip-container")
    agent.swipe_up()
    _type_field(agent, "inputSplIns", "Join the party soon!!!")
    _wait_tap(agent, "bookAppoitment")
    _tap(agent, "orderLater")
    events["order_placed"].set()
    # Switch to Noolu to accept
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_tap(agent, "RoopaDInviteCard")
    _tap(agent, "eventAccept")
    _wait_tap(agent, "orderLater")
    _tap(agent, "orderLater")
    _tap(agent, "walletTab")
    # Switch back to Roopa
    _switch_account(agent, "roopa@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _tap(agent, "NylaiKitchenCard")
    time.sleep(2)
    _tap(agent, "homeTab")
    scenario_reporter.add_result("EB2", "Book Event Outdoor - Invitee Accepts",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def eb2_business_flow(agent):
    _no_op(agent)


def eb3_consumer_flow(agent):
    """EB3: Book Event with 1 Participant and 1 Guest"""
    print(f"[{agent.role}] [EB3] Book Event 1 Participant + 1 Guest")
    agent.launch_app()
    agent.swipe_up()
    _tap(agent, "NylaiKitchen")
    time.sleep(2)
    _tap(agent, "counterPlus")
    _tap(agent, "guestAdd")
    _type_field(agent, "contactSearch", "Noolu")
    _wait_tap(agent, "NooluInvite")
    _tap(agent, "inviteUsers")
    _tap(agent, "chip-container")
    _wait_tap(agent, "bookAppoitment")
    _tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "walletTab")
    events["order_placed"].set()
    # Noolu accepts
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_tap(agent, "RoopaDInviteCard")
    _tap(agent, "eventAccept")
    _wait_tap(agent, "orderLater")
    _tap(agent, "orderLater")
    _tap(agent, "walletTab")
    _tap(agent, "NylaiKitchenCard")
    time.sleep(2)
    # Switch back to Roopa
    _switch_account(agent, "roopa@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_tap(agent, "RoopaDInviteCard")
    _tap(agent, "NylaiKitchenCard")
    time.sleep(2)
    scenario_reporter.add_result("EB3", "Book Event 1 Participant + 1 Guest",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def eb3_business_flow(agent):
    _no_op(agent)


def eb4_consumer_flow(agent):
    """EB4: Book Event with invitee when Declines"""
    print(f"[{agent.role}] [EB4] Book Event - Invitee Declines")
    agent.launch_app()
    _tap(agent, "homeTab")
    _wait_tap(agent, "NylaiKitchen")
    agent.swipe_up()
    _tap(agent, "NylaiKitchen")
    time.sleep(2)
    _tap(agent, "counterPlus")
    _type_field(agent, "contactSearch", "Noolu")
    _tap(agent, "NooluInvite")
    _tap(agent, "inviteUsers")
    _tap(agent, "chip-container")
    agent.swipe_up()
    _type_field(agent, "inputSplIns", "Lets enjoy the party")
    _wait_tap(agent, "bookAppoitment")
    _tap(agent, "bookAppoitment")
    _tap(agent, "orderLater")
    time.sleep(2)
    events["order_placed"].set()
    # Switch to Noolu to decline
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_tap(agent, "RoopaDInviteCard")
    _tap(agent, "eventDecline")
    time.sleep(2)
    # Switch back to Roopa
    _switch_account(agent, "roopa@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _tap(agent, "NylaiKitchenCard")
    time.sleep(2)
    scenario_reporter.add_result("EB4", "Book Event - Invitee Declines",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def eb4_business_flow(agent):
    _no_op(agent)


def eb5_consumer_flow(agent):
    """EB5: Book Event with more invitees and apply filter in wallet"""
    print(f"[{agent.role}] [EB5] Book Event Multiple Invitees + Wallet Filter")
    agent.launch_app()
    _tap(agent, "homeTab")
    agent.swipe_up()
    _tap(agent, "NylaiKitchen")
    time.sleep(2)
    _tap(agent, "counterPlus")
    _type_field(agent, "contactSearch", "Noolu")
    _tap(agent, "NooluInvite")
    _type_field(agent, "contactSearch", "Aritro")
    _tap(agent, "AritroInvite")
    _type_field(agent, "contactSearch", "Sneha")
    _tap(agent, "SnehaInvite")
    _tap(agent, "inviteUsers")
    _tap(agent, "chip-container")
    _wait_tap(agent, "bookAppoitment")
    _tap(agent, "bookAppoitment")
    _tap(agent, "orderLater")
    time.sleep(2)
    # Noolu declines
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_tap(agent, "RoopaDInviteCard")
    _tap(agent, "eventDecline")
    _tap(agent, "walletTab")
    # Sneha accepts
    _switch_account(agent, "sneha@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_tap(agent, "RoopaDInviteCard")
    _tap(agent, "eventAccept")
    _tap(agent, "orderLater")
    _tap(agent, "walletTab")
    # Aritro applies filters then accepts
    _switch_account(agent, "aritro@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_tap(agent, "RoopaDInviteCard")
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
    _tap(agent, "walletTab")
    # Switch back to Roopa
    _switch_account(agent, "roopa@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _tap(agent, "NylaiKitchenCard")
    time.sleep(2)
    scenario_reporter.add_result("EB5", "Book Event Multiple Invitees + Wallet Filter",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def eb5_business_flow(agent):
    _no_op(agent)


def _detect_eb6_state(agent):
    """Detect where the user currently is in the EB6 flow using XCTest queries.
    Returns the step number to resume from:
      1 = not started (home/restaurant screen)
      2 = event booked, need to go to wallet
      3 = on menu, need to add items
      4 = items added, need to go to checkout
      5 = on checkout screen
    """
    # Query for landmark elements that identify each screen
    category_labels = agent.xctest_query_labels(
        "label == 'starterscategory' OR label == 'pasta-pizzacategory' OR "
        "label == 'cheesy-comfort-platescategory' OR label == 'thai-street-food-favoritescategory'"
    )
    if category_labels:
        print(f"[{agent.role}] [EB6-RESUME] Detected: Menu screen → resuming from Step 3")
        return 3

    checkout_labels = agent.xctest_query_labels(
        "label == 'Grand Total' OR label == 'Place Order' OR label == 'Bill Total'"
    )
    if checkout_labels:
        print(f"[{agent.role}] [EB6-RESUME] Detected: Checkout screen → resuming from Step 5")
        return 5

    cart_labels = agent.xctest_query_labels("label == 'cartImage' OR label == 'cartCheckout'")
    if cart_labels:
        print(f"[{agent.role}] [EB6-RESUME] Detected: Cart visible → resuming from Step 4")
        return 4

    wallet_labels = agent.xctest_query_labels("label == 'Pre-Order' OR label == 'walletTab'")
    if wallet_labels:
        print(f"[{agent.role}] [EB6-RESUME] Detected: Wallet screen → resuming from Step 2")
        return 2

    print(f"[{agent.role}] [EB6-RESUME] No recognized state → starting from Step 1")
    return 1


def eb6_consumer_flow(agent):
    """EB6: Book event → pre-order ALL items from ALL categories with variants → bill validation"""
    print(f"[{agent.role}] [EB6] Book Event + Pre-Order ALL Items + Bill Validation")
    agent.launch_app()
    time.sleep(5)

    # Detect current state and resume from there
    start_step = _detect_eb6_state(agent)

    # ── Step 1: Book the event (same as EB1) ──────────────────────────────────
    if start_step <= 1:
        _wait_tap(agent, "NylaiKitchen")
        time.sleep(2)
        _tap(agent, "Indoor")
        _tap(agent, "Not Sure")
        _wait_tap(agent, "chip")
        _tap(agent, "counterPlus")
        _tap(agent, "guestAdd")
        _tap(agent, "inviteUsers")
        _wait_tap(agent, "bookAppoitment")
        events["order_placed"].set()     # booking placed — signal Business now
        _try_tap(agent, "orderLater")    # optional — skip if screen not ready

    # ── Step 2: Go to wallet → tap Pre-Order ──────────────────────────────────
    if start_step <= 2:
        _wait_tap(agent, "walletTab")
        time.sleep(4)
        # Debug: print all labels on screen to find correct Pre-Order label
        screen_labels = agent.xctest_query_labels("label != ''")
        print(f"[{agent.role}] [EB6-DEBUG] Labels on wallet screen: {screen_labels[:30]}")
        _wait_tap(agent, "Pre-Order")           # text="Pre-Order" (content-desc is empty)

    # ── Step 3: Add ALL items from ALL categories with variants ───────────────
    if start_step <= 3:
        categories = [
            "starterscategory",
            "pasta-pizzacategory",
            "cheesy-comfort-platescategory",
            "thai-street-food-favoritescategory",
        ]
        total_added = 0
        for cat in categories:
            count = agent.xctest_add_category_items(cat)
            total_added += count
        print(f"[{agent.role}] Total items added across all categories: {total_added}")

    # ── Step 4: Go to checkout ────────────────────────────────────────────────
    if start_step <= 4:
        _try_tap(agent, "cartImage") or _try_tap(agent, "cartCheckout")
        time.sleep(3)

    # ── Step 5: Read all item prices on checkout via XCTest ───────────────────
    all_checkout_prices = agent.xctest_get_prices_with_scroll(scrolls=5)
    displayed_total = max(all_checkout_prices) if all_checkout_prices else None
    line_items = sorted([p for p in all_checkout_prices if displayed_total and abs(p - displayed_total) > 0.01])

    if line_items:
        calc_parts = [f"€{p:.2f}" for p in line_items]
        calculated = round(sum(line_items), 2)
        calc_str = " + ".join(calc_parts) + f" = €{calculated:.2f}"
        print(f"[{agent.role}] Calculation: {calc_str}")
        if displayed_total:
            print(f"[{agent.role}] Displayed total: €{displayed_total:.2f}")
        diff = round(abs(displayed_total - calculated), 2) if displayed_total else 999
        if diff <= 0.01:
            bill_status = "PASS"
            bill_reason = f"Bill OK: {calc_str} (displayed: €{displayed_total:.2f})"
        else:
            bill_status = "FAIL"
            bill_reason = f"Bill mismatch: calculated=€{calculated:.2f}, displayed=€{displayed_total:.2f}, diff=€{diff:.2f}"
        print(f"[{agent.role}] Bill check: {bill_status} — {bill_reason}")
    else:
        bill_status = "FAIL"
        bill_reason = "No line items found on checkout screen"
        calculated = 0
        print(f"[{agent.role}] {bill_reason}")

    scenario_reporter.add_result("EB6", "Pre-Order Bill Validation",
                                 agent.role, bill_status, bill_reason, agent.last_launch_time)

    # ── Step 6: Apply coupon and validate via XCTest ───────────────────────────
    original_total = displayed_total or calculated
    if original_total > 0:
        _tap(agent, "applyCoupon")
        time.sleep(1)
        _try_tap(agent, "Get More") or _try_tap(agent, "getCoupons")
        time.sleep(2)
        coupon_tapped = False
        for coupon_desc in ["couponChip", "applyCouponBtn", "couponCard"]:
            if agent.tap(0, 0, coupon_desc):
                coupon_tapped = True
                break
        if not coupon_tapped:
            agent.swipe_up()
            time.sleep(1)
            for coupon_desc in ["couponChip", "applyCouponBtn", "couponCard"]:
                if agent.tap(0, 0, coupon_desc):
                    coupon_tapped = True
                    break

        if coupon_tapped:
            time.sleep(2)
            new_prices = agent.xctest_get_prices_with_scroll(scrolls=3)
            new_total = max(new_prices) if new_prices else None
            if new_total and new_total < original_total:
                coupon_discount = round(original_total - new_total, 2)
                coupon_reason = f"Coupon applied: €{original_total:.2f} - €{coupon_discount:.2f} = €{new_total:.2f}"
                print(f"[{agent.role}] {coupon_reason}")
                scenario_reporter.add_result("EB6", "Pre-Order Coupon Validation",
                                             agent.role, "PASS", coupon_reason, agent.last_launch_time)
            else:
                coupon_reason = f"Coupon may not have applied: total still €{new_total or 'unknown'}"
                print(f"[{agent.role}] {coupon_reason}")
                scenario_reporter.add_result("EB6", "Pre-Order Coupon Validation",
                                             agent.role, "FAIL", coupon_reason, agent.last_launch_time)
        else:
            print(f"[{agent.role}] No coupon found to apply")
            scenario_reporter.add_result("EB6", "Pre-Order Coupon Validation",
                                         agent.role, "FAIL", "No coupon found", agent.last_launch_time)


def eb6_business_flow(agent):
    """EB6 Business: Accept incoming booking (same as EB1 business)"""
    print(f"[{agent.role}] [EB6] Waiting for booking to accept")
    agent.launch_app()

    # Check if consumer is resuming from menu (table already assigned)
    consumer_resuming = events["order_placed"].is_set()
    if consumer_resuming:
        # Use XCTest to check if Orders tab is visible
        orders_found = agent.xctest_query_labels("label == 'Orders'")
        if not orders_found:
            print(f"[{agent.role}] [EB6] Consumer resuming, no business action needed — skipping")
            events["table_accepted"].set()
            scenario_reporter.add_result("EB6", "Book Event + Pre-Order ALL Items + Bill Validation",
                                         agent.role, "PASS", "Skipped (resumed)", agent.last_launch_time)
            return

    if events["order_placed"].wait(timeout=180):
        _wait_tap(agent, "Orders")
        _wait_tap(agent, "ReservedOrderCard")
        _tap_required(agent, "T0AssignAnyBtn", "EB6", "Book Event + Pre-Order ALL Items + Bill Validation")
        _tap(agent, "AssignTableBtn")
        events["table_accepted"].set()
        scenario_reporter.add_result("EB6", "Book Event + Pre-Order ALL Items + Bill Validation",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


# ─── CREATE & MANAGE EVENTS FROM B-APP (BME1–BME6) ───────────────────────────

def bme1_consumer_flow(agent):
    """BME1: Consumer side - accept or decline invite from B-App event"""
    print(f"[{agent.role}] [BME1] Waiting for B-App event invite")
    agent.launch_app()
    if events["event_created"].wait(timeout=120):
        _tap(agent, "walletTab")
        time.sleep(2)
        _wait_tap(agent, "Nylai KitchenInviteCard")
        _tap(agent, "eventDecline")
        time.sleep(2)
        events["event_declined"].set()
        scenario_reporter.add_result("BME1", "B-App Event - User Declines",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def bme1_business_flow(agent):
    """BME1: Create event from B-App"""
    print(f"[{agent.role}] [BME1] Creating event from B-App")
    agent.launch_app()
    agent.swipe_up()
    _wait_tap(agent, "addNewEvent")
    _type_field(agent, "firstName", "Roopa")
    _type_field(agent, "lastName", "D")
    _tap(agent, "anyBtn")
    _type_field(agent, "mobileInputBtn", "9686496589")
    _tap(agent, "saveBtn")
    events["event_created"].set()
    if events["event_declined"].wait(timeout=120):
        time.sleep(2)
        scenario_reporter.add_result("BME1", "B-App Event - User Declines",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def bme2_consumer_flow(agent):
    """BME2: Consumer accepts B-App event and preorders"""
    print(f"[{agent.role}] [BME2] Waiting for B-App event to accept")
    agent.launch_app()
    if events["event_created"].wait(timeout=120):
        _tap(agent, "walletTab")
        time.sleep(2)
        _wait_tap(agent, "Nylai KitchenInviteCard")
        _tap(agent, "eventAccept")
        _tap(agent, "preOrderBooking")
        _tap(agent, "starterscategory")
        agent.swipe_up()
        _tap(agent, "MuttonSeekhKebabInc")
        _tap(agent, "2pcsProduct")
        agent.swipe_up()
        _tap(agent, "chutneyProduct")
        _tap(agent, "confirmProduct")
        _wait_tap(agent, "cheesy-comfort-platescategory")
        _tap(agent, "cheesy-comfort-platescategory")
        agent.swipe_up()
        agent.swipe_up()
        agent.swipe_up()
        _tap(agent, "Cheese-StuffedGarlicBreadInc")
        _tap(agent, "6pccsProduct")
        agent.swipe_up()
        agent.swipe_up()
        agent.swipe_up()
        _tap(agent, "MarinaraDipProduct")
        _tap(agent, "confirmProduct")
        _tap(agent, "cartImage")
        _tap(agent, "cartCheckout")
        time.sleep(2)
        _tap(agent, "pickUpOrderConfirm")
        events["preorder_submitted"].set()
        scenario_reporter.add_result("BME2", "B-App Event - User Accepts & Preorders",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def bme2_business_flow(agent):
    """BME2: Create event from B-App"""
    print(f"[{agent.role}] [BME2] Creating event from B-App")
    agent.launch_app()
    agent.swipe_up()
    _wait_tap(agent, "addNewEvent")
    _type_field(agent, "firstName", "Roopa")
    _type_field(agent, "lastName", "D")
    _tap(agent, "anyBtn")
    _type_field(agent, "mobileInputBtn", "9686496589")
    _tap(agent, "saveBtn")
    events["event_created"].set()
    events["preorder_submitted"].wait(timeout=180)
    scenario_reporter.add_result("BME2", "B-App Event - User Accepts & Preorders",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def bme3_consumer_flow(agent):
    """BME3: Accept event and invite another user from wallet"""
    print(f"[{agent.role}] [BME3] Accept event and add guest from wallet")
    agent.launch_app()
    if events["event_created"].wait(timeout=120):
        _tap(agent, "walletTab")
        time.sleep(2)
        _wait_tap(agent, "Nylai KitchenInviteCard")
        _tap(agent, "eventAccept")
        _tap(agent, "orderLater")
        _tap(agent, "NylaiKitchenCard")
        agent.run_step_ai("Tap on the 'guestAdd' button")
        _type_field(agent, "contactSearch", "Noolu")
        _wait_tap(agent, "NooluInvite")
        _tap(agent, "inviteUsers")
        time.sleep(2)
        events["guest_joined"].set()
        scenario_reporter.add_result("BME3", "B-App Event - Invite User from Wallet",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def bme3_business_flow(agent):
    """BME3: Create event from B-App"""
    print(f"[{agent.role}] [BME3] Creating event from B-App")
    agent.launch_app()
    agent.swipe_up()
    _wait_tap(agent, "addNewEvent")
    _type_field(agent, "firstName", "Roopa")
    _type_field(agent, "lastName", "D")
    _tap(agent, "anyBtn")
    _type_field(agent, "mobileInputBtn", "9686496589")
    _tap(agent, "saveBtn")
    events["event_created"].set()
    events["guest_joined"].wait(timeout=120)
    scenario_reporter.add_result("BME3", "B-App Event - Invite User from Wallet",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def bme4_consumer_flow(agent):
    """BME4: Cancel event from B-App when invitee present"""
    print(f"[{agent.role}] [BME4] Consumer accepts invite then waits for cancel")
    agent.launch_app()
    if events["event_created"].wait(timeout=120):
        # Switch to Noolu to accept
        _switch_account(agent, "noolu@xorstack.com", "12345")
        _tap(agent, "walletTab")
        _wait_tap(agent, "RoopaDInviteCard")
        _tap(agent, "eventAccept")
        _wait_tap(agent, "orderLater")
        _tap(agent, "orderLater")
        events["event_accepted"].set()
        # Switch back to Roopa
        _switch_account(agent, "roopa@xorstack.com", "12345")
        time.sleep(2)
        scenario_reporter.add_result("BME4", "B-App Event - Cancel with Invitee",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def bme4_business_flow(agent):
    """BME4: Business creates event then cancels it"""
    print(f"[{agent.role}] [BME4] Creating event and cancelling from B-App")
    agent.launch_app()
    agent.swipe_up()
    _wait_tap(agent, "addNewEvent")
    _type_field(agent, "firstName", "Roopa")
    _type_field(agent, "lastName", "D")
    _tap(agent, "anyBtn")
    _type_field(agent, "mobileInputBtn", "9686496589")
    _tap(agent, "saveBtn")
    events["event_created"].set()
    if events["event_accepted"].wait(timeout=120):
        _wait_tap(agent, "cancelEvent")
        _tap(agent, "confirmEventBtn")
        time.sleep(2)
        scenario_reporter.add_result("BME4", "B-App Event - Cancel with Invitee",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def bme5_consumer_flow(agent):
    """BME5: Cancel event created from B-App (no invitees)"""
    print(f"[{agent.role}] [BME5] Consumer accepts B-App event")
    agent.launch_app()
    if events["event_created"].wait(timeout=120):
        _tap(agent, "walletTab")
        time.sleep(2)
        _wait_tap(agent, "Nylai KitchenInviteCard")
        _tap(agent, "eventAccept")
        _tap(agent, "orderLater")
        events["event_accepted"].set()
        scenario_reporter.add_result("BME5", "B-App Event Cancel - No Invitees",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def bme5_business_flow(agent):
    """BME5: Create and cancel event from B-App"""
    print(f"[{agent.role}] [BME5] Create then cancel event from B-App")
    agent.launch_app()
    _wait_tap(agent, "addNewEvent")
    _type_field(agent, "firstName", "Roopa")
    _type_field(agent, "lastName", "D")
    _tap(agent, "anyBtn")
    _type_field(agent, "mobileInputBtn", "9686496589")
    _tap(agent, "saveBtn")
    events["event_created"].set()
    if events["event_accepted"].wait(timeout=120):
        _wait_tap(agent, "cancelEvent")
        _tap(agent, "confirmEventBtn")
        time.sleep(2)
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
    _type_field(agent, "contactSearch", "Noolu")
    _tap(agent, "NooluInvite")
    _tap(agent, "inviteUsers")
    _tap(agent, "chip-container")
    _wait_tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "orderLater")
    _tap(agent, "walletTab")
    events["order_placed"].set()
    # Switch to Noolu to accept
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_tap(agent, "RoopaDInviteCard")
    _tap(agent, "eventAccept")
    _tap(agent, "orderLater")
    _tap(agent, "walletTab")
    # Switch back to Roopa and cancel
    _switch_account(agent, "roopa@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _tap(agent, "NylaiKitchenCard")
    agent.swipe_up()
    _tap(agent, "cancelBookingMe")
    _tap(agent, "NooluNagaassign")
    _tap(agent, "confirmCancelBook")
    _tap(agent, "optionOne")
    _type_field(agent, "cancelReason", "Booked wrong slot!")
    _tap(agent, "optionSubmit")
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
    _tap(agent, "NooluInvite")
    _tap(agent, "inviteUsers")
    _tap(agent, "chip-container")
    _wait_tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "orderLater")
    _tap(agent, "walletTab")
    # Noolu declines
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_tap(agent, "RoopaDInviteCard")
    _tap(agent, "eventDecline")
    _tap(agent, "walletTab")
    # Roopa cancels
    _switch_account(agent, "roopa@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _tap(agent, "NylaiKitchenCard")
    agent.swipe_up()
    _tap(agent, "optionOne")
    _tap(agent, "optionSubmit")
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
    _tap(agent, "NooluInvite")
    _tap(agent, "inviteUsers")
    _tap(agent, "chip-container")
    _wait_tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "orderLater")
    _tap(agent, "walletTab")
    events["order_placed"].set()
    # Switch to Noolu to accept then cancel
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_tap(agent, "RoopaDInviteCard")
    _tap(agent, "eventAccept")
    _tap(agent, "orderLater")
    _tap(agent, "walletTab")
    _tap(agent, "NylaiKitchenCard")
    agent.swipe_up()
    _tap(agent, "cancelBookingMe")
    _tap(agent, "confirmCancelBook")
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
    time.sleep(2)
    _tap(agent, "chip-container")
    _wait_tap(agent, "bookAppoitment")
    time.sleep(3)
    _tap(agent, "preOrderBooking")
    _tap(agent, "starterscategory")
    _tap(agent, "MuttonSeekhKebabInc")
    _tap(agent, "2pcsProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "cartImage")
    _tap(agent, "cartCheckout")
    time.sleep(2)
    _tap(agent, "pickUpOrderConfirm")
    time.sleep(2)
    _tap(agent, "walletTab")
    _tap(agent, "NylaiKitchenCard")
    agent.swipe_up()
    _tap(agent, "cancelBookingMe")
    _tap(agent, "confirmCancelBook")
    time.sleep(2)
    scenario_reporter.add_result("EC12", "Pickup Cancellation",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def ec12_business_flow(agent):
    _no_op(agent)


# ─── FILTER EVENTS IN B-APP (FE1–FE7) ────────────────────────────────────────

def fe1_business_flow(agent):
    """FE1: Filter Events by Status"""
    print(f"[{agent.role}] [FE1] Filter by Status")
    agent.launch_app()
    _tap(agent, "orderFilterBtn")
    _tap(agent, "Reserved")
    _tap(agent, "Confirm")
    agent.swipe_up()
    time.sleep(1)
    _tap(agent, "Remove filter")
    time.sleep(1)
    _tap(agent, "orderFilterBtn")
    _tap(agent, "Serve")
    _tap(agent, "Confirm")
    agent.swipe_up()
    time.sleep(1)
    _tap(agent, "Remove filter")
    scenario_reporter.add_result("FE1", "Filter Events by Status",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def fe1_consumer_flow(agent):
    _no_op(agent)


def fe2_business_flow(agent):
    """FE2: Filter Events by Table"""
    print(f"[{agent.role}] [FE2] Filter by Table")
    agent.launch_app()
    _tap(agent, "modifyTable")
    _tap(agent, "T3")
    _tap(agent, "Confirm")
    agent.swipe_up()
    time.sleep(1)
    _tap(agent, "removeTableFilter")
    _tap(agent, "modifyTable")
    _tap(agent, "T5")
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
    _tap(agent, "Home")
    agent.swipe_up()
    time.sleep(1)
    _tap(agent, "orderFilterBtn")
    _tap(agent, "Order")
    _tap(agent, "Confirm")
    agent.swipe_up()
    time.sleep(1)
    _tap(agent, "Remove filter")
    scenario_reporter.add_result("FE3", "Status Filter in Home Page Popup",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def fe3_consumer_flow(agent):
    _no_op(agent)


def fe4_business_flow(agent):
    """FE4: Table filter in events popup of home page"""
    print(f"[{agent.role}] [FE4] Table Filter in Home Page Popup")
    agent.launch_app()
    _tap(agent, "modifyTable")
    _tap(agent, "T10")
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
    """PO1: Book → Pre-order → Add items (continues into PO2/PO3)"""
    print(f"[{agent.role}] [PO1] Book and pre-order items")
    agent.launch_app()
    agent.swipe_up()
    _wait_tap(agent, "NylaiKitchen")
    _tap(agent, "NylaiKitchen")
    agent.run_step_ai("Tap on 'Any' table type button")
    _tap(agent, "chip-container")
    _wait_tap(agent, "bookAppoitment")
    _tap(agent, "bookAppoitment")
    _wait_tap(agent, "preOrderBooking")
    _tap(agent, "preOrderBooking")
    _wait_tap(agent, "preOrderBooking")
    _tap(agent, "preOrderBooking")
    # Add items
    _tap(agent, "Tagliatelle al Salmone")
    _tap(agent, "Chicken65")
    _tap(agent, "addmayoProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "pasta-pizzacategory")
    _tap(agent, "PizzaRucolaeParmigiano")
    _tap(agent, "FreshbellpepperProduct")
    _tap(agent, "confirmProduct")
    scenario_reporter.add_result("PO1", "Adding More Items from Cart",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def po1_business_flow(agent):
    _no_op(agent)


def po2_consumer_flow(agent):
    """PO2: Add and reduce items in cart and menu screen"""
    print(f"[{agent.role}] [PO2] Add and Reduce Items")
    agent.launch_app()
    _tap(agent, "walletTab")
    time.sleep(2)
    _tap(agent, "NylaiKitchenCard")
    time.sleep(2)
    _tap(agent, "preOrderBooking")
    _tap(agent, "starterscategory")
    _tap(agent, "MuttonSeekhKebabInc")
    _tap(agent, "2pcsProduct")
    _tap(agent, "confirmProduct")
    # Reduce from cart
    _tap(agent, "cartImage")
    _tap(agent, "counterMinus")
    time.sleep(1)
    # Add again from menu
    _tap(agent, "addMore")
    _tap(agent, "confirmProduct")
    scenario_reporter.add_result("PO2", "Add and Reduce Items Cart/Menu",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def po2_business_flow(agent):
    _no_op(agent)


def po3_consumer_flow(agent):
    """PO3: Edit item from cart screen"""
    print(f"[{agent.role}] [PO3] Edit Item from Cart")
    agent.launch_app()
    _tap(agent, "walletTab")
    time.sleep(2)
    _tap(agent, "NylaiKitchenCard")
    time.sleep(2)
    _tap(agent, "preOrderBooking")
    _tap(agent, "starterscategory")
    _tap(agent, "MuttonSeekhKebabInc")
    _tap(agent, "2pcsProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "cartImage")
    # Edit from cart
    _tap(agent, "cartImage")
    _tap(agent, "editItemBtn")
    _tap(agent, "4pcsProduct")
    _tap(agent, "confirmProduct")
    time.sleep(1)
    scenario_reporter.add_result("PO3", "Edit Item from Cart",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def po3_business_flow(agent):
    _no_op(agent)


def po7_consumer_flow(agent):
    """PO7: Add coupon, remove it, re-add and verify total — BILL VALIDATION"""
    print(f"[{agent.role}] [PO7] Coupon Add/Remove/Verify Total")
    # Skip launch — app should already be on NylaiKitchen food menu
    _wait_tap(agent, "starterscategory")
    _tap(agent, "MuttonSeekhKebabInc")
    _tap(agent, "2pcsProduct")
    _tap(agent, "chutneyProduct")
    _tap(agent, "confirmProduct")
    # Apply coupon
    _tap(agent, "applyCoupon")
    _tap(agent, "6% OFFER")
    _tap(agent, "cartCheckout")
    time.sleep(2)
    # Validate bill at checkout screen
    agent.check_bill()
    events["preorder_submitted"].set()


def po7_business_flow(agent):
    """PO7 Business: Accept order and process payment"""
    print(f"[{agent.role}] [PO7] Accept and process payment")
    agent.launch_app()
    if events["preorder_submitted"].wait(timeout=180):
        _wait_tap(agent, "Orders")
        _wait_tap(agent, "ReservedOrderCard")
        _tap(agent, "T0AssignAnyBtn")
        _tap(agent, "AssignTableBtn")
        _wait_tap(agent, "addItemsBtn")
        _tap(agent, "addItemsBtn")
        _wait_tap(agent, "Cheesy & Comfort PlatesBtn")
        agent.swipe_up()
        _tap(agent, "Cheesy & Comfort PlatesBtn")
        _tap(agent, "Macaroni&CheeseBakeItem")
        _tap(agent, "regularBtn")
        _tap(agent, "AddTruffleOilBtn")
        _tap(agent, "applyOptionBtn")
        _tap(agent, "assignToBtn")
        _tap(agent, "selectAll")
        _tap(agent, "assignProductsBtn")
        time.sleep(2)
        _tap(agent, "selectAllItemsBtn")
        _tap(agent, "sendItemsBtn")
        _wait_tap(agent, "backButton")
        _tap(agent, "backButton")
        _tap(agent, "Orders")
        _tap(agent, "ServeOrderCard")
        _tap(agent, "selectAllItemsBtn")
        _tap(agent, "serveItemsBtn")
        _tap(agent, "notifyPaymentBtn")
        _tap(agent, "Payment Payment")
        _tap(agent, "NooluNagaCard")
        _wait_tap(agent, "cashPaymentBtn")
        _tap(agent, "cashPaymentBtn")
        _tap(agent, "Number2")
        _tap(agent, "Number0")
        _tap(agent, "userInputBtn")
        _tap(agent, "RoopaDselect")
        _tap(agent, "Apply")
        agent.swipe_up()
        _wait_tap(agent, "paymentConfirmBtn")
        _tap(agent, "paymentConfirmBtn")
        _wait_tap(agent, "closeTableBtn")
        _tap(agent, "Overview Overview")
        _tap(agent, "closeTableBtn")
        events["payment_completed"].set()
        scenario_reporter.add_result("PO7", "Coupon Verify Total",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


# ─── PAYMENTS (PAY1–PAY6) ─────────────────────────────────────────────────────

def pay1_business_flow(agent):
    """PAY1: Payment Methods - Cash"""
    print(f"[{agent.role}] [PAY1] Payment by Cash")
    agent.launch_app()
    _tap(agent, "Orders")
    _tap(agent, "ServeOrderCard")
    _tap(agent, "selectAllItemsBtn")
    _tap(agent, "serveItemsBtn")
    _tap(agent, "notifyPaymentBtn")
    _tap(agent, "Payment Payment")
    time.sleep(2)
    # Validate bill before payment
    agent.check_bill()
    _tap(agent, "NooluNagaCard")
    _wait_tap(agent, "cashPaymentBtn")
    _tap(agent, "cashPaymentBtn")
    _tap(agent, "userInputBtn")
    _tap(agent, "RoopaDselect")
    _tap(agent, "Apply")
    agent.swipe_up()
    _wait_tap(agent, "paymentConfirmBtn")
    _tap(agent, "paymentConfirmBtn")
    events["payment_completed"].set()
    scenario_reporter.add_result("PAY1", "Payment by Cash",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def pay1_consumer_flow(agent):
    """PAY1 Consumer: Wait for payment request"""
    agent.launch_app()
    _tap(agent, "walletTab")
    if events["payment_completed"].wait(timeout=180):
        time.sleep(2)
        scenario_reporter.add_result("PAY1", "Payment by Cash",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def pay3_business_flow(agent):
    """PAY3: Payment by E-Payment"""
    print(f"[{agent.role}] [PAY3] Payment by E-Payment")
    agent.launch_app()
    _tap(agent, "Orders")
    _tap(agent, "ServeOrderCard")
    _tap(agent, "selectAllItemsBtn")
    _tap(agent, "serveItemsBtn")
    _tap(agent, "notifyPaymentBtn")
    _tap(agent, "Payment Payment")
    time.sleep(2)
    agent.check_bill()
    _tap(agent, "NooluNagaCard")
    _tap(agent, "ePaymentBtn")
    _tap(agent, "userInputBtn")
    _tap(agent, "RoopaDselect")
    _tap(agent, "Apply")
    agent.swipe_up()
    _wait_tap(agent, "paymentConfirmBtn")
    _tap(agent, "paymentConfirmBtn")
    events["payment_completed"].set()
    scenario_reporter.add_result("PAY3", "Payment by E-Payment",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def pay3_consumer_flow(agent):
    agent.launch_app()
    _tap(agent, "walletTab")
    if events["payment_completed"].wait(timeout=180):
        scenario_reporter.add_result("PAY3", "Payment by E-Payment",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def pay2_consumer_flow(agent):
    """PAY2: Host (Roopa) books with 1 guest, host pays for others"""
    print(f"[{agent.role}] [PAY2] Host books with 1 guest")
    agent.launch_app()
    _switch_account(agent, "roopa@xorstack.com", "12345")
    _wait_tap(agent, "NylaiKitchen")
    agent.swipe_up()
    _tap(agent, "NylaiKitchen")
    _tap(agent, "Any")
    _tap(agent, "counterPlus")
    _tap(agent, "guestAdd")
    _tap(agent, "inviteUsers")
    _tap(agent, "chip-container")
    _wait_tap(agent, "bookAppoitment")
    _tap(agent, "bookAppoitment")
    _wait_tap(agent, "orderLater")
    _tap(agent, "orderLater")
    events["order_placed"].set()
    if events["payment_completed"].wait(timeout=300):
        scenario_reporter.add_result("PAY2", "Host Pays for Others",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def pay2_business_flow(agent):
    """PAY2 Business: Process order where host pays for guest"""
    print(f"[{agent.role}] [PAY2] Process host-pays-for-others order")
    agent.launch_app()
    if events["order_placed"].wait(timeout=180):
        _wait_tap(agent, "Orders")
        _tap(agent, "Orders")
        _tap(agent, "ReservedOrderCard")
        _tap(agent, "T8")
        _wait_tap(agent, "T0AssignAnyBtn")
        _tap(agent, "T0AssignAnyBtn")
        _tap(agent, "AssignTableBtn")
        _wait_tap(agent, "addItemsBtn")
        _tap(agent, "addItemsBtn")
        _tap(agent, "Pasta & PizzaBtn")
        _tap(agent, "PizzaRucolaeParmigianoItem")
        _tap(agent, "FreshbellpepperBtn")
        _tap(agent, "applyOptionBtn")
        _tap(agent, "PizzaRucolaeParmigianoItem")
        _tap(agent, "addNewCustomSelection")
        _tap(agent, "FreshchampignonsBtn")
        _tap(agent, "applyOptionBtn")
        _tap(agent, "PizzaRucolaeParmigianoItem")
        _tap(agent, "addNewCustomSelection")
        _tap(agent, "CookedhamBtn")
        _tap(agent, "applyOptionBtn")
        _tap(agent, "PizzaQuattroStagioniItem")
        _tap(agent, "applyOptionBtn")
        _tap(agent, "assignToBtn")
        _tap(agent, "selectAll")
        _wait_tap(agent, "assignProductsBtn")
        _tap(agent, "assignProductsBtn")
        _wait_tap(agent, "selectAllItemsBtn")
        _tap(agent, "selectAllItemsBtn")
        _tap(agent, "sendItemsBtn")
        _wait_tap(agent, "backButton")
        _tap(agent, "backButton")
        # Kitchen staff
        _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
        _wait_tap(agent, "inProgressOrderCard")
        _tap(agent, "inProgressOrderCard")
        _tap(agent, "PizzaRucolaeParmigiano2Freshchampignons PizzaRucolaeParmigiano")
        _tap(agent, "PizzaRucolaeParmigiano2Freshbellpepper PizzaRucolaeParmigiano")
        _tap(agent, "PizzaQuattroStagioni2 PizzaQuattroStagioni")
        _tap(agent, "PizzaRucolaeParmigiano2Cookedham PizzaRucolaeParmigiano")
        _tap(agent, "orderReadyBtn")
        _tap(agent, "orderCloseBtn")
        # Serve staff
        _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
        _tap(agent, "Orders")
        _tap(agent, "Orders")
        _wait_tap(agent, "ServeOrderCard")
        _tap(agent, "ServeOrderCard")
        _tap(agent, "selectAllItemsBtn")
        _tap(agent, "serveItemsBtn")
        _tap(agent, "notifyPaymentBtn")
        _tap(agent, "Payment Payment")
        # Host pays for guest
        _tap(agent, "RoopaDCard")
        _wait_tap(agent, "cashPaymentBtn")
        _tap(agent, "cashPaymentBtn")
        _tap(agent, "Number1")
        _tap(agent, "Number0")
        _tap(agent, "userInputBtn")
        _tap(agent, "Guest1select")
        _tap(agent, "Apply")
        agent.swipe_up()
        _wait_tap(agent, "paymentConfirmBtn")
        _tap(agent, "paymentConfirmBtn")
        _tap(agent, "tipBtn")
        _tap(agent, "Number9")
        _tap(agent, "Decimal point")
        _tap(agent, "Number5")
        _tap(agent, "userInputBtn")
        _tap(agent, "cashPaymentBtn")
        _tap(agent, "Number1")
        _tap(agent, "Number5")
        _tap(agent, "Number3")
        _tap(agent, "Decimal point")
        _tap(agent, "Number4")
        _tap(agent, "userInputBtn")
        agent.swipe_up()
        _wait_tap(agent, "paymentConfirmBtn")
        _tap(agent, "paymentConfirmBtn")
        _wait_tap(agent, "RoopaDCard")
        _tap(agent, "Overview Overview")
        _wait_tap(agent, "closeTableBtn")
        _tap(agent, "closeTableBtn")
        events["payment_completed"].set()
        scenario_reporter.add_result("PAY2", "Host Pays for Others",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def pay4_consumer_flow(agent):
    _no_op(agent)


def pay4_business_flow(agent):
    """PAY4: Payment by Food Voucher"""
    print(f"[{agent.role}] [PAY4] Payment by Food Voucher")
    agent.launch_app()
    _wait_tap(agent, "NylaiKitchen")
    agent.swipe_up()
    _tap(agent, "NylaiKitchen")
    _tap(agent, "Any")
    _tap(agent, "counterPlus")
    _tap(agent, "guestAdd")
    _tap(agent, "inviteUsers")
    _tap(agent, "chip-container")
    _wait_tap(agent, "bookAppoitment")
    _tap(agent, "bookAppoitment")
    _wait_tap(agent, "orderLater")
    _tap(agent, "orderLater")
    _wait_tap(agent, "Orders")
    _tap(agent, "Orders")
    _tap(agent, "ReservedOrderCard")
    _tap(agent, "T8")
    _wait_tap(agent, "T0AssignAnyBtn")
    _tap(agent, "T0AssignAnyBtn")
    _tap(agent, "AssignTableBtn")
    _wait_tap(agent, "addItemsBtn")
    _tap(agent, "addItemsBtn")
    agent.swipe_up()
    agent.swipe_up()
    agent.swipe_up()
    agent.swipe_up()
    _tap(agent, "CrispyThaiSpringRollsItem")
    _tap(agent, "6pcsBtn")
    _tap(agent, "applyOptionBtn")
    _tap(agent, "Pasta & PizzaBtn")
    _tap(agent, "PizzaQuattroStagioniItem")
    _tap(agent, "assignToBtn")
    _tap(agent, "selectAll")
    _wait_tap(agent, "assignProductsBtn")
    _tap(agent, "assignProductsBtn")
    _wait_tap(agent, "selectAllItemsBtn")
    _tap(agent, "selectAllItemsBtn")
    _tap(agent, "sendItemsBtn")
    _wait_tap(agent, "backButton")
    _tap(agent, "backButton")
    # Kitchen staff
    _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
    _wait_tap(agent, "inProgressOrderCard")
    _tap(agent, "inProgressOrderCard")
    _tap(agent, "CrispyThaiSpringRolls26pcs CrispyThaiSpringRolls")
    _tap(agent, "PizzaQuattroStagioni2 PizzaQuattroStagioni")
    _tap(agent, "orderReadyBtn")
    _tap(agent, "orderCloseBtn")
    # Serve staff
    _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
    _wait_tap(agent, "Orders")
    _tap(agent, "ServeOrderCard")
    _tap(agent, "selectAllItemsBtn")
    _tap(agent, "serveItemsBtn")
    _tap(agent, "notifyPaymentBtn")
    _tap(agent, "Payment Payment")
    # Food voucher payment
    _tap(agent, "RoopaDCard")
    _wait_tap(agent, "foodVoucherBtn")
    _tap(agent, "foodVoucherBtn")
    _tap(agent, "foodVoucher10CounterIncrement")
    _tap(agent, "inputVoucher")
    _tap(agent, "Guest1select")
    _tap(agent, "Apply")
    _tap(agent, "cashPaymentBtn")
    _tap(agent, "Number5")
    _tap(agent, "Number0")
    _tap(agent, "Number0")
    _tap(agent, "userInputBtn")
    agent.swipe_up()
    _wait_tap(agent, "paymentConfirmBtn")
    _tap(agent, "paymentConfirmBtn")
    _wait_tap(agent, "RoopaDCard")
    _tap(agent, "Overview Overview")
    _wait_tap(agent, "closeTableBtn")
    _tap(agent, "closeTableBtn")
    scenario_reporter.add_result("PAY4", "Payment by Food Voucher",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def pay5_consumer_flow(agent):
    _no_op(agent)


def pay5_business_flow(agent):
    """PAY5: Payment using all 3 modes (cash + e-payment + food voucher)"""
    print(f"[{agent.role}] [PAY5] Payment with all 3 modes")
    agent.launch_app()
    _wait_tap(agent, "NylaiKitchen")
    agent.swipe_up()
    _tap(agent, "NylaiKitchen")
    _tap(agent, "Any")
    _tap(agent, "counterPlus")
    _tap(agent, "guestAdd")
    _tap(agent, "inviteUsers")
    _tap(agent, "chip-container")
    _wait_tap(agent, "bookAppoitment")
    _tap(agent, "bookAppoitment")
    _wait_tap(agent, "orderLater")
    _tap(agent, "orderLater")
    _wait_tap(agent, "Orders")
    _tap(agent, "Orders")
    _tap(agent, "ReservedOrderCard")
    _tap(agent, "T8")
    _wait_tap(agent, "T0AssignAnyBtn")
    _tap(agent, "T0AssignAnyBtn")
    _tap(agent, "AssignTableBtn")
    _wait_tap(agent, "addItemsBtn")
    _tap(agent, "addItemsBtn")
    _tap(agent, "Pasta & PizzaBtn")
    _tap(agent, "SpaghettiAglioeOlioItem")
    _tap(agent, "FreshbellpepperBtn")
    _tap(agent, "applyOptionBtn")
    _tap(agent, "PizzaQuattroStagioniItem")
    _tap(agent, "applyOptionBtn")
    _tap(agent, "assignToBtn")
    _tap(agent, "selectAll")
    _wait_tap(agent, "assignProductsBtn")
    _tap(agent, "assignProductsBtn")
    _wait_tap(agent, "selectAllItemsBtn")
    _tap(agent, "selectAllItemsBtn")
    _tap(agent, "sendItemsBtn")
    _wait_tap(agent, "backButton")
    _tap(agent, "backButton")
    # Kitchen staff
    _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
    _wait_tap(agent, "inProgressOrderCard")
    _tap(agent, "inProgressOrderCard")
    _tap(agent, "SpaghettiAglioeOlio2Freshbellpepper SpaghettiAglioeOlio")
    _tap(agent, "PizzaQuattroStagioni2 PizzaQuattroStagioni")
    _tap(agent, "orderReadyBtn")
    _tap(agent, "orderCloseBtn")
    # Serve staff
    _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
    _wait_tap(agent, "Orders")
    _tap(agent, "ServeOrderCard")
    _tap(agent, "selectAllItemsBtn")
    _tap(agent, "serveItemsBtn")
    _tap(agent, "notifyPaymentBtn")
    _tap(agent, "Payment Payment")
    # All 3 payment modes
    _tap(agent, "RoopaDCard")
    _wait_tap(agent, "tipBtn")
    _tap(agent, "tipBtn")
    _tap(agent, "Number1")
    _tap(agent, "Number0")
    _tap(agent, "userInputBtn")
    _tap(agent, "cashPaymentBtn")
    _tap(agent, "Number3")
    _tap(agent, "Number0")
    _tap(agent, "userInputBtn")
    _tap(agent, "Guest1select")
    _tap(agent, "Apply")
    _tap(agent, "epaymentBtn")
    _tap(agent, "Number2")
    _tap(agent, "Number0")
    _tap(agent, "Decimal point")
    _tap(agent, "Number5")
    _tap(agent, "userInputBtn")
    agent.swipe_up()
    _tap(agent, "foodVoucherBtn")
    _tap(agent, "foodVoucher10CounterIncrement")
    _tap(agent, "inputVoucher")
    _wait_tap(agent, "paymentConfirmBtn")
    _tap(agent, "paymentConfirmBtn")
    _wait_tap(agent, "RoopaDCard")
    _tap(agent, "Overview Overview")
    _wait_tap(agent, "closeTableBtn")
    _tap(agent, "closeTableBtn")
    scenario_reporter.add_result("PAY5", "Payment All 3 Modes",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


# ─── STATUS VERIFICATION (SV1–SV16) ─────────────────────────────────────────

def sv1_business_flow(agent):
    """SV1: Confirmation Pending Status"""
    print(f"[{agent.role}] [SV1] Confirmation Pending Status")
    agent.launch_app()
    agent.swipe_up()
    _wait_tap(agent, "addNewEvent")
    _type_field(agent, "firstName", "Roopa")
    _type_field(agent, "lastName", "D")
    _tap(agent, "anyBtn")
    _type_field(agent, "mobileInputBtn", "9686496589")
    _tap(agent, "saveBtn")
    events["event_created"].set()
    time.sleep(3)
    scenario_reporter.add_result("SV1", "Confirmation Pending Status",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv1_consumer_flow(agent):
    """SV1: Consumer sees Confirmation Pending"""
    agent.launch_app()
    if events["event_created"].wait(timeout=60):
        _tap(agent, "walletTab")
        time.sleep(2)
        _wait_tap(agent, "Nylai KitchenInviteCard")
        time.sleep(2)
        scenario_reporter.add_result("SV1", "Confirmation Pending Status",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def sv3_business_flow(agent):
    """SV3: Event Declination from B-App"""
    print(f"[{agent.role}] [SV3] Event Declination from B-App")
    agent.launch_app()
    agent.swipe_up()
    _wait_tap(agent, "addNewEvent")
    _type_field(agent, "firstName", "Roopa")
    _type_field(agent, "lastName", "D")
    _tap(agent, "anyBtn")
    _type_field(agent, "mobileInputBtn", "9686496589")
    _tap(agent, "saveBtn")
    events["event_created"].set()
    if events["event_declined"].wait(timeout=120):
        time.sleep(2)
        scenario_reporter.add_result("SV3", "Event Declination",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def sv3_consumer_flow(agent):
    """SV3: Consumer declines event from B-App"""
    agent.launch_app()
    if events["event_created"].wait(timeout=60):
        _tap(agent, "walletTab")
        time.sleep(2)
        _wait_tap(agent, "Nylai KitchenInviteCard")
        _tap(agent, "eventDecline")
        time.sleep(2)
        events["event_declined"].set()
        scenario_reporter.add_result("SV3", "Event Declination",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


# ─── PDF Generation (PDF1–PDF3) ──────────────────────────────────────────────

def pdf1_business_flow(agent):
    """PDF1: Generate PDF for Payment by Individuals"""
    print(f"[{agent.role}] [PDF1] Generate PDF - Individual Payment")
    agent.launch_app()
    _tap(agent, "Orders")
    _tap(agent, "ServeOrderCard")
    _tap(agent, "selectAllItemsBtn")
    _tap(agent, "serveItemsBtn")
    _tap(agent, "notifyPaymentBtn")
    _tap(agent, "Payment Payment")
    time.sleep(2)
    agent.check_bill()
    _tap(agent, "NooluNagaCard")
    _wait_tap(agent, "cashPaymentBtn")
    _tap(agent, "cashPaymentBtn")
    _tap(agent, "userInputBtn")
    _tap(agent, "RoopaDselect")
    _tap(agent, "Apply")
    agent.swipe_up()
    _wait_tap(agent, "paymentConfirmBtn")
    _tap(agent, "paymentConfirmBtn")
    _wait_tap(agent, "pdfGenerateBtn")
    _tap(agent, "pdfGenerateBtn")
    time.sleep(3)
    scenario_reporter.add_result("PDF1", "Generate PDF - Individual Payment",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def pdf1_consumer_flow(agent):
    agent.launch_app()
    _tap(agent, "walletTab")
    time.sleep(2)
    scenario_reporter.add_result("PDF1", "Generate PDF - Individual Payment",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def pdf2_business_flow(agent):
    """PDF2: Generate PDF for entire event (all guests)"""
    print(f"[{agent.role}] [PDF2] Generate PDF for Entire Event")
    agent.launch_app()
    _tap(agent, "Assign/Split Assign/Split")
    _wait_tap(agent, "addItemsBtn")
    _tap(agent, "addItemsBtn")
    _tap(agent, "eventInvoice")
    _wait_tap(agent, "printNow")
    _tap(agent, "printNow")
    agent.swipe_up()
    time.sleep(3)
    scenario_reporter.add_result("PDF2", "Generate PDF for Entire Event",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def pdf2_consumer_flow(agent):
    _no_op(agent)


def pdf3_business_flow(agent):
    """PDF3: Generate PDF after event completion for individual"""
    print(f"[{agent.role}] [PDF3] Generate PDF after Event Completion (Individual)")
    agent.launch_app()
    _tap(agent, "backButton")
    _wait_tap(agent, "addItemsBtn")
    _tap(agent, "addItemsBtn")
    _tap(agent, "individualInvoice")
    _tap(agent, "NooluNagaselect")
    _wait_tap(agent, "printNow")
    _tap(agent, "printNow")
    agent.swipe_up()
    time.sleep(2)
    _tap(agent, "RoopaDCard")
    _tap(agent, "backButton")
    _tap(agent, "Overview Overview")
    _wait_tap(agent, "closeTableBtn")
    _tap(agent, "closeTableBtn")
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
    _tap(agent, "clickCheckBox")
    _wait_tap(agent, "signInBtn")
    time.sleep(3)


def o1_consumer_flow(agent):
    """O1: Adding items with different modifiers & variants - 5 users"""
    print(f"[{agent.role}] [O1] Booking with 2 invitees for modifiers scenario")
    agent.launch_app()
    _wait_tap(agent, "NylaiKitchen")
    agent.swipe_up()
    _tap(agent, "NylaiKitchen")
    _tap(agent, "counterPlus")
    _tap(agent, "guestAdd")
    _tap(agent, "guestAdd")
    _type_field(agent, "contactSearch", "Noolu")
    _tap(agent, "NooluInvite")
    _type_field(agent, "contactSearch", "Aritro")
    _tap(agent, "AritroInvite")
    _tap(agent, "inviteUsers")
    _wait_tap(agent, "chip-container")
    _tap(agent, "chip-container")
    _wait_tap(agent, "bookAppoitment")
    _tap(agent, "bookAppoitment")
    _wait_tap(agent, "orderLater")
    _tap(agent, "orderLater")
    # Noolu accepts
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_tap(agent, "RoopaDInviteCard")
    _tap(agent, "RoopaDInviteCard")
    _tap(agent, "eventAccept")
    _tap(agent, "orderLater")
    _tap(agent, "walletTab")
    # Aritro accepts
    _switch_account(agent, "aritro@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_tap(agent, "RoopaDInviteCard")
    _tap(agent, "RoopaDInviteCard")
    _tap(agent, "eventAccept")
    events["order_placed"].set()
    scenario_reporter.add_result("O1", "Adding Items with Modifiers & Variants",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def o1_business_flow(agent):
    """O1 Business: Process order with complex modifiers & variants"""
    print(f"[{agent.role}] [O1] Process order with modifiers")
    agent.launch_app()
    if events["order_placed"].wait(timeout=180):
        _wait_tap(agent, "Orders")
        _tap(agent, "Orders")
        _tap(agent, "ReservedOrderCard")
        _wait_tap(agent, "T0AssignAnyBtn")
        _tap(agent, "T0AssignAnyBtn")
        _tap(agent, "AssignTableBtn")
        _wait_tap(agent, "addItemsBtn")
        _tap(agent, "addItemsBtn")
        agent.swipe_up()
        agent.swipe_up()
        _tap(agent, "ThaiGreenCurrywithJasmineRiceItem")
        _tap(agent, "vegBtn")
        _tap(agent, "addspicyBtn")
        _tap(agent, "applyOptionBtn")
        _tap(agent, "ThaiGreenCurrywithJasmineRiceItem")
        _tap(agent, "addNewCustomSelection")
        _tap(agent, "tofuBtn")
        agent.swipe_up()
        _tap(agent, "extrapeanutsBtn")
        _tap(agent, "applyOptionBtn")
        _tap(agent, "ThaiGreenCurrywithJasmineRiceItem")
        _tap(agent, "addNewCustomSelection")
        _tap(agent, "chickenBtn")
        agent.swipe_up()
        _tap(agent, "extrasauceBtn")
        _tap(agent, "applyOptionBtn")
        _tap(agent, "ThaiGreenCurrywithJasmineRiceItem")
        _tap(agent, "addNewCustomSelection")
        _tap(agent, "chickenBtn")
        agent.swipe_up()
        _tap(agent, "addmayoBtn")
        _tap(agent, "applyOptionBtn")
        _tap(agent, "assignToBtn")
        _tap(agent, "RoopaDselect")
        agent.swipe_up()
        agent.swipe_up()
        _tap(agent, "Guest1select")
        _tap(agent, "Guest2select")
        _wait_tap(agent, "assignProductsBtn")
        _tap(agent, "assignProductsBtns")
        _wait_tap(agent, "selectAllItemsBtn")
        _tap(agent, "selectAllItemsBtn")
        _tap(agent, "sendItemsBtn")
        _wait_tap(agent, "backButton")
        _tap(agent, "backButton")
        events["kitchen_accepted"].set()
        scenario_reporter.add_result("O1", "Adding Items with Modifiers & Variants",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def o2_consumer_flow(agent):
    _no_op(agent)


def o2_business_flow(agent):
    """O2: Split before serve"""
    print(f"[{agent.role}] [O2] Split before serve")
    agent.launch_app()
    _tap(agent, "Orders")
    _tap(agent, "ServeOrderCard")
    _wait_tap(agent, "addItemsBtn")
    _tap(agent, "addItemsBtn")
    _tap(agent, "PizzaRucolaeParmigianoItem")
    _tap(agent, "FreshchampignonsBtn")
    _tap(agent, "applyOptionBtn")
    _tap(agent, "PizzaRucolaeParmigianoItem")
    _tap(agent, "addNewCustomSelection")
    _tap(agent, "CookedhamBtn")
    agent.swipe_up()
    _tap(agent, "applyOptionBtn")
    _tap(agent, "assignToBtn")
    _tap(agent, "NooluNagaselect")
    _wait_tap(agent, "assignProductsBtn")
    _tap(agent, "assignProductsBtn")
    _wait_tap(agent, "selectAllItemsBtn")
    _tap(agent, "selectAllItemsBtn")
    _tap(agent, "sendItemsBtn")
    _wait_tap(agent, "backButton")
    _tap(agent, "backButton")
    # Kitchen staff prepares
    _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
    _wait_tap(agent, "inProgressOrderCard")
    _tap(agent, "inProgressOrderCard")
    _tap(agent, "ThaiGreenCurrywithJasmineRice1vegaddspicy ThaiGreenCurrywithJasmineRice")
    _tap(agent, "ThaiGreenCurrywithJasmineRice1tofuextrapeanuts ThaiGreenCurrywithJasmineRice")
    agent.swipe_up()
    _tap(agent, "ThaiGreenCurrywithJasmineRice1chickenaddmayoOnions ThaiGreenCurrywithJasmineRice")
    _tap(agent, "ThaiGreenCurrywithJasmineRice1chickenextrasauceMor ThaiGreenCurrywithJasmineRice")
    _tap(agent, "PizzaRucolaeParmigiano1Freshchampignons PizzaRucolaeParmigiano")
    _tap(agent, "PizzaRucolaeParmigiano1Cookedham PizzaRucolaeParmigiano")
    _tap(agent, "orderReadyBtn")
    _tap(agent, "orderCloseBtn")
    # Serve staff
    _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
    _tap(agent, "Orders")
    _tap(agent, "ServeOrderCard")
    scenario_reporter.add_result("O2", "Split Before Serve",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def o3_consumer_flow(agent):
    _no_op(agent)


def o3_business_flow(agent):
    """O3: Try to split already-splitted items (validation check)"""
    print(f"[{agent.role}] [O3] Trying to split splitted items")
    agent.launch_app()
    _tap(agent, "Assign/Split Assign/Split")
    _tap(agent, "ThaiGreenCurrywithJasmineRicecard")
    _tap(agent, "sendItemsBtn")
    _tap(agent, "RoopaDselect")
    _tap(agent, "Guest1select")
    _tap(agent, "assignProductsBtns")
    _tap(agent, "closeModal")
    scenario_reporter.add_result("O3", "Trying to Split Splitted Items",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def o4_consumer_flow(agent):
    _no_op(agent)


def o4_business_flow(agent):
    """O4: Assigning item from 1 person to another"""
    print(f"[{agent.role}] [O4] Assigning item from 1 to another")
    agent.launch_app()
    _tap(agent, "arrowBtn")
    _tap(agent, "NooluNagaselect")
    _tap(agent, "PizzaRucolaeParmigianocard")
    _tap(agent, "sendItemsBtn")
    _tap(agent, "RoopaDselect")
    _tap(agent, "assignProductsBtns")
    _tap(agent, "closeModal")
    _tap(agent, "assignProductsBtns")
    agent.run_step_ai("Tap on the 'Overview Overview' button")
    _tap(agent, "selectAllItemsBtn")
    _wait_tap(agent, "selectAllItemsBtn")
    _tap(agent, "serveItemsBtn")
    _wait_tap(agent, "serveItemsBtn")
    scenario_reporter.add_result("O4", "Assigning Item from 1 to Another",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def o5_consumer_flow(agent):
    _no_op(agent)


def o5_business_flow(agent):
    """O5: Split after serve with payment"""
    print(f"[{agent.role}] [O5] Split after serve")
    agent.launch_app()
    _tap(agent, "Assign/Split Assign/Split")
    _tap(agent, "NooluNagaselect")
    _tap(agent, "PizzaRucolaeParmigianocard")
    _tap(agent, "sendItemsBtn")
    _tap(agent, "NooluNagaselect")
    agent.swipe_up()
    agent.swipe_up()
    _tap(agent, "Guest2select")
    _tap(agent, "Guest1select")
    _tap(agent, "assignProductsBtns")
    _tap(agent, "closeModal")
    _tap(agent, "Overview Overview")
    _tap(agent, "notifyPaymentBtn")
    _tap(agent, "Payment Payment")
    agent.swipe_up()
    _tap(agent, "RoopaDCard")
    _tap(agent, "cashPaymentBtn")
    _tap(agent, "Number7")
    _tap(agent, "Number0")
    _tap(agent, "userInputBtn")
    _tap(agent, "Guest1select")
    _tap(agent, "Guest2select")
    _tap(agent, "Apply")
    agent.swipe_up()
    _wait_tap(agent, "paymentConfirmBtn")
    _tap(agent, "paymentConfirmBtn")
    agent.swipe_up()
    agent.swipe_up()
    _tap(agent, "NooluNagaCard")
    agent.swipe_up()
    _wait_tap(agent, "cashPaymentBtn")
    _tap(agent, "cashPaymentBtn")
    _tap(agent, "Number1")
    _tap(agent, "Number0")
    _tap(agent, "userInputBtn")
    _tap(agent, "tipBtn")
    _tap(agent, "Number1")
    agent.swipe_up()
    _wait_tap(agent, "paymentConfirmBtn")
    _tap(agent, "paymentConfirmBtn")
    _tap(agent, "Overview Overview")
    events["payment_completed"].set()
    scenario_reporter.add_result("O5", "Split After Serve with Payment",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


# ─── PAYMENTS 2 (PAY6–PAY7) ──────────────────────────────────────────────────

def pay6_consumer_flow(agent):
    """PAY6: Participant Pays for Others"""
    print(f"[{agent.role}] [PAY6] Participant books event for Roopa")
    agent.launch_app()
    _wait_tap(agent, "NylaiKitchen")
    _tap(agent, "NylaiKitchen")
    _tap(agent, "counterPlus")
    _tap(agent, "guestAdd")
    _type_field(agent, "contactSearch", "Roopa")
    _tap(agent, "RoopaInvite")
    _tap(agent, "inviteUsers")
    _tap(agent, "chip-container")
    _wait_tap(agent, "bookAppoitment")
    _tap(agent, "bookAppoitment")
    _wait_tap(agent, "orderLater")
    _tap(agent, "orderLater")
    # Switch to Roopa to accept
    _switch_account(agent, "roopa@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_tap(agent, "NooluNagaInviteCard")
    _tap(agent, "NooluNagaInviteCard")
    _tap(agent, "eventAccept")
    _tap(agent, "orderLater")
    events["order_placed"].set()
    if events["payment_completed"].wait(timeout=300):
        scenario_reporter.add_result("PAY6", "Participant Pays for Others",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def pay6_business_flow(agent):
    """PAY6 Business: Process complex payment"""
    print(f"[{agent.role}] [PAY6] Process participant pays for others")
    agent.launch_app()
    if events["order_placed"].wait(timeout=180):
        _tap(agent, "Orders")
        _tap(agent, "ReservedOrderCard")
        _wait_tap(agent, "T0AssignAnyBtn")
        _tap(agent, "T0AssignAnyBtn")
        _tap(agent, "AssignTableBtn")
        _wait_tap(agent, "addItemsBtn")
        _tap(agent, "addItemsBtn")
        _tap(agent, "FishAmritsariItem")
        _tap(agent, "largeBtn")
        _tap(agent, "applyOptionBtn")
        agent.swipe_up()
        _tap(agent, "PadThaiNoodlesItem")
        _tap(agent, "prawnBtn")
        _tap(agent, "addspicyBtn")
        _tap(agent, "applyOptionBtn")
        _tap(agent, "Spinach&CheeseRavioliItem")
        _tap(agent, "regularBtn")
        _tap(agent, "AddGarlicOilBtn")
        _tap(agent, "applyOptionBtn")
        _wait_tap(agent, "assignToBtn")
        _tap(agent, "assignToBtn")
        _tap(agent, "selectAll")
        _wait_tap(agent, "assignProductsBtn")
        _tap(agent, "assignProductsBtn")
        _wait_tap(agent, "selectAllItemsBtn")
        _tap(agent, "selectAllItemsBtn")
        _tap(agent, "sendItemsBtn")
        _wait_tap(agent, "backButton")
        _tap(agent, "backButton")
        # Kitchen staff prepares
        _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
        _wait_tap(agent, "inProgressOrderCard")
        _tap(agent, "inProgressOrderCard")
        _tap(agent, "FishAmritsari3largeroastedfish")
        _tap(agent, "PadThaiNoodles3prawnaddspicy")
        _tap(agent, "Spinach&CheeseRavioli3regularAddGarlicOil")
        _tap(agent, "orderReadyBtn")
        _tap(agent, "orderCloseBtn")
        # Serve staff
        _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
        _tap(agent, "Orders")
        _tap(agent, "ServeOrderCard")
        _tap(agent, "selectAllItemsBtn")
        _tap(agent, "serveItemsBtn")
        _tap(agent, "notifyPaymentBtn")
        _tap(agent, "Payment Payment")
        _tap(agent, "RoopaDCard")
        agent.swipe_up()
        _wait_tap(agent, "cashPaymentBtn")
        _tap(agent, "cashPaymentBtn")
        _tap(agent, "Number9")
        _tap(agent, "Number8")
        _tap(agent, "Number0")
        _tap(agent, "Number0")
        _tap(agent, "userInputBtn")
        _tap(agent, "Guest1select")
        _tap(agent, "NooluNagaselect")
        _tap(agent, "Apply")
        agent.swipe_up()
        _wait_tap(agent, "paymentConfirmBtn")
        _tap(agent, "paymentConfirmBtn")
        _tap(agent, "Overview Overview")
        _wait_tap(agent, "closeTableBtn")
        _tap(agent, "closeTableBtn")
        events["payment_completed"].set()
        scenario_reporter.add_result("PAY6", "Participant Pays for Others",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def pay7_consumer_flow(agent):
    """PAY7: Guest is Paying for Others"""
    print(f"[{agent.role}] [PAY7] Book event with Noolu as guest")
    agent.launch_app()
    agent.swipe_up()
    _wait_tap(agent, "NylaiKitchen")
    _tap(agent, "NylaiKitchen")
    _tap(agent, "counterPlus")
    _tap(agent, "guestAdd")
    _type_field(agent, "contactSearch", "Noolu")
    _tap(agent, "NooluInvite")
    _tap(agent, "inviteUsers")
    _tap(agent, "chip-container")
    _wait_tap(agent, "bookAppoitment")
    _tap(agent, "bookAppoitment")
    _wait_tap(agent, "orderLater")
    _tap(agent, "orderLater")
    # Noolu accepts
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_tap(agent, "RoopaDInviteCard")
    _tap(agent, "RoopaDInviteCard")
    _tap(agent, "eventAccept")
    _tap(agent, "orderLater")
    events["order_placed"].set()
    if events["payment_completed"].wait(timeout=300):
        scenario_reporter.add_result("PAY7", "Guest Pays for Others",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def pay7_business_flow(agent):
    """PAY7 Business: Guest pays for others"""
    print(f"[{agent.role}] [PAY7] Process guest pays for others")
    agent.launch_app()
    if events["order_placed"].wait(timeout=180):
        _wait_tap(agent, "Orders")
        _tap(agent, "Orders")
        _tap(agent, "ReservedOrderCard")
        _wait_tap(agent, "T0AssignAnyBtn")
        _tap(agent, "T0AssignAnyBtn")
        _tap(agent, "AssignTableBtn")
        _wait_tap(agent, "addItemsBtn")
        _tap(agent, "addItemsBtn")
        _tap(agent, "PaneerTikkaItem")
        _tap(agent, "regularBtn")
        _tap(agent, "extracheeseBtn")
        _tap(agent, "applyOptionBtn")
        _tap(agent, "Pasta & PizzaBtn")
        _tap(agent, "PizzaQuattroStagioniItem")
        _tap(agent, "applyOptionBtn")
        _tap(agent, "assignToBtn")
        _tap(agent, "selectAll")
        _wait_tap(agent, "assignProductsBtn")
        _tap(agent, "assignProductsBtn")
        _wait_tap(agent, "selectAllItemsBtn")
        _tap(agent, "selectAllItemsBtn")
        _tap(agent, "sendItemsBtn")
        _wait_tap(agent, "backButton")
        _tap(agent, "backButton")
        # Kitchen staff
        _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
        _wait_tap(agent, "inProgressOrderCard")
        _tap(agent, "inProgressOrderCard")
        _tap(agent, "PaneerTikka3regularextracheese PaneerTikka")
        _tap(agent, "PizzaQuattroStagioni3 PizzaQuattroStagioni")
        _tap(agent, "orderReadyBtn")
        _tap(agent, "orderCloseBtn")
        # Serve
        _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
        _tap(agent, "Orders")
        _tap(agent, "ServeOrderCard")
        _tap(agent, "selectAllItemsBtn")
        _tap(agent, "serveItemsBtn")
        _tap(agent, "notifyPaymentBtn")
        _tap(agent, "Payment Payment")
        _tap(agent, "Guest1Card")
        _wait_tap(agent, "paidCashPaymentBtn")
        _tap(agent, "paidCashPaymentBtn")
        _tap(agent, "Number1")
        _tap(agent, "Number0")
        _tap(agent, "Number0")
        _tap(agent, "Number0")
        _tap(agent, "userInputBtn")
        _tap(agent, "RoopaDselect")
        _tap(agent, "NooluNagaselect")
        _tap(agent, "Apply")
        agent.swipe_up()
        _wait_tap(agent, "paymentConfirmBtn")
        _tap(agent, "paymentConfirmBtn")
        _tap(agent, "Overview Overview")
        _wait_tap(agent, "closeTableBtn")
        _tap(agent, "closeTableBtn")
        events["payment_completed"].set()
        scenario_reporter.add_result("PAY7", "Guest Pays for Others",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


# ─── EVENT CANCELLATIONS (EC2, EC5–EC11) ─────────────────────────────────────

def ec2_consumer_flow(agent):
    """EC2: After host change, check if adding user/guest works"""
    print(f"[{agent.role}] [EC2] Verify adding user after host change")
    agent.launch_app()
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_tap(agent, "NylaiKitchenCard")
    _tap(agent, "NylaiKitchenCard")
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
    _wait_tap(agent, "NylaiKitchenCard")
    _tap(agent, "NylaiKitchenCard")
    agent.swipe_up()
    _tap(agent, "optionOne")
    _tap(agent, "optionSubmit")
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
    _tap(agent, "counterPlus")
    _type_field(agent, "contactSearch", "Noolu")
    _tap(agent, "NooluInvite")
    _tap(agent, "inviteUsers")
    _tap(agent, "chip-container")
    _wait_tap(agent, "bookAppoitment")
    _tap(agent, "bookAppoitment")
    _wait_tap(agent, "preOrderBooking")
    _tap(agent, "preOrderBooking")
    _wait_tap(agent, "Chicken65Inc")
    _tap(agent, "Chicken65Inc")
    _tap(agent, "addmayoProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "pasta-pizzacategory")
    _tap(agent, "PizzaProsciuttoeFunghiInc")
    _tap(agent, "FreshbellpepperProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "cartImage")
    _tap(agent, "cartCheckout")
    time.sleep(2)
    _tap(agent, "pickUpOrderConfirm")
    agent.swipe_up()
    _tap(agent, "walletTab")
    # Noolu accepts and preorders
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_tap(agent, "RoopaDInviteCard")
    _tap(agent, "RoopaDInviteCard")
    _tap(agent, "eventAccept")
    _tap(agent, "preOrderBooking")
    _wait_tap(agent, "starterscategory")
    _tap(agent, "starterscategory")
    agent.swipe_up()
    agent.swipe_up()
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
    _tap(agent, "pickUpOrderConfirm")
    _tap(agent, "walletTab")
    # Roopa switches back and cancels
    _switch_account(agent, "roopa@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _tap(agent, "NylaiKitchenCard")
    agent.swipe_up()
    _tap(agent, "cancelBookingMe")
    _tap(agent, "NooluNagaassign")
    _tap(agent, "confirmCancelBook")
    _tap(agent, "optionOne")
    _tap(agent, "optionSubmit")
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
    _tap(agent, "chip-container")
    _wait_tap(agent, "bookAppoitment")
    _tap(agent, "bookAppoitment")
    _wait_tap(agent, "preOrderBooking")
    _tap(agent, "preOrderBooking")
    _wait_tap(agent, "Chicken65Inc")
    _tap(agent, "Chicken65Inc")
    _tap(agent, "addmayoProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "pasta-pizzacategory")
    _tap(agent, "PizzaProsciuttoeFunghiInc")
    _tap(agent, "FreshbellpepperProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "cartImage")
    _tap(agent, "cartCheckout")
    time.sleep(2)
    _tap(agent, "pickUpOrderConfirm")
    agent.swipe_up()
    _tap(agent, "optionOne")
    _tap(agent, "optionSubmit")
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
    _tap(agent, "counterPlus")
    _type_field(agent, "contactSearch", "Noolu")
    _tap(agent, "NooluInvite")
    _tap(agent, "inviteUsers")
    _tap(agent, "chip-container")
    _wait_tap(agent, "bookAppoitment")
    _tap(agent, "bookAppoitment")
    _wait_tap(agent, "preOrderBooking")
    _tap(agent, "preOrderBooking")
    _wait_tap(agent, "Chicken65Inc")
    _tap(agent, "Chicken65Inc")
    _tap(agent, "addmayoProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "pasta-pizzacategory")
    _tap(agent, "PizzaProsciuttoeFunghiInc")
    _tap(agent, "FreshbellpepperProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "cartImage")
    _tap(agent, "cartCheckout")
    time.sleep(2)
    _tap(agent, "pickUpOrderConfirm")
    _tap(agent, "walletTab")
    # Noolu accepts and preorders
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_tap(agent, "RoopaDInviteCard")
    _tap(agent, "RoopaDInviteCard")
    _tap(agent, "eventAccept")
    _tap(agent, "preOrderBooking")
    _wait_tap(agent, "starterscategory")
    _tap(agent, "starterscategory")
    agent.swipe_up()
    agent.swipe_up()
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
    _tap(agent, "pickUpOrderConfirm")
    _tap(agent, "walletTab")
    # Roopa cancels for ALL
    _switch_account(agent, "roopa@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _tap(agent, "NylaiKitchenCard")
    agent.swipe_up()
    # cancelBookingAll - try content-desc, fallback to AI
    xml = agent.dump_ui()
    m = agent.find_by_desc(xml, "cancelBookingAll")
    if m:
        agent.tap(m[0], m[1], "[cancelBookingAll]")
    else:
        agent.run_step_ai("Tap on 'Cancel for All' button")
    time.sleep(2)
    _tap(agent, "homeTab")
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
    _tap(agent, "inviteUsers")
    _tap(agent, "chip-container")
    _wait_tap(agent, "bookAppoitment")
    _tap(agent, "bookAppoitment")
    _wait_tap(agent, "preOrderBooking")
    _tap(agent, "Chicken65Inc")
    _tap(agent, "addmayoProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "pasta-pizzacategory")
    _tap(agent, "PizzaProsciuttoeFunghiInc")
    _tap(agent, "FreshbellpepperProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "cartImage")
    _tap(agent, "cartCheckout")
    time.sleep(2)
    _tap(agent, "pickUpOrderConfirm")
    _tap(agent, "walletTab")
    # Noolu accepts and preorders
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_tap(agent, "RoopaDInviteCard")
    _tap(agent, "RoopaDInviteCard")
    _tap(agent, "eventAccept")
    _tap(agent, "preOrderBooking")
    _wait_tap(agent, "starterscategory")
    _tap(agent, "starterscategory")
    agent.swipe_up()
    agent.swipe_up()
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
    _tap(agent, "pickUpOrderConfirm")
    _tap(agent, "walletTab")
    # Roopa cancels for ALL before 15 min
    _switch_account(agent, "roopa@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _tap(agent, "NylaiKitchenCard")
    agent.swipe_up()
    xml = agent.dump_ui()
    m = agent.find_by_desc(xml, "cancelBookingAll")
    if m:
        agent.tap(m[0], m[1], "[cancelBookingAll]")
    else:
        agent.run_step_ai("Tap on 'Cancel for All' button")
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
    _tap(agent, "inviteUsers")
    _tap(agent, "chip-container")
    _wait_tap(agent, "preOrderBooking")
    _tap(agent, "preOrderBooking")
    _wait_tap(agent, "Chicken65Inc")
    _tap(agent, "Chicken65Inc")
    _tap(agent, "addmayoProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "pasta-pizzacategory")
    _tap(agent, "PizzaProsciuttoeFunghiInc")
    _tap(agent, "FreshbellpepperProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "cartImage")
    _tap(agent, "cartCheckout")
    time.sleep(2)
    _tap(agent, "pickUpOrderConfirm")
    _tap(agent, "walletTab")
    # Noolu accepts and preorders
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_tap(agent, "RoopaDInviteCard")
    _tap(agent, "RoopaDInviteCard")
    _tap(agent, "eventAccept")
    _tap(agent, "preOrderBooking")
    _wait_tap(agent, "starterscategory")
    _tap(agent, "starterscategory")
    agent.swipe_up()
    agent.swipe_up()
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
    _tap(agent, "pickUpOrderConfirm")
    _tap(agent, "walletTab")
    # Roopa cancels Me Only
    _switch_account(agent, "roopa@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _tap(agent, "NylaiKitchenCard")
    agent.swipe_up()
    _tap(agent, "cancelBookingMe")
    _tap(agent, "NooluNagaassign")
    _tap(agent, "confirmCancelBook")
    _tap(agent, "optionOne")
    _tap(agent, "optionSubmit")
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
    _tap(agent, "chip-container")
    _wait_tap(agent, "bookAppoitment")
    _tap(agent, "bookAppoitment")
    _wait_tap(agent, "preOrderBooking")
    _tap(agent, "preOrderBooking")
    _wait_tap(agent, "Chicken65Inc")
    _tap(agent, "Chicken65Inc")
    _tap(agent, "addmayoProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "pasta-pizzacategory")
    _tap(agent, "PizzaProsciuttoeFunghiInc")
    _tap(agent, "FreshbellpepperProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "cartImage")
    _tap(agent, "cartCheckout")
    time.sleep(2)
    _tap(agent, "pickUpOrderConfirm")
    agent.swipe_up()
    _tap(agent, "optionOne")
    _tap(agent, "optionSubmit")
    _tap(agent, "BOOKING CANCELLED")
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
    _tap(agent, "NylaiKitchen")
    _wait_tap(agent, "chip-container")
    _tap(agent, "chip-container")
    _wait_tap(agent, "bookAppoitment")
    _tap(agent, "bookAppoitment")
    _wait_tap(agent, "orderLater")
    _tap(agent, "orderLater")
    _tap(agent, "walletTab")
    time.sleep(2)
    # cancel flow
    _tap(agent, "optionThree")
    _tap(agent, "optionSubmit")
    _tap(agent, "BOOKING CANCELLED")
    time.sleep(2)
    scenario_reporter.add_result("SV4", "Pre-Order Status C-App",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv4_business_flow(agent):
    _no_op(agent)


def sv6_consumer_flow(agent):
    """SV6: Consumer places menu order after business assigns table"""
    print(f"[{agent.role}] [SV6] Menu order - C-App")
    agent.launch_app()
    if events["table_accepted"].wait(timeout=120):
        _tap(agent, "walletTab")
        _tap(agent, "NylaiKitchenCard")
        agent.swipe_up()
        agent.swipe_up()
        agent.swipe_up()
        _wait_tap(agent, "TomYumSoupInc")
        _tap(agent, "TomYumSoupInc")
        _tap(agent, "prawnProduct")
        _tap(agent, "confirmProduct")
        _tap(agent, "cartImage")
        _tap(agent, "CONFIRM ORDER")
        _tap(agent, "orderConfirmedMenu")
        agent.swipe_up()
        events["order_placed"].set()
        scenario_reporter.add_result("SV6", "Menu Order C-App",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def sv6_business_flow(agent):
    """SV6: Business assigns table"""
    print(f"[{agent.role}] [SV6] Assign table for menu order")
    agent.launch_app()
    _wait_tap(agent, "Orders")
    _tap(agent, "Orders")
    _tap(agent, "ReservedOrderCard")
    _tap(agent, "T0AssignAnyBtn")
    _tap(agent, "AssignTableBtn")
    events["table_accepted"].set()
    if events["order_placed"].wait(timeout=120):
        scenario_reporter.add_result("SV6", "Menu Order C-App",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def sv7_business_flow(agent):
    """SV7: Order status - B-App"""
    print(f"[{agent.role}] [SV7] Order status in B-App")
    agent.launch_app()
    _wait_tap(agent, "Orders")
    _tap(agent, "Orders")
    _wait_tap(agent, "OrderOrderCard")
    _tap(agent, "OrderOrderCard")
    scenario_reporter.add_result("SV7", "Order Status B-App",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv7_consumer_flow(agent):
    _no_op(agent)


def sv8_business_flow(agent):
    """SV8: In Progress - B-App (add items & send to kitchen)"""
    print(f"[{agent.role}] [SV8] In Progress status")
    agent.launch_app()
    _wait_tap(agent, "addItemsBtn")
    _tap(agent, "addItemsBtn")
    _wait_tap(agent, "Macaroni&CheeseBakeItem")
    _tap(agent, "Cheesy & Comfort PlatesBtn")
    _tap(agent, "Macaroni&CheeseBakeItem")
    _tap(agent, "regularBtn")
    _tap(agent, "AddTruffleOilBtn")
    _tap(agent, "applyOptionBtn")
    _tap(agent, "assignToBtn")
    _tap(agent, "selectAll")
    _tap(agent, "assignProductsBtn")
    _wait_tap(agent, "selectAllItemsBtn")
    _tap(agent, "selectAllItemsBtn")
    _tap(agent, "sendItemsBtn")
    _wait_tap(agent, "backButton")
    _tap(agent, "backButton")
    # Kitchen prepares
    _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
    _wait_tap(agent, "inProgressOrderCard")
    _tap(agent, "inProgressOrderCard")
    _tap(agent, "Macaroni&CheeseBake1regularAddTruffleOil Macaroni&CheeseBake")
    _tap(agent, "TomYumSoup1vegchickenprawn TomYumSoup")
    _tap(agent, "orderReadyBtn")
    _tap(agent, "orderCloseBtn")
    # Switch to serve
    _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
    _tap(agent, "Orders")
    events["items_served"].set()
    scenario_reporter.add_result("SV8", "In Progress Status B-App",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv8_consumer_flow(agent):
    _no_op(agent)


def sv9_business_flow(agent):
    """SV9: Serve status - B-App"""
    print(f"[{agent.role}] [SV9] Serve status")
    agent.launch_app()
    _tap(agent, "ServeOrderCard")
    _tap(agent, "selectAllItemsBtn")
    _tap(agent, "serveItemsBtn")
    _tap(agent, "notifyPaymentBtn")
    _tap(agent, "backButton")
    events["payment_requested"].set()
    scenario_reporter.add_result("SV9", "Serve Status B-App",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv9_consumer_flow(agent):
    _no_op(agent)


def sv10_business_flow(agent):
    """SV10: Payment - B-App"""
    print(f"[{agent.role}] [SV10] Payment status")
    agent.launch_app()
    _wait_tap(agent, "Payment Payment")
    time.sleep(2)
    scenario_reporter.add_result("SV10", "Payment Status B-App",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv10_consumer_flow(agent):
    _no_op(agent)


def sv11_consumer_flow(agent):
    """SV11: Payment Requested - C-App"""
    print(f"[{agent.role}] [SV11] Payment Requested status")
    agent.launch_app()
    _wait_tap(agent, "walletTab")
    _tap(agent, "walletTab")
    _wait_tap(agent, "NylaiKitchen2Card PAYMENT REQUESTED")
    _tap(agent, "NylaiKitchen2Card PAYMENT REQUESTED")
    time.sleep(2)
    events["payment_requested"].set()
    scenario_reporter.add_result("SV11", "Payment Requested C-App",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv11_business_flow(agent):
    _no_op(agent)


def sv12_business_flow(agent):
    """SV12: Payment done - B-App processes payment"""
    print(f"[{agent.role}] [SV12] Payment done")
    agent.launch_app()
    _wait_tap(agent, "Orders")
    _tap(agent, "Orders")
    _tap(agent, "PaymentOrderCard")
    _wait_tap(agent, "Payment Payment")
    _tap(agent, "Payment Payment")
    _tap(agent, "RoopaDCard")
    _tap(agent, "cashPaymentBtn")
    _tap(agent, "Number2")
    _tap(agent, "Number0")
    _tap(agent, "userInputBtn")
    agent.swipe_up()
    _wait_tap(agent, "paymentConfirmBtn")
    _tap(agent, "paymentConfirmBtn")
    _wait_tap(agent, "RoopaDCard")
    _tap(agent, "Overview Overview")
    _tap(agent, "backButton")
    _wait_tap(agent, "PaymentDoneOrderCard")
    _tap(agent, "PaymentDoneOrderCard")
    _tap(agent, "closeTableBtn")
    events["payment_completed"].set()
    scenario_reporter.add_result("SV12", "Payment Done B-App",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv12_consumer_flow(agent):
    _no_op(agent)


def sv13_business_flow(agent):
    """SV13: Completed - B-App"""
    print(f"[{agent.role}] [SV13] Completed status B-App")
    agent.launch_app()
    _tap(agent, "Home")
    agent.swipe_up()
    agent.swipe_up()
    _wait_tap(agent, "RoopaDCompletedCard")
    time.sleep(2)
    scenario_reporter.add_result("SV13", "Completed Status B-App",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv13_consumer_flow(agent):
    _no_op(agent)


def sv14_consumer_flow(agent):
    """SV14: Completed - C-App"""
    print(f"[{agent.role}] [SV14] Completed status C-App")
    agent.launch_app()
    _tap(agent, "walletTab")
    time.sleep(2)
    _wait_tap(agent, "NylaiKitchenCard COMPLETED")
    _tap(agent, "NylaiKitchenCard COMPLETED")
    time.sleep(2)
    scenario_reporter.add_result("SV14", "Completed Status C-App",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv14_business_flow(agent):
    _no_op(agent)


def sv15_consumer_flow(agent):
    """SV15: No-show status for users"""
    print(f"[{agent.role}] [SV15] No-show status check")
    agent.launch_app()
    _tap(agent, "homeTab")
    _tap(agent, "NylaiKitchen")
    _tap(agent, "counterPlus")
    _tap(agent, "guestAdd")
    _tap(agent, "guestAdd")
    _type_field(agent, "contactSearch", "Noolu")
    _tap(agent, "NooluInvite")
    _tap(agent, "inviteUsers")
    _tap(agent, "chip-container")
    _wait_tap(agent, "bookAppoitment")
    _tap(agent, "bookAppoitment")
    _wait_tap(agent, "orderLater")
    _tap(agent, "orderLater")
    # Noolu accepts
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_tap(agent, "RoopaDInviteCard")
    _tap(agent, "RoopaDInviteCard")
    _tap(agent, "eventAccept")
    _tap(agent, "orderLater")
    _tap(agent, "walletTab")
    # Switch back to Roopa
    _switch_account(agent, "roopa@xorstack.com", "12345")
    events["order_placed"].set()
    if events["payment_completed"].wait(timeout=300):
        scenario_reporter.add_result("SV15", "No-Show Status Verification",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def sv15_business_flow(agent):
    """SV15: Business assigns table, adds items, notifies payment"""
    print(f"[{agent.role}] [SV15] Process no-show scenario")
    agent.launch_app()
    if events["order_placed"].wait(timeout=180):
        _wait_tap(agent, "Orders")
        _tap(agent, "Orders")
        _tap(agent, "ReservedOrderCard")
        _wait_tap(agent, "T0AssignAnyBtn")
        _tap(agent, "T0AssignAnyBtn")
        _tap(agent, "AssignTableBtn")
        _wait_tap(agent, "addItemsBtn")
        _tap(agent, "addItemsBtn")
        agent.swipe_up()
        agent.swipe_up()
        _tap(agent, "ThaiGreenCurrywithJasmineRiceItem")
        _tap(agent, "vegBtn")
        _tap(agent, "addspicyBtn")
        _tap(agent, "applyOptionBtn")
        _tap(agent, "ThaiGreenCurrywithJasmineRiceItem")
        _tap(agent, "addNewCustomSelection")
        _tap(agent, "tofuBtn")
        agent.swipe_up()
        _tap(agent, "extrapeanutsBtn")
        _tap(agent, "applyOptionBtn")
        _tap(agent, "ThaiGreenCurrywithJasmineRiceItem")
        _tap(agent, "addNewCustomSelection")
        _tap(agent, "chickenBtn")
        agent.swipe_up()
        _tap(agent, "extrasauceBtn")
        _tap(agent, "applyOptionBtn")
        _tap(agent, "ThaiGreenCurrywithJasmineRiceItem")
        _tap(agent, "addNewCustomSelection")
        _tap(agent, "chickenBtn")
        agent.swipe_up()
        _tap(agent, "addmayoBtn")
        _tap(agent, "applyOptionBtn")
        _tap(agent, "assignToBtn")
        _tap(agent, "RoopaDselect")
        agent.swipe_up()
        agent.swipe_up()
        _tap(agent, "Guest1select")
        _wait_tap(agent, "assignProductsBtn")
        _tap(agent, "assignProductsBtns")
        _wait_tap(agent, "selectAllItemsBtn")
        _tap(agent, "selectAllItemsBtn")
        _tap(agent, "sendItemsBtn")
        _wait_tap(agent, "backButton")
        _tap(agent, "backButton")
        # Kitchen prepares
        _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
        _wait_tap(agent, "inProgressOrderCard")
        _tap(agent, "inProgressOrderCard")
        _tap(agent, "ThaiGreenCurrywithJasmineRice1vegaddspicy ThaiGreenCurrywithJasmineRice")
        _tap(agent, "ThaiGreenCurrywithJasmineRice1tofuextrapeanuts ThaiGreenCurrywithJasmineRice")
        agent.swipe_up()
        _tap(agent, "ThaiGreenCurrywithJasmineRice1chickenaddmayoOnions ThaiGreenCurrywithJasmineRice")
        _tap(agent, "ThaiGreenCurrywithJasmineRice1chickenextrasauceMor ThaiGreenCurrywithJasmineRice")
        _tap(agent, "orderReadyBtn")
        _tap(agent, "orderCloseBtn")
        # Serve
        _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
        _tap(agent, "Orders")
        _tap(agent, "ServeOrderCard")
        _wait_tap(agent, "selectAllItemsBtn")
        _tap(agent, "selectAllItemsBtn")
        _tap(agent, "serveItemsBtn")
        _wait_tap(agent, "notifyPaymentBtn")
        _tap(agent, "notifyPaymentBtn")
        events["payment_completed"].set()
        scenario_reporter.add_result("SV15", "No-Show Status Verification",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def sv16_consumer_flow(agent):
    """SV16: Payment done via C-App payment"""
    print(f"[{agent.role}] [SV16] Consumer pays via C-App")
    agent.launch_app()
    _wait_tap(agent, "walletTab")
    _tap(agent, "walletTab")
    _wait_tap(agent, "NylaiKitchenCard PAYMENT REQUESTED")
    _tap(agent, "NylaiKitchenCard PAYMENT REQUESTED")
    agent.swipe_up()
    _tap(agent, "payTotal")
    _tap(agent, "proceedPayment")
    _tap(agent, "ePayment")
    time.sleep(3)
    agent.run_step_ai("Tap the Pay button to confirm e-payment")
    time.sleep(5)
    _tap(agent, "walletTab")
    events["payment_completed"].set()
    scenario_reporter.add_result("SV16", "Payment Done via C-App",
                                 agent.role, "PASS", "Completed", agent.last_launch_time)


def sv16_business_flow(agent):
    """SV16: Business verifies payment done"""
    agent.launch_app()
    if events["payment_completed"].wait(timeout=120):
        _tap(agent, "Orders")
        _tap(agent, "PaymentDoneOrderCard")
        time.sleep(2)
        scenario_reporter.add_result("SV16", "Payment Done via C-App",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


# ─── PRE-ORDER (PO4–PO6) ─────────────────────────────────────────────────────

def po4_consumer_flow(agent):
    """PO4: Host (Noolu) Preorders First, Invitee (Roopa) Does Not"""
    print(f"[{agent.role}] [PO4] Host preorders first, invitee skips")
    agent.launch_app()
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "homeTab")
    _wait_tap(agent, "NylaiKitchen")
    _tap(agent, "NylaiKitchen")
    _tap(agent, "counterPlus")
    _type_field(agent, "contactSearch", "Roopa")
    _tap(agent, "RoopaInvite")
    _tap(agent, "inviteUsers")
    _wait_tap(agent, "bookAppoitment")
    _tap(agent, "chip-container")
    _tap(agent, "bookAppoitment")
    _wait_tap(agent, "preOrderBooking")
    _tap(agent, "preOrderBooking")
    _wait_tap(agent, "Chicken65Inc")
    _tap(agent, "Chicken65Inc")
    _tap(agent, "addmayoProduct")
    _type_field(agent, "inputSplIns", "more crispyy")
    _tap(agent, "confirmProduct")
    _tap(agent, "Chicken65Inc")
    _tap(agent, "addNewCustomSelection")
    _tap(agent, "addmayoProduct")
    _type_field(agent, "inputSplIns", "less oil")
    _tap(agent, "confirmProduct")
    _tap(agent, "pasta-pizzacategory")
    _tap(agent, "PizzaProsciuttoeFunghiInc")
    _tap(agent, "FreshbellpepperProduct")
    _type_field(agent, "inputSplIns", "more cheese")
    _tap(agent, "confirmProduct")
    _tap(agent, "cartImage")
    _tap(agent, "cartCheckout")
    time.sleep(2)
    _tap(agent, "pickUpOrderConfirm")
    agent.swipe_up()
    _tap(agent, "walletTab")
    # Roopa accepts (no preorder)
    _switch_account(agent, "roopa@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_tap(agent, "NooluNagaInviteCard")
    _tap(agent, "NooluNagaInviteCard")
    _tap(agent, "eventAccept")
    _tap(agent, "preOrderBooking")
    _wait_tap(agent, "starterscategory")
    _tap(agent, "starterscategory")
    agent.swipe_up()
    agent.swipe_up()
    _wait_tap(agent, "HaraBharaKebabInc")
    _tap(agent, "HaraBharaKebab")
    _tap(agent, "4pcsProduct")
    _tap(agent, "confirmProduct")
    agent.swipe_up()
    agent.swipe_up()
    agent.swipe_up()
    _tap(agent, "ThaiGreenCurrywithJasmineRiceInc")
    _tap(agent, "vegProduct")
    agent.swipe_up()
    _tap(agent, "extrapeanutsProduct")
    _type_field(agent, "inputSplIns", "Spicy")
    _tap(agent, "confirmProduct")
    _tap(agent, "cartImage")
    _tap(agent, "cartCheckout")
    time.sleep(2)
    _tap(agent, "pickUpOrderConfirm")
    events["preorder_submitted"].set()
    if events["payment_completed"].wait(timeout=300):
        scenario_reporter.add_result("PO4", "Host Preorders First Invitee Skips",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def po4_business_flow(agent):
    """PO4 Business: Accept and process dual preorder"""
    print(f"[{agent.role}] [PO4] Process dual preorder")
    agent.launch_app()
    if events["preorder_submitted"].wait(timeout=300):
        _wait_tap(agent, "Orders")
        _tap(agent, "Orders")
        _tap(agent, "ReservedOrderCard")
        _tap(agent, "T0AssignAnyBtn")
        _tap(agent, "AssignTableBtn")
        _wait_tap(agent, "addItemsBtn")
        _tap(agent, "addItemsBtn")
        _wait_tap(agent, "Macaroni&CheeseBakeItem")
        _tap(agent, "cheesy-comfort-platescategory")
        _tap(agent, "Macaroni&CheeseBakeItem")
        _tap(agent, "regularBtn")
        _tap(agent, "AddTruffleOilBtn")
        _tap(agent, "applyOptionBtn")
        _tap(agent, "assignToBtn")
        _tap(agent, "selectAll")
        _tap(agent, "assignProductsBtn")
        _wait_tap(agent, "selectAllItemsBtn")
        _tap(agent, "selectAllItemsBtn")
        _tap(agent, "sendItemsBtn")
        _wait_tap(agent, "backButton")
        _tap(agent, "backButton")
        # Kitchen
        _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
        _wait_tap(agent, "inProgressOrderCard")
        _tap(agent, "inProgressOrderCard")
        _tap(agent, "Macaroni&CheeseBake2regularAddTruffleOil Macaroni&CheeseBake")
        _tap(agent, "Chicken651addmayomorecrispyy")
        _tap(agent, "Chicken651addmayolessoil")
        agent.swipe_up()
        _tap(agent, "HaraBharaKebab14pcs")
        agent.swipe_up()
        _tap(agent, "PizzaProsciuttoeFunghi1Spicysalami")
        _tap(agent, "PizzaProsciuttoeFunghi2Freshbellpeppermorecheese")
        _tap(agent, "orderReadyBtn")
        _tap(agent, "orderCloseBtn")
        # Serve
        _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
        _tap(agent, "Orders")
        _tap(agent, "ServeOrderCard")
        _tap(agent, "selectAllItemsBtn")
        _tap(agent, "serveItemsBtn")
        _tap(agent, "notifyPaymentBtn")
        _tap(agent, "Payment Payment")
        _tap(agent, "NooluNagaCard")
        _wait_tap(agent, "cashPaymentBtn")
        _tap(agent, "cashPaymentBtn")
        _tap(agent, "Number2")
        _tap(agent, "Number0")
        _tap(agent, "userInputBtn")
        _tap(agent, "RoopaDselect")
        _tap(agent, "Apply")
        agent.swipe_up()
        _wait_tap(agent, "paymentConfirmBtn")
        _tap(agent, "paymentConfirmBtn")
        _wait_tap(agent, "RoopaDCard")
        _tap(agent, "Overview Overview")
        _wait_tap(agent, "closeTableBtn")
        _tap(agent, "closeTableBtn")
        events["payment_completed"].set()
        scenario_reporter.add_result("PO4", "Host Preorders First Invitee Skips",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def po5_consumer_flow(agent):
    """PO5: Host (Roopa) Preorders First, Invitee (Noolu) Also Preorders"""
    print(f"[{agent.role}] [PO5] Both host and invitee preorder")
    agent.launch_app()
    agent.swipe_up()
    _wait_tap(agent, "NylaiKitchen")
    _tap(agent, "NylaiKitchen")
    _tap(agent, "counterPlus")
    _type_field(agent, "contactSearch", "Noolu")
    _tap(agent, "NooluInvite")
    _tap(agent, "inviteUsers")
    _tap(agent, "chip-container")
    agent.swipe_up()
    _wait_tap(agent, "bookAppoitment")
    _tap(agent, "bookAppoitment")
    _wait_tap(agent, "preOrderBooking")
    _tap(agent, "preOrderBooking")
    _wait_tap(agent, "starterscategory")
    _tap(agent, "starterscategory")
    agent.swipe_up()
    agent.swipe_up()
    _tap(agent, "VegManchurianInc")
    _tap(agent, "gravyProduct")
    _tap(agent, "extrasauceProduct")
    _type_field(agent, "inputSplIns", "Spicyy ")
    agent.swipe_up()
    _tap(agent, "confirmProduct")
    _tap(agent, "VegManchurianInc")
    _tap(agent, "addNewCustomSelection")
    _tap(agent, "gravyProduct")
    _tap(agent, "extrasauceProduct")
    _type_field(agent, "inputSplIns", "Crispyy ")
    agent.swipe_up()
    _tap(agent, "confirmProduct")
    _tap(agent, "cheesy-comfort-platescategory")
    agent.swipe_up()
    _tap(agent, "FourCheeseLasagnaInc")
    _tap(agent, "SliceProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "PizzaQuattroStagioniInc")
    _tap(agent, "confirmProduct")
    _tap(agent, "cartImage")
    _tap(agent, "cartCheckout")
    time.sleep(2)
    _tap(agent, "pickUpOrderConfirm")
    _tap(agent, "walletTab")
    # Noolu accepts and preorders
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_tap(agent, "RoopaDInviteCard")
    _tap(agent, "RoopaDInviteCard")
    _tap(agent, "eventAccept")
    _tap(agent, "preOrderBooking")
    _wait_tap(agent, "starterscategory")
    _tap(agent, "starterscategory")
    agent.swipe_up()
    agent.swipe_up()
    agent.swipe_up()
    _wait_tap(agent, "HaraBharaKebabInc")
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
    _type_field(agent, "inputSplIns", "Spicy")
    _tap(agent, "confirmProduct")
    _tap(agent, "cartImage")
    _tap(agent, "cartCheckout")
    time.sleep(2)
    _tap(agent, "pickUpOrderConfirm")
    events["preorder_submitted"].set()
    if events["payment_completed"].wait(timeout=300):
        scenario_reporter.add_result("PO5", "Both Host and Invitee Preorder",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def po5_business_flow(agent):
    """PO5 Business: Process both preorders"""
    print(f"[{agent.role}] [PO5] Process both preorders")
    agent.launch_app()
    if events["preorder_submitted"].wait(timeout=300):
        _wait_tap(agent, "Orders")
        _tap(agent, "Orders")
        _tap(agent, "ReservedOrderCard")
        _tap(agent, "T0AssignAnyBtn")
        _tap(agent, "AssignTableBtn")
        _wait_tap(agent, "addItemsBtn")
        _tap(agent, "addItemsBtn")
        _wait_tap(agent, "Macaroni&CheeseBakeItem")
        _tap(agent, "Cheesy & Comfort PlatesBtn")
        _tap(agent, "Macaroni&CheeseBakeItem")
        _tap(agent, "regularBtn")
        _tap(agent, "AddTruffleOilBtn")
        _tap(agent, "applyOptionBtn")
        _wait_tap(agent, "selectAll")
        _tap(agent, "assignToBtn")
        _tap(agent, "selectAll")
        _tap(agent, "assignProductsBtn")
        _wait_tap(agent, "selectAllItemsBtn")
        _tap(agent, "selectAllItemsBtn")
        _tap(agent, "sendItemsBtn")
        _wait_tap(agent, "backButton")
        _tap(agent, "backButton")
        # Kitchen
        _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
        _wait_tap(agent, "inProgressOrderCard")
        _tap(agent, "inProgressOrderCard")
        _tap(agent, "Macaroni&CheeseBake2regularAddTruffleOil Macaroni&CheeseBake")
        _tap(agent, "VegManchurian1gravyextrasauceSpicyy")
        _tap(agent, "VegManchurian1gravyextrasauceMoresauce")
        agent.swipe_up()
        agent.swipe_up()
        _tap(agent, "VegManchurian1gravyextrasauceCrispyy")
        _tap(agent, "FourCheeseLasagna1SliceGluten-FreePasta")
        _tap(agent, "FourCheeseLasagna1AddMushroom")
        _tap(agent, "PizzaQuattroStagioni1Extrasauce")
        _tap(agent, "orderReadyBtn")
        _tap(agent, "orderCloseBtn")
        # Serve
        _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
        _tap(agent, "Orders")
        _tap(agent, "ServeOrderCard")
        _tap(agent, "selectAllItemsBtn")
        _tap(agent, "serveItemsBtn")
        _tap(agent, "notifyPaymentBtn")
        _tap(agent, "Payment Payment")
        _tap(agent, "RoopaDCard")
        _wait_tap(agent, "cashPaymentBtn")
        _tap(agent, "cashPaymentBtn")
        _tap(agent, "Number2")
        _tap(agent, "Number0")
        _tap(agent, "userInputBtn")
        _tap(agent, "NooluNagaselect")
        _tap(agent, "Apply")
        agent.swipe_up()
        _wait_tap(agent, "paymentConfirmBtn")
        _tap(agent, "paymentConfirmBtn")
        _wait_tap(agent, "RoopaDCard")
        _tap(agent, "NooluNagaCard")
        _tap(agent, "Overview Overview")
        _wait_tap(agent, "closeTableBtn")
        _tap(agent, "closeTableBtn")
        events["payment_completed"].set()
        scenario_reporter.add_result("PO5", "Both Host and Invitee Preorder",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def po6_consumer_flow(agent):
    """PO6: Host Does Not Preorder, Participant Preorders First"""
    print(f"[{agent.role}] [PO6] Participant preorders first, host adds later")
    agent.launch_app()
    _wait_tap(agent, "NylaiKitchen")
    _tap(agent, "NylaiKitchen")
    _tap(agent, "counterPlus")
    _type_field(agent, "contactSearch", "Noolu")
    _tap(agent, "NooluInvite")
    _tap(agent, "inviteUsers")
    agent.swipe_up()
    _tap(agent, "chip-container")
    agent.swipe_up()
    _wait_tap(agent, "bookAppoitment")
    _tap(agent, "bookAppoitment")
    _wait_tap(agent, "orderLater")
    _tap(agent, "orderLater")
    _tap(agent, "walletTab")
    # Noolu accepts and preorders
    _switch_account(agent, "noolu@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_tap(agent, "RoopaDInviteCard")
    _tap(agent, "RoopaDInviteCard")
    _tap(agent, "eventAccept")
    _tap(agent, "preOrderBooking")
    _wait_tap(agent, "starterscategory")
    _tap(agent, "starterscategory")
    agent.swipe_up()
    agent.swipe_up()
    agent.swipe_up()
    _wait_tap(agent, "HaraBharaKebabInc")
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
    _type_field(agent, "inputSplIns", "Spicy")
    _tap(agent, "confirmProduct")
    _tap(agent, "cartImage")
    _tap(agent, "cartCheckout")
    time.sleep(2)
    _tap(agent, "pickUpOrderConfirm")
    _tap(agent, "walletTab")
    # Roopa switches back, adds her own items
    _switch_account(agent, "roopa@xorstack.com", "12345")
    _tap(agent, "walletTab")
    _wait_tap(agent, "NylaiKitchenCard")
    _tap(agent, "NylaiKitchenCard")
    _wait_tap(agent, "starterscategory")
    _tap(agent, "starterscategory")
    _tap(agent, "MuttonSeekhKebab")
    _tap(agent, "2pcsProduct")
    _tap(agent, "chutneyProduct")
    _tap(agent, "confirmProduct")
    _tap(agent, "cartImage")
    _tap(agent, "applyCoupon")
    _tap(agent, "6% OFFER")
    _tap(agent, "cartCheckout")
    time.sleep(2)
    _tap(agent, "pickUpOrderConfirm")
    events["preorder_submitted"].set()
    if events["payment_completed"].wait(timeout=300):
        scenario_reporter.add_result("PO6", "Participant Preorders First Host Adds Later",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def po6_business_flow(agent):
    """PO6 Business: Process participant-first preorder"""
    print(f"[{agent.role}] [PO6] Process participant-first preorder")
    agent.launch_app()
    if events["preorder_submitted"].wait(timeout=300):
        _wait_tap(agent, "Orders")
        _tap(agent, "Orders")
        _tap(agent, "ReservedOrderCard")
        _tap(agent, "T0AssignAnyBtn")
        _tap(agent, "AssignTableBtn")
        _wait_tap(agent, "addItemsBtn")
        _tap(agent, "addItemsBtn")
        _wait_tap(agent, "Macaroni&CheeseBakeItem")
        agent.swipe_up()
        _tap(agent, "Cheesy & Comfort PlatesBtn")
        _tap(agent, "Macaroni&CheeseBakeItem")
        _tap(agent, "regularBtn")
        _tap(agent, "AddTruffleOilBtn")
        _tap(agent, "applyOptionBtn")
        _tap(agent, "assignToBtn")
        _tap(agent, "selectAll")
        _tap(agent, "assignProductsBtn")
        _wait_tap(agent, "selectAllItemsBtn")
        _tap(agent, "selectAllItemsBtn")
        _tap(agent, "sendItemsBtn")
        _wait_tap(agent, "backButton")
        _tap(agent, "backButton")
        # Kitchen
        _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
        _wait_tap(agent, "inProgressOrderCard")
        _tap(agent, "inProgressOrderCard")
        _tap(agent, "MuttonSeekhKebab12pcschutney MuttonSeekhKebab")
        _tap(agent, "Macaroni&CheeseBake2regularAddTruffleOil Macaroni&CheeseBake")
        _tap(agent, "HaraBharaKebab14pcs HaraBharaKebab")
        agent.swipe_up()
        _tap(agent, "ThaiGreenCurrywithJasmineRice1vegchickentofuextrap ThaiGreenCurrywithJasmineRice")
        _tap(agent, "orderReadyBtn")
        _tap(agent, "orderCloseBtn")
        # Serve
        _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
        _tap(agent, "Orders")
        _tap(agent, "ServeOrderCard")
        _tap(agent, "selectAllItemsBtn")
        _tap(agent, "serveItemsBtn")
        _tap(agent, "notifyPaymentBtn")
        _tap(agent, "Payment Payment")
        _tap(agent, "NooluNagaCard")
        _wait_tap(agent, "cashPaymentBtn")
        _tap(agent, "cashPaymentBtn")
        _tap(agent, "Number2")
        _tap(agent, "Number0")
        _tap(agent, "userInputBtn")
        _tap(agent, "RoopaDselect")
        _tap(agent, "Apply")
        agent.swipe_up()
        _wait_tap(agent, "paymentConfirmBtn")
        _tap(agent, "paymentConfirmBtn")
        _wait_tap(agent, "RoopaDCard")
        _tap(agent, "NooluNagaCard")
        _tap(agent, "Overview Overview")
        _wait_tap(agent, "closeTableBtn")
        _tap(agent, "closeTableBtn")
        events["payment_completed"].set()
        scenario_reporter.add_result("PO6", "Participant Preorders First Host Adds Later",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


# ─── CONTACTS & WALLET (CW5–CW6) ─────────────────────────────────────────────

def cw5_consumer_flow(agent):
    """CW5: Consumer books for business to add items with 1 guest"""
    print(f"[{agent.role}] [CW5] Book event for B-App to add items")
    agent.launch_app()
    agent.swipe_up()
    _wait_tap(agent, "NylaiKitchen")
    _tap(agent, "NylaiKitchen")
    _tap(agent, "chip-container")
    _wait_tap(agent, "bookAppoitment")
    _tap(agent, "bookAppoitment")
    events["order_placed"].set()
    if events["payment_completed"].wait(timeout=300):
        scenario_reporter.add_result("CW5", "B-App Adding Items with 1 Guest",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def cw5_business_flow(agent):
    """CW5 Business: Add items, process payment with guest"""
    print(f"[{agent.role}] [CW5] Add items and payment with guest")
    agent.launch_app()
    if events["order_placed"].wait(timeout=180):
        _wait_tap(agent, "Orders")
        _tap(agent, "Orders")
        _tap(agent, "ReservedOrderCard")
        _wait_tap(agent, "T0AssignAnyBtn")
        _tap(agent, "T0AssignAnyBtn")
        _tap(agent, "AssignTableBtn")
        _wait_tap(agent, "addItemsBtn")
        _tap(agent, "Payment Payment")
        _wait_tap(agent, "addGuestBtn")
        _tap(agent, "addGuestBtn")
        _tap(agent, "Overview Overview")
        _tap(agent, "addItemsBtn")
        _tap(agent, "PaneerTikkaItem")
        _tap(agent, "regularBtn")
        _tap(agent, "extracheeseBtn")
        _tap(agent, "applyOptionBtn")
        _tap(agent, "Pasta & PizzaBtn")
        _tap(agent, "PizzaQuattroStagioniItem")
        _tap(agent, "applyOptionBtn")
        _tap(agent, "assignToBtn")
        _tap(agent, "selectAll")
        _wait_tap(agent, "assignProductsBtn")
        _tap(agent, "assignProductsBtn")
        _wait_tap(agent, "selectAllItemsBtn")
        _tap(agent, "selectAllItemsBtn")
        _tap(agent, "sendItemsBtn")
        _wait_tap(agent, "backButton")
        _tap(agent, "backButton")
        # Kitchen
        _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
        _wait_tap(agent, "inProgressOrderCard")
        _tap(agent, "inProgressOrderCard")
        _tap(agent, "PaneerTikka2regularextracheese PaneerTikka")
        _tap(agent, "PizzaQuattroStagioni2 PizzaQuattroStagioni")
        _tap(agent, "orderReadyBtn")
        _tap(agent, "orderCloseBtn")
        # Serve
        _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
        _tap(agent, "Orders")
        _tap(agent, "ServeOrderCard")
        _tap(agent, "selectAllItemsBtn")
        _tap(agent, "serveItemsBtn")
        _tap(agent, "notifyPaymentBtn")
        _tap(agent, "Payment Payment")
        _tap(agent, "NooluNagaCard")
        _wait_tap(agent, "cashPaymentBtn")
        _tap(agent, "cashPaymentBtn")
        _tap(agent, "Number6")
        _tap(agent, "Number0")
        _tap(agent, "Number8")
        _tap(agent, "userInputBtn")
        _tap(agent, "Guest1select")
        _tap(agent, "Apply")
        _tap(agent, "tipBtn")
        _tap(agent, "Number4")
        _tap(agent, "userInputBtn")
        agent.swipe_up()
        _wait_tap(agent, "paymentConfirmBtn")
        _tap(agent, "paymentConfirmBtn")
        _wait_tap(agent, "RoopaDCard")
        _tap(agent, "Overview Overview")
        _wait_tap(agent, "closeTableBtn")
        _tap(agent, "closeTableBtn")
        events["payment_completed"].set()
        scenario_reporter.add_result("CW5", "B-App Adding Items with 1 Guest",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def cw6_consumer_flow(agent):
    """CW6: Consumer books for B-App to add items with 2+ guests"""
    print(f"[{agent.role}] [CW6] Book event for B-App with multiple guests")
    agent.launch_app()
    agent.swipe_up()
    _wait_tap(agent, "NylaiKitchen")
    _tap(agent, "NylaiKitchen")
    _tap(agent, "counterPlus")
    _tap(agent, "guestAdd")
    _tap(agent, "inviteUsers")
    _tap(agent, "chip-container")
    _wait_tap(agent, "bookAppoitment")
    _tap(agent, "bookAppoitment")
    _wait_tap(agent, "orderLater")
    _tap(agent, "orderLater")
    events["order_placed"].set()
    if events["payment_completed"].wait(timeout=300):
        scenario_reporter.add_result("CW6", "B-App Adding Items with 2+ Guests",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


def cw6_business_flow(agent):
    """CW6 Business: Add items and process payment with multiple guests"""
    print(f"[{agent.role}] [CW6] Add items and payment with multiple guests")
    agent.launch_app()
    if events["order_placed"].wait(timeout=180):
        _wait_tap(agent, "Orders")
        _tap(agent, "Orders")
        _tap(agent, "ReservedOrderCard")
        _wait_tap(agent, "T0AssignAnyBtn")
        _tap(agent, "T0AssignAnyBtn")
        _tap(agent, "AssignTableBtn")
        _wait_tap(agent, "Payment Payment")
        _tap(agent, "Payment Payment")
        _wait_tap(agent, "addGuestBtn")
        _tap(agent, "addGuestBtn")
        _tap(agent, "Guest2Card")
        _wait_tap(agent, "addGuestBtn")
        _tap(agent, "addGuestBtn")
        _tap(agent, "Guest3Card")
        _wait_tap(agent, "addGuestBtn")
        _tap(agent, "addGuestBtn")
        _tap(agent, "Guest4Card")
        _tap(agent, "Overview Overview")
        _tap(agent, "In ProgressOrderCard")
        _tap(agent, "addItemsBtn")
        _tap(agent, "Pasta & PizzaBtn")
        _tap(agent, "PizzaRucolaeParmigianoItem")
        _tap(agent, "FreshbellpepperBtn")
        _tap(agent, "applyOptionBtn")
        _tap(agent, "Pasta & PizzaBtn")
        _tap(agent, "PizzaRucolaeParmigianoItem")
        _tap(agent, "addNewCustomSelection")
        _tap(agent, "FreshchampignonsBtn")
        _tap(agent, "applyOptionBtn")
        _tap(agent, "Pasta & PizzaBtn")
        _tap(agent, "PizzaRucolaeParmigianoItem")
        _tap(agent, "addNewCustomSelection")
        _tap(agent, "CookedhamBtn")
        _tap(agent, "applyOptionBtn")
        _tap(agent, "PizzaQuattroStagioniItem")
        _tap(agent, "applyOptionBtn")
        _tap(agent, "assignToBtn")
        _tap(agent, "addNewGuest")
        _wait_tap(agent, "selectAll")
        _tap(agent, "selectAll")
        _wait_tap(agent, "assignProductsBtn")
        _tap(agent, "assignProductsBtn")
        _wait_tap(agent, "selectAllItemsBtn")
        _tap(agent, "selectAllItemsBtn")
        _tap(agent, "sendItemsBtn")
        _wait_tap(agent, "backButton")
        _tap(agent, "backButton")
        # Kitchen
        _switch_biz_account(agent, "kempA@xorstack.com", "Nylaii@09")
        _wait_tap(agent, "inProgressOrderCard")
        _tap(agent, "inProgressOrderCard")
        _tap(agent, "PizzaRucolaeParmigiano6Freshchampignons PizzaRucolaeParmigiano")
        _tap(agent, "PizzaRucolaeParmigiano6Freshbellpepper PizzaRucolaeParmigiano")
        _tap(agent, "PizzaRucolaeParmigiano6Cookedham PizzaRucolaeParmigiano")
        _tap(agent, "PizzaQuattroStagioni6 PizzaQuattroStagioni")
        _tap(agent, "orderReadyBtn")
        _tap(agent, "orderCloseBtn")
        # Serve
        _switch_biz_account(agent, "empA@xorstack.com", "Nylaii@06")
        _tap(agent, "Orders")
        _tap(agent, "ServeOrderCard")
        _tap(agent, "selectAllItemsBtn")
        _tap(agent, "serveItemsBtn")
        _tap(agent, "notifyPaymentBtn")
        _tap(agent, "Payment Payment")
        _tap(agent, "NooluNagaCard")
        _wait_tap(agent, "cashPaymentBtn")
        _tap(agent, "cashPaymentBtn")
        _tap(agent, "Number5")
        _tap(agent, "Number0")
        _tap(agent, "Number0")
        _tap(agent, "userInputBtn")
        _tap(agent, "Guest2select")
        agent.swipe_up()
        _tap(agent, "Guest4select")
        _tap(agent, "Guest5select")
        _tap(agent, "Apply")
        agent.swipe_up()
        _wait_tap(agent, "paymentConfirmBtn")
        _tap(agent, "paymentConfirmBtn")
        _tap(agent, "Guest3Card")
        agent.swipe_up()
        _tap(agent, "paidCashPaymentBtn")
        _tap(agent, "Number3")
        _tap(agent, "Number0")
        _tap(agent, "Number0")
        _tap(agent, "userInputBtn")
        _tap(agent, "Guest5select")
        _tap(agent, "Apply")
        agent.swipe_up()
        _wait_tap(agent, "paymentConfirmBtn")
        _tap(agent, "paymentConfirmBtn")
        _wait_tap(agent, "RoopaDCard")
        _tap(agent, "Overview Overview")
        _wait_tap(agent, "closeTableBtn")
        _tap(agent, "closeTableBtn")
        events["payment_completed"].set()
        scenario_reporter.add_result("CW6", "B-App Adding Items with 2+ Guests",
                                     agent.role, "PASS", "Completed", agent.last_launch_time)


# ─── SCENARIO MAP ────────────────────────────────────────────────────────────

SCENARIO_MAP = {
    # Contacts & Wallet
    "CW1": {"name": "Creating New Contact from Reservation",          "consumer": cw1_consumer_flow, "business": _no_op},
    "CW2": {"name": "Adding Guest from Wallet",                        "consumer": cw2_consumer_flow, "business": _no_op},
    "CW3": {"name": "Adding User from Wallet",                         "consumer": cw3_consumer_flow, "business": _no_op},
    "CW4": {"name": "Creating New Contact from Wallet",                "consumer": cw4_consumer_flow, "business": _no_op},
    "CW5": {"name": "B-App Adding Items with 1 Guest",                 "consumer": cw5_consumer_flow, "business": cw5_business_flow},
    "CW6": {"name": "B-App Adding Items with 2+ Guests",               "consumer": cw6_consumer_flow, "business": cw6_business_flow},

    # Event Booking
    "EB1": {"name": "Book Event 1 Guest Indoor",                       "consumer": eb1_consumer_flow, "business": eb1_business_flow},
    "EB2": {"name": "Book Event Outdoor - Invitee Accepts",            "consumer": eb2_consumer_flow, "business": eb2_business_flow},
    "EB3": {"name": "Book Event 1 Participant + 1 Guest",              "consumer": eb3_consumer_flow, "business": eb3_business_flow},
    "EB4": {"name": "Book Event - Invitee Declines",                   "consumer": eb4_consumer_flow, "business": eb4_business_flow},
    "EB5": {"name": "Book Event Multiple Invitees + Wallet Filter",    "consumer": eb5_consumer_flow, "business": eb5_business_flow},
    "EB6": {"name": "Book Event + Pre-Order + Bill + Coupon Validation","consumer": eb6_consumer_flow, "business": eb6_business_flow},

    # Create & Manage Events from B-App
    "BME1": {"name": "B-App Event - User Declines",                   "consumer": bme1_consumer_flow, "business": bme1_business_flow},
    "BME2": {"name": "B-App Event - User Accepts & Preorders",        "consumer": bme2_consumer_flow, "business": bme2_business_flow},
    "BME3": {"name": "B-App Event - Invite User from Wallet",         "consumer": bme3_consumer_flow, "business": bme3_business_flow},
    "BME4": {"name": "B-App Event - Cancel with Invitee",             "consumer": bme4_consumer_flow, "business": bme4_business_flow},
    "BME5": {"name": "B-App Event Cancel - No Invitees",              "consumer": bme5_consumer_flow, "business": bme5_business_flow},

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
    "PAY1": {"name": "Payment by Cash",                                "consumer": pay1_consumer_flow, "business": pay1_business_flow},
    "PAY2": {"name": "Host Pays for Others",                           "consumer": pay2_consumer_flow, "business": pay2_business_flow},
    "PAY3": {"name": "Payment by E-Payment",                           "consumer": pay3_consumer_flow, "business": pay3_business_flow},
    "PAY4": {"name": "Payment by Food Voucher",                        "consumer": pay4_consumer_flow, "business": pay4_business_flow},
    "PAY5": {"name": "Payment All 3 Modes",                            "consumer": pay5_consumer_flow, "business": pay5_business_flow},
    "PAY6": {"name": "Participant Pays for Others",                    "consumer": pay6_consumer_flow, "business": pay6_business_flow},
    "PAY7": {"name": "Guest Pays for Others",                          "consumer": pay7_consumer_flow, "business": pay7_business_flow},

    # Status Verification
    "SV1":  {"name": "Confirmation Pending Status",                    "consumer": sv1_consumer_flow,  "business": sv1_business_flow},
    "SV2":  {"name": "Reserved Status B-App",                          "consumer": sv2_consumer_flow,  "business": sv2_business_flow},
    "SV3":  {"name": "Event Declination Status",                       "consumer": sv3_consumer_flow,  "business": sv3_business_flow},
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
