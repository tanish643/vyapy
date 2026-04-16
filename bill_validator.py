"""
Bill Validator for Vyapy QA Bot.
Extracts item prices from checkout screen and validates math.
Currency: € (Euro)
"""
import re

# Keywords that identify a bill/checkout screen
BILL_SCREEN_KEYWORDS = [
    "grand total", "total amount", "bill total", "amount due",
    "pay now", "checkout", "payment summary", "order total",
    "subtotal", "total payable", "net amount", "place order"
]

# Labels that appear next to the final total value
TOTAL_LABELS = [
    "Grand Total", "Total Amount", "Total", "TOTAL",
    "Bill Total", "Amount Due", "Order Total", "Net Amount",
    "Total Payable", "Subtotal", "Place Order"
]


def is_bill_screen(xml):
    lower = xml.lower()
    return any(kw in lower for kw in BILL_SCREEN_KEYWORDS)


def _parse_price(text):
    """Parse a price string like '123.45 €' or '€123.45' or '123.45' to float."""
    cleaned = re.sub(r'[€₹₨Rs,\s]', '', str(text)).strip()
    try:
        val = float(cleaned)
        return val if val > 0 else None
    except (ValueError, TypeError):
        return None


def extract_all_prices(xml):
    """Extract all numeric price-like values visible on screen."""
    prices = []
    seen = set()

    # Match prices like "123.45 €", "€123.45", "123.45", "1,234.56 €"
    for attr in ['text', 'content-desc']:
        for m in re.finditer(rf'{attr}="([^"]*(?:\d+[,.]?\d*)\s*€?[^"]*)"', xml):
            raw = m.group(1)
            # Extract numeric part
            price_match = re.search(r'([\d,]+\.\d{1,2})\s*€?', raw)
            if price_match:
                val = _parse_price(price_match.group(1))
                if val and val >= 0.01 and val not in seen:
                    prices.append(val)
                    seen.add(val)

    return prices


def extract_line_items(xml):
    """Extract item names with their prices from checkout XML.
    Returns list of (item_name, price) tuples."""
    items = []
    # Look for text elements that contain item names followed by prices
    # Pattern: text="Item Name" ... text="123.45 €" nearby
    texts = re.findall(r'text="([^"]+)"', xml)

    i = 0
    while i < len(texts):
        text = texts[i]
        # Skip empty, small, and non-item texts
        if len(text) > 2 and not re.match(r'^[\d.,€₹\s]+$', text):
            # Look for a price in the next few text elements
            for j in range(i + 1, min(i + 5, len(texts))):
                price_match = re.search(r'([\d,]+\.\d{1,2})\s*€?', texts[j])
                if price_match:
                    val = _parse_price(price_match.group(1))
                    if val:
                        items.append((text.strip(), val))
                    break
        i += 1
    return items


def extract_line_items_from_multiple_dumps(xml_dumps):
    """Extract item names with their prices from multiple UI dumps (scrolled screens).
    Filters out non-item rows (DATE, INVOICE, TICKET, EC-Card, Total, VAT, Excl.Tax, ATI).
    Deduplicates items by name+price combo.
    Returns list of (item_name, price) tuples."""
    skip_patterns = [
        r'\bdate\b', r'\binvoice\b', r'\bticket\b',
        r'\btotal\b', r'\bvat\b', r'\btax\b', r'\bexcl',
        r'\bati\b', r'\bsubtotal\b', r'\bgrand\b',
        r'\bec-?card\b', r'\bbank\s*card\b', r'\bpayment\b',
        r'\bcoupon\b', r'\btip\b', r'\bdelivery\b',
    ]
    skip_re = re.compile('|'.join(skip_patterns), re.IGNORECASE)

    all_items = []
    seen = set()

    for xml in xml_dumps:
        items = extract_line_items(xml)
        for name, price in items:
            if skip_re.search(name):
                continue
            key = (name.strip(), price)
            if key not in seen:
                all_items.append((name, price))
                seen.add(key)

    return all_items


