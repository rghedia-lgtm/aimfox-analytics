"""
Generates JSON, CSV, and HTML reports from Aimfox analytics data.
All reports are saved to reports/ subfolder with timestamps.
"""

import csv
import json
import os
from datetime import datetime

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")


def _ensure_dir():
    os.makedirs(REPORTS_DIR, exist_ok=True)


def _fname(prefix: str, ext: str) -> str:
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    return os.path.join(REPORTS_DIR, f"{prefix}_{ts}.{ext}")


def _latest_fname(prefix: str, ext: str) -> str:
    return os.path.join(REPORTS_DIR, f"{prefix}_latest.{ext}")


# ── JSON ──────────────────────────────────────────────────────────────────────

def save_json(data: dict):
    _ensure_dir()
    for path in [_fname("report", "json"), _latest_fname("report", "json")]:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
    return path


# ── CSV ───────────────────────────────────────────────────────────────────────

def save_csv_campaigns(campaigns: list):
    _ensure_dir()
    fields = ["name", "state", "type", "outreach", "targets",
              "completion_pct", "accepted_recent", "replies_recent", "created", "owners"]
    for path in [_fname("campaigns", "csv"), _latest_fname("campaigns", "csv")]:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(campaigns)
    return path


def save_csv_recent_leads(recent_leads: list):
    _ensure_dir()
    fields = ["transition", "timestamp", "campaign_name", "account_id",
              "target_urn", "is_drip"]
    flat = []
    for e in recent_leads:
        target = e.get("target") or {}
        flat.append({
            "transition": e.get("transition", ""),
            "timestamp": e.get("timestamp", ""),
            "campaign_name": e.get("campaign_name", ""),
            "account_id": e.get("account_id", ""),
            "target_name": target.get("full_name", ""),
            "target_occupation": target.get("occupation", ""),
            "target_urn": e.get("target_urn", ""),
            "is_drip": e.get("is_drip", False),
        })
    all_fields = ["transition", "timestamp", "campaign_name", "account_id",
                  "target_name", "target_occupation", "target_urn", "is_drip"]
    for path in [_fname("leads", "csv"), _latest_fname("leads", "csv")]:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_fields)
            writer.writeheader()
            writer.writerows(flat)
    return path


def save_csv_conversations(conversations: list):
    _ensure_dir()
    rows = []
    for conv in conversations:
        participants = conv.get("participants", [])
        lead_name = participants[0].get("full_name", "") if participants else ""
        occupation = participants[0].get("occupation", "") if participants else ""
        messages = conv.get("_messages", [])
        for msg in messages:
            rows.append({
                "lead_name": lead_name,
                "occupation": occupation,
                "owner_account": conv.get("owner", ""),
                "connected": conv.get("connected", False),
                "msg_date": str(msg.get("created_at", ""))[:10],
                "sender": (msg.get("sender") or {}).get("full_name", ""),
                "automated": msg.get("automated", False),
                "body": (msg.get("body") or "").replace("\n", " ").strip()[:500],
            })
    fields = ["lead_name", "occupation", "owner_account", "connected",
              "msg_date", "sender", "automated", "body"]
    for path in [_fname("conversations", "csv"), _latest_fname("conversations", "csv")]:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    return path


# ── HTML ──────────────────────────────────────────────────────────────────────

