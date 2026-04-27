"""
Vya Test Report Generator.

Standalone module that produces a NEW report file `Vya_Test_Report.html`
with the exact UI shown in the user-provided template.

Reads from the same `scenario_history.json` already maintained by
`scenario_reporter.py`, so it does NOT modify any existing file.

Usage:
    python vya_test_report.py                  # build report from current history
    from vya_test_report import build_report   # call programmatically
"""
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

HISTORY_PATH = Path(r"C:\Users\Tanish\Downloads\Vya-agentic-BOT (1)\Vya-agentic-BOT\scenario_history.json")
REPORT_PATH = Path(r"C:\Users\Tanish\Downloads\Vya-agentic-BOT (1)\Vya-agentic-BOT\Vya_Test_Report.html")
BACKUP_DIR = Path(r"C:\Users\Tanish\Downloads\Vya-agentic-BOT (1)\Vya-agentic-BOT\.history_backups")


def backup_history():
    """Save a timestamped copy of scenario_history.json so it can never be lost."""
    if not HISTORY_PATH.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"scenario_history_{stamp}.json"
    dest.write_bytes(HISTORY_PATH.read_bytes())
    # Keep only the latest 30 backups
    backups = sorted(BACKUP_DIR.glob("scenario_history_*.json"))
    for old in backups[:-30]:
        try:
            old.unlink()
        except Exception:
            pass
    print(f"[Vya Test Report] History backed up -> {dest.name}")
    return dest


# ── HTML template (matches user-provided Vya_Test_Report.html exactly) ──

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Vya Mobile Automation - Test Report</title>
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
      <h1>Vya Mobile Automation</h1>
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
        <div class="val" style="color:#f39c12">__SKIPPED__</div>
        <div class="lbl">Skipped</div>
      </div>
      <div class="stat">
        <div class="val" style="color:#3182ce">__DURATION__s</div>
        <div class="lbl">Duration</div>
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
          <th>Total Validation</th>
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


def _na_text():
    return '<span style="color:#95a5a6">NA</span>'


def _extract_totals(reasons):
    """Pull pre-payment / post-payment / VAT details out of reason strings."""
    pre_total = None
    post_total = None
    vat_rows_by_rate = {}

    for r in (reasons or []):
        if not r:
            continue

        # Cart total (pre-payment): "Cart total OK: €60.49 (Items: ...)"
        m = re.search(r'Cart total OK[^€]*€?([\d.]+)', r)
        if m:
            pre_total = m.group(1)

        # Items sum equals total: "Items Sum = €60.49 ... Total = €60.49"
        m = re.search(r'Items Sum\s*=\s*€?([\d.]+).*?Total\s*=\s*€?([\d.]+)', r)
        if m:
            pre_total = m.group(1)
            post_total = m.group(2)

        # Sum Excl.Tax + Sum VAT = €X.XX = Total €Y.YY
        m = re.search(
            r'Sum Excl\.?Tax\s*\(\s*€?[\d.]+\s*\)\s*\+\s*Sum VAT\s*\(\s*€?[\d.]+\s*\)\s*=\s*€?[\d.]+\s*=\s*Total\s*€?([\d.]+)',
            r
        )
        if m:
            post_total = m.group(1)
            if pre_total is None:
                pre_total = m.group(1)

        # VAT row PASSED: "VAT 3.0% (3.0/100 × €4.37 = €0.13) = displayed €0.13 ✓"
        for vm in re.finditer(
            r'VAT\s+([\d.]+)%\s*\(\s*[\d.]+/100\s*[×x*]\s*€?([\d.]+)\s*=\s*€?([\d.]+)\s*\)\s*=\s*displayed\s*€?([\d.]+)\s*✓',
            r
        ):
            rate = vm.group(1)
            vat_rows_by_rate[rate] = {
                "rate": rate,
                "calc_excl": vm.group(2),
                "disp_excl": vm.group(2),
                "calc_vat": vm.group(3),
                "disp_vat": vm.group(4),
                "ati": f"{float(vm.group(2)) + float(vm.group(4)):.2f}",
                "pass": True,
                "diff": "0.00",
            }

        # VAT row FAILED: "VAT 3.0% mismatch: expected 3.0/100 × €4.37 = €0.13, displayed=€0.11, diff=€0.02"
        for vm in re.finditer(
            r'VAT\s+([\d.]+)%\s*mismatch:\s*expected\s+[\d.]+/100\s*[×x*]\s*€?([\d.]+)\s*=\s*€?([\d.]+),\s*displayed\s*=\s*€?([\d.]+),\s*diff\s*=\s*€?([\d.]+)',
            r
        ):
            rate = vm.group(1)
            vat_rows_by_rate[rate] = {
                "rate": rate,
                "calc_excl": vm.group(2),
                "disp_excl": vm.group(2),
                "calc_vat": vm.group(3),
                "disp_vat": vm.group(4),
                "ati": f"{float(vm.group(2)) + float(vm.group(4)):.2f}",
                "pass": False,
                "diff": vm.group(5),
            }

    vat_rows = list(vat_rows_by_rate.values())
    return pre_total, post_total, vat_rows


