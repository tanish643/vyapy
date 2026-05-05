"""
Vya Combined Payments Report Generator (Set 2: PAY9-PAY11).

COMPLETELY SEPARATE from the pre-order report and other payment reports.
Same UI/styling, but different output file, separate backups, and ONLY
shows scenarios PAY9 through PAY11 (Combined Payments scenarios:
Invitee Pays for Guest / Self+tip / Self+Bonus Savings).

Output:
    Vya_Combined_Payments_Report.html

Usage:
    python vya_combined_payments_report.py
    from vya_combined_payments_report import build_report
"""
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

# ── Strict isolation: own paths, own backups ───────────────────────────────
HISTORY_PATH = Path(r"C:\Users\Tanish\Downloads\Vya-agentic-BOT (1)\Vya-agentic-BOT\scenario_history.json")
REPORT_PATH = Path(r"C:\Users\Tanish\Downloads\Vya-agentic-BOT (1)\Vya-agentic-BOT\Vya_Combined_Payments_Report.html")
BACKUP_DIR = Path(r"C:\Users\Tanish\Downloads\Vya-agentic-BOT (1)\Vya-agentic-BOT\.combined_payments_report_backups")

# ── Scenario tagging: PAY9 through PAY11 only ──────────────────────────────
PAYMENT_NUM_PATTERN = re.compile(r'^PAY(9|10|11)$', re.IGNORECASE)


def is_payment_scenario(record):
    """Returns True only for PAY9, PAY10, PAY11 scenarios."""
    num = (record.get("num") or "").strip()
    if not num:
        return False
    return bool(PAYMENT_NUM_PATTERN.match(num))


def backup_history():
    """Save a timestamped copy of scenario_history.json to a combined-payments
    backup folder. Independent from other report backups."""
    if not HISTORY_PATH.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"combined_payments_history_{stamp}.json"
    dest.write_bytes(HISTORY_PATH.read_bytes())
    backups = sorted(BACKUP_DIR.glob("combined_payments_history_*.json"))
    for old in backups[:-30]:
        try:
            old.unlink()
        except Exception:
            pass
    print(f"[Vya Combined Payments Report] History backed up -> {dest.name}")
    return dest


# ── HTML template (identical UI to pre-order report) ──────────────────────

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Vya Combined Payments Automation - Test Report</title>
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
      <h1>Vya Combined Payments Automation</h1>
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


def _extract_bill_check_sections(reasons):
    """Split reasons into one section per 'Bill check' string (Pre, Post, etc.)
    so each gets its own VAT table in the validation cell."""
    sections = []
    seen_payloads = set()
    for r in (reasons or []):
        if not r or 'Bill check' not in r:
            continue
        payload = r.split('Bill check', 1)[1]
        if payload in seen_payloads:
            continue
        seen_payloads.add(payload)
        section = {'vat_rows': []}
        m = re.search(
            r'Items\s*sum\s*mismatch:\s*displayed\s*=\s*€?([\d.]+),\s*calculated\s*=\s*€?([\d.]+),\s*diff\s*=\s*€?([\d.]+)',
            r, re.IGNORECASE,
        )
        if m:
            section['items_sum'] = {'displayed': m.group(1), 'calculated': m.group(2),
                                    'diff': m.group(3), 'pass': False}
        for vm in re.finditer(
            r'VAT\s+([\d.]+)%\s*mismatch:\s*expected\s+[\d.]+/100\s*[×x*]\s*€?([\d.]+)\s*=\s*€?([\d.]+),\s*displayed\s*=\s*€?([\d.]+),\s*diff\s*=\s*€?([\d.]+)',
            r,
        ):
            section['vat_rows'].append({
                'rate': vm.group(1),
                'calc_excl': vm.group(2), 'disp_excl': vm.group(2),
                'calc_vat': vm.group(3), 'disp_vat': vm.group(4),
                'ati': f"{float(vm.group(2)) + float(vm.group(4)):.2f}",
                'pass': False, 'diff': vm.group(5),
            })
        for vm in re.finditer(
            r'VAT\s+([\d.]+)%\s*\(\s*[\d.]+/100\s*[×x*]\s*€?([\d.]+)\s*=\s*€?([\d.]+)\s*\)\s*=\s*displayed\s*€?([\d.]+)\s*✓',
            r,
        ):
            rate = vm.group(1)
            if not any(vr['rate'] == rate for vr in section['vat_rows']):
                section['vat_rows'].append({
                    'rate': rate,
                    'calc_excl': vm.group(2), 'disp_excl': vm.group(2),
                    'calc_vat': vm.group(3), 'disp_vat': vm.group(4),
                    'ati': f"{float(vm.group(2)) + float(vm.group(4)):.2f}",
                    'pass': True, 'diff': '0.00',
                })
        m = re.search(
            r'Total\s*breakdown\s*mismatch:\s*sum\s*Excl\.?Tax\s*\(\s*€?([\d.]+)\s*\)\s*\+\s*sum\s*VAT\s*\(\s*€?([\d.]+)\s*\)\s*=\s*€?([\d.]+),\s*displayed\s*Total\s*=\s*€?([\d.]+),\s*diff\s*=\s*€?([\d.]+)',
            r, re.IGNORECASE,
        )
        if m:
            section['total_breakdown'] = {
                'sum_excl': m.group(1), 'sum_vat': m.group(2),
                'calculated': m.group(3), 'displayed': m.group(4), 'diff': m.group(5),
                'pass': False,
            }
        sections.append(section)
    for i, s in enumerate(sections):
        if i == 0:
            s['label'] = 'Pre-Payment Bill Check'
        elif i == 1:
            s['label'] = 'Post-Payment Bill Check'
        else:
            s['label'] = f'Bill Check #{i + 1}'
    return sections


