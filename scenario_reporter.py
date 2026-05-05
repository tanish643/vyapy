"""
Scenario Reporter for Vyapy Multi-Agent QA Bot.
Tracks PASS/FAIL per scenario and writes a live-updating HTML report.
Persists results to JSON so previous runs are visible in the report.

JSON structure:
{
  "current": { "num", "name", "status", "error", "timestamp", "consumer_status",
               "business_status", "launch_time", "reasons",
               "consumer_reasons", "business_reasons" },
  "history": [ ... same shape, newest first ... ]
}
"""
import json
import re
import threading
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

REPORT_PATH = Path(r"C:\Users\Tanish\Downloads\Vya-agentic-BOT (1)\Vya-agentic-BOT\new_scenario_report.html")
HISTORY_PATH = Path(r"C:\Users\Tanish\Downloads\Vya-agentic-BOT (1)\Vya-agentic-BOT\scenario_history.json")

_lock = threading.Lock()
_run_id = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ── In-memory state for current run ──────────────────────────────────────
_current_scenario_num = None
_current_result = None
_session_history = []


# ── JSON persistence ─────────────────────────────────────────────────────

def _load_data():
    if not HISTORY_PATH.exists():
        return {"current": None, "history": []}
    try:
        raw = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"current": None, "history": []}

    if isinstance(raw, list):
        migrated = [_normalize_legacy_entry(r) for r in raw]
        return {"current": None, "history": migrated[-200:]}

    if not isinstance(raw, dict):
        return {"current": None, "history": []}
    raw.setdefault("current", None)
    raw.setdefault("history", [])
    return raw


def _normalize_legacy_entry(r):
    reasons = r.get("reasons") or []
    if not reasons and r.get("reason"):
        reasons = [r["reason"]]
    error_str = "; ".join([x for x in reasons if x and x != "Completed"])
    return {
        "num": r.get("num", ""),
        "name": r.get("name", ""),
        "status": r.get("status", "PASS"),
        "error": error_str,
        "timestamp": r.get("run_id", r.get("time", "")),
        "consumer_status": r.get("status") if r.get("role") == "Consumer" else "N/A",
        "business_status": r.get("status") if r.get("role") == "Business" else "N/A",
        "launch_time": r.get("launch_time"),
        "reasons": reasons,
        "consumer_reasons": [r["reason"]] if r.get("role") == "Consumer" and r.get("reason") else [],
        "business_reasons": [r["reason"]] if r.get("role") == "Business" and r.get("reason") else [],
    }


def _save_data(data):
    try:
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        if len(data.get("history", [])) > 500:
            data["history"] = data["history"][:500]
        HISTORY_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"[Report] Warning: could not save data: {e}")


# ── Core public API (backward-compatible signature) ──────────────────────

def add_result(scenario_num, scenario_name, role, status, reason,
               launch_time=None, screenshot_path=None, screen_load_time=None):
    global _current_scenario_num, _current_result

    with _lock:
        snum = str(scenario_num)

        if _current_result is not None and _current_scenario_num != snum:
            _rotate_current_to_history()

        if _current_result is None or _current_scenario_num != snum:
            _current_scenario_num = snum
            _current_result = {
                "num": snum,
                "name": scenario_name,
                "status": status,
                "error": reason if status == "FAIL" else "",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "consumer_status": "N/A",
                "business_status": "N/A",
                "launch_time": launch_time,
                "reasons": [reason] if reason else [],
                "consumer_reasons": [],
                "business_reasons": [],
            }
            if role == "Consumer":
                _current_result["consumer_status"] = status
                if reason:
                    _current_result["consumer_reasons"].append(reason)
            elif role == "Business":
                _current_result["business_status"] = status
                if reason:
                    _current_result["business_reasons"].append(reason)
        else:
            if _current_result["status"] != "FAIL" and status == "FAIL":
                _current_result["status"] = "FAIL"

            if reason:
                if reason not in _current_result.get("reasons", []):
                    _current_result.setdefault("reasons", []).append(reason)
                fail_reasons = [x for x in _current_result["reasons"]
                                if x and x != "Completed"]
                # error text only reflects failures
                if _current_result["status"] == "FAIL":
                    _current_result["error"] = "; ".join(fail_reasons)

            if role == "Consumer":
                prev = _current_result["consumer_status"]
                if prev == "N/A" or (prev != "FAIL" and status == "FAIL"):
                    _current_result["consumer_status"] = status
                if reason:
                    lst = _current_result.setdefault("consumer_reasons", [])
                    if reason not in lst:
                        lst.append(reason)
            elif role == "Business":
                prev = _current_result["business_status"]
                if prev == "N/A" or (prev != "FAIL" and status == "FAIL"):
                    _current_result["business_status"] = status
                if reason:
                    lst = _current_result.setdefault("business_reasons", [])
                    if reason not in lst:
                        lst.append(reason)

            if launch_time is not None:
                prev_lt = _current_result.get("launch_time")
                if prev_lt is None or launch_time < prev_lt:
                    _current_result["launch_time"] = launch_time

        # Overall status rule: FAIL if either side failed; PASS only if both PASS
        c = _current_result.get("consumer_status", "N/A")
        b = _current_result.get("business_status", "N/A")
        if c == "FAIL" or b == "FAIL":
            _current_result["status"] = "FAIL"
        elif c == "PASS" and b == "PASS":
            _current_result["status"] = "PASS"

        _persist_and_render()


def _rotate_current_to_history():
    global _current_result, _current_scenario_num
    if _current_result is not None:
        _session_history.insert(0, dict(_current_result))
        _current_result = None
        _current_scenario_num = None


def _persist_and_render():
    data = _load_data()
    merged_history = list(_session_history) + data.get("history", [])
    if len(merged_history) > 500:
        merged_history = merged_history[:500]
    data["current"] = dict(_current_result) if _current_result else None
    data["history"] = merged_history
    _save_data(data)
    _write_html(data)


# ── End-of-run API ───────────────────────────────────────────────────────

def save_run_to_history():
    global _current_result, _current_scenario_num
    with _lock:
        if _current_result is not None:
            _rotate_current_to_history()
        data = _load_data()
        full_history = list(_session_history) + data.get("history", [])
        if len(full_history) > 500:
            full_history = full_history[:500]
        data["current"] = None
        data["history"] = full_history
        _save_data(data)
        _write_html(data)
        print(f"[Report] Saved {len(_session_history)} results to history ({len(full_history)} total)")


def _format_failure_clean(error_text):
    """Convert raw bot error dump into client-friendly structured lines.
    Extracts Pre/Post totals + VAT mismatches and returns indented lines."""
    if not error_text:
        return []
    lines = []
    seen = set()

    m = re.search(r'Cart total OK[^€]*€?([\d.]+)', error_text)
    if m and ("pre" not in seen):
        lines.append(f"          Pre-Payment Total: €{m.group(1)}")
        seen.add("pre")

    m = re.search(
        r'Sum Excl\.?Tax\s*\(\s*€?[\d.]+\s*\)\s*\+\s*Sum VAT\s*\(\s*€?[\d.]+\s*\)\s*=\s*€?[\d.]+\s*=\s*Total\s*€?([\d.]+)',
        error_text,
    )
    if m and ("post" not in seen):
        lines.append(f"          Post-Payment Total: €{m.group(1)}")
        seen.add("post")

    for vm in re.finditer(
        r'VAT\s+([\d.]+)%\s*mismatch:\s*expected\s+[\d.]+/100\s*[×x*]\s*€?([\d.]+)\s*=\s*€?([\d.]+),\s*displayed\s*=\s*€?([\d.]+),\s*diff\s*=\s*€?([\d.]+)',
        error_text,
    ):
        rate, _calc_excl, expected, displayed, diff = vm.groups()
        lines.append(
            f"          VAT {rate}% mismatch: expected €{expected}, "
            f"displayed €{displayed}, diff €{diff}"
        )

    has_fails = any("mismatch" in l for l in lines)
    if has_fails:
        for vm in re.finditer(
            r'VAT\s+([\d.]+)%\s*\(\s*[\d.]+/100\s*[×x*]\s*€?[\d.]+\s*=\s*€?([\d.]+)\s*\)\s*=\s*displayed\s*€?([\d.]+)\s*✓',
            error_text,
        ):
            rate, expected, _displayed = vm.groups()
            lines.append(f"          VAT {rate}% OK: €{expected} (matches)")

    m = re.search(
        r'Bill\s*total\s*mismatch:\s*displayed\s*=\s*€?([\d.]+),\s*calculated\s*=\s*€?([\d.]+),\s*diff\s*=\s*€?([\d.]+)',
        error_text, re.IGNORECASE,
    )
    if m:
        lines.append(
            f"          Bill total mismatch: displayed €{m.group(1)}, "
            f"calculated €{m.group(2)}, diff €{m.group(3)}"
        )

    m = re.search(
        r'Items\s*sum\s*mismatch:\s*displayed\s*=\s*€?([\d.]+),\s*calculated\s*=\s*€?([\d.]+),\s*diff\s*=\s*€?([\d.]+)',
        error_text, re.IGNORECASE,
    )
    if m:
        lines.append(
            f"          Items sum mismatch: displayed €{m.group(1)}, "
            f"calculated €{m.group(2)}, diff €{m.group(3)}"
        )

    if "Interrupted by user" in error_text and not lines:
        lines.append("          Interrupted by user")

    return lines