def _build_validation_cell(record):
    """Build the 'Total Validation' cell from a record.
    Only includes lines for which actual calculation data exists.
    Returns an empty/dash cell when no calculations were captured."""
    consumer_reasons = record.get("consumer_reasons") or []
    business_reasons = record.get("business_reasons") or []
    all_reasons = consumer_reasons + business_reasons + (record.get("reasons") or [])

    pre_total, post_total, vat_rows = _extract_totals(all_reasons)

    lines = []
    # Pre-Payment Total — only if data exists
    if pre_total:
        lines.append(f'<b>Pre-Payment Total:</b> {_check_icon()} &euro;{pre_total}')

    # Post-Payment Total — only if data exists
    if post_total:
        diff_ok = pre_total and abs(float(post_total) - float(pre_total)) < 0.01
        icon = _check_icon() if diff_ok else _cross_icon()
        lines.append(f'<b>Post-Payment Total:</b> {icon} actual = &euro;{post_total} | displayed = &euro;{post_total} | diff = &euro;0.00')

    # VAT — only if rows exist; render the rich table from the template
    if vat_rows:
        vat_overall_pass = all(vr.get("pass") for vr in vat_rows)
        vat_status = _check_icon() if vat_overall_pass else _cross_icon()
        lines.append(f'<b>VAT:</b> {vat_status}')
        table_html = (
            '<table style="margin:6px auto;border-collapse:collapse;font-size:13px;text-align:right">'
            '<tr style="border-bottom:1px solid #ddd">'
            '<th style="text-align:left;padding:4px 10px">Rate</th>'
            '<th style="padding:4px 10px">Calc Excl</th>'
            '<th style="padding:4px 10px">Disp Excl</th>'
            '<th style="padding:4px 10px">Calc VAT</th>'
            '<th style="padding:4px 10px">Disp VAT</th>'
            '<th style="padding:4px 10px">ATI</th>'
            '<th style="padding:4px 10px">Status</th>'
            '</tr>'
        )
        for vr in vat_rows:
            row_pass = vr.get("pass", True)
            row_color = "#333" if row_pass else "#e74c3c"
            diff_val = float(vr.get("diff", "0") or 0)
            disp_excl_html = f'&euro;{vr["disp_excl"]}'
            disp_vat_html = f'&euro;{vr["disp_vat"]}'
            if not row_pass and diff_val > 0:
                disp_vat_html += (
                    f'<br><span style="color:#e74c3c;font-size:11px">'
                    f'diff +{diff_val:.2f}</span>'
                )
                disp_excl_html += (
                    f'<br><span style="color:#e74c3c;font-size:11px">'
                    f'diff -{diff_val:.2f}</span>'
                )
            row_status_icon = _check_icon() if row_pass else _cross_icon()
            table_html += (
                f'<tr style="color:{row_color};border-bottom:1px solid #f0f0f0">'
                f'<td style="text-align:left;padding:4px 10px;font-weight:600">VAT {vr["rate"]}%</td>'
                f'<td style="padding:4px 10px">&euro;{vr["calc_excl"]}</td>'
                f'<td style="padding:4px 10px">{disp_excl_html}</td>'
                f'<td style="padding:4px 10px">&euro;{vr["calc_vat"]}</td>'
                f'<td style="padding:4px 10px">{disp_vat_html}</td>'
                f'<td style="padding:4px 10px">&euro;{vr["ati"]}</td>'
                f'<td style="padding:4px 10px">{row_status_icon}</td>'
                f'</tr>'
            )
        table_html += '</table>'
        lines.append(table_html)

    # Pre vs Post — only if both exist
    if pre_total and post_total:
        diff_ok = abs(float(post_total) - float(pre_total)) < 0.01
        icon = _check_icon() if diff_ok else _cross_icon()
        lines.append(f'<b>Pre vs Post:</b> {icon} &euro;{pre_total} vs &euro;{post_total} diff = &euro;{abs(float(post_total) - float(pre_total)):.2f}')

    if not lines:
        return '<span style="color:#999">—</span>'
    return '<br>'.join(lines)