def validate_items_sum_only(xml_dumps):
    """Items-only check: sum of item prices = displayed Total. NO VAT check.
    Use this for checkout/bill screens where you only want to verify items add up."""
    result = {
        "pass": True,
        "items_sum": None,
        "grand_total": None,
        "line_items": [],
        "reason": ""
    }

    line_items = extract_line_items_from_multiple_dumps(xml_dumps)
    grand_total = find_total_from_multiple_dumps(xml_dumps)

    result["line_items"] = line_items
    result["grand_total"] = grand_total

    if grand_total is None:
        result["pass"] = False
        result["reason"] = "Could not find Total amount"
        return result

    if not line_items:
        result["pass"] = False
        result["reason"] = f"Total=€{grand_total:.2f} but no items found to verify"
        return result

    # Deduplicate prices by value to avoid counting same item from multiple scroll dumps
    seen_prices = set()
    unique_prices = []
    for name, price in line_items:
        if price in seen_prices:
            continue
        if abs(price - grand_total) <= 0.01:
            continue
        seen_prices.add(price)
        unique_prices.append(price)
    items_sum = round(sum(unique_prices), 2)
    result["items_sum"] = items_sum
    diff = round(abs(items_sum - grand_total), 2)

    if diff <= 0.01:
        result["pass"] = True
        result["reason"] = f"Items sum OK: €{items_sum:.2f} = Total €{grand_total:.2f}"
    else:
        result["pass"] = False
        result["reason"] = (
            f"Items sum mismatch: sum=€{items_sum:.2f}, Total=€{grand_total:.2f}, diff=€{diff:.2f}"
        )

    return result


def extract_all_prices_from_multiple_dumps(xml_dumps):
    """Extract all prices from multiple UI dumps, deduplicated."""
    all_prices = []
    seen = set()

    for xml in xml_dumps:
        prices = extract_all_prices(xml)
        for p in prices:
            if p not in seen:
                all_prices.append(p)
                seen.add(p)

    return all_prices


def extract_vat_info(xml):
    """Extract VAT percentage, VAT amount, and Excl.Tax from the bill screen.
    Returns dict with vat_percent, vat_amount, excl_tax."""
    vat_info = {"vat_percent": None, "vat_amount": None, "excl_tax": None}

    # Find VAT percentage — patterns like "VAT 14%", "VAT 14% INCL."
    for m in re.finditer(r'(?:text|content-desc)="([^"]*VAT[^"]*\d+(?:\.\d+)?\s*%[^"]*)"', xml, re.IGNORECASE):
        raw = m.group(1)
        pct_match = re.search(r'(\d+(?:\.\d+)?)\s*%', raw)
        if pct_match:
            vat_info["vat_percent"] = float(pct_match.group(1))
            break

    # Extract all text values for row-based parsing
    all_texts = re.findall(r'(?:text|content-desc)="([^"]+)"', xml)

    # Find "Excl. Tax" / "Excl.Tax" label and its value (next price after the label)
    for i, text in enumerate(all_texts):
        if re.search(r'\bexcl\.?\s*tax\b', text, re.IGNORECASE):
            # Look for the next price value nearby
            for j in range(i + 1, min(i + 10, len(all_texts))):
                price_match = re.search(r'([\d,]+\.\d{1,2})\s*€?', all_texts[j])
                if price_match:
                    val = _parse_price(price_match.group(1))
                    if val:
                        vat_info["excl_tax"] = val
                        break
            break

    # Find "VAT X% INCL." row — it has 3 prices in sequence: Excl.Tax, VAT, ATI
    # We want the MIDDLE price (2nd one) which is the VAT amount
    for i, text in enumerate(all_texts):
        if re.search(r'VAT\s*\d+(?:\.\d+)?\s*%.*INCL', text, re.IGNORECASE):
            prices_found = []
            for j in range(i + 1, min(i + 15, len(all_texts))):
                price_match = re.search(r'([\d,]+\.\d{1,2})\s*€?', all_texts[j])
                if price_match:
                    val = _parse_price(price_match.group(1))
                    if val:
                        prices_found.append(val)
                        if len(prices_found) >= 3:
                            break
            # The middle price is the VAT amount
            if len(prices_found) >= 2:
                vat_info["vat_amount"] = prices_found[1]
            break

    # Fallback: if VAT amount not found via "VAT X% INCL." row, try exact "VAT" label
    if vat_info["vat_amount"] is None:
        for i, text in enumerate(all_texts):
            stripped = text.strip()
            if stripped.lower() == "vat":
                # Collect multiple prices and pick the smallest (VAT is usually smaller than Excl.Tax and Total)
                prices_found = []
                for j in range(i + 1, min(i + 15, len(all_texts))):
                    price_match = re.search(r'([\d,]+\.\d{1,2})\s*€?', all_texts[j])
                    if price_match:
                        val = _parse_price(price_match.group(1))
                        if val:
                            prices_found.append(val)
                            if len(prices_found) >= 3:
                                break
                # Middle price is VAT amount in "Excl.Tax VAT ATI" column layout
                if len(prices_found) >= 2:
                    vat_info["vat_amount"] = prices_found[1]
                elif len(prices_found) == 1:
                    vat_info["vat_amount"] = prices_found[0]
                break

    return vat_info