def save_html_report(accounts: list, campaigns: list, recent_leads: list,
                     conversations: list):
    _ensure_dir()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    def _td(v):
        return f"<td>{v}</td>"

    # Campaigns table
    camp_rows = ""
    for c in campaigns:
        state_color = {"ACTIVE": "#22c55e", "DONE": "#6366f1", "INIT": "#f59e0b"}.get(c.get("state", ""), "#94a3b8")
        camp_rows += f"""<tr>
            <td>{c.get('name','')}</td>
            <td><span style="color:{state_color};font-weight:600">{c.get('state','')}</span></td>
            <td>{c.get('type','')}</td>
            <td>{c.get('targets',0)}</td>
            <td>{c.get('completion_pct','0%')}</td>
            <td><b>{c.get('accepted_recent',0)}</b></td>
            <td>{c.get('replies_recent',0)}</td>
            <td>{c.get('created','')}</td>
        </tr>"""

    # Recent leads table
    acc_map = {a["id"]: a.get("full_name", "?") for a in accounts}
    leads_rows = ""
    for e in recent_leads:
        target = e.get("target") or {}
        t = e.get("transition", "").upper()
        color = "#22c55e" if t == "ACCEPTED" else "#f59e0b"
        leads_rows += f"""<tr>
            <td><span style="color:{color};font-weight:600">{t}</span></td>
            <td>{target.get('full_name','')}</td>
            <td style="font-size:12px;color:#94a3b8">{(target.get('occupation') or '')[:60]}</td>
            <td>{e.get('campaign_name','')}</td>
            <td>{acc_map.get(e.get('account_id',''), e.get('account_id',''))}</td>
            <td>{(e.get('timestamp') or '')[:10]}</td>
        </tr>"""

    # Conversations
    conv_html = ""
    for conv in conversations:
        participants = conv.get("participants", [])
        lead_name = participants[0].get("full_name", "-") if participants else "-"
        occupation = (participants[0].get("occupation") or "")[:60] if participants else ""
        messages = conv.get("_messages", [])
        msgs_html = ""
        for msg in messages:
            body = (msg.get("body") or "").strip()
            if not body and not msg.get("attachments"):
                continue
            sender = (msg.get("sender") or {}).get("full_name", "?")
            ts_msg = str(msg.get("created_at", ""))[:10]
            auto = " <span style='color:#6366f1;font-size:11px'>[auto]</span>" if msg.get("automated") else ""
            content = body[:300].replace("<", "&lt;").replace(">", "&gt;") or "[attachment]"
            side = "right" if not msg.get("automated") and sender != lead_name else "left"
            bg = "#1e293b" if side == "right" else "#0f172a"
            msgs_html += f"""
            <div style="display:flex;justify-content:flex-{side};margin:4px 0">
              <div style="background:{bg};border-radius:8px;padding:8px 12px;max-width:70%">
                <div style="font-size:11px;color:#64748b;margin-bottom:2px">{sender}{auto} &middot; {ts_msg}</div>
                <div style="font-size:13px;color:#e2e8f0">{content}</div>
              </div>
            </div>"""

        conv_html += f"""
        <div style="background:#1e293b;border-radius:10px;padding:16px;margin-bottom:12px">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <div>
              <span style="font-weight:600;color:#f1f5f9">{lead_name}</span>
              <span style="color:#64748b;font-size:12px;margin-left:8px">{occupation}</span>
            </div>
            <span style="color:#22c55e;font-size:12px">{len(messages)} messages</span>
          </div>
          <div style="margin-top:10px">{msgs_html}</div>
        </div>"""

    # Summary stats
    total_targets = sum(c.get("targets", 0) or 0 for c in campaigns)
    total_accepted = sum(c.get("accepted_recent", 0) for c in campaigns)
    total_replies = sum(c.get("replies_recent", 0) for c in campaigns)
    active_camps = sum(1 for c in campaigns if c.get("state") == "ACTIVE")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Aimfox Report - {ts}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0f172a; color: #e2e8f0; padding: 24px; }}
  h1 {{ font-size: 24px; font-weight: 700; color: #f1f5f9; }}
  h2 {{ font-size: 16px; font-weight: 600; color: #94a3b8; text-transform: uppercase;
       letter-spacing: 1px; margin: 28px 0 12px; }}
  .ts {{ color: #64748b; font-size: 13px; margin-top: 4px; }}
  .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 20px 0; }}
  .stat {{ background: #1e293b; border-radius: 10px; padding: 16px; }}
  .stat-val {{ font-size: 32px; font-weight: 700; color: #38bdf8; }}
  .stat-lbl {{ font-size: 12px; color: #64748b; margin-top: 4px; }}
  table {{ width: 100%; border-collapse: collapse; background: #1e293b;
          border-radius: 10px; overflow: hidden; font-size: 13px; }}
  th {{ background: #334155; color: #94a3b8; font-weight: 600; padding: 10px 12px;
       text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }}
  td {{ padding: 9px 12px; border-bottom: 1px solid #0f172a; color: #cbd5e1; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: #273344; }}
</style>
</head>
<body>
<h1>Aimfox Analytics Report</h1>
<div class="ts">Generated: {ts}</div>

<div class="stats">
  <div class="stat"><div class="stat-val">{len(campaigns)}</div><div class="stat-lbl">Total Campaigns</div></div>
  <div class="stat"><div class="stat-val">{active_camps}</div><div class="stat-lbl">Active Campaigns</div></div>
  <div class="stat"><div class="stat-val">{total_accepted}</div><div class="stat-lbl">Connections Accepted</div></div>
  <div class="stat"><div class="stat-val">{total_replies}</div><div class="stat-lbl">Replies Received</div></div>
</div>

<h2>Campaigns</h2>
<table>
  <thead><tr>
    <th>Campaign</th><th>State</th><th>Type</th><th>Targets</th>
    <th>Done%</th><th>Accepted</th><th>Replies</th><th>Created</th>
  </tr></thead>
  <tbody>{camp_rows}</tbody>
</table>

<h2>Recent Lead Events</h2>
<table>
  <thead><tr>
    <th>Event</th><th>Lead</th><th>Occupation</th>
    <th>Campaign</th><th>Account</th><th>Date</th>
  </tr></thead>
  <tbody>{leads_rows}</tbody>
</table>

<h2>Conversations ({len(conversations)} active)</h2>
{conv_html}

</body>
</html>"""

    for path in [_fname("report", "html"), _latest_fname("report", "html")]:
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
    return path


# ── Master save ───────────────────────────────────────────────────────────────

def save_all(accounts: list, campaigns: list, recent_leads: list,
             conversations: list) -> dict:
    data = {
        "generated_at": datetime.now().isoformat(),
        "accounts": accounts,
        "campaigns": campaigns,
        "recent_leads": recent_leads,
        "conversations": [
            {k: v for k, v in c.items() if k != "_messages"} | {"messages": c.get("_messages", [])}
            for c in conversations
        ],
    }
    paths = {
        "json": save_json(data),
        "csv_campaigns": save_csv_campaigns(campaigns),
        "csv_leads": save_csv_recent_leads(recent_leads),
        "csv_conversations": save_csv_conversations(conversations),
        "html": save_html_report(accounts, campaigns, recent_leads, conversations),
    }
    return paths