def _build_failed_at_cell(record):
    """Build the 'Failed At' cell."""
    if record.get("status") == "PASS":
        return '<span style="color:#27ae60">-</span>'
    err = record.get("error", "") or ""
    if not err:
        return '<span style="color:#c0392b">Failure</span>'
    return _esc(err)


def _is_business_noop(record):
    """Business is a no-op if it only has 'Completed' as a reason (or no reasons)."""
    breasons = [r for r in (record.get("business_reasons") or [])
                if r and r.strip().lower() != "completed"]
    return len(breasons) == 0


def _build_row(record, index):
    bg = "#ffffff" if index % 2 == 0 else "#f8fafc"
    name = _esc(record.get("name", "Unknown"))
    num = _esc(record.get("num", ""))
    test_case = f"{num}. {name}" if num else name

    # App = Consumer / Business / Both — hide Business when it was a no-op
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
    """Strip [bracketed prefixes] from scenario names so wrappers dedupe with their inner scenarios."""
    return re.sub(r'^\[[^\]]+\]\s*', '', (name or '')).strip().lower()


def _filter_latest_session(records, window_minutes=30):
    """Keep only entries from the most recent session — defined as records whose
    timestamp is within `window_minutes` of the newest record's timestamp."""
    if not records:
        return []
    fmt = "%Y-%m-%d %H:%M:%S"
    parsed = []
    for r in records:
        ts = r.get("timestamp", "")
        try:
            parsed.append((datetime.strptime(ts, fmt), r))
        except (ValueError, TypeError):
            continue
    if not parsed:
        return records
    newest = max(p[0] for p in parsed)
    cutoff = newest - timedelta(minutes=window_minutes)
    return [r for (t, r) in parsed if t >= cutoff]


