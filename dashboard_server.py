"""
Aimfox Live Dashboard Server
-----------------------------
Serves a real-time dashboard. Every browser refresh fetches fresh data
directly from the Aimfox API.

Run:
    python dashboard_server.py
Then open: http://localhost:8080
"""

import os
import sys
import logging
from flask import Flask, jsonify, render_template_string
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(__file__))

from aimfox_client import AimfoxClient
from analytics import (
    fetch_accounts, fetch_campaigns, fetch_recent_leads,
    fetch_conversations_with_messages, build_campaign_stats,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)
PORT = int(os.getenv("DASHBOARD_PORT", 8080))


def get_live_data():
    client = AimfoxClient()
    accounts   = fetch_accounts(client)
    campaigns  = fetch_campaigns(client)
    recent     = fetch_recent_leads(client)
    convos     = fetch_conversations_with_messages(client)
    camp_rows  = build_campaign_stats(campaigns, recent)
    return accounts, camp_rows, recent, convos


def build_stats(accounts, campaigns, recent_leads, convos, filter_account=None):
    """Build per-account and overall stats dict."""
    acc_map = {a["id"]: a for a in accounts}

    def match(owner_id):
        return filter_account is None or str(owner_id) == str(filter_account)

    # Campaigns for this account
    filtered_camps = [c for c in campaigns if not filter_account or
                      any(str(o) == str(filter_account) for o in (c.get("owners") or []))]

    targets_sent   = sum(c.get("targets", 0) or 0 for c in filtered_camps)
    accepted       = sum(c.get("accepted_recent", 0) for c in filtered_camps)
    replies        = sum(c.get("replies_recent", 0) for c in filtered_camps)
    active_camps   = sum(1 for c in filtered_camps if c.get("state") == "ACTIVE")

    # Conversations for this account
    filtered_convos = [c for c in convos if not filter_account or
                       str(c.get("owner", "")) == str(filter_account)]
    connected_convos = [c for c in filtered_convos if c.get("connected")]

    messages_sent = 0
    for conv in connected_convos:
        owner_id = conv.get("owner", "")
        acc = acc_map.get(owner_id, {})
        acc_name = acc.get("full_name", owner_id)
        for msg in conv.get("_messages", []):
            sender_name = (msg.get("sender") or {}).get("full_name", "")
            if sender_name == acc_name or msg.get("automated"):
                messages_sent += 1

    unread = sum(c.get("unread_count", 0) for c in filtered_convos)

    return {
        "targets_sent": targets_sent,
        "accepted": accepted,
        "replies": replies,
        "messages_sent": messages_sent,
        "active_campaigns": active_camps,
        "total_campaigns": len(filtered_camps),
        "active_conversations": len(connected_convos),
        "unread_messages": unread,
        "accept_rate": f"{accepted/targets_sent*100:.1f}%" if targets_sent else "—",
        "reply_rate": f"{replies/accepted*100:.1f}%" if accepted else "—",
    }


@app.route("/api/data")
def api_data():
    try:
        accounts, campaigns, recent, convos = get_live_data()

        # Overall stats
        overall = build_stats(accounts, campaigns, recent, convos)

        # Per-account stats
        account_stats = []
        for acc in accounts:
            s = build_stats(accounts, campaigns, recent, convos, acc["id"])
            account_stats.append({
                "id": acc["id"],
                "name": acc.get("full_name", acc["id"]),
                "state": acc.get("state", ""),
                "picture": acc.get("picture_url", ""),
                "occupation": acc.get("occupation", ""),
                "premium": acc.get("premium", False),
                "stats": s,
            })

        # Campaigns (with owner name)
        acc_map = {a["id"]: a.get("full_name", a["id"]) for a in accounts}
        camp_list = []
        for c in campaigns:
            owners = c.get("owners") or []
            camp_list.append({
                **c,
                "owner_names": [acc_map.get(o, o) for o in owners],
            })

        # Recent leads
        leads_list = []
        for e in recent:
            target = e.get("target") or {}
            leads_list.append({
                "transition": e.get("transition", ""),
                "timestamp": (e.get("timestamp") or "")[:10],
                "campaign_name": e.get("campaign_name", ""),
                "account_id": e.get("account_id", ""),
                "account_name": acc_map.get(e.get("account_id", ""), ""),
                "target_name": target.get("full_name", ""),
                "target_occupation": target.get("occupation", ""),
                "target_picture": target.get("picture_url", ""),
            })

        # Conversations
        conv_list = []
        for conv in convos:
            parts = conv.get("participants", [])
            lead = parts[0] if parts else {}
            messages = []
            for msg in conv.get("_messages", []):
                body = (msg.get("body") or "").strip()
                if body or msg.get("attachments"):
                    messages.append({
                        "sender": (msg.get("sender") or {}).get("full_name", ""),
                        "body": body[:300] if body else "[attachment]",
                        "automated": msg.get("automated", False),
                        "date": str(msg.get("created_at", ""))[:10],
                    })
            conv_list.append({
                "owner": conv.get("owner", ""),
                "owner_name": acc_map.get(conv.get("owner", ""), ""),
                "connected": conv.get("connected", False),
                "unread": conv.get("unread_count", 0),
                "lead_name": lead.get("full_name", ""),
                "lead_picture": lead.get("picture_url", ""),
                "lead_occupation": lead.get("occupation", ""),
                "messages": messages,
            })

        return jsonify({
            "overall": overall,
            "accounts": account_stats,
            "campaigns": camp_list,
            "recent_leads": leads_list,
            "conversations": conv_list,
        })
    except Exception as e:
        log.error("API error: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/")