def extract_vat_from_multiple_dumps(xml_dumps):
    """Extract VAT info from multiple dumps. Merges non-None values across dumps."""
    merged = {"vat_percent": None, "vat_amount": None, "excl_tax": None}
    for xml in xml_dumps:
        info = extract_vat_info(xml)
        for key in merged:
            if merged[key] is None and info.get(key) is not None:
                merged[key] = info[key]
    return merged


def extract_all_vat_rows(xml_dumps):
    """Find ALL VAT rate rows in the bill screen.
    Each row has format: 'VAT X% INCL.' followed by 1-3 prices.
    - 3 prices: full bill row (Excl.Tax, VAT, ATI)
    - 1 price: cart VAT display (just VAT amount)
    Returns a list of dicts: [{vat_percent, excl_tax, vat_amount, ati}, ...]
    Deduplicates by vat_percent across dumps."""
    rows = []
    seen_percents = set()
    for xml in xml_dumps:
        all_texts = re.findall(r'(?:text|content-desc)="([^"]+)"', xml)
        for i, text in enumerate(all_texts):
            m = re.search(r'VAT\s*(\d+(?:\.\d+)?)\s*%', text, re.IGNORECASE)
            if m:
                pct = float(m.group(1))
                if pct in seen_percents:
                    continue
                # Collect next 3 prices after the VAT label
                prices_found = []
                for j in range(i + 1, min(i + 15, len(all_texts))):
                    price_match = re.search(r'([\d,]+\.\d{1,2})\s*€?', all_texts[j])
                    if price_match:
                        val = _parse_price(price_match.group(1))
                        if val:
                            prices_found.append(val)
                            if len(prices_found) >= 3:
                                break
                if len(prices_found) >= 3:
                    # Full bill row with Excl.Tax, VAT amount, ATI
                    row = {
                        "vat_percent": pct,
                        "excl_tax": prices_found[0],
                        "vat_amount": prices_found[1],
                        "ati": prices_found[2],
                    }
                    rows.append(row)
                    seen_percents.add(pct)
                elif len(prices_found) >= 1:
                    # Cart-style: only VAT amount shown next to "VAT X%"
                    row = {
                        "vat_percent": pct,
                        "excl_tax": None,
                        "vat_amount": prices_found[0],
                        "ati": None,
                    }
                    rows.append(row)
                    seen_percents.add(pct)
    return rows


def validate_vat(subtotal, vat_percent, displayed_vat_amount):
    """Validate VAT calculation: vatAmount = (vatPercent / 100) * subtotal.
    Returns dict with pass/fail and reason."""
    expected_vat = round((vat_percent / 100) * subtotal, 2)
    diff = round(abs(displayed_vat_amount - expected_vat), 2)

    if diff > 0.01:
        return {
            "pass": False,
            "reason": (
                f"VAT mismatch: ({vat_percent}% of €{subtotal:.2f}) = €{expected_vat:.2f}, "
                f"displayed=€{displayed_vat_amount:.2f}, diff=€{diff:.2f}"
            )
        }
    return {
        "pass": True,
        "reason": (
            f"VAT OK: {vat_percent}% of €{subtotal:.2f} = €{displayed_vat_amount:.2f}"
        )
    }


def find_labeled_total(xml):
    """Find total value that is labeled with Grand Total / Total Amount etc."""
    for label in TOTAL_LABELS:
        pattern = rf'(?:text|content-desc)="{re.escape(label)}"'
        m = re.search(pattern, xml, re.IGNORECASE)
        if m:
            nearby = xml[m.start(): m.start() + 600]
            price_m = re.search(
                r'(?:text|content-desc)="(?:€)?\s*([\d,]+\.\d{1,2})\s*€?"',
                nearby
            )
            if price_m:
                val = _parse_price(price_m.group(1))
                if val:
                    return val
    return None


