"""
Vya Payment Report Generator.

COMPLETELY SEPARATE from the pre-order report (vya_test_report.py).
Same UI/styling, but different output file, separate backups, and ONLY
shows scenarios tagged as payment (num starts with PAY/PAYC).

Output:
    Vya_Payment_Report.html   (NEVER touches Vya_Test_Report.html)

Usage:
    python vya_payment_report.py                  # build report from current history
    from vya_payment_report import build_report   # call programmatically
"""
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

# ── Strict isolation: own paths, own backups ───────────────────────────────
HISTORY_PATH = Path(r"C:\Users\Tanish\Downloads\Vya-agentic-BOT (1)\Vya-agentic-BOT\scenario_history.json")
REPORT_PATH = Path(r"C:\Users\Tanish\Downloads\Vya-agentic-BOT (1)\Vya-agentic-BOT\Vya_Payment_Report.html")
BACKUP_DIR = Path(r"C:\Users\Tanish\Downloads\Vya-agentic-BOT (1)\Vya-agentic-BOT\.payment_report_backups")

# ── Scenario tagging: which scenario nums are "payment" ────────────────────
PAYMENT_NUM_PATTERN = re.compile(r'^PAY[A-Z]?\d+$', re.IGNORECASE)


def is_payment_scenario(record):
    """Tagging system. Returns True if this record is a payment scenario.
    Strictly identifies by scenario num prefix (PAY1, PAY2, PAYC1, etc.)."""
    num = (record.get("num") or "").strip()
    if not num:
        return False
    if PAYMENT_NUM_PATTERN.match(num):
        return True
    # Belt-and-suspenders: also check name for "payment" keyword
    name = (record.get("name") or "").lower()
    if "payment" in name and num.upper().startswith("PAY"):
        return True
    return False


def backup_history():
    """Save a timestamped copy of scenario_history.json to a payment-only
    backup folder. Independent from preorder backups."""
    if not HISTORY_PATH.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"payment_history_{stamp}.json"
    dest.write_bytes(HISTORY_PATH.read_bytes())
    backups = sorted(BACKUP_DIR.glob("payment_history_*.json"))
    for old in backups[:-30]:
        try:
            old.unlink()
        except Exception:
            pass
    print(f"[Vya Payment Report] History backed up -> {dest.name}")
    return dest