def print_summary():
    all_results = []
    if _current_result:
        all_results.append(_current_result)
    all_results.extend(_session_history)

    passed = sum(1 for r in all_results if r["status"] == "PASS")
    failed = sum(1 for r in all_results if r["status"] == "FAIL")
    total = len(all_results)
    print("\n" + "=" * 60)
    print(f"  VYAPY QA RESULTS: {passed}/{total} PASSED | {failed} FAILED")
    print("=" * 60)
    for r in all_results:
        icon = "PASS" if r["status"] == "PASS" else "FAIL"
        launch = f"({r['launch_time']:.1f}s)" if r.get("launch_time") else ""
        print(f"  [{icon}] [{r['num']}] {r['name']} {launch}")
        if r["status"] == "FAIL" and r.get("error"):
            clean_lines = _format_failure_clean(r["error"])
            if clean_lines:
                for line in clean_lines:
                    print(line)
            else:
                # Fallback if structured parsing didn't find anything: short raw
                short = r["error"][:200] + ("..." if len(r["error"]) > 200 else "")
                print(f"          -> {short}")
    print(f"\n  Report: {REPORT_PATH}")
    print("=" * 60)


# ── Helpers for HTML generation ──────────────────────────────────────────

def _esc(text):
    if text is None or text == "":
        return ""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def _tc_id(num):
    """Generate a formal Test Case ID from scenario number."""
    return f"VYA-TC-{str(num).upper()}"


def _status_badge(status, size="sm"):
    cls_size = {"sm": "", "lg": " badge-lg", "xl": " badge-xl"}.get(size, "")
    if status == "PASS":
        return f'<span class="badge badge-pass{cls_size}"><i class="fa-solid fa-circle-check"></i> PASS</span>'
    if status == "FAIL":
        return f'<span class="badge badge-fail{cls_size}"><i class="fa-solid fa-circle-xmark"></i> FAIL</span>'
    return f'<span class="badge badge-na{cls_size}"><i class="fa-solid fa-minus"></i> N/A</span>'


# System/terminal names we try to detect inside reason strings
_SYSTEM_HINTS = ["Roopa", "Nooku", "Guest1", "Guest2", "Host", "RoopaDCard", "Cash", "E-Payment"]


def _detect_system(text):
    if not text:
        return None
    for name in _SYSTEM_HINTS:
        if re.search(rf'\b{re.escape(name)}\b', text, re.IGNORECASE):
            return name
    return None


def _categorise_segment(seg):
    """Return heading name for a calc segment based on keywords."""
    s = seg.lower()
    if "vat" in s or "tax" in s:
        return "VAT Calculation", "fa-percent"
    if "coupon" in s or "discount" in s or "offer" in s:
        return "Coupon Calculation", "fa-ticket"
    if "tip" in s or "gratuity" in s:
        return "Tip Calculation", "fa-hand-holding-dollar"
    if "cart" in s:
        return "Cart Total Calculation", "fa-cart-shopping"
    if "items sum" in s or "item" in s and "=" in s:
        return "Items Sum Calculation", "fa-list-check"
    if "bill" in s and "ok" in s:
        return "Bill Calculation", "fa-receipt"
    if "bill" in s:
        return "Bill Calculation", "fa-receipt"
    if "total" in s:
        return "Total Calculation", "fa-calculator"
    if "before payment" in s:
        return "Before Payment Calculation", "fa-clock"
    if "after payment" in s:
        return "After Payment Calculation", "fa-check-double"
    if "sum" in s:
        return "Sum Calculation", "fa-plus"
    return "Calculation", "fa-calculator"


def _format_formula_steps(text):
    """Turn a formula-like string into an ordered list of step lines.
    Splits around '=' to make LHS vs RHS a multi-line step list."""
    cleaned = text.strip()
    if not cleaned:
        return []
    steps = []
    # Extract the (content inside parens) if present, else whole text
    paren_match = re.search(r'\(([^)]+)\)', cleaned)
    formula = paren_match.group(1) if paren_match else cleaned

    # Split on '=' to separate computation from result
    if "=" in formula:
        parts = [p.strip() for p in formula.split("=") if p.strip()]
        for i, p in enumerate(parts):
            if i < len(parts) - 1:
                steps.append({"line": p, "op": "="})
            else:
                steps.append({"line": p, "op": "result"})
    else:
        steps.append({"line": formula, "op": "note"})
    return steps


def _parse_calculations(reasons, role_hint=None):
    """Parse a list of reason strings into structured calculation blocks.

    Returns a list of dicts:
        { "title", "icon", "system", "raw", "steps": [{line, op}] }
    """
    blocks = []
    if not reasons:
        return blocks
    for raw in reasons:
        if not raw or raw.strip().lower() == "completed":
            continue
        # Remove leading tags like "Bill check PASSED: " or "PASSED: "
        body = re.sub(r'^(Bill check\s*)?(PASSED|FAILED)\s*[:—-]\s*', '', raw, flags=re.IGNORECASE)
        # Some validators join multi-check strings with ' | '
        segments = [s.strip() for s in re.split(r'\s*\|\s*|\s*\|\|\s*', body) if s.strip()]
        if not segments:
            segments = [body]
        for seg in segments:
            title, icon = _categorise_segment(seg)
            system = _detect_system(seg) or role_hint
            steps = _format_formula_steps(seg)
            blocks.append({
                "title": title,
                "icon": icon,
                "system": system,
                "raw": seg,
                "steps": steps,
            })
    return blocks


def _render_calc_block(block):
    steps_html = ""
    for s in block["steps"]:
        if s["op"] == "result":
            steps_html += f'<li class="calc-step calc-result"><span class="step-bullet">=</span><span>{_esc(s["line"])}</span></li>'
        elif s["op"] == "=":
            steps_html += f'<li class="calc-step"><span class="step-bullet">→</span><span>{_esc(s["line"])}</span></li>'
        else:
            steps_html += f'<li class="calc-step"><span class="step-bullet">•</span><span>{_esc(s["line"])}</span></li>'
    sys_chip = (f'<span class="calc-system"><i class="fa-solid fa-microchip"></i> {_esc(block["system"])}</span>'
                if block.get("system") else "")
    return (
        f'<div class="calc-block">'
        f'  <div class="calc-head">'
        f'    <div class="calc-title"><i class="fa-solid {block["icon"]}"></i> {_esc(block["title"])}</div>'
        f'    {sys_chip}'
        f'  </div>'
        f'  <ol class="calc-steps">{steps_html}</ol>'
        f'  <div class="calc-raw" title="raw string">{_esc(block["raw"])}</div>'
        f'</div>'
    )


def _build_reason_panel(role, status, reasons):
    """Render a per-role reason panel (Consumer or Business)."""
    icon = "fa-user" if role == "Consumer" else "fa-briefcase"
    status_cls = "tone-pass" if status == "PASS" else ("tone-fail" if status == "FAIL" else "tone-na")
    reasons = [r for r in (reasons or []) if r and r.strip().lower() != "completed"]
    if reasons:
        bullets = "".join(
            f'<li><i class="fa-solid fa-angle-right"></i> {_esc(r)}</li>' for r in reasons
        )
        body = f'<ul class="reason-list">{bullets}</ul>'
    else:
        body = '<p class="reason-empty"><i class="fa-regular fa-circle"></i> No notes reported</p>'
    return (
        f'<div class="reason-panel {status_cls}">'
        f'  <div class="reason-head">'
        f'    <div class="reason-role"><i class="fa-solid {icon}"></i> {role}</div>'
        f'    {_status_badge(status)}'
        f'  </div>'
        f'  {body}'
        f'</div>'
    )


def _build_home_card(current):
    if not current:
        return (
            '<div class="empty-state">'
            '  <div class="empty-orb"></div>'
            '  <i class="fa-solid fa-satellite-dish"></i>'
            '  <h3>Awaiting Scenario</h3>'
            '  <p>No scenario is currently executing. The dashboard will update live when a run starts.</p>'
            '</div>'
        )

    num = current.get("num", "")
    name = current.get("name", "")
    tc_id = _tc_id(num)
    overall = current.get("status", "N/A")
    c_status = current.get("consumer_status", "N/A")
    b_status = current.get("business_status", "N/A")
    launch = current.get("launch_time")
    launch_str = f"{launch:.2f}s" if isinstance(launch, (int, float)) else "—"
    ts = current.get("timestamp", "")

    overall_badge = _status_badge(overall, size="xl")
    tone_cls = "tone-pass" if overall == "PASS" else ("tone-fail" if overall == "FAIL" else "tone-na")

    # Per-role reasons (fallback to flat 'reasons' list if missing)
    c_reasons = current.get("consumer_reasons") or []
    b_reasons = current.get("business_reasons") or []
    if not c_reasons and not b_reasons and current.get("reasons"):
        flat = [r for r in current["reasons"] if r and r.strip().lower() != "completed"]
        c_reasons = flat if c_status != "N/A" else []
        b_reasons = flat if b_status != "N/A" else []

    c_panel = _build_reason_panel("Consumer", c_status, c_reasons)
    b_panel = _build_reason_panel("Business", b_status, b_reasons)

    # Calculations — parse every non-empty reason from both roles
    calc_blocks_c = _parse_calculations(c_reasons, role_hint="Consumer")
    calc_blocks_b = _parse_calculations(b_reasons, role_hint="Business")
    all_calc = calc_blocks_c + calc_blocks_b

    if all_calc:
        calc_html = '<div class="calc-grid">'
        calc_html += "".join(_render_calc_block(b) for b in all_calc)
        calc_html += '</div>'
        calc_section = (
            '<section class="calc-section">'
            '  <div class="section-head">'
            '    <h2><i class="fa-solid fa-square-root-variable"></i> Results &amp; Calculations</h2>'
            '    <span class="section-sub">Step-by-step breakdown of every check that ran</span>'
            '  </div>'
            f'  {calc_html}'
            '</section>'
        )
    else:
        calc_section = ""

    return (
        f'<div class="scenario-card {tone_cls}">'
        f'  <div class="scenario-shine"></div>'
        f'  <div class="scenario-head">'
        f'    <div class="scenario-ident">'
        f'      <div class="scenario-meta-row">'
        f'        <span class="tc-chip"><i class="fa-solid fa-hashtag"></i> Test Case {_esc(num)}</span>'
        f'        <span class="tc-chip tc-id"><i class="fa-solid fa-fingerprint"></i> {_esc(tc_id)}</span>'
        f'      </div>'
        f'      <h1 class="scenario-title">{_esc(name) or "Unnamed Scenario"}</h1>'
        f'      <div class="scenario-micro">'
        f'        <span><i class="fa-regular fa-clock"></i> {_esc(ts)}</span>'
        f'        <span><i class="fa-solid fa-gauge-high"></i> Launch {launch_str}</span>'
        f'      </div>'
        f'    </div>'
        f'    <div class="scenario-overall">{overall_badge}</div>'
        f'  </div>'
        f'  <div class="role-grid">'
        f'    {c_panel}'
        f'    {b_panel}'
        f'  </div>'
        f'  {calc_section}'
        f'</div>'
    )