def find_checkout_total(xml):
    """Find the total on checkout screen - looks for CHECKOUT text with price."""
    # Pattern: "CHECKOUT (N) ∙ 123.45 €" or similar
    m = re.search(r'text="[^"]*(?:CHECKOUT|Place Order|Total)[^"]*?([\d,]+\.\d{1,2})\s*€?"', xml, re.IGNORECASE)
    if m:
        return _parse_price(m.group(1))
    return find_labeled_total(xml)


def find_total_from_multiple_dumps(xml_dumps):
    """Find the total from multiple dumps — check the last dump first (bottom of screen)."""
    # Check from last dump (bottom of screen where total usually is)
    for xml in reversed(xml_dumps):
        total = find_labeled_total(xml)
        if total:
            return total
        total = find_checkout_total(xml)
        if total:
            return total
    # Fallback: largest price across all dumps
    all_prices = extract_all_prices_from_multiple_dumps(xml_dumps)
    if all_prices:
        return max(all_prices)
    return None


def validate_bill(xml):
    """
    Validate bill math on current screen (single dump — legacy).

    Returns:
        dict with keys:
            is_bill_screen (bool)
            pass (bool)
            displayed_total (float or None)
            calculated_total (float or None)
            line_items (list of (name, price))
            diff (float)
            reason (str)
            calculation (str) — "item1: €X + item2: €Y = €Z"
    """
    return validate_bill_from_dumps([xml])


def validate_bill_from_dumps(xml_dumps):
    """
    Validate bill math from multiple UI dumps (scrolled screens).
    Collects all items from all dumps, finds total, validates sum.

    Returns:
        dict with keys:
            is_bill_screen (bool)
            pass (bool)
            displayed_total (float or None)
            calculated_total (float or None)
            line_items (list of (name, price))
            diff (float)
            reason (str)
            calculation (str)
    """
    result = {
        "is_bill_screen": False,
        "pass": True,
        "displayed_total": None,
        "calculated_total": None,
        "line_items": [],
        "diff": 0.0,
        "reason": "Not a bill screen",
        "calculation": ""
    }

    # Check if any dump is a bill screen
    for xml in xml_dumps:
        if is_bill_screen(xml):
            result["is_bill_screen"] = True
            break

    if not result["is_bill_screen"]:
        return result

    # Find displayed total from all dumps
    displayed_total = find_total_from_multiple_dumps(xml_dumps)

    if displayed_total is None:
        result["pass"] = False
        result["reason"] = "Bill screen detected but could not find total amount"
        return result

    result["displayed_total"] = displayed_total

    # Get all line items from all dumps
    line_items = extract_line_items_from_multiple_dumps(xml_dumps)

    if not line_items:
        # Fallback: use raw prices
        all_prices = extract_all_prices_from_multiple_dumps(xml_dumps)
        line_items_prices = [p for p in all_prices if abs(p - displayed_total) > 0.01]
        if not line_items_prices:
            result["reason"] = f"Bill screen: total=€{displayed_total:.2f} (no line items to cross-check)"
            return result
        calculated = round(sum(line_items_prices), 2)
        diff = round(abs(displayed_total - calculated), 2)
        result["calculated_total"] = calculated
        result["line_items"] = [(f"item", p) for p in line_items_prices]
        result["diff"] = diff
        calc_parts = [f"€{p:.2f}" for p in line_items_prices]
        result["calculation"] = " + ".join(calc_parts) + f" = €{calculated:.2f}"
    else:
        prices = [p for name, p in line_items if abs(p - displayed_total) > 0.01]
        if not prices:
            result["reason"] = f"Bill screen: total=€{displayed_total:.2f} (no line items to cross-check)"
            return result
        calculated = round(sum(prices), 2)
        diff = round(abs(displayed_total - calculated), 2)
        result["calculated_total"] = calculated
        result["line_items"] = line_items
        result["diff"] = diff
        calc_parts = [f"{name}: €{p:.2f}" for name, p in line_items if abs(p - displayed_total) > 0.01]
        result["calculation"] = " + ".join(calc_parts) + f" = €{calculated:.2f}"

    if diff > 0.01:
        result["pass"] = False
        result["reason"] = (
            f"Bill mismatch: displayed=€{displayed_total:.2f}, "
            f"calculated=€{calculated:.2f}, diff=€{diff:.2f}; "
            f"Items: {result['calculation']}"
        )
    else:
        result["reason"] = f"Bill OK: €{displayed_total:.2f} ({result['calculation']})"

    # VAT validation
    vat_info = extract_vat_from_multiple_dumps(xml_dumps)
    result["vat_percent"] = vat_info["vat_percent"]
    result["vat_amount"] = vat_info["vat_amount"]

    if vat_info["vat_percent"] is not None and vat_info["vat_amount"] is not None:
        # Calculate subtotal (total before VAT) = items sum without VAT amount
        subtotal = calculated
        if vat_info["vat_amount"] in [p for _, p in result["line_items"]]:
            subtotal = round(calculated - vat_info["vat_amount"], 2)

        vat_result = validate_vat(subtotal, vat_info["vat_percent"], vat_info["vat_amount"])
        result["vat_check"] = vat_result
        if not vat_result["pass"]:
            result["pass"] = False
            result["reason"] += f" | {vat_result['reason']}"
        else:
            result["reason"] += f" | {vat_result['reason']}"

    return result