# ── HTML template (identical UI to pre-order report) ──────────────────────

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Vya Payment Automation - Test Report</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #f0f2f5;
      padding: 30px;
      color: #333;
    }
    .card {
      max-width: 1500px;
      margin: 0 auto;
      background: #fff;
      border-radius: 12px;
      box-shadow: 0 2px 16px rgba(0,0,0,.08);
      overflow: hidden;
    }
    .header {
      background: #1a202c;
      color: #fff;
      padding: 24px 32px;
    }
    .header h1 { font-size: 24px; font-weight: 700; }
    .header p  { font-size: 15px; opacity: .8; margin-top: 4px; }
    .stats { display: flex; border-bottom: 2px solid #e2e8f0; }
    .stat {
      flex: 1; padding: 18px; text-align: center;
      border-right: 1px solid #e2e8f0;
    }
    .stat:last-child { border-right: none; }
    .stat .val { font-size: 28px; font-weight: 800; }
    .stat .lbl { font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 1px; margin-top: 4px; }
    table { width: 100%; border-collapse: collapse; }
    thead th {
      background: #f7fafc;
      padding: 16px 20px;
      font-size: 16px;
      font-weight: 700;
      color: #333;
      border-bottom: 2px solid #e2e8f0;
      text-align: center;
    }
    thead th:first-child { text-align: left; }
    td {
      padding: 14px 20px;
      border-bottom: 1px solid #edf2f7;
      font-size: 14px;
      vertical-align: top;
    }
    .td-name { font-weight: 500; color: #2d3748; }
    .td-c { text-align: center; }
    .td-bill {
      padding: 16px 20px;
      font-size: 15px;
      line-height: 2.0;
      text-align: center;
      min-width: 500px;
    }
    .muted { color: #999; }
    tr:hover td { background: #f7fafc; }
  </style>
</head>
<body>
  <div class="card">
    <div class="header">
      <h1>Vya Payment Automation</h1>
      <p>Device: __DEVICE__ &nbsp;&middot;&nbsp; Platform: __PLATFORM__</p>
    </div>

    <div class="stats">
      <div class="stat">
        <div class="val">__TOTAL__</div>
        <div class="lbl">Total</div>
      </div>
      <div class="stat">
        <div class="val" style="color:#27ae60">__PASSED__</div>
        <div class="lbl">Passed</div>
      </div>
      <div class="stat">
        <div class="val" style="color:#e74c3c">__FAILED__</div>
        <div class="lbl">Failed</div>
      </div>
      <div class="stat">
        <div class="val" style="color:#805ad5">__PASS_RATE__%</div>
        <div class="lbl">Pass Rate</div>
      </div>
    </div>

    <table>
      <thead>
        <tr>
          <th>Test Case</th>
          <th>App</th>
          <th>Status</th>
          <th>Payment Validation</th>
          <th>Failed At</th>
        </tr>
      </thead>
      <tbody>
        __ROWS__
      </tbody>
    </table>

  </div>
</body>
</html>"""


# ── Helpers (private to this module — strict isolation) ───────────────────

def _esc(text):
    if text is None:
        return ""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def _load_history():
    if not HISTORY_PATH.exists():
        return {"current": None, "history": []}
    try:
        return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"current": None, "history": []}


def _status_badge(status):
    if status == "PASS":
        return ('<span style="background:#27ae60;color:#fff;padding:4px 14px;border-radius:20px;'
                'font-size:11px;font-weight:700;letter-spacing:.5px">PASSED</span>')
    if status == "FAIL":
        return ('<span style="background:#e74c3c;color:#fff;padding:4px 14px;border-radius:20px;'
                'font-size:11px;font-weight:700;letter-spacing:.5px">FAILED</span>')
    return ('<span style="background:#f39c12;color:#fff;padding:4px 14px;border-radius:20px;'
            'font-size:11px;font-weight:700;letter-spacing:.5px">SKIPPED</span>')


def _check_icon():
    return '<span style="color:#27ae60;font-size:16px;font-weight:bold">&#10003;</span>'


def _cross_icon():
    return '<span style="color:#e74c3c;font-size:16px;font-weight:bold">&#10007;</span>'


def _extract_payment_meta(reasons):
    """Pull payment-specific metadata out of reason strings.
    Looks for: amount paid, payment method, transaction id, refund, etc."""
    meta = {
        "amount": None,
        "method": None,
        "txn_id": None,
        "refund": None,
        "bill_total": None,
    }
    for r in (reasons or []):
        if not r:
            continue
        # Amount paid: "Paid €100.00" / "Cash €350" / "amount = €X"
        m = re.search(r'(?:Paid|Amount|Total\s*Paid)\s*[:=]?\s*€?([\d,]+\.\d{1,2})', r, re.IGNORECASE)
        if m:
            meta["amount"] = m.group(1)
        # Payment method: "Cash" / "Card" / "UPI" / "E-Payment"
        m = re.search(r'\b(Cash|Card|UPI|E[- ]?Payment|Wallet|PayPal|Voucher)\b', r, re.IGNORECASE)
        if m and not meta["method"]:
            meta["method"] = m.group(1)
        # Transaction id
        m = re.search(r'(?:Txn|Transaction|Order)\s*(?:Id|#)?\s*[:=]?\s*([A-Z0-9-]{6,})', r, re.IGNORECASE)
        if m:
            meta["txn_id"] = m.group(1)
        # Refund
        m = re.search(r'Refund(?:ed)?\s*[:=]?\s*€?([\d,]+\.\d{1,2})', r, re.IGNORECASE)
        if m:
            meta["refund"] = m.group(1)
        # Bill total: "Bill total: €X" / "Total: €X"
        m = re.search(r'(?:Bill\s*)?Total\s*[:=]?\s*€?([\d,]+\.\d{1,2})', r, re.IGNORECASE)
        if m and not meta["bill_total"]:
            meta["bill_total"] = m.group(1)
    return meta


def _build_validation_cell(record):
    """Build the 'Payment Validation' cell from a record."""
    consumer_reasons = record.get("consumer_reasons") or []
    business_reasons = record.get("business_reasons") or []
    all_reasons = consumer_reasons + business_reasons + (record.get("reasons") or [])

    meta = _extract_payment_meta(all_reasons)
    lines = []

    if meta["bill_total"]:
        lines.append(f'<b>Bill Total:</b> {_check_icon()} &euro;{meta["bill_total"]}')
    if meta["method"]:
        lines.append(f'<b>Payment Method:</b> <span style="color:#333">{_esc(meta["method"])}</span>')
    if meta["amount"]:
        lines.append(f'<b>Amount Paid:</b> {_check_icon()} &euro;{meta["amount"]}')
    if meta["txn_id"]:
        lines.append(f'<b>Transaction ID:</b> <span style="color:#333">{_esc(meta["txn_id"])}</span>')
    if meta["refund"]:
        lines.append(f'<b>Refund:</b> <span style="color:#e67e22">&euro;{meta["refund"]}</span>')

    if not lines:
        return '<span style="color:#999">—</span>'
    return '<br>'.join(lines)


def _build_failed_at_cell(record):
    if record.get("status") == "PASS":
        return '<span style="color:#27ae60">-</span>'
    err = record.get("error", "") or ""
    if not err:
        return '<span style="color:#c0392b">Failure</span>'
    return _esc(err)


def _is_business_noop(record):
    breasons = [r for r in (record.get("business_reasons") or [])
                if r and r.strip().lower() != "completed"]
    return len(breasons) == 0


def _has_screenshot(record):
    """Check if the record has a screenshot path — used for the test case label."""
    sp = record.get("screenshot_path")
    return bool(sp and Path(sp).exists() if sp else False)


def _build_row(record, index):
    bg = "#ffffff" if index % 2 == 0 else "#f8fafc"
    name = _esc(record.get("name", "Unknown"))
    num = _esc(record.get("num", ""))
    test_case = f"{num}. {name}" if num else name

    # Append small camera icon if a screenshot exists
    if _has_screenshot(record):
        test_case += ' <span title="Screenshot available" style="color:#3182ce">[screenshot]</span>'

    # Execution time
    launch_time = record.get("launch_time")
    if launch_time is not None:
        test_case += f'<br><span style="color:#888;font-size:12px">Execution: {launch_time:.1f}s</span>'

    consumer_status = record.get("consumer_status", "N/A")
    business_status = record.get("business_status", "N/A")
    business_real = (business_status != "N/A") and (not _is_business_noop(record))
    if consumer_status != "N/A" and business_real:
        app = "Consumer + Business"
    elif consumer_status != "N/A":
        app = "Consumer"
    elif business_real:
        app = "Business"
    else:
        app = "—"

    status_html = _status_badge(record.get("status", "PASS"))
    validation_html = _build_validation_cell(record)
    failed_at_html = _build_failed_at_cell(record)

    return (
        f'<tr style="background:{bg}">'
        f'<td style="padding:14px 20px;border-bottom:1px solid #edf2f7;font-size:15px;'
        f'font-weight:500;vertical-align:top;line-height:1.8">{test_case}</td>'
        f'<td class="td-c" style="font-size:15px">{app}</td>'
        f'<td class="td-c">{status_html}</td>'
        f'<td class="td-bill">{validation_html}</td>'
        f'<td style="padding:14px 20px;border-bottom:1px solid #edf2f7;color:#c0392b;'
        f'font-size:15px;font-weight:500;vertical-align:top">{failed_at_html}</td>'
        f'</tr>'
    )


def _trimmed_name(name):
    return re.sub(r'^\[[^\]]+\]\s*', '', (name or '')).strip().lower()


def _dedupe_by_name(records):
    """Cluster by 15-min-gap runs, prefer non-interrupted, then most informative."""
    fmt = "%Y-%m-%d %H:%M:%S"

    def _ts(r):
        try:
            return datetime.strptime(r.get("timestamp", ""), fmt)
        except (ValueError, TypeError):
            return None

    groups = {}
    for r in records:
        key = _trimmed_name(r.get("name", ""))
        if not key:
            continue
        groups.setdefault(key, []).append(r)

    def _is_interrupted_run(run_entries):
        for r in run_entries:
            for fld in ("reasons", "consumer_reasons", "business_reasons"):
                for rsn in (r.get(fld) or []):
                    if rsn and "interrupted" in rsn.lower():
                        return True
        return False

    def _split_into_runs(group):
        with_ts = [(r, _ts(r)) for r in group]
        valid = [(r, t) for (r, t) in with_ts if t is not None]
        no_ts = [r for (r, t) in with_ts if t is None]
        if not valid:
            return [group]
        valid.sort(key=lambda x: x[1], reverse=True)
        runs = []
        current_run = [valid[0][0]]
        prev_t = valid[0][1]
        for r, t in valid[1:]:
            if (prev_t - t) > timedelta(minutes=15):
                runs.append(current_run)
                current_run = [r]
            else:
                current_run.append(r)
            prev_t = t
        runs.append(current_run)
        if no_ts:
            if runs:
                runs[0].extend(no_ts)
            else:
                runs.append(no_ts)
        return runs

    def _informative_score(run):
        score = 0
        for r in run:
            for fld in ("reasons", "consumer_reasons", "business_reasons"):
                for rsn in (r.get(fld) or []):
                    if not rsn:
                        continue
                    low = rsn.lower()
                    if "interrupt" in low or low.strip() == "completed":
                        continue
                    score += 1
        return score

    merged_list = []
    for key, group in groups.items():
        runs = _split_into_runs(group)
        chosen_run = None
        for run in runs:
            if not _is_interrupted_run(run):
                chosen_run = run
                break
        if chosen_run is None:
            chosen_run = max(runs, key=_informative_score) if runs else group
        latest_group = chosen_run

        base = dict(latest_group[0])
        base["consumer_reasons"] = list(base.get("consumer_reasons") or [])
        base["business_reasons"] = list(base.get("business_reasons") or [])
        base["reasons"] = list(base.get("reasons") or [])

        for r in latest_group[1:]:
            for fld in ("consumer_reasons", "business_reasons", "reasons"):
                for rsn in (r.get(fld) or []):
                    if rsn and rsn not in base[fld]:
                        base[fld].append(rsn)
            if r.get("status") == "FAIL":
                base["status"] = "FAIL"
            if r.get("consumer_status") == "FAIL":
                base["consumer_status"] = "FAIL"
            if r.get("business_status") == "FAIL":
                base["business_status"] = "FAIL"
            if len(str(r.get("num", ""))) > len(str(base.get("num", ""))):
                base["num"] = r["num"]
                base["name"] = r["name"]

        fail_reasons = [x for x in base["reasons"] +
                        base["consumer_reasons"] +
                        base["business_reasons"]
                        if x and x.strip().lower() != "completed"]
        if base.get("status") == "FAIL":
            base["error"] = "; ".join(dict.fromkeys(fail_reasons))
        else:
            base["error"] = ""

        merged_list.append(base)

    return merged_list


def generate_payment_report(device="Android Phone", platform="Android"):
    """Public, name-clearly-payment generator. Calls build_report internally."""
    return build_report(device=device, platform=platform)


def build_report(device="Android Phone", platform="Android"):
    """Build the payment-only HTML report. Reads scenario_history.json,
    filters to payment scenarios only, and writes Vya_Payment_Report.html.
    Pre-order report file is NEVER touched."""
    try:
        backup_history()
    except Exception as _e:
        print(f"[Vya Payment Report] Backup skipped: {_e}")

    data = _load_history()
    history = data.get("history", []) or []
    current = data.get("current")

    all_records = []
    if current:
        all_records.append(current)
    all_records.extend(history)

    # ── Strict isolation: only payment scenarios ──────────────────────────
    payment_records = [r for r in all_records if is_payment_scenario(r)]

    # Dedupe by name (latest run wins)
    payment_records = _dedupe_by_name(payment_records)

    total = len(payment_records)
    passed = sum(1 for r in payment_records if r.get("status") == "PASS")
    failed = sum(1 for r in payment_records if r.get("status") == "FAIL")
    pass_rate = round((passed / total) * 100) if total else 0

    rows_html = "\n        ".join(_build_row(r, i) for i, r in enumerate(payment_records))
    if not rows_html:
        rows_html = ('<tr><td colspan="5" style="text-align:center;padding:40px;color:#999">'
                     'No payment test results yet</td></tr>')

    html = (HTML_TEMPLATE
            .replace("__DEVICE__", _esc(device))
            .replace("__PLATFORM__", _esc(platform))
            .replace("__TOTAL__", str(total))
            .replace("__PASSED__", str(passed))
            .replace("__FAILED__", str(failed))
            .replace("__PASS_RATE__", str(pass_rate))
            .replace("__ROWS__", rows_html))

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(html, encoding="utf-8")
    print(f"[Vya Payment Report] Written {total} payment result(s) -> {REPORT_PATH}")
    return REPORT_PATH


if __name__ == "__main__":
    build_report()