def _format_reason_cell(r):
    """Short formatted reason for history table cell."""
    if not r.get("error") and not r.get("reasons"):
        return "—"
    err = r.get("error") or "; ".join(r.get("reasons", []))
    # Multi-line formatting
    parts = [p.strip() for p in re.split(r';\s*|\|\s*', err) if p.strip()]
    if not parts:
        return _esc(err)
    return "<br>".join(f'<span class="err-line">{_esc(p)}</span>' for p in parts)


def _build_history_groups(history):
    """Group history rows by date (YYYY-MM-DD) into collapsible <details> sections."""
    if not history:
        return (
            '<div class="empty-state small">'
            '  <i class="fa-regular fa-folder-open"></i>'
            '  <p>No scenarios in history yet.</p>'
            '</div>'
        )

    groups = OrderedDict()
    for r in history:
        ts = r.get("timestamp", "") or ""
        date_key = ts[:10] if len(ts) >= 10 else "Undated"
        groups.setdefault(date_key, []).append(r)

    html_parts = []
    first = True
    for date_key, rows in groups.items():
        pass_n = sum(1 for r in rows if r.get("status") == "PASS")
        fail_n = sum(1 for r in rows if r.get("status") == "FAIL")
        row_html = ""
        for r in rows:
            st = r.get("status", "PASS")
            bg = "row-pass" if st == "PASS" else "row-fail"
            badge = _status_badge(st)
            c_badge = _status_badge(r.get("consumer_status", "N/A"))
            b_badge = _status_badge(r.get("business_status", "N/A"))
            reason_cell = _format_reason_cell(r)
            ts = _esc(r.get("timestamp", ""))
            launch_str = f'{r["launch_time"]:.2f}s' if r.get("launch_time") is not None else "—"
            num = r.get("num", "")
            tc_id = _tc_id(num)
            row_html += (
                f'<tr class="{bg}">'
                f'  <td><span class="scenario-id">{_esc(num)}</span></td>'
                f'  <td class="name-cell">{_esc(r.get("name", ""))}</td>'
                f'  <td class="tcid-cell">{_esc(tc_id)}</td>'
                f'  <td>{badge}</td>'
                f'  <td>{c_badge}</td>'
                f'  <td>{b_badge}</td>'
                f'  <td class="error-cell">{reason_cell}</td>'
                f'  <td class="time-cell">{launch_str}</td>'
                f'  <td class="time-cell">{ts}</td>'
                f'</tr>'
            )
        open_attr = " open" if first else ""
        first = False
        html_parts.append(
            f'<details class="date-group"{open_attr}>'
            f'  <summary class="date-summary">'
            f'    <div class="date-summary-left">'
            f'      <i class="fa-solid fa-calendar-day"></i>'
            f'      <span class="date-label">{_esc(date_key)}</span>'
            f'      <span class="date-count">{len(rows)} scenarios</span>'
            f'    </div>'
            f'    <div class="date-summary-right">'
            f'      <span class="mini-chip mini-pass"><i class="fa-solid fa-check"></i> {pass_n}</span>'
            f'      <span class="mini-chip mini-fail"><i class="fa-solid fa-xmark"></i> {fail_n}</span>'
            f'      <i class="fa-solid fa-chevron-down chev"></i>'
            f'    </div>'
            f'  </summary>'
            f'  <div class="table-container">'
            f'    <table>'
            f'      <thead>'
            f'        <tr>'
            f'          <th>TC #</th><th>Name</th><th>TC ID</th>'
            f'          <th>Status</th><th>Consumer</th><th>Business</th>'
            f'          <th>Reason / Error</th><th>Launch</th><th>Timestamp</th>'
            f'        </tr>'
            f'      </thead>'
            f'      <tbody>{row_html}</tbody>'
            f'    </table>'
            f'  </div>'
            f'</details>'
        )

    return "\n".join(html_parts)


# ── HTML generation ──────────────────────────────────────────────────────