def extract_cart_items_with_quantity(xml):
    """Extract cart items that have 'x N' quantity pattern.
    Pairs each item with the closest price in the same horizontal row (similar Y).
    Returns list of (name, price) with each line counted separately (no dedup)."""
    # Step 1: Find all nodes with text + bounds
    nodes = []
    node_pattern = re.compile(
        r'<node[^>]*?(?:text|content-desc)="([^"]+)"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
        re.IGNORECASE
    )
    for m in node_pattern.finditer(xml):
        text = m.group(1)
        x1, y1, x2, y2 = int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
        if x1 == 0 and y1 == 0 and x2 == 0 and y2 == 0:
            continue
        nodes.append({"text": text, "y": (y1 + y2) // 2, "x": (x1 + x2) // 2})
    # Also try reverse order (bounds before text)
    node_pattern2 = re.compile(
        r'<node[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*?(?:text|content-desc)="([^"]+)"',
        re.IGNORECASE
    )
    for m in node_pattern2.finditer(xml):
        x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        text = m.group(5)
        if x1 == 0 and y1 == 0 and x2 == 0 and y2 == 0:
            continue
        node = {"text": text, "y": (y1 + y2) // 2, "x": (x1 + x2) // 2}
        if node not in nodes:
            nodes.append(node)

    # Step 2: Identify items (x N pattern) and prices
    items_found = []  # list of {"name": str, "y": int}
    prices_found = []  # list of {"price": float, "y": int}

    qty_pattern = re.compile(r'(.+?\s*x\s*\d+)\s*$', re.IGNORECASE)
    price_pattern = re.compile(r'^\s*(?:€)?\s*([\d,]+\.\d{1,2})\s*€?\s*$')

    for node in nodes:
        text = node["text"].strip()
        # Check if it's an item with "x N" pattern
        qty_match = qty_pattern.match(text)
        if qty_match:
            items_found.append({"name": qty_match.group(1).strip(), "y": node["y"]})
            continue
        # Check if it's a standalone price
        price_match = price_pattern.match(text)
        if price_match:
            val = _parse_price(price_match.group(1))
            if val:
                prices_found.append({"price": val, "y": node["y"]})

    # Step 3: Pair each item with closest price in the same row (Y within tolerance)
    items = []
    Y_TOLERANCE = 80  # pixels
    used_prices = set()
    for item in items_found:
        best_price = None
        best_dist = float("inf")
        best_idx = None
        for i, p in enumerate(prices_found):
            if i in used_prices:
                continue
            dist = abs(p["y"] - item["y"])
            if dist < Y_TOLERANCE and dist < best_dist:
                best_dist = dist
                best_price = p["price"]
                best_idx = i
        if best_price is not None:
            items.append((item["name"], best_price))
            used_prices.add(best_idx)

    return items


def validate_cart_total_only(xml_dumps):
    """Check: sum of item prices = cart total. No VAT check.
    Only counts items matching 'x N' pattern.
    Scrolls through cart and uses MAX count per (name, price) across all dumps
    to handle multi-item carts without over-counting from scroll duplication."""
    result = {
        "pass": True,
        "displayed_total": None,
        "calculated_total": None,
        "line_items": [],
        "diff": 0.0,
        "reason": ""
    }

    if not xml_dumps:
        result["pass"] = False
        result["reason"] = "No UI dumps to check"
        return result

    displayed_total = find_total_from_multiple_dumps(xml_dumps)
    if displayed_total is None:
        result["pass"] = False
        result["reason"] = "Cart screen: could not find total amount"
        return result

    result["displayed_total"] = displayed_total

    # Build set of VAT/Excl.Tax/ATI values to exclude (in case cart shows them)
    vat_rows = extract_all_vat_rows(xml_dumps)
    exclude_values = set()
    for row in vat_rows:
        if row["excl_tax"] is not None:
            exclude_values.add(row["excl_tax"])
        if row["vat_amount"] is not None:
            exclude_values.add(row["vat_amount"])
        if row["ati"] is not None:
            exclude_values.add(row["ati"])

    # Collect items from each dump separately, count (name, price) frequency per dump
    max_count_per_item = {}  # {(name, price): max_count_seen_in_any_dump}
    for xml in xml_dumps:
        items_in_dump = extract_cart_items_with_quantity(xml)
        dump_counts = {}
        for name, price in items_in_dump:
            if abs(price - displayed_total) <= 0.01:
                continue
            # Skip prices matching VAT/Excl.Tax/ATI values
            if any(abs(price - v) <= 0.01 for v in exclude_values):
                continue
            key = (name, price)
            dump_counts[key] = dump_counts.get(key, 0) + 1
        for key, count in dump_counts.items():
            if count > max_count_per_item.get(key, 0):
                max_count_per_item[key] = count

    # Build final item list based on max counts
    final_items = []
    item_prices = []
    for (name, price), count in max_count_per_item.items():
        for _ in range(count):
            final_items.append((name, price))
            item_prices.append(price)

    # Fallback: if no items matched the 'x N' pattern, try legacy extraction
    if not item_prices:
        legacy_items = extract_line_items_from_multiple_dumps(xml_dumps)
        seen = set()
        for name, price in legacy_items:
            if price in seen or abs(price - displayed_total) <= 0.01:
                continue
            seen.add(price)
            item_prices.append(price)
            final_items.append((name, price))

    if not item_prices:
        result["reason"] = f"Cart: total=€{displayed_total:.2f} (no items to verify)"
        return result

    calculated = round(sum(item_prices), 2)
    diff = round(abs(displayed_total - calculated), 2)
    result["calculated_total"] = calculated
    result["line_items"] = final_items
    result["diff"] = diff

    calc_parts = [f"€{p:.2f}" for p in item_prices]
    calc_str = " + ".join(calc_parts) + f" = €{calculated:.2f}"

    if diff > 0.01:
        result["pass"] = False
        result["reason"] = (
            f"Cart total mismatch: displayed=€{displayed_total:.2f}, "
            f"calculated=€{calculated:.2f}, diff=€{diff:.2f}; Items: {calc_str}"
        )
    else:
        result["reason"] = f"Cart total OK: €{displayed_total:.2f} (Items: {calc_str})"

    return result


def validate_bill_with_vat(xml_dumps):
    """Full bill check — handles MULTIPLE VAT rates (3%, 14%, etc.).
    For each VAT row: validates (VAT% / 100) × Excl.Tax = VAT amount.
    Also validates: items sum = Total, and sum(Excl.Tax) + sum(VAT amount) = Total.
    """
    result = {
        "pass": True,
        "items_sum": None,
        "grand_total": None,
        "vat_rows": [],
        "line_items": [],
        "checks": [],
        "reason": ""
    }

    # Extract everything using the cart-style extraction (x N pattern, Y-matching)
    grand_total = find_total_from_multiple_dumps(xml_dumps)
    vat_rows = extract_all_vat_rows(xml_dumps)

    # Build set of VAT/Excl.Tax/ATI values to exclude from item sum
    exclude_values = set()
    for row in vat_rows:
        if row["excl_tax"] is not None:
            exclude_values.add(row["excl_tax"])
        if row["vat_amount"] is not None:
            exclude_values.add(row["vat_amount"])
        if row["ati"] is not None:
            exclude_values.add(row["ati"])

    # Collect items using max-count-per-dump to handle duplicates
    max_count_per_item = {}
    for xml in xml_dumps:
        items_in_dump = extract_cart_items_with_quantity(xml)
        dump_counts = {}
        for name, price in items_in_dump:
            if grand_total is not None and abs(price - grand_total) <= 0.01:
                continue
            if any(abs(price - v) <= 0.01 for v in exclude_values):
                continue
            key = (name, price)
            dump_counts[key] = dump_counts.get(key, 0) + 1
        for key, count in dump_counts.items():
            if count > max_count_per_item.get(key, 0):
                max_count_per_item[key] = count

    # Build final items list with correct multiplicity
    line_items = []
    for (name, price), count in max_count_per_item.items():
        for _ in range(count):
            line_items.append((name, price))

    result["line_items"] = line_items
    result["grand_total"] = grand_total
    result["vat_rows"] = vat_rows

    checks_passed = []
    checks_failed = []

    # Check 1: Items sum = Total
    if line_items and grand_total is not None:
        items_sum = round(sum(p for _, p in line_items), 2)
        result["items_sum"] = items_sum
        diff = round(abs(items_sum - grand_total), 2)
        if diff <= 0.01:
            checks_passed.append(f"Items sum (€{items_sum:.2f}) = Total (€{grand_total:.2f}) ✓")
        else:
            checks_failed.append(
                f"Items sum mismatch: displayed=€{grand_total:.2f}, calculated=€{items_sum:.2f}, diff=€{diff:.2f}"
            )

    # Check 2: For EACH VAT row, verify (VAT% / 100) × Excl.Tax = VAT amount
    for row in vat_rows:
        pct = row["vat_percent"]
        excl = row["excl_tax"]
        vat_amt = row["vat_amount"]
        if pct is not None and excl is not None and vat_amt is not None:
            expected_vat = round((pct / 100) * excl, 2)
            diff = round(abs(vat_amt - expected_vat), 2)
            if diff <= 0.01:
                checks_passed.append(
                    f"VAT {pct}% ({pct}/100 × €{excl:.2f} = €{expected_vat:.2f}) = displayed €{vat_amt:.2f} ✓"
                )
            else:
                checks_failed.append(
                    f"VAT {pct}% mismatch: expected {pct}/100 × €{excl:.2f} = €{expected_vat:.2f}, "
                    f"displayed=€{vat_amt:.2f}, diff=€{diff:.2f}"
                )

    # Check 3: sum(Excl.Tax) + sum(VAT amount) = Total
    if vat_rows and grand_total is not None:
        total_excl = round(sum(r["excl_tax"] for r in vat_rows if r["excl_tax"] is not None), 2)
        total_vat = round(sum(r["vat_amount"] for r in vat_rows if r["vat_amount"] is not None), 2)
        expected_total = round(total_excl + total_vat, 2)
        diff = round(abs(grand_total - expected_total), 2)
        if diff <= 0.01:
            checks_passed.append(
                f"Sum Excl.Tax (€{total_excl:.2f}) + Sum VAT (€{total_vat:.2f}) = €{expected_total:.2f} = Total €{grand_total:.2f} ✓"
            )
        else:
            checks_failed.append(
                f"Total breakdown mismatch: sum Excl.Tax (€{total_excl:.2f}) + sum VAT (€{total_vat:.2f}) = €{expected_total:.2f}, "
                f"displayed Total=€{grand_total:.2f}, diff=€{diff:.2f}"
            )

    result["checks"] = checks_passed + checks_failed

    if checks_failed:
        result["pass"] = False
        parts = []
        if checks_passed:
            parts.append("PASSED: " + " | ".join(checks_passed))
        parts.append("FAILED: " + " | ".join(checks_failed))
        result["reason"] = "Bill check — " + " || ".join(parts)
    elif checks_passed:
        result["reason"] = "Bill check PASSED: " + " | ".join(checks_passed)
    else:
        result["pass"] = False
        result["reason"] = "Could not find items/VAT/Total to verify"

    return result


def validate_coupon(xml, original_total, coupon_value):
    """
    Validate that coupon was applied correctly.
    expected_total = original_total - coupon_value
    """
    displayed_total = find_labeled_total(xml)
    if displayed_total is None:
        displayed_total = find_checkout_total(xml)
    if displayed_total is None:
        all_prices = extract_all_prices(xml)
        displayed_total = max(all_prices) if all_prices else None

    if displayed_total is None:
        return {"pass": False, "reason": "Could not find total after coupon applied"}

    expected = round(original_total - coupon_value, 2)
    diff = round(abs(displayed_total - expected), 2)

    if diff > 0.01:
        return {
            "pass": False,
            "reason": (
                f"Coupon mismatch: expected=€{expected:.2f}, "
                f"displayed=€{displayed_total:.2f}, diff=€{diff:.2f}"
            )
        }
    return {
        "pass": True,
        "reason": (
            f"Coupon OK: €{original_total:.2f} - €{coupon_value:.2f} = €{displayed_total:.2f}"
        )
    }