def _render_vat_table(vat_rows):
    if not vat_rows:
        return ''
    html = (
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
        row_pass = vr.get('pass', True)
        row_color = '#333' if row_pass else '#e74c3c'
        diff_val = float(vr.get('diff', '0') or 0)
        disp_excl_html = f'&euro;{vr["disp_excl"]}'
        disp_vat_html = f'&euro;{vr["disp_vat"]}'
        if not row_pass and diff_val > 0:
            disp_vat_html += f'<br><span style="color:#e74c3c;font-size:11px">diff +{diff_val:.2f}</span>'
            disp_excl_html += f'<br><span style="color:#e74c3c;font-size:11px">diff -{diff_val:.2f}</span>'
        row_status_icon = _check_icon() if row_pass else _cross_icon()
        html += (
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
    return html + '</table>'


def _build_validation_cell(record):
    """Build the validation cell — one VAT table block per bill check section."""
    consumer_reasons = record.get('consumer_reasons') or []
    business_reasons = record.get('business_reasons') or []
    all_reasons = consumer_reasons + business_reasons + (record.get('reasons') or [])
    sections = _extract_bill_check_sections(all_reasons)
    if not sections:
        return '<span style="color:#999">&mdash;</span>'

    blocks = []
    for s in sections:
        block_lines = [
            f'<div style="font-weight:700;color:#1a202c;margin:10px 0 4px 0;font-size:14px">'
            f'{s["label"]}</div>'
        ]
        if s.get('items_sum'):
            it = s['items_sum']
            icon = _cross_icon()
            block_lines.append(
                f'<b>Items Total:</b> {icon} displayed &euro;{it["displayed"]} '
                f'&nbsp;|&nbsp; calculated &euro;{it["calculated"]} '
                f'&nbsp;|&nbsp; diff &euro;{it["diff"]}'
            )
        vat_rows = s.get('vat_rows') or []
        if vat_rows:
            vat_overall_pass = all(vr.get('pass') for vr in vat_rows)
            vat_status = _check_icon() if vat_overall_pass else _cross_icon()
            block_lines.append(f'<b>VAT:</b> {vat_status}')
            block_lines.append(_render_vat_table(vat_rows))
        if s.get('total_breakdown'):
            tb = s['total_breakdown']
            icon = _cross_icon()
            block_lines.append(
                f'<b>Total Breakdown:</b> {icon} calculated &euro;{tb["calculated"]} '
                f'&nbsp;|&nbsp; displayed &euro;{tb["displayed"]} '
                f'&nbsp;|&nbsp; diff &euro;{tb["diff"]}'
            )
        blocks.append('<br>'.join(block_lines))
    return '<hr style="border:0;border-top:1px dashed #cbd5e0;margin:10px 0">'.join(blocks)


def _format_failed_at_html(err):
    """Convert a raw failure dump into clean, structured HTML lines.
    Splits on 'Bill check' to separate pre/post-payment sections, then extracts:
    items-sum, VAT %, total-breakdown, and bill-total mismatches into one line each.
    """
    if not err:
        return ""
    lines = []
    sections = re.split(r';\s*Bill check', err)
    for idx, raw_section in enumerate(sections):
        section_lines = []
        section = raw_section
        if idx == 0:
            label = "Pre-Payment Bill Check" if "Bill check" in section else None
        elif idx == 1:
            label = "Post-Payment Bill Check"
        else:
            label = f"Bill Check #{idx + 1}"

        for m in re.finditer(
            r'Items\s*sum\s*mismatch:\s*displayed\s*=\s*€?([\d.]+),\s*calculated\s*=\s*€?([\d.]+),\s*diff\s*=\s*€?([\d.]+)',
            section, re.IGNORECASE,
        ):
            section_lines.append(
                f'<span style="color:#e74c3c">&#10007;</span> Items sum mismatch: '
                f'displayed &euro;{m.group(1)} &nbsp;|&nbsp; calculated &euro;{m.group(2)} '
                f'&nbsp;|&nbsp; diff &euro;{m.group(3)}'
            )

        for m in re.finditer(
            r'VAT\s+([\d.]+)%\s*mismatch:\s*expected\s+[\d.]+/100\s*[×x*]\s*€?[\d.]+\s*=\s*€?([\d.]+),\s*displayed\s*=\s*€?([\d.]+),\s*diff\s*=\s*€?([\d.]+)',
            section,
        ):
            section_lines.append(
                f'<span style="color:#e74c3c">&#10007;</span> VAT {m.group(1)}% mismatch: '
                f'expected &euro;{m.group(2)} &nbsp;|&nbsp; displayed &euro;{m.group(3)} '
                f'&nbsp;|&nbsp; diff &euro;{m.group(4)}'
            )

        for m in re.finditer(
            r'Total\s*breakdown\s*mismatch:\s*sum\s*Excl\.?Tax\s*\(\s*€?([\d.]+)\s*\)\s*\+\s*sum\s*VAT\s*\(\s*€?([\d.]+)\s*\)\s*=\s*€?([\d.]+),\s*displayed\s*Total\s*=\s*€?([\d.]+),\s*diff\s*=\s*€?([\d.]+)',
            section, re.IGNORECASE,
        ):
            section_lines.append(
                f'<span style="color:#e74c3c">&#10007;</span> Total breakdown mismatch: '
                f'calculated &euro;{m.group(3)} &nbsp;|&nbsp; displayed &euro;{m.group(4)} '
                f'&nbsp;|&nbsp; diff &euro;{m.group(5)}'
            )

        for m in re.finditer(
            r'Bill\s*total\s*mismatch:\s*displayed\s*=\s*€?([\d.]+),\s*calculated\s*=\s*€?([\d.]+),\s*diff\s*=\s*€?([\d.]+)',
            section, re.IGNORECASE,
        ):
            section_lines.append(
                f'<span style="color:#e74c3c">&#10007;</span> Bill total mismatch: '
                f'displayed &euro;{m.group(1)} &nbsp;|&nbsp; calculated &euro;{m.group(2)} '
                f'&nbsp;|&nbsp; diff &euro;{m.group(3)}'
            )

        if section_lines:
            if label:
                lines.append(f'<div style="font-weight:700;color:#1a202c;margin-top:6px">{label}</div>')
            lines.extend(section_lines)

    if "Interrupted by user" in err and not lines:
        lines.append('<span style="color:#888">Interrupted by user</span>')

    if not lines:
        return ""
    return ('<div style="text-align:left;line-height:1.8;font-size:13px;color:#c0392b">'
            + '<br>'.join(lines) + '</div>')


def _build_failed_at_cell(record):
    if record.get("status") == "PASS":
        return '<span style="color:#27ae60">-</span>'
    err = record.get("error", "") or ""
    if not err:
        return '<span style="color:#c0392b">Failure</span>'
    structured = _format_failed_at_html(err)
    if structured:
        return structured
    return f'<span style="font-size:13px">{_esc(err[:400])}{"…" if len(err) > 400 else ""}</span>'


def _is_business_noop(record):
    breasons = [r for r in (record.get("business_reasons") or [])
                if r and r.strip().lower() != "completed"]
    return len(breasons) == 0


def _has_screenshot(record):
    sp = record.get("screenshot_path")
    return bool(sp and Path(sp).exists() if sp else False)


def _build_row(record, index):
    bg = "#ffffff" if index % 2 == 0 else "#f8fafc"
    name = _esc(record.get("name", "Unknown"))
    num = _esc(record.get("num", ""))
    test_case = f"{num}. {name}" if num else name
    if _has_screenshot(record):
        test_case += ' <span title="Screenshot available" style="color:#3182ce">[screenshot]</span>'
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


def build_report(device="Android Phone", platform="Android"):
    """Build the Combined Payments HTML report (PAY9-PAY11)."""
    try:
        backup_history()
    except Exception as _e:
        print(f"[Vya Combined Payments Report] Backup skipped: {_e}")

    data = _load_history()
    history = data.get("history", []) or []
    current = data.get("current")

    all_records = []
    if current:
        all_records.append(current)
    all_records.extend(history)

    payment_records = [r for r in all_records if is_payment_scenario(r)]
    payment_records = _dedupe_by_name(payment_records)

    total = len(payment_records)
    passed = sum(1 for r in payment_records if r.get("status") == "PASS")
    failed = sum(1 for r in payment_records if r.get("status") == "FAIL")
    pass_rate = round((passed / total) * 100) if total else 0

    rows_html = "\n        ".join(_build_row(r, i) for i, r in enumerate(payment_records))
    if not rows_html:
        rows_html = ('<tr><td colspan="5" style="text-align:center;padding:40px;color:#999">'
                     'No combined-payments test results yet</td></tr>')

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
    print(f"[Vya Combined Payments Report] Written {total} result(s) -> {REPORT_PATH}")
    return REPORT_PATH


if __name__ == "__main__":
    build_report()