def _write_html(data=None):
    if data is None:
        data = _load_data()
        if _current_result:
            data["current"] = dict(_current_result)

    current = data.get("current")
    history = data.get("history", [])

    if not current and history:
        current = history[0]

    all_session = []
    if _current_result:
        all_session.append(_current_result)
    all_session.extend(_session_history)
    if not all_session and history:
        all_session = list(history)
    passed = sum(1 for r in all_session if r["status"] == "PASS")
    failed = sum(1 for r in all_session if r["status"] == "FAIL")
    total = len(all_session)
    pass_pct = round(passed / total * 100) if total > 0 else 0

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    home_content = _build_home_card(current)
    history_content = _build_history_groups(history)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vyapy Scenarios | Dashboard</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    <style>
        :root {{
            --bg-0: #03000a;
            --bg-1: #07021a;
            --bg-2: #0c0428;
            --surface: rgba(15, 5, 40, 0.55);
            --surface-solid: #0c0428;
            --surface-strong: rgba(25, 8, 60, 0.78);
            --surface-hi: rgba(40, 14, 90, 0.85);
            --border: rgba(255, 0, 234, 0.15);
            --border-strong: rgba(0, 255, 240, 0.42);
            --neon:   #ff00ea;          /* magenta  */
            --neon-2: #00fff0;          /* cyan     */
            --neon-3: #00ff88;          /* terminal green */
            --neon-4: #fff200;          /* yellow   */
            --neon-5: #b537ff;          /* violet   */
            --ok: #00ff88;
            --ok-soft: rgba(0, 255, 136, 0.14);
            --ok-edge: rgba(0, 255, 136, 0.55);
            --bad: #ff2e63;
            --bad-soft: rgba(255, 46, 99, 0.14);
            --bad-edge: rgba(255, 46, 99, 0.55);
            --warn: #fff200;
            --warn-soft: rgba(255, 242, 0, 0.14);
            --text: #ffffff;
            --text-dim: #c7b8e6;
            --text-muted: #6b5a8c;
            --glow-mag: 0 0 12px rgba(255,0,234,0.55), 0 0 24px rgba(255,0,234,0.35);
            --glow-cyn: 0 0 12px rgba(0,255,240,0.55), 0 0 24px rgba(0,255,240,0.35);
            --glow-grn: 0 0 12px rgba(0,255,136,0.55), 0 0 24px rgba(0,255,136,0.35);
            --shadow-lg: 0 30px 70px -18px rgba(0,0,0,0.85), 0 0 60px -10px rgba(255,0,234,0.25), 0 0 80px -15px rgba(0,255,240,0.18);
        }}

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        html, body {{ height: 100%; }}

        body {{
            font-family: 'Inter', 'Space Grotesk', system-ui, sans-serif;
            color: var(--text);
            background: var(--bg-0);
            min-height: 100vh;
            padding: 2rem;
            line-height: 1.55;
            overflow-x: hidden;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
            position: relative;
        }}
        /* Matrix rain canvas */
        #matrix-bg {{
            position: fixed; top: 0; left: 0;
            width: 100vw; height: 100vh;
            z-index: 0; opacity: 0.32;
            pointer-events: none;
            mix-blend-mode: screen;
        }}
        /* Mesh gradient + radial glows */
        body::before {{
            content: "";
            position: fixed; inset: 0;
            background-image:
                radial-gradient(900px 600px at 5% -10%, rgba(255,0,234,0.32), transparent 60%),
                radial-gradient(800px 600px at 95% 5%, rgba(0,255,240,0.28), transparent 60%),
                radial-gradient(700px 500px at 50% 110%, rgba(181,55,255,0.28), transparent 60%),
                radial-gradient(600px 400px at 90% 90%, rgba(0,255,136,0.18), transparent 60%);
            pointer-events: none; z-index: 0;
            animation: meshDrift 22s ease-in-out infinite alternate;
        }}
        /* Scanlines + grid overlay */
        body::after {{
            content: "";
            position: fixed; inset: 0;
            background-image:
                repeating-linear-gradient(
                    0deg,
                    rgba(0,255,240,0.03) 0px, rgba(0,255,240,0.03) 1px,
                    transparent 1px, transparent 3px
                ),
                linear-gradient(rgba(255,0,234,0.05) 1px, transparent 1px),
                linear-gradient(90deg, rgba(0,255,240,0.05) 1px, transparent 1px);
            background-size: 100% 3px, 60px 60px, 60px 60px;
            mask-image: radial-gradient(ellipse 90% 70% at 50% 40%, #000 25%, transparent 100%);
            pointer-events: none; z-index: 0;
            animation: scanMove 8s linear infinite;
        }}

        .container {{ max-width: 1440px; margin: 0 auto; position: relative; z-index: 1; }}

        /* ── Header ───────────────────────────────────────── */
        header {{
            display: flex; justify-content: space-between; align-items: center;
            gap: 1.5rem; flex-wrap: wrap;
            margin-bottom: 2rem;
            animation: fadeDown 0.7s cubic-bezier(.2,.8,.2,1) both;
        }}
        .brand {{ display: flex; align-items: center; gap: 1rem; }}
        .brand-orb {{
            width: 56px; height: 56px; border-radius: 16px;
            position: relative;
            background: conic-gradient(from 0deg,
                #ff00ea, #00fff0, #00ff88, #fff200, #b537ff, #ff00ea);
            display: grid; place-items: center;
            box-shadow:
                0 0 30px rgba(255,0,234,0.6),
                0 0 60px rgba(0,255,240,0.4),
                inset 0 0 20px rgba(255,255,255,0.15);
            animation: spin 5s linear infinite;
        }}
        .brand-orb::before {{
            content: ""; position: absolute; inset: 4px;
            border-radius: 12px; background: var(--bg-0);
            box-shadow: inset 0 0 25px rgba(255,0,234,0.45), inset 0 0 50px rgba(0,255,240,0.2);
        }}
        .brand-orb::after {{
            content: ""; position: absolute; inset: -4px;
            border-radius: 18px;
            background: conic-gradient(from 90deg, #ff00ea, #00fff0, #00ff88, #ff00ea);
            z-index: -1; opacity: 0.5; filter: blur(12px);
            animation: spin 8s linear infinite reverse;
        }}
        .brand-orb i {{
            position: relative; z-index: 2;
            color: #fff; font-size: 1.3rem;
            text-shadow:
                0 0 8px var(--neon),
                0 0 16px var(--neon-2),
                -1px 0 0 var(--neon), 1px 0 0 var(--neon-2);
            animation: glitchHue 6s linear infinite;
        }}
        .brand h1 {{
            font-size: 2.4rem; font-weight: 700; letter-spacing: -0.02em;
            background: linear-gradient(110deg,
                #ff00ea 0%, #b537ff 25%, #00fff0 55%, #00ff88 80%, #ff00ea 100%);
            background-size: 250% 100%;
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
            background-clip: text;
            filter: drop-shadow(0 0 14px rgba(255,0,234,0.5)) drop-shadow(0 0 22px rgba(0,255,240,0.4));
            animation: gradientShift 8s ease infinite, titleGlitch 7s steps(1) infinite;
            position: relative;
        }}
        .brand h1::after {{
            content: "_";
            margin-left: 0.2rem;
            color: var(--neon-2);
            -webkit-text-fill-color: var(--neon-2);
            text-shadow: 0 0 10px var(--neon-2);
            animation: caretBlink 1s steps(1) infinite;
        }}
        .brand p {{
            color: var(--neon-2); font-size: 0.78rem; letter-spacing: 0.18em;
            text-transform: uppercase; margin-top: 4px;
            text-shadow: 0 0 8px rgba(0,255,240,0.5);
            font-family: 'JetBrains Mono', monospace;
        }}
        .brand p::before {{ content: "> "; color: var(--neon-3); }}

        .status-strip {{
            display: inline-flex; align-items: center; gap: 0.85rem;
            padding: 0.65rem 1.15rem; border-radius: 999px;
            background: rgba(15,5,40,0.65); backdrop-filter: blur(14px);
            border: 1px solid var(--border-strong);
            font-size: 0.8rem; color: var(--text);
            box-shadow: 0 0 20px rgba(0,255,240,0.25), inset 0 0 18px rgba(255,0,234,0.05);
            font-family: 'JetBrains Mono', monospace;
            position: relative; overflow: hidden;
            transition: transform .25s, box-shadow .25s;
        }}
        .status-strip::before {{
            content: ""; position: absolute; inset: 0;
            background: linear-gradient(90deg, transparent, rgba(0,255,240,0.15), transparent);
            transform: translateX(-100%);
            animation: stripScan 4s linear infinite;
        }}
        .status-strip:hover {{ box-shadow: 0 0 28px rgba(0,255,240,0.4), inset 0 0 22px rgba(255,0,234,0.1); }}
        .pulse-dot {{
            width: 9px; height: 9px; border-radius: 50%;
            background: var(--ok); position: relative;
            box-shadow: 0 0 10px var(--ok), 0 0 18px var(--ok);
        }}
        .pulse-dot::after {{
            content: ""; position: absolute; inset: 0; border-radius: 50%;
            background: var(--ok);
            animation: pulseRing 1.6s ease-out infinite;
        }}
        .status-strip .sep {{ color: var(--neon); opacity: 0.7; }}
        .status-strip .mono {{ font-family: 'JetBrains Mono', monospace; color: var(--neon-2); text-shadow: 0 0 8px rgba(0,255,240,0.6); }}

        /* ── Stats ───────────────────────────────────────── */
        .stats {{
            display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 1.1rem; margin-bottom: 2rem;
        }}
        .stat {{
            position: relative; overflow: hidden;
            padding: 1.4rem 1.5rem; border-radius: 18px;
            background: rgba(15,5,40,0.55); backdrop-filter: blur(14px);
            border: 1px solid var(--border);
            transition: transform .35s cubic-bezier(.2,.8,.2,1),
                        box-shadow .35s, background .35s;
            opacity: 0; transform: translateY(20px) scale(.96);
            animation: statIn 0.7s cubic-bezier(.2,.8,.2,1) forwards;
            transform-style: preserve-3d; perspective: 800px;
        }}
        .stat:nth-child(1) {{ animation-delay: 0.05s; }}
        .stat:nth-child(2) {{ animation-delay: 0.16s; }}
        .stat:nth-child(3) {{ animation-delay: 0.27s; }}
        .stat:nth-child(4) {{ animation-delay: 0.38s; }}
        /* Animated rotating gradient ring */
        .stat::before {{
            content: ""; position: absolute; inset: -2px;
            border-radius: 18px;
            background: conic-gradient(from var(--ang, 0deg),
                transparent 0deg, var(--neon) 40deg, transparent 80deg,
                transparent 180deg, var(--neon-2) 220deg, transparent 260deg);
            z-index: -1;
            animation: spin 6s linear infinite;
            opacity: 0;
            transition: opacity .35s;
        }}
        .stat:hover::before {{ opacity: 0.85; }}
        /* Inner mask so only the border shows */
        .stat::after {{
            content: ""; position: absolute; inset: 1px;
            border-radius: 17px;
            background: rgba(7,2,26,0.94);
            z-index: -1;
        }}
        .stat:hover {{
            transform: translateY(-6px) rotateX(2deg) rotateY(-2deg);
            box-shadow: 0 25px 50px -15px rgba(0,0,0,0.7),
                        0 0 30px rgba(255,0,234,0.35),
                        0 0 50px rgba(0,255,240,0.25);
        }}
        .stat .label {{
            display: inline-flex; align-items: center; gap: 0.55rem;
            text-transform: uppercase; letter-spacing: 0.14em;
            font-size: 0.7rem; color: var(--text-dim); font-weight: 600;
            font-family: 'JetBrains Mono', monospace;
        }}
        .stat .label::before {{
            content: "▸"; color: var(--neon); font-size: 0.85rem;
            text-shadow: 0 0 8px var(--neon);
            animation: blink 1.4s ease-in-out infinite;
        }}
        .stat.total .label {{ color: #ffb8f7; }}
        .stat.total .label::before {{ color: var(--neon); text-shadow: 0 0 12px var(--neon); }}
        .stat.pass  .label {{ color: #b8ffd7; }}
        .stat.pass  .label::before {{ color: var(--ok); text-shadow: 0 0 12px var(--ok); }}
        .stat.fail  .label {{ color: #ffb8c8; }}
        .stat.fail  .label::before {{ color: var(--bad); text-shadow: 0 0 12px var(--bad); }}
        .stat.rate  .label {{ color: #fff8a8; }}
        .stat.rate  .label::before {{ color: var(--warn); text-shadow: 0 0 12px var(--warn); }}
        .stat .value {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 3rem; font-weight: 700;
            margin-top: 0.4rem;
            letter-spacing: -0.02em;
            background: linear-gradient(180deg, #ffffff 0%, var(--neon-2) 100%);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
            background-clip: text;
            filter: drop-shadow(0 0 10px rgba(0,255,240,0.5));
            position: relative;
        }}
        .stat.total .value {{
            background: linear-gradient(180deg, #fff, var(--neon));
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
            filter: drop-shadow(0 0 10px rgba(255,0,234,0.55));
        }}
        .stat.pass .value {{
            background: linear-gradient(180deg, #fff, var(--ok));
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
            filter: drop-shadow(0 0 10px rgba(0,255,136,0.55));
        }}
        .stat.fail .value {{
            background: linear-gradient(180deg, #fff, var(--bad));
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
            filter: drop-shadow(0 0 10px rgba(255,46,99,0.55));
        }}
        .stat.rate .value {{
            background: linear-gradient(180deg, #fff, var(--warn));
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
            filter: drop-shadow(0 0 10px rgba(255,242,0,0.55));
        }}
        .stat .bar {{
            margin-top: 1rem; height: 4px; border-radius: 999px;
            background: rgba(255,255,255,0.06); overflow: hidden;
            position: relative;
        }}
        .stat .bar span {{
            display: block; height: 100%;
            background: linear-gradient(90deg, var(--neon), var(--neon-2));
            box-shadow: 0 0 10px var(--neon), 0 0 18px var(--neon-2);
            animation: barFill 1.1s 0.5s cubic-bezier(.2,.8,.2,1) both;
            transform-origin: left;
            position: relative;
        }}
        .stat .bar span::after {{
            content: ""; position: absolute; right: 0; top: -2px;
            width: 8px; height: 8px; border-radius: 50%;
            background: #fff; box-shadow: 0 0 12px #fff, 0 0 20px var(--neon-2);
            animation: barTip 2s ease-in-out infinite;
        }}
        .stat.pass .bar span {{ background: linear-gradient(90deg, var(--ok), #4ade80); box-shadow: 0 0 10px var(--ok); }}
        .stat.fail .bar span {{ background: linear-gradient(90deg, var(--bad), #ff8aa6); box-shadow: 0 0 10px var(--bad); }}
        .stat.rate .bar span {{ background: linear-gradient(90deg, var(--warn), #ffec5c); box-shadow: 0 0 10px var(--warn); }}

        /* ── Tabs ───────────────────────────────────────── */
        .tabs {{
            display: inline-flex; gap: 4px; padding: 5px; border-radius: 14px;
            background: rgba(15,5,40,0.6); backdrop-filter: blur(12px);
            border: 1px solid var(--border-strong);
            margin-bottom: 1.8rem;
            box-shadow: 0 0 22px rgba(0,255,240,0.15), inset 0 0 18px rgba(255,0,234,0.05);
        }}
        .tab-btn {{
            position: relative; overflow: hidden;
            padding: 0.85rem 1.45rem; border: 0; cursor: pointer;
            background: transparent; color: var(--text-dim);
            font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; font-weight: 600;
            border-radius: 10px; letter-spacing: 0.08em;
            text-transform: uppercase;
            transition: color .25s ease, text-shadow .25s ease;
            z-index: 1;
        }}
        .tab-btn:hover {{ color: var(--neon-2); text-shadow: 0 0 10px var(--neon-2); }}
        .tab-btn i {{ margin-right: 0.5rem; font-size: 0.85rem; }}
        .tab-btn.active {{
            color: #fff;
            background: linear-gradient(135deg, var(--neon) 0%, var(--neon-5) 50%, var(--neon-2) 100%);
            background-size: 200% 200%;
            box-shadow:
                0 0 22px rgba(255,0,234,0.6),
                0 0 40px rgba(0,255,240,0.4),
                inset 0 1px 0 rgba(255,255,255,0.2);
            text-shadow: 0 1px 6px rgba(0,0,0,0.4);
            animation: tabPop 0.4s cubic-bezier(.2,.8,.2,1), gradientShift 4s ease infinite;
        }}
        .tab-btn.active::before {{
            content: ""; position: absolute; inset: 0;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent);
            transform: translateX(-100%);
            animation: tabSweep 2.5s ease-in-out infinite;
        }}
        .tab-content {{ display: none; }}
        .tab-content.active {{
            display: block;
            animation: fadeUp 0.5s cubic-bezier(.2,.8,.2,1) both;
        }}

        /* ── Scenario Card (HOME) ───────────────────────────────────────── */
        .scenario-card {{
            position: relative; padding: 2.2rem; border-radius: 22px;
            background: rgba(7,2,26,0.7); backdrop-filter: blur(20px);
            border: 1px solid var(--border-strong);
            box-shadow: var(--shadow-lg);
            overflow: hidden;
            animation: cardIn 0.7s cubic-bezier(.2,.8,.2,1) both;
            transform-style: preserve-3d; perspective: 1200px;
            transition: transform .4s cubic-bezier(.2,.8,.2,1), box-shadow .4s;
        }}
        /* Scanlines overlay on the card */
        .scenario-card::before {{
            content: ""; position: absolute; inset: 0;
            background: repeating-linear-gradient(
                0deg, rgba(0,255,240,0.04) 0, rgba(0,255,240,0.04) 1px,
                transparent 1px, transparent 4px);
            pointer-events: none;
            mix-blend-mode: overlay;
        }}
        /* Animated rotating border ring */
        .scenario-card::after {{
            content: ""; position: absolute; inset: -1px;
            border-radius: 22px;
            background: conic-gradient(from var(--ang, 0deg),
                var(--neon) 0deg, transparent 90deg, transparent 180deg,
                var(--neon-2) 270deg, transparent 360deg);
            z-index: -1; opacity: 0.7;
            animation: spin 8s linear infinite;
            filter: blur(2px);
        }}
        .scenario-card.tone-pass {{
            box-shadow: var(--shadow-lg),
                0 0 50px -10px rgba(0,255,136,0.55),
                inset 0 0 70px rgba(0,255,136,0.06);
            border-color: rgba(0,255,136,0.4);
        }}
        .scenario-card.tone-fail {{
            box-shadow: var(--shadow-lg),
                0 0 50px -10px rgba(255,46,99,0.6),
                inset 0 0 70px rgba(255,46,99,0.06);
            border-color: rgba(255,46,99,0.4);
        }}
        .scenario-shine {{
            position: absolute; top: -50%; left: -30%;
            width: 60%; height: 200%;
            background: linear-gradient(90deg, transparent, rgba(0,255,240,0.18), transparent);
            transform: rotate(20deg);
            animation: cardShine 4.5s ease-in-out infinite;
            pointer-events: none;
        }}
        .scenario-head {{
            display: flex; justify-content: space-between; align-items: flex-start;
            gap: 1.3rem; flex-wrap: wrap; margin-bottom: 1.7rem;
            position: relative; z-index: 2;
        }}
        .scenario-meta-row {{ display: flex; gap: 0.55rem; flex-wrap: wrap; margin-bottom: 0.85rem; }}
        .tc-chip {{
            display: inline-flex; align-items: center; gap: 0.4rem;
            padding: 0.4rem 0.95rem; border-radius: 999px;
            font-size: 0.74rem; font-weight: 600;
            background: rgba(255,0,234,0.12); color: #ffb8f7;
            border: 1px solid rgba(255,0,234,0.42);
            box-shadow: 0 0 16px -4px rgba(255,0,234,0.5);
            font-family: 'JetBrains Mono', monospace;
            text-shadow: 0 0 8px rgba(255,0,234,0.55);
            transition: transform .2s, box-shadow .25s;
        }}
        .tc-chip:hover {{ transform: translateY(-2px); box-shadow: 0 0 24px -2px rgba(255,0,234,0.7); }}
        .tc-chip i {{ opacity: 0.85; }}
        .tc-chip.tc-id {{
            background: rgba(0,255,240,0.10); color: #aef9ff;
            border-color: rgba(0,255,240,0.45);
            box-shadow: 0 0 16px -4px rgba(0,255,240,0.55);
            text-shadow: 0 0 8px rgba(0,255,240,0.55);
        }}
        .tc-chip.tc-id:hover {{ box-shadow: 0 0 24px -2px rgba(0,255,240,0.7); }}
        .scenario-title {{
            font-size: 1.85rem; font-weight: 700; letter-spacing: -0.015em;
            line-height: 1.18;
            background: linear-gradient(135deg, #fff 0%, var(--neon-2) 100%);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
            filter: drop-shadow(0 0 12px rgba(0,255,240,0.3));
        }}
        .scenario-micro {{
            margin-top: 0.65rem; display: flex; gap: 1.2rem; flex-wrap: wrap;
            color: var(--text-dim); font-size: 0.8rem;
            font-family: 'JetBrains Mono', monospace;
        }}
        .scenario-micro span {{ position: relative; padding-left: 0.2rem; }}
        .scenario-micro i {{ margin-right: 0.4rem; color: var(--neon-3); text-shadow: 0 0 8px var(--neon-3); }}
        .scenario-overall {{ flex-shrink: 0; }}

        /* ── Role grid ───────────────────────────────────────── */
        .role-grid {{
            display: grid; grid-template-columns: 1fr 1fr;
            gap: 1rem; margin-bottom: 1.6rem;
        }}
        .reason-panel {{
            position: relative; overflow: hidden;
            padding: 1.2rem 1.3rem; border-radius: 14px;
            background: rgba(7,2,26,0.7);
            border: 1px solid var(--border);
            transition: transform .3s, box-shadow .3s, border-color .3s;
            animation: fadeUp 0.6s 0.15s cubic-bezier(.2,.8,.2,1) both;
        }}
        .reason-panel::before {{
            content: ""; position: absolute; top: 0; left: 0; bottom: 0; width: 3px;
            background: var(--neon); box-shadow: 0 0 10px var(--neon);
        }}
        .reason-panel.tone-pass::before {{ background: var(--ok); box-shadow: 0 0 14px var(--ok); }}
        .reason-panel.tone-fail::before {{ background: var(--bad); box-shadow: 0 0 14px var(--bad); }}
        .reason-panel:hover {{
            transform: translateY(-3px);
            box-shadow: 0 12px 28px -8px rgba(0,0,0,0.6), 0 0 24px -8px var(--neon-2);
            border-color: var(--border-strong);
        }}
        .reason-panel.tone-pass {{ box-shadow: 0 0 22px -10px rgba(0,255,136,0.5); }}
        .reason-panel.tone-fail {{ box-shadow: 0 0 22px -10px rgba(255,46,99,0.5); }}
        .reason-head {{
            display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 0.95rem;
        }}
        .reason-role {{
            font-size: 0.92rem; font-weight: 600;
            color: var(--text);
            font-family: 'JetBrains Mono', monospace;
            letter-spacing: 0.05em;
        }}
        .reason-role i {{ color: var(--neon-2); margin-right: 0.45rem; text-shadow: 0 0 8px var(--neon-2); }}
        .reason-list {{ list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.4rem; }}
        .reason-list li {{
            color: var(--text-dim); font-size: 0.84rem; line-height: 1.5;
            padding: 0.5rem 0.7rem; border-radius: 8px;
            background: rgba(0,255,240,0.03);
            border-left: 2px solid var(--neon);
            font-family: 'JetBrains Mono', monospace;
            transition: background .2s, transform .2s, border-color .2s, color .2s;
        }}
        .reason-list li:hover {{
            background: rgba(0,255,240,0.07);
            transform: translateX(4px);
            color: var(--text);
        }}
        .reason-list li i {{ color: var(--neon-2); margin-right: 0.4rem; font-size: 0.7rem; }}
        .reason-list li::before {{
            content: "$ "; color: var(--neon-3); font-weight: 700;
            text-shadow: 0 0 8px var(--neon-3);
        }}
        .tone-fail .reason-list li {{ border-left-color: var(--bad); background: rgba(255,46,99,0.04); }}
        .tone-pass .reason-list li {{ border-left-color: var(--ok); background: rgba(0,255,136,0.04); }}
        .reason-empty {{ color: var(--text-muted); font-size: 0.84rem; font-family: 'JetBrains Mono', monospace; }}
        .reason-empty::before {{ content: "// "; color: var(--neon); }}
        .reason-empty i {{ margin-right: 0.35rem; }}

        /* ── Calculations (terminal style) ───────────────────────── */
        .calc-section {{
            padding: 1.5rem 1.4rem 1.2rem;
            border-radius: 16px;
            background: linear-gradient(180deg, rgba(7,2,26,0.85), rgba(15,5,40,0.6));
            border: 1px solid var(--border-strong);
            box-shadow: 0 0 30px -8px rgba(0,255,240,0.2), inset 0 0 40px rgba(255,0,234,0.04);
            animation: fadeUp 0.6s 0.2s cubic-bezier(.2,.8,.2,1) both;
            position: relative;
        }}
        .calc-section::before {{
            content: "● ● ●";
            position: absolute; top: 0.85rem; left: 1.4rem;
            color: var(--bad); font-size: 0.6rem; letter-spacing: 0.4em;
            opacity: 0.6;
        }}
        .section-head {{ margin-bottom: 1.1rem; padding-top: 0.4rem; }}
        .section-head h2 {{
            font-size: 1.05rem; font-weight: 700; letter-spacing: 0.04em;
            color: var(--text); display: flex; align-items: center; gap: 0.55rem;
            font-family: 'JetBrains Mono', monospace;
            text-transform: uppercase;
        }}
        .section-head h2 i {{ color: var(--neon); text-shadow: 0 0 12px var(--neon); }}
        .section-sub {{
            display: block; margin-top: 0.3rem;
            color: var(--neon-3); font-size: 0.78rem;
            font-family: 'JetBrains Mono', monospace;
        }}
        .section-sub::before {{ content: "// "; color: var(--text-muted); }}
        .calc-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(290px, 1fr)); gap: 0.9rem; }}
        .calc-block {{
            padding: 1.1rem 1.15rem; border-radius: 12px;
            background: rgba(2,0,12,0.85);
            border: 1px solid var(--border);
            transition: transform .3s cubic-bezier(.2,.8,.2,1),
                        box-shadow .3s, border-color .3s;
            animation: fadeUp 0.5s cubic-bezier(.2,.8,.2,1) both;
            position: relative; overflow: hidden;
        }}
        .calc-block::before {{
            content: ""; position: absolute; top: 0; left: -100%;
            width: 100%; height: 2px;
            background: linear-gradient(90deg, transparent, var(--neon-2), transparent);
            box-shadow: 0 0 8px var(--neon-2);
            transition: left .8s ease;
        }}
        .calc-block:hover::before {{ left: 100%; }}
        .calc-block:hover {{
            transform: translateY(-3px);
            border-color: var(--neon-2);
            box-shadow: 0 12px 28px -10px rgba(0,0,0,0.65), 0 0 24px -8px var(--neon-2);
        }}
        .calc-head {{
            display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 0.8rem; gap: 0.5rem;
        }}
        .calc-title {{
            font-size: 0.9rem; font-weight: 600; color: var(--text);
            display: flex; align-items: center; gap: 0.5rem;
            font-family: 'JetBrains Mono', monospace;
            letter-spacing: 0.03em;
        }}
        .calc-title i {{ color: var(--neon); font-size: 0.85rem; text-shadow: 0 0 10px var(--neon); }}
        .calc-system {{
            font-size: 0.7rem; padding: 0.25rem 0.65rem; border-radius: 999px;
            background: rgba(255,242,0,0.12); color: var(--neon-4);
            border: 1px solid rgba(255,242,0,0.45);
            box-shadow: 0 0 14px -4px rgba(255,242,0,0.6);
            text-shadow: 0 0 8px rgba(255,242,0,0.55);
            font-family: 'JetBrains Mono', monospace;
        }}
        .calc-system i {{ margin-right: 0.3rem; }}
        .calc-steps {{
            list-style: none; padding: 0; margin: 0 0 0.5rem;
            display: flex; flex-direction: column; gap: 0.35rem;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.82rem;
        }}
        .calc-step {{
            display: flex; gap: 0.6rem; align-items: flex-start;
            padding: 0.4rem 0.6rem; border-radius: 7px;
            background: rgba(0,255,240,0.025);
            color: var(--text-dim);
            transition: background .2s, color .2s, transform .2s;
            border-left: 2px solid transparent;
        }}
        .calc-step:hover {{
            background: rgba(0,255,240,0.06);
            color: var(--text);
            transform: translateX(3px);
            border-left-color: var(--neon-2);
        }}
        .calc-step .step-bullet {{
            color: var(--neon); font-weight: 700; min-width: 14px;
            text-shadow: 0 0 8px var(--neon);
        }}
        .calc-step.calc-result {{
            background: linear-gradient(90deg, rgba(0,255,136,0.16), rgba(0,255,136,0.04));
            color: #c8ffd9;
            border: 1px solid rgba(0,255,136,0.4);
            box-shadow: inset 0 0 18px rgba(0,255,136,0.06);
            font-weight: 600;
        }}
        .calc-step.calc-result .step-bullet {{ color: var(--ok); text-shadow: 0 0 10px var(--ok); }}
        .calc-raw {{
            margin-top: 0.55rem; padding-top: 0.55rem;
            border-top: 1px dashed rgba(255,0,234,0.18);
            font-size: 0.7rem; color: var(--text-muted);
            font-family: 'JetBrains Mono', monospace;
            word-break: break-word;
        }}
        .calc-raw::before {{ content: "raw> "; color: var(--neon); }}

        /* ── Empty state ───────────────────────────────────────── */
        .empty-state {{
            position: relative; padding: 4rem 2rem; text-align: center;
            border-radius: 16px; background: var(--surface);
            border: 1px dashed var(--border-strong);
            overflow: hidden;
            animation: fadeUp 0.5s ease both;
        }}
        .empty-state.small {{ padding: 2.5rem 1.5rem; }}
        .empty-state h3 {{
            font-size: 1.1rem; font-weight: 600; color: var(--text);
            margin-bottom: 0.4rem;
        }}
        .empty-state p {{ color: var(--text-dim); font-size: 0.85rem; max-width: 420px; margin: 0 auto; }}
        .empty-state > i {{
            font-size: 1.7rem; color: var(--text-muted);
            margin-bottom: 0.8rem; display: block;
            animation: floatY 3s ease-in-out infinite;
        }}
        .empty-orb {{
            width: 90px; height: 90px; border-radius: 50%;
            margin: 0 auto 1rem;
            background: radial-gradient(circle at 35% 35%, rgba(99,102,241,0.7), transparent 65%),
                        radial-gradient(circle at 70% 70%, rgba(139,92,246,0.5), transparent 65%);
            filter: blur(14px); opacity: 0.55;
            animation: orbPulse 3.2s ease-in-out infinite;
        }}

        /* ── Badges (heavy neon) ───────────────────────────────────────── */
        .badge {{
            display: inline-flex; align-items: center; gap: 0.45rem;
            padding: 0.35rem 0.85rem; border-radius: 999px;
            font-size: 0.7rem; font-weight: 700;
            text-transform: uppercase; letter-spacing: 0.1em;
            line-height: 1;
            font-family: 'JetBrains Mono', monospace;
            backdrop-filter: blur(8px);
            transition: transform .25s, box-shadow .25s;
        }}
        .badge:hover {{ transform: translateY(-2px) scale(1.04); }}
        .badge i {{
            font-size: 0; width: 7px; height: 7px; border-radius: 50%;
            background: currentColor; display: inline-block;
            box-shadow: 0 0 8px currentColor, 0 0 14px currentColor;
        }}
        .badge-pass {{
            background: rgba(0,255,136,0.12); color: var(--ok);
            border: 1px solid var(--ok-edge);
            text-shadow: 0 0 8px rgba(0,255,136,0.7);
            box-shadow: 0 0 14px -4px rgba(0,255,136,0.55);
        }}
        .badge-fail {{
            background: rgba(255,46,99,0.12); color: var(--bad);
            border: 1px solid var(--bad-edge);
            text-shadow: 0 0 8px rgba(255,46,99,0.7);
            box-shadow: 0 0 14px -4px rgba(255,46,99,0.6);
        }}
        .badge-na   {{
            background: rgba(180,180,210,0.06); color: var(--text-dim);
            border: 1px solid rgba(180,180,210,0.2);
        }}
        .badge-lg  {{ font-size: 0.78rem; padding: 0.45rem 1rem; }}
        .badge-xl  {{
            font-size: 0.92rem; padding: 0.6rem 1.3rem;
            font-weight: 700; letter-spacing: 0.14em;
            box-shadow: 0 0 30px -4px currentColor, inset 0 0 18px rgba(255,255,255,0.05);
            animation: badgeGlow 2.4s ease-in-out infinite;
        }}
        .badge-xl i {{ width: 10px; height: 10px; box-shadow: 0 0 10px currentColor, 0 0 18px currentColor; }}
        .badge-xl.badge-pass i, .badge-pass.badge-xl i {{ animation: dotPulse 1.6s ease-in-out infinite; }}
        .badge-xl.badge-fail i, .badge-fail.badge-xl i {{ animation: dotPulse 1.4s ease-in-out infinite; }}

        /* ── History ───────────────────────────────────────── */
        .date-group {{
            margin-bottom: 0.85rem;
            background: var(--surface);
            border: 1px solid var(--border); border-radius: 12px;
            overflow: hidden;
            animation: fadeUp 0.5s ease both;
        }}
        .date-group[open] {{ border-color: var(--border-strong); }}
        .date-summary {{
            list-style: none; cursor: pointer;
            padding: 0.9rem 1.2rem;
            display: flex; justify-content: space-between; align-items: center;
            transition: background .2s;
        }}
        .date-summary::-webkit-details-marker {{ display: none; }}
        .date-summary:hover {{ background: var(--surface-strong); }}
        .date-summary-left {{ display: flex; align-items: center; gap: 0.7rem; }}
        .date-summary-left i {{ color: var(--text-muted); font-size: 0.85rem; }}
        .date-label {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.9rem; font-weight: 500; color: var(--text);
        }}
        .date-count {{
            font-size: 0.7rem; color: var(--text-muted);
            padding: 0.18rem 0.5rem; border-radius: 999px;
            background: var(--surface-strong);
            border: 1px solid var(--border);
        }}
        .date-summary-right {{ display: flex; align-items: center; gap: 0.5rem; }}
        .mini-chip {{
            font-size: 0.68rem; padding: 0.18rem 0.5rem; border-radius: 999px;
            font-family: 'Inter', sans-serif; font-weight: 500;
            display: inline-flex; align-items: center; gap: 0.3rem;
        }}
        .mini-pass {{ background: var(--ok-soft); color: var(--ok); border: 1px solid var(--ok-edge); }}
        .mini-fail {{ background: var(--bad-soft); color: var(--bad); border: 1px solid var(--bad-edge); }}
        .chev {{ color: var(--text-muted); transition: transform .3s cubic-bezier(.2,.8,.2,1); font-size: 0.78rem; }}
        .date-group[open] .chev {{ transform: rotate(180deg); }}

        .table-container {{ width: 100%; overflow-x: auto; max-height: 62vh; overflow-y: auto; }}
        table {{ width: 100%; border-collapse: collapse; text-align: left; min-width: 960px; }}
        thead {{ position: sticky; top: 0; z-index: 5; }}
        th {{
            background: linear-gradient(180deg, rgba(7,2,26,0.95), rgba(15,5,40,0.85));
            backdrop-filter: blur(8px);
            padding: 0.9rem 1.1rem;
            font-size: 0.7rem; color: var(--neon-2);
            text-transform: uppercase; letter-spacing: 0.12em;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
            border-bottom: 1px solid var(--border-strong);
            text-shadow: 0 0 8px rgba(0,255,240,0.4);
        }}
        td {{
            padding: 0.85rem 1.1rem; border-bottom: 1px solid var(--border);
            font-size: 0.83rem; color: var(--text); vertical-align: middle;
        }}
        tbody tr {{ transition: background .25s, transform .25s, box-shadow .25s; }}
        tbody tr:hover {{
            background: rgba(255,0,234,0.06);
            box-shadow: inset 0 0 20px rgba(0,255,240,0.07);
        }}
        .row-pass td {{ background: rgba(0,255,136,0.025); }}
        .row-fail td {{ background: rgba(255,46,99,0.05); }}
        .scenario-id {{
            font-family: 'JetBrains Mono', monospace; font-weight: 700;
            color: var(--neon); letter-spacing: 0.04em;
            text-shadow: 0 0 8px rgba(255,0,234,0.55);
        }}
        .tcid-cell {{
            font-family: 'JetBrains Mono', monospace; font-size: 0.76rem;
            color: var(--neon-2); text-shadow: 0 0 6px rgba(0,255,240,0.4);
        }}
        .name-cell {{ color: var(--text); font-weight: 500; }}
        .error-cell {{ color: var(--text-dim); max-width: 420px; font-size: 0.8rem; font-family: 'JetBrains Mono', monospace; }}
        .err-line {{ display: block; padding: 2px 0; border-left: 2px solid var(--bad); padding-left: 0.6rem; margin-bottom: 3px; }}
        .row-pass .err-line {{ border-left-color: var(--ok); }}
        .time-cell {{ color: var(--neon-3); font-family: 'JetBrains Mono', monospace; font-size: 0.76rem; white-space: nowrap; text-shadow: 0 0 6px rgba(0,255,136,0.35); }}

        /* ── Footer ───────────────────────────────────────── */
        footer {{
            margin-top: 3rem; padding: 1.6rem 0;
            text-align: center; font-size: 0.8rem;
            color: var(--text-muted); letter-spacing: 0.06em;
            border-top: 1px solid var(--border);
            font-family: 'JetBrains Mono', monospace;
        }}
        footer span {{
            background: linear-gradient(135deg, var(--neon), var(--neon-2), var(--neon-3));
            background-size: 200% 200%;
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
            font-weight: 700;
            filter: drop-shadow(0 0 12px rgba(255,0,234,0.45));
            animation: gradientShift 5s ease infinite;
        }}

        /* ── Animations ───────────────────────────────────────── */
        @keyframes fadeDown   {{ from {{ opacity:0; transform: translateY(-14px);}} to {{ opacity:1; transform: translateY(0);}} }}
        @keyframes fadeUp     {{ from {{ opacity:0; transform: translateY(14px);}}  to {{ opacity:1; transform: translateY(0);}} }}
        @keyframes fadeIn     {{ from {{ opacity:0; }} to {{ opacity:1; }} }}
        @keyframes statIn     {{ to   {{ opacity:1; transform: translateY(0) scale(1); }} }}
        @keyframes cardIn     {{ from {{ opacity:0; transform: translateY(24px) scale(.97);}} to {{ opacity:1; transform: translateY(0) scale(1);}} }}
        @keyframes tabPop     {{ 0% {{ transform: scale(.92); opacity: .5;}} 100% {{ transform: scale(1); opacity: 1;}} }}
        @keyframes pulseRing  {{ 0% {{ box-shadow: 0 0 0 0 rgba(0,255,136,0.7);}} 75%,100% {{ box-shadow: 0 0 0 12px rgba(0,255,136,0);}} }}
        @keyframes dotPulse   {{ 0%,100% {{ box-shadow: 0 0 6px currentColor, 0 0 12px currentColor;}} 50% {{ box-shadow: 0 0 14px currentColor, 0 0 28px currentColor, 0 0 40px currentColor;}} }}
        @keyframes barFill    {{ from {{ transform: scaleX(0); }} to {{ transform: scaleX(1); }} }}
        @keyframes barTip     {{ 0%,100% {{ opacity: 0.7; transform: scale(1); }} 50% {{ opacity: 1; transform: scale(1.4); }} }}
        @keyframes cardShine  {{ 0% {{ transform: translateX(-100%) rotate(20deg);}} 50% {{ transform: translateX(450%) rotate(20deg);}} 100% {{ transform: translateX(450%) rotate(20deg);}} }}
        @keyframes gradientShift {{ 0%,100% {{ background-position: 0% 50%; }} 50% {{ background-position: 100% 50%; }} }}
        @keyframes meshDrift  {{ 0% {{ transform: translate3d(0,0,0) scale(1); }} 100% {{ transform: translate3d(60px, 40px, 0) scale(1.05); }} }}
        @keyframes scanMove   {{ 0% {{ background-position: 0 0, 0 0, 0 0; }} 100% {{ background-position: 0 60px, 0 0, 0 0; }} }}
        @keyframes stripScan  {{ 0% {{ transform: translateX(-100%);}} 100% {{ transform: translateX(100%); }} }}
        @keyframes tabSweep   {{ 0% {{ transform: translateX(-100%);}} 60%,100% {{ transform: translateX(100%); }} }}
        @keyframes spin       {{ to {{ transform: rotate(360deg); }} }}
        @keyframes blink      {{ 0%,80%,100% {{ opacity: 1; }} 40% {{ opacity: 0.25; }} }}
        @keyframes caretBlink {{ 0%,49% {{ opacity: 1; }} 50%,100% {{ opacity: 0; }} }}
        @keyframes glitchHue  {{ 0%,100% {{ filter: hue-rotate(0deg); }} 50% {{ filter: hue-rotate(60deg); }} }}
        @keyframes titleGlitch {{
            0%,92%,100% {{ transform: translate(0,0); text-shadow: 0 0 14px rgba(255,0,234,0.5), 0 0 22px rgba(0,255,240,0.4); }}
            93% {{ transform: translate(2px,-1px); }}
            94% {{ transform: translate(-2px,1px); }}
            95% {{ transform: translate(0,0); text-shadow: -2px 0 var(--neon), 2px 0 var(--neon-2); }}
            96% {{ transform: translate(1px,1px); }}
            97% {{ transform: translate(0,0); }}
        }}
        @keyframes badgeGlow  {{ 0%,100% {{ filter: drop-shadow(0 0 6px currentColor); }} 50% {{ filter: drop-shadow(0 0 18px currentColor); }} }}
        @keyframes floatY     {{ 0%,100% {{ transform: translateY(0); }} 50% {{ transform: translateY(-8px); }} }}
        @keyframes orbPulse   {{ 0%,100% {{ transform: scale(1); opacity: 0.55; }} 50% {{ transform: scale(1.15); opacity: 0.85; }} }}
        @keyframes shine      {{ 0%,100% {{ opacity: 0; }} }}
        @keyframes badgePulse {{ 0%,100% {{ opacity: 1; }} }}
        @keyframes pulseDot   {{ 0%,100% {{ opacity: 1; }} }}
        @keyframes aurora     {{ 0%,100% {{ opacity: 1; }} }}

        /* Reduced motion */
        @media (prefers-reduced-motion: reduce) {{
            *, *::before, *::after {{
                animation-duration: 0.01ms !important;
                animation-iteration-count: 1 !important;
                transition-duration: 0.01ms !important;
            }}
        }}

        /* ── Responsive ───────────────────────────────────────── */
        @media (max-width: 900px) {{
            body {{ padding: 1rem; }}
            .role-grid {{ grid-template-columns: 1fr; }}
            .scenario-title {{ font-size: 1.4rem; }}
            .brand h1 {{ font-size: 1.6rem; }}
        }}
    </style>
</head>
<body>
    <canvas id="matrix-bg"></canvas>
    <div class="container">

        <!-- Header -->
        <header>
            <div class="brand">
                <div class="brand-orb"><i class="fa-solid fa-atom"></i></div>
                <div>
                    <h1>Vyapy Scenarios</h1>
                    <p>Realtime multi-agent QA intelligence</p>
                </div>
            </div>
            <div class="status-strip">
                <span class="pulse-dot"></span>
                <span>SYSTEM ONLINE</span>
                <span class="sep">|</span>
                <span class="mono">{now_str}</span>
            </div>
        </header>

        <!-- Stats -->
        <section class="stats">
            <div class="stat total">
                <div class="label">Total Executed</div>
                <div class="value" data-target="{total}">0</div>
                <div class="bar"><span style="width: 100%"></span></div>
            </div>
            <div class="stat pass">
                <div class="label">Passed</div>
                <div class="value" data-target="{passed}">0</div>
                <div class="bar"><span style="width: {pass_pct}%"></span></div>
            </div>
            <div class="stat fail">
                <div class="label">Failed</div>
                <div class="value" data-target="{failed}">0</div>
                <div class="bar"><span style="width: {100 - pass_pct if total else 0}%"></span></div>
            </div>
            <div class="stat rate">
                <div class="label">Success Rate</div>
                <div class="value" data-target="{pass_pct}" data-suffix="%">0%</div>
                <div class="bar"><span style="width: {pass_pct}%"></span></div>
            </div>
        </section>

        <!-- Tabs -->
        <div class="tabs">
            <button class="tab-btn active" data-tab="home" onclick="switchTab('home')">
                <i class="fa-solid fa-bolt-lightning"></i> HOME
            </button>
            <button class="tab-btn" data-tab="history" onclick="switchTab('history')">
                <i class="fa-solid fa-clock-rotate-left"></i> HISTORY ({len(history)})
            </button>
        </div>

        <!-- HOME -->
        <div id="tab-home" class="tab-content active">
            {home_content}
        </div>

        <!-- HISTORY -->
        <div id="tab-history" class="tab-content">
            {history_content}
        </div>

        <footer>
            <span>Vyapy QA Bot</span> &mdash; Multi-Agent Test Orchestration
        </footer>
    </div>

    <script>
        // ── Tab switching with hash persistence ──
        function switchTab(name) {{
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
            var tc = document.getElementById('tab-' + name);
            if (tc) tc.classList.add('active');
            document.querySelectorAll('.tab-btn[data-tab="' + name + '"]').forEach(b => b.classList.add('active'));
            window.location.hash = name;
        }}
        (function() {{
            var h = window.location.hash.replace('#', '');
            if (h === 'history') switchTab('history');
        }})();

        // ── Animated counters with digit scramble ──
        (function() {{
            var CHARS = '01アイウエカキクケサシスセタチツテナニヌネハヒフヘマミムメヤユヨラリルレ';
            function animate(el) {{
                var target = parseFloat(el.getAttribute('data-target')) || 0;
                var suffix = el.getAttribute('data-suffix') || '';
                var duration = 1400;
                var start = performance.now();
                function tick(t) {{
                    var p = Math.min(1, (t - start) / duration);
                    var eased = 1 - Math.pow(1 - p, 3);
                    var val = target * eased;
                    if (p < 0.85) {{
                        var num = Math.round(val);
                        // scramble effect: prepend a random char during the run
                        var s = String(num);
                        if (Math.random() < 0.35) {{
                            s = CHARS.charAt(Math.floor(Math.random() * CHARS.length)) + s.slice(1);
                        }}
                        el.textContent = s + suffix;
                    }} else {{
                        el.textContent = (target % 1 === 0 ? Math.round(val) : val.toFixed(1)) + suffix;
                    }}
                    if (p < 1) requestAnimationFrame(tick);
                }}
                requestAnimationFrame(tick);
            }}
            document.querySelectorAll('.stat .value').forEach(animate);
        }})();

        // ── Matrix rain background ──
        (function() {{
            var canvas = document.getElementById('matrix-bg');
            if (!canvas) return;
            var ctx = canvas.getContext('2d');
            var W = canvas.width = window.innerWidth;
            var H = canvas.height = window.innerHeight;
            var fs = 16;
            var cols = Math.floor(W / fs);
            var drops = new Array(cols).fill(0).map(() => Math.random() * -100);
            var glyphs = '01アイウエカキクケサシスセタチツテナニヌネハヒフヘマミムメヤユヨラリルレロ$#%&@*+=<>{{}}[]/_-';
            var palette = ['#ff00ea', '#00fff0', '#00ff88', '#b537ff'];
            function draw() {{
                ctx.fillStyle = 'rgba(3,0,10,0.08)';
                ctx.fillRect(0, 0, W, H);
                ctx.font = fs + "px 'JetBrains Mono', monospace";
                for (var i = 0; i < drops.length; i++) {{
                    var ch = glyphs.charAt(Math.floor(Math.random() * glyphs.length));
                    var color = palette[i % palette.length];
                    ctx.shadowColor = color;
                    ctx.shadowBlur = 8;
                    ctx.fillStyle = color;
                    ctx.fillText(ch, i * fs, drops[i] * fs);
                    if (drops[i] * fs > H && Math.random() > 0.975) drops[i] = 0;
                    drops[i] += 0.6;
                }}
            }}
            var raf;
            function loop() {{ draw(); raf = requestAnimationFrame(loop); }}
            loop();
            window.addEventListener('resize', function() {{
                W = canvas.width = window.innerWidth;
                H = canvas.height = window.innerHeight;
                cols = Math.floor(W / fs);
                drops = new Array(cols).fill(0).map(() => Math.random() * -100);
            }});
        }})();

        // ── 3D tilt on stat cards + scenario card ──
        (function() {{
            var els = document.querySelectorAll('.stat, .scenario-card, .calc-block');
            els.forEach(function(el) {{
                el.addEventListener('mousemove', function(e) {{
                    var r = el.getBoundingClientRect();
                    var x = (e.clientX - r.left) / r.width;
                    var y = (e.clientY - r.top) / r.height;
                    var rx = (0.5 - y) * 8;
                    var ry = (x - 0.5) * 10;
                    el.style.transform = 'perspective(900px) rotateX(' + rx + 'deg) rotateY(' + ry + 'deg) translateY(-4px)';
                }});
                el.addEventListener('mouseleave', function() {{
                    el.style.transform = '';
                }});
            }});
        }})();

        // ── Scramble badges on hover ──
        (function() {{
            var CH = '!<>-_\\\\/[]{{}}—=+*^?#________';
            document.querySelectorAll('.badge-xl').forEach(function(el) {{
                var orig = el.textContent.trim();
                var iconHTML = el.querySelector('i') ? el.querySelector('i').outerHTML : '';
                el.addEventListener('mouseenter', function() {{
                    var iter = 0;
                    var interval = setInterval(function() {{
                        var s = orig.split('').map(function(c, i) {{
                            if (i < iter) return orig.charAt(i);
                            return CH.charAt(Math.floor(Math.random() * CH.length));
                        }}).join('');
                        el.innerHTML = iconHTML + ' ' + s;
                        iter += 1;
                        if (iter > orig.length) {{ clearInterval(interval); el.innerHTML = iconHTML + ' ' + orig; }}
                    }}, 35);
                }});
            }});
        }})();
    </script>
</body>
</html>"""

    try:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(html, encoding="utf-8")
        status_str = f"{passed}/{total} passed"
        if _current_result:
            status_str += f" | Current: {_current_result['num']}"
        print(f"[Report] {status_str} -> {REPORT_PATH.name}")
    except Exception as e:
        print(f"[Report] Warning: could not write HTML: {e}")