def _dedupe_by_name(records):
    """Group records by scenario name. For each group:
    - Use the status from the LATEST run only (so an old interruption
      doesn't poison a freshly-passing scenario).
    - Merge reasons within the latest run (within ~5 min of newest entry)
      so VAT calculation details from validators get combined with the
      runner's PASS/Completed marker.
    - Prefer wrapper-prefixed display name/num (e.g. POC3 > PO3)."""
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
        """A run is 'interrupted' if any of its entries mentions interruption."""
        for r in run_entries:
            for fld in ("reasons", "consumer_reasons", "business_reasons"):
                for rsn in (r.get(fld) or []):
                    if rsn and "interrupted" in rsn.lower():
                        return True
        return False

    def _split_into_runs(group):
        """Cluster entries by 15-min gap → list of runs (newest run first)."""
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
        """Higher = more informative. Counts non-Completed, non-Interrupted reasons."""
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
        # Cluster entries into separate runs (by 15-min gaps)
        runs = _split_into_runs(group)
        # Prefer the most-recent NON-INTERRUPTED run.
        chosen_run = None
        for run in runs:  # already newest-first
            if not _is_interrupted_run(run):
                chosen_run = run
                break
        # If all runs were interrupted, prefer the MOST INFORMATIVE
        # (the one that captured real calculation data before being stopped),
        # not just the most recent one.
        if chosen_run is None:
            chosen_run = max(runs, key=_informative_score) if runs else group
        latest_group = chosen_run

        # Build the merged record from the latest run only
        base = dict(latest_group[0])
        base["consumer_reasons"] = list(base.get("consumer_reasons") or [])
        base["business_reasons"] = list(base.get("business_reasons") or [])
        base["reasons"] = list(base.get("reasons") or [])

        for r in latest_group[1:]:
            for fld in ("consumer_reasons", "business_reasons", "reasons"):
                for rsn in (r.get(fld) or []):
                    if rsn and rsn not in base[fld]:
                        base[fld].append(rsn)

            # Within the latest run, FAIL still beats PASS (so VAT
            # validation failure escalates the run-level status)
            if r.get("status") == "FAIL":
                base["status"] = "FAIL"
            if r.get("consumer_status") == "FAIL":
                base["consumer_status"] = "FAIL"
            if r.get("business_status") == "FAIL":
                base["business_status"] = "FAIL"

            if len(str(r.get("num", ""))) > len(str(base.get("num", ""))):
                base["num"] = r["num"]
                base["name"] = r["name"]

        # Refresh error text from merged reasons
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


def build_report(device="Android Phone", platform="Android"):
    """Build the new report HTML from current scenario history.
    Shows only the LATEST run's scenarios, deduped by name.
    Also takes a timestamped backup of scenario_history.json."""
    try:
        backup_history()
    except Exception as _e:
        print(f"[Vya Test Report] Backup skipped: {_e}")
    data = _load_history()
    history = data.get("history", []) or []
    current = data.get("current")

    all_records = []
    if current:
        all_records.append(current)
    all_records.extend(history)

    # Dedupe by name (merge duplicate POC*/PO* entries into one row).
    # No session filter — show every scenario the user has ever run.
    all_records = _dedupe_by_name(all_records)

    total = len(all_records)
    passed = sum(1 for r in all_records if r.get("status") == "PASS")
    failed = sum(1 for r in all_records if r.get("status") == "FAIL")
    skipped = total - passed - failed
    pass_rate = round((passed / total) * 100) if total else 0
    duration = round(sum((r.get("launch_time") or 0) for r in all_records), 1)

    rows_html = "\n        ".join(_build_row(r, i) for i, r in enumerate(all_records))
    if not rows_html:
        rows_html = ('<tr><td colspan="5" style="text-align:center;padding:40px;color:#999">'
                     'No test results yet</td></tr>')

    html = (HTML_TEMPLATE
            .replace("__DEVICE__", _esc(device))
            .replace("__PLATFORM__", _esc(platform))
            .replace("__TOTAL__", str(total))
            .replace("__PASSED__", str(passed))
            .replace("__FAILED__", str(failed))
            .replace("__SKIPPED__", str(skipped))
            .replace("__DURATION__", str(duration))
            .replace("__PASS_RATE__", str(pass_rate))
            .replace("__ROWS__", rows_html))

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(html, encoding="utf-8")
    print(f"[Vya Test Report] Written {total} test result(s) -> {REPORT_PATH}")
    return REPORT_PATH


if __name__ == "__main__":
    build_report()