def dashboard():
    return render_template_string(DASHBOARD_HTML)


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Aimfox Dashboard</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f5f7fa;color:#1e293b}
.topbar{background:#fff;border-bottom:1px solid #e2e8f0;padding:0 32px;display:flex;align-items:center;justify-content:space-between;height:60px;position:sticky;top:0;z-index:100;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.logo{font-size:18px;font-weight:700;color:#2563eb;letter-spacing:-.5px}
.logo span{color:#1e293b}
.refresh-btn{background:#2563eb;color:#fff;border:none;padding:8px 18px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;display:flex;align-items:center;gap:6px;transition:background .2s}
.refresh-btn:hover{background:#1d4ed8}
.refresh-btn.loading{background:#94a3b8;cursor:not-allowed}
.last-updated{font-size:12px;color:#94a3b8}
.main{max-width:1400px;margin:0 auto;padding:24px 32px}
.section-title{font-size:13px;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:.8px;margin-bottom:14px}
/* Account tabs */
.account-tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:28px;background:#fff;padding:12px;border-radius:12px;border:1px solid #e2e8f0;box-shadow:0 1px 3px rgba(0,0,0,.04)}
.tab{padding:8px 16px;border-radius:8px;cursor:pointer;font-size:13px;font-weight:500;color:#64748b;border:1.5px solid transparent;transition:all .15s;display:flex;align-items:center;gap:8px;white-space:nowrap}
.tab img{width:24px;height:24px;border-radius:50%;object-fit:cover;background:#e2e8f0}
.tab:hover{background:#f1f5f9;color:#1e293b}
.tab.active{background:#eff6ff;color:#2563eb;border-color:#bfdbfe;font-weight:600}
.tab .dot{width:7px;height:7px;border-radius:50%;background:#22c55e;flex-shrink:0}
/* Stat cards */
.stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:28px}
@media(max-width:900px){.stats-grid{grid-template-columns:repeat(2,1fr)}}
.stat-card{background:#fff;border-radius:12px;padding:20px;border:1px solid #e2e8f0;box-shadow:0 1px 3px rgba(0,0,0,.04)}
.stat-card .val{font-size:32px;font-weight:700;color:#1e293b;line-height:1}
.stat-card .lbl{font-size:12px;color:#94a3b8;margin-top:6px;font-weight:500}
.stat-card .rate{font-size:12px;color:#22c55e;margin-top:4px;font-weight:600}
.stat-card.blue .val{color:#2563eb}
.stat-card.green .val{color:#16a34a}
.stat-card.purple .val{color:#7c3aed}
.stat-card.orange .val{color:#ea580c}
/* Tables */
.card{background:#fff;border-radius:12px;border:1px solid #e2e8f0;box-shadow:0 1px 3px rgba(0,0,0,.04);margin-bottom:24px;overflow:hidden}
.card-header{padding:16px 20px;border-bottom:1px solid #f1f5f9;display:flex;align-items:center;justify-content:space-between}
.card-header h3{font-size:14px;font-weight:600;color:#1e293b}
.card-header .count{font-size:12px;color:#94a3b8;background:#f1f5f9;padding:2px 8px;border-radius:20px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{padding:10px 16px;text-align:left;font-size:11px;font-weight:600;color:#94a3b8;text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid #f1f5f9;white-space:nowrap}
td{padding:11px 16px;border-bottom:1px solid #f8fafc;color:#374151;vertical-align:middle}
tr:last-child td{border-bottom:none}
tr:hover td{background:#fafbfc}
.badge{display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:600}
.badge-active{background:#dcfce7;color:#16a34a}
.badge-done{background:#ede9fe;color:#7c3aed}
.badge-init{background:#fef3c7;color:#d97706}
.badge-paused{background:#fee2e2;color:#dc2626}
.badge-accepted{background:#dcfce7;color:#16a34a}
.badge-reply{background:#dbeafe;color:#2563eb}
/* Conversations */
.conv-list{padding:12px 16px}
.conv-item{border:1px solid #e2e8f0;border-radius:10px;margin-bottom:10px;overflow:hidden}
.conv-header{padding:12px 14px;background:#fafafa;display:flex;align-items:center;gap:10px;cursor:pointer;user-select:none}
.conv-header:hover{background:#f1f5f9}
.conv-avatar{width:36px;height:36px;border-radius:50%;object-fit:cover;background:#e2e8f0;flex-shrink:0}
.conv-info{flex:1;min-width:0}
.conv-name{font-weight:600;font-size:13px;color:#1e293b}
.conv-occ{font-size:11px;color:#94a3b8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.conv-meta{display:flex;align-items:center;gap:8px;flex-shrink:0}
.unread-badge{background:#ef4444;color:#fff;border-radius:20px;padding:1px 7px;font-size:11px;font-weight:700}
.msg-count{font-size:11px;color:#94a3b8}
.chevron{font-size:12px;color:#94a3b8;transition:transform .2s}
.conv-body{display:none;padding:12px 14px;background:#fff;border-top:1px solid #f1f5f9;max-height:320px;overflow-y:auto}
.conv-body.open{display:block}
.msg-row{display:flex;gap:8px;margin-bottom:10px}
.msg-row.sent{flex-direction:row-reverse}
.msg-bubble{max-width:72%;padding:8px 12px;border-radius:12px;font-size:12px;line-height:1.5}
.msg-row.received .msg-bubble{background:#f1f5f9;color:#1e293b;border-bottom-left-radius:4px}
.msg-row.sent .msg-bubble{background:#eff6ff;color:#1e40af;border-bottom-right-radius:4px}
.msg-sender{font-size:10px;color:#94a3b8;margin-bottom:2px}
.msg-auto{color:#7c3aed;font-size:10px}
.avatar-sm{width:26px;height:26px;border-radius:50%;background:#e2e8f0;flex-shrink:0;font-size:10px;display:flex;align-items:center;justify-content:center;color:#64748b;font-weight:600;margin-top:2px}
/* Loading */
#loading{position:fixed;inset:0;background:rgba(255,255,255,.8);display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:999;gap:12px}
.spinner{width:40px;height:40px;border:3px solid #e2e8f0;border-top-color:#2563eb;border-radius:50%;animation:spin .7s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.loading-text{font-size:14px;color:#64748b;font-weight:500}
#error-box{background:#fef2f2;border:1px solid #fecaca;color:#dc2626;padding:16px;border-radius:10px;margin-bottom:20px;display:none}
</style>
</head>
<body>

<div id="loading">
  <div class="spinner"></div>
  <div class="loading-text">Fetching live data from Aimfox...</div>
</div>

<div class="topbar">
  <div class="logo">Aimfox <span>Dashboard</span></div>
  <div style="display:flex;align-items:center;gap:16px">
    <div class="last-updated" id="last-updated"></div>
    <button class="refresh-btn" id="refresh-btn" onclick="loadData()">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
      Refresh
    </button>
  </div>
</div>

<div class="main">
  <div id="error-box"></div>

  <!-- Account Tabs -->
  <div class="section-title">Filter by Account</div>
  <div class="account-tabs" id="account-tabs"></div>

  <!-- Stats -->
  <div class="stats-grid" id="stats-grid"></div>

  <!-- Campaigns -->
  <div class="card">
    <div class="card-header">
      <h3>Campaigns</h3>
      <span class="count" id="camp-count">—</span>
    </div>
    <table>
      <thead><tr>
        <th>Campaign</th><th>State</th><th>Type</th>
        <th>Targets</th><th>Accepted</th><th>Replies</th><th>Account</th><th>Created</th>
      </tr></thead>
      <tbody id="camp-body"></tbody>
    </table>
  </div>

  <!-- Recent Leads -->
  <div class="card">
    <div class="card-header">
      <h3>Recent Lead Events</h3>
      <span class="count" id="leads-count">—</span>
    </div>
    <table>
      <thead><tr>
        <th>Event</th><th>Lead</th><th>Occupation</th>
        <th>Campaign</th><th>Account</th><th>Date</th>
      </tr></thead>
      <tbody id="leads-body"></tbody>
    </table>
  </div>

  <!-- Conversations -->
  <div class="card">
    <div class="card-header">
      <h3>Conversations</h3>
      <span class="count" id="conv-count">—</span>
    </div>
    <div class="conv-list" id="conv-list"></div>
  </div>
</div>

<script>
let allData = null;
let activeAccount = 'all';

async function loadData() {
  const btn = document.getElementById('refresh-btn');
  const loading = document.getElementById('loading');
  const errBox = document.getElementById('error-box');
  btn.classList.add('loading');
  btn.textContent = 'Loading...';
  loading.style.display = 'flex';
  errBox.style.display = 'none';

  try {
    const res = await fetch('/api/data');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    allData = await res.json();
    if (allData.error) throw new Error(allData.error);
    renderAll();
    document.getElementById('last-updated').textContent =
      'Updated: ' + new Date().toLocaleTimeString();
  } catch(e) {
    errBox.textContent = 'Error fetching data: ' + e.message;
    errBox.style.display = 'block';
  } finally {
    btn.classList.remove('loading');
    btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg> Refresh';
    loading.style.display = 'none';
  }
}

function renderAll() {
  renderTabs();
  renderStats();
  renderCampaigns();
  renderLeads();
  renderConversations();
}

function renderTabs() {
  const container = document.getElementById('account-tabs');
  let html = `<div class="tab ${activeAccount==='all'?'active':''}" onclick="setAccount('all')">
    <div class="dot"></div> All Accounts
  </div>`;
  for (const acc of allData.accounts) {
    const initial = acc.name.charAt(0).toUpperCase();
    html += `<div class="tab ${activeAccount===acc.id?'active':''}" onclick="setAccount('${acc.id}')">
      ${acc.picture
        ? `<img src="${acc.picture}" onerror="this.style.display='none'">`
        : `<div style="width:24px;height:24px;border-radius:50%;background:#dbeafe;color:#2563eb;font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center">${initial}</div>`}
      ${acc.name.split(' ').slice(0,2).join(' ')}
      ${acc.stats.unread_messages > 0 ? `<span class="unread-badge">${acc.stats.unread_messages}</span>` : ''}
    </div>`;
  }
  container.innerHTML = html;
}

function getCurrentStats() {
  if (activeAccount === 'all') return allData.overall;
  const acc = allData.accounts.find(a => a.id === activeAccount);
  return acc ? acc.stats : allData.overall;
}

function renderStats() {
  const s = getCurrentStats();
  document.getElementById('stats-grid').innerHTML = `
    <div class="stat-card blue">
      <div class="val">${s.targets_sent.toLocaleString()}</div>
      <div class="lbl">Requests Sent</div>
      <div class="rate">${s.total_campaigns} campaigns</div>
    </div>
    <div class="stat-card green">
      <div class="val">${s.accepted.toLocaleString()}</div>
      <div class="lbl">Connections Accepted</div>
      <div class="rate">Rate: ${s.accept_rate}</div>
    </div>
    <div class="stat-card purple">
      <div class="val">${s.messages_sent.toLocaleString()}</div>
      <div class="lbl">Messages Sent</div>
      <div class="rate">${s.active_conversations} active convos</div>
    </div>
    <div class="stat-card orange">
      <div class="val">${s.replies.toLocaleString()}</div>
      <div class="lbl">Replies Received</div>
      <div class="rate">Rate: ${s.reply_rate}</div>
    </div>`;
}

function filteredCamps() {
  if (activeAccount === 'all') return allData.campaigns;
  return allData.campaigns.filter(c =>
    (c.owners || []).some(o => String(o) === String(activeAccount)));
}

function filteredLeads() {
  if (activeAccount === 'all') return allData.recent_leads;
  return allData.recent_leads.filter(l => String(l.account_id) === String(activeAccount));
}

function filteredConvos() {
  if (activeAccount === 'all') return allData.conversations;
  return allData.conversations.filter(c => String(c.owner) === String(activeAccount));
}

const STATE_BADGE = {
  ACTIVE: 'badge-active', DONE: 'badge-done',
  INIT: 'badge-init', PAUSED: 'badge-paused'
};

function renderCampaigns() {
  const camps = filteredCamps();
  document.getElementById('camp-count').textContent = camps.length;
  document.getElementById('camp-body').innerHTML = camps.map(c => `
    <tr>
      <td style="font-weight:500;max-width:280px">${c.name}</td>
      <td><span class="badge ${STATE_BADGE[c.state]||'badge-init'}">${c.state}</span></td>
      <td style="color:#64748b">${c.type}</td>
      <td style="font-weight:600">${(c.targets||0).toLocaleString()}</td>
      <td style="color:#16a34a;font-weight:600">${c.accepted_recent||0}</td>
      <td style="color:#2563eb;font-weight:600">${c.replies_recent||0}</td>
      <td style="color:#64748b;font-size:12px">${(c.owner_names||[]).join(', ')}</td>
      <td style="color:#94a3b8;font-size:12px">${c.created||''}</td>
    </tr>`).join('');
}

function renderLeads() {
  const leads = filteredLeads();
  document.getElementById('leads-count').textContent = leads.length;
  document.getElementById('leads-body').innerHTML = leads.map(l => `
    <tr>
      <td><span class="badge ${l.transition==='accepted'?'badge-accepted':'badge-reply'}">${l.transition.toUpperCase()}</span></td>
      <td style="font-weight:500">${l.target_name}</td>
      <td style="color:#64748b;font-size:12px;max-width:200px">${(l.target_occupation||'').slice(0,55)}</td>
      <td style="max-width:200px;font-size:12px">${l.campaign_name}</td>
      <td style="color:#64748b;font-size:12px">${l.account_name}</td>
      <td style="color:#94a3b8;font-size:12px">${l.timestamp}</td>
    </tr>`).join('');
}

function renderConversations() {
  const convos = filteredConvos();
  document.getElementById('conv-count').textContent = convos.length;
  document.getElementById('conv-list').innerHTML = convos.map((conv, i) => {
    const msgs = conv.messages.map((m, j) => {
      const isSent = m.automated || (m.sender === conv.owner_name);
      return `<div class="msg-row ${isSent?'sent':'received'}">
        <div class="avatar-sm">${(m.sender||'?').charAt(0)}</div>
        <div>
          <div class="msg-sender">${m.sender||''}${m.automated?' <span class="msg-auto">[auto]</span>':''} · ${m.date}</div>
          <div class="msg-bubble">${m.body.replace(/</g,'&lt;').replace(/>/g,'&gt;')}</div>
        </div>
      </div>`;
    }).join('');

    return `<div class="conv-item">
      <div class="conv-header" onclick="toggleConv(${i})">
        <div class="avatar-sm" style="width:36px;height:36px;font-size:14px">${(conv.lead_name||'?').charAt(0)}</div>
        <div class="conv-info">
          <div class="conv-name">${conv.lead_name}</div>
          <div class="conv-occ">${(conv.lead_occupation||'').slice(0,60)}</div>
        </div>
        <div class="conv-meta">
          ${conv.unread > 0 ? `<span class="unread-badge">${conv.unread}</span>` : ''}
          <span class="msg-count">${conv.messages.length} msgs</span>
          <span style="font-size:11px;color:#94a3b8">${conv.owner_name}</span>
          <span class="chevron" id="chev-${i}">▼</span>
        </div>
      </div>
      <div class="conv-body" id="conv-body-${i}">${msgs}</div>
    </div>`;
  }).join('');
}

function toggleConv(i) {
  const body = document.getElementById('conv-body-' + i);
  const chev = document.getElementById('chev-' + i);
  const open = body.classList.toggle('open');
  chev.style.transform = open ? 'rotate(180deg)' : '';
}

function setAccount(id) {
  activeAccount = id;
  renderAll();
}

loadData();
</script>
</body>
</html>"""

if __name__ == "__main__":
    log.info("Aimfox Live Dashboard starting on http://localhost:%d", PORT)
    app.run(host="0.0.0.0", port=PORT, debug=False)
