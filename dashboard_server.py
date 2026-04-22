"""
Aimfox Live Dashboard Server
-----------------------------
Real-time dashboard — fetches fresh data from Aimfox API on every refresh.
Cached for 2 minutes so rapid refreshes are instant.

Run:  python dashboard_server.py
Open: http://localhost:8080
"""

import os, sys, logging, time
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
CACHE_TTL = 30  # seconds

_cache = {"data": None, "ts": 0}


def owners_list(owners_val):
    """Normalise owners to always be a list of strings."""
    if not owners_val:
        return []
    if isinstance(owners_val, list):
        return [str(o) for o in owners_val]
    # analytics.py joins owners into a comma-separated string
    return [o.strip() for o in str(owners_val).split(",") if o.strip()]


def get_live_data(force=False):
    now = time.time()
    if not force and _cache["data"] and (now - _cache["ts"]) < CACHE_TTL:
        return _cache["data"]

    client = AimfoxClient()
    accounts  = fetch_accounts(client)
    campaigns = fetch_campaigns(client)
    recent    = fetch_recent_leads(client)
    convos    = fetch_conversations_with_messages(client)
    rows      = build_campaign_stats(campaigns, recent)

    # Normalise owners in every row to a list
    for r in rows:
        r["owners"] = owners_list(r.get("owners"))

    _cache["data"] = (accounts, rows, recent, convos)
    _cache["ts"] = now
    return _cache["data"]


def build_stats(accounts, campaigns, recent_leads, convos, filter_id=None):
    acc_map = {a["id"]: a for a in accounts}

    filtered_camps = [
        c for c in campaigns
        if not filter_id or filter_id in owners_list(c.get("owners"))
    ]
    filtered_convos = [
        c for c in convos
        if not filter_id or str(c.get("owner", "")) == filter_id
    ]
    connected = [c for c in filtered_convos if c.get("connected")]

    targets  = sum(c.get("targets", 0) or 0 for c in filtered_camps)
    accepted = sum(c.get("accepted_recent", 0) for c in filtered_camps)
    replies  = sum(c.get("replies_recent", 0) for c in filtered_camps)

    messages_sent = 0
    for conv in connected:
        acc = acc_map.get(conv.get("owner", ""), {})
        acc_name = acc.get("full_name", "")
        for msg in conv.get("_messages", []):
            sender = (msg.get("sender") or {}).get("full_name", "")
            if msg.get("automated") or sender == acc_name:
                messages_sent += 1

    return {
        "targets_sent":       targets,
        "accepted":           accepted,
        "replies":            replies,
        "messages_sent":      messages_sent,
        "active_campaigns":   sum(1 for c in filtered_camps if c.get("state") == "ACTIVE"),
        "total_campaigns":    len(filtered_camps),
        "active_conversations": len(connected),
        "unread_messages":    sum(c.get("unread_count", 0) for c in filtered_convos),
        "accept_rate":  f"{accepted/targets*100:.1f}%" if targets  else "—",
        "reply_rate":   f"{replies/accepted*100:.1f}%" if accepted else "—",
    }


@app.route("/api/data")
def api_data():
    force = False  # set True if you add ?refresh=1 later
    try:
        accounts, campaigns, recent, convos = get_live_data(force)
        acc_map = {a["id"]: a.get("full_name", a["id"]) for a in accounts}

        # Per-account stats
        account_stats = []
        for acc in accounts:
            s = build_stats(accounts, campaigns, recent, convos, acc["id"])
            account_stats.append({
                "id":         acc["id"],
                "name":       acc.get("full_name", acc["id"]),
                "picture":    acc.get("picture_url", ""),
                "occupation": acc.get("occupation", ""),
                "premium":    acc.get("premium", False),
                "state":      acc.get("state", ""),
                "stats":      s,
            })

        # Campaigns — send owners as list of IDs + owner_names as list of names
        camp_list = []
        for c in campaigns:
            ow = owners_list(c.get("owners"))
            camp_list.append({
                **{k: v for k, v in c.items() if k != "owners"},
                "owners":      ow,
                "owner_names": [acc_map.get(o, o) for o in ow],
            })

        # Recent leads
        leads_list = [{
            "transition":        e.get("transition", ""),
            "timestamp":         (e.get("timestamp") or "")[:10],
            "campaign_name":     e.get("campaign_name", ""),
            "account_id":        e.get("account_id", ""),
            "account_name":      acc_map.get(e.get("account_id", ""), ""),
            "target_name":       (e.get("target") or {}).get("full_name", ""),
            "target_occupation": (e.get("target") or {}).get("occupation", ""),
        } for e in recent]

        # Conversations
        conv_list = []
        for conv in convos:
            parts = conv.get("participants", [])
            lead  = parts[0] if parts else {}
            msgs  = []
            for msg in conv.get("_messages", []):
                body = (msg.get("body") or "").strip()
                if body or msg.get("attachments"):
                    msgs.append({
                        "sender":    (msg.get("sender") or {}).get("full_name", ""),
                        "body":      body[:300] if body else "[attachment]",
                        "automated": msg.get("automated", False),
                        "date":      str(msg.get("created_at", ""))[:10],
                    })
            conv_list.append({
                "owner":            conv.get("owner", ""),
                "owner_name":       acc_map.get(conv.get("owner", ""), ""),
                "connected":        conv.get("connected", False),
                "unread":           conv.get("unread_count", 0),
                "lead_name":        lead.get("full_name", ""),
                "lead_picture":     lead.get("picture_url", ""),
                "lead_occupation":  lead.get("occupation", ""),
                "messages":         msgs,
            })

        return jsonify({
            "overall":      build_stats(accounts, campaigns, recent, convos),
            "accounts":     account_stats,
            "campaigns":    camp_list,
            "recent_leads": leads_list,
            "conversations":conv_list,
            "cached":       (time.time() - _cache["ts"]) < CACHE_TTL,
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
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f1f5f9;color:#1e293b}
.topbar{background:#fff;border-bottom:1px solid #e2e8f0;padding:0 32px;display:flex;align-items:center;justify-content:space-between;height:58px;position:sticky;top:0;z-index:100;box-shadow:0 1px 4px rgba(0,0,0,.06)}
.logo{font-size:17px;font-weight:700;color:#2563eb;letter-spacing:-.3px}
.logo span{color:#1e293b}
.topbar-right{display:flex;align-items:center;gap:14px}
.last-updated{font-size:12px;color:#94a3b8}
.cached-badge{font-size:11px;color:#f59e0b;background:#fef3c7;padding:2px 8px;border-radius:20px;font-weight:600}
.refresh-btn{background:#2563eb;color:#fff;border:none;padding:8px 18px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;display:flex;align-items:center;gap:6px;transition:all .2s}
.refresh-btn:hover{background:#1d4ed8}
.refresh-btn:disabled{background:#94a3b8;cursor:not-allowed}
.main{max-width:1380px;margin:0 auto;padding:24px 28px}
/* Filter bar */
.filter-bar{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:12px 18px;margin-bottom:24px;display:flex;align-items:center;gap:16px;box-shadow:0 1px 3px rgba(0,0,0,.04)}
.filter-lbl{font-size:11px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;white-space:nowrap}
/* Account dropdown */
.acc-dd{position:relative;min-width:240px}
.acc-trigger{display:flex;align-items:center;gap:9px;padding:8px 12px;background:#f8fafc;border:1.5px solid #e2e8f0;border-radius:8px;cursor:pointer;user-select:none;font-size:13px;font-weight:600;color:#1e293b;transition:border-color .15s,background .15s}
.acc-trigger:hover,.acc-trigger.open{border-color:#2563eb;background:#eff6ff;color:#2563eb}
.acc-tav{width:26px;height:26px;border-radius:50%;background:#dbeafe;color:#2563eb;font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center;overflow:hidden;flex-shrink:0}
.acc-tav img{width:26px;height:26px;border-radius:50%;object-fit:cover}
.acc-tname{flex:1}
.dd-chev{flex-shrink:0;transition:transform .2s;color:#94a3b8}
.acc-menu{position:absolute;top:calc(100% + 6px);left:0;min-width:280px;background:#fff;border:1px solid #e2e8f0;border-radius:10px;box-shadow:0 8px 28px rgba(0,0,0,.13);z-index:300;overflow:hidden;display:none}
.acc-menu.open{display:block}
.acc-opt{display:flex;align-items:center;gap:10px;padding:10px 14px;cursor:pointer;font-size:13px;color:#374151;transition:background .1s;border-bottom:1px solid #f8fafc}
.acc-opt:last-child{border-bottom:none}
.acc-opt:hover{background:#f1f5f9}
.acc-opt.sel{background:#eff6ff;color:#2563eb}
.acc-oav{width:32px;height:32px;border-radius:50%;background:#dbeafe;color:#2563eb;font-size:12px;font-weight:700;display:flex;align-items:center;justify-content:center;overflow:hidden;flex-shrink:0}
.acc-oav img{width:32px;height:32px;border-radius:50%;object-fit:cover}
.acc-oinfo{flex:1;min-width:0}
.acc-oname{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.acc-osub{font-size:11px;color:#94a3b8;margin-top:2px}
.unread-pill{background:#ef4444;color:#fff;border-radius:20px;padding:1px 7px;font-size:10px;font-weight:700;line-height:1.5;flex-shrink:0}
/* Stats */
.stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:24px}
@media(max-width:800px){.stats-grid{grid-template-columns:repeat(2,1fr)}}
.stat{background:#fff;border-radius:12px;padding:18px 20px;border:1px solid #e2e8f0;box-shadow:0 1px 3px rgba(0,0,0,.04);position:relative;overflow:hidden}
.stat::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;border-radius:12px 12px 0 0}
.stat.blue::before{background:#2563eb}
.stat.green::before{background:#16a34a}
.stat.purple::before{background:#7c3aed}
.stat.orange::before{background:#ea580c}
.stat-val{font-size:34px;font-weight:800;line-height:1;margin-bottom:6px}
.stat.blue .stat-val{color:#2563eb}
.stat.green .stat-val{color:#16a34a}
.stat.purple .stat-val{color:#7c3aed}
.stat.orange .stat-val{color:#ea580c}
.stat-lbl{font-size:13px;color:#64748b;font-weight:500}
.stat-sub{font-size:11px;color:#22c55e;margin-top:4px;font-weight:600}
/* Cards */
.card{background:#fff;border-radius:12px;border:1px solid #e2e8f0;box-shadow:0 1px 3px rgba(0,0,0,.04);margin-bottom:20px;overflow:hidden}
.card-head{padding:14px 18px;border-bottom:1px solid #f1f5f9;display:flex;align-items:center;justify-content:space-between}
.card-head h3{font-size:14px;font-weight:700;color:#1e293b}
.count-pill{font-size:12px;color:#64748b;background:#f1f5f9;padding:2px 10px;border-radius:20px;font-weight:600}
table{width:100%;border-collapse:collapse;font-size:13px}
th{padding:9px 14px;text-align:left;font-size:10px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:.6px;border-bottom:1px solid #f1f5f9;background:#fafbfc;white-space:nowrap}
td{padding:11px 14px;border-bottom:1px solid #f8fafc;color:#374151;vertical-align:middle}
tr:last-child td{border-bottom:none}
tr:hover td{background:#fafbff}
.badge{display:inline-block;padding:2px 9px;border-radius:20px;font-size:11px;font-weight:700;white-space:nowrap}
.b-active{background:#dcfce7;color:#16a34a}
.b-done{background:#ede9fe;color:#7c3aed}
.b-init{background:#fef3c7;color:#b45309}
.b-paused{background:#fee2e2;color:#dc2626}
.b-accepted{background:#dcfce7;color:#16a34a}
.b-reply{background:#dbeafe;color:#2563eb}
/* Conversations */
.conv-list{padding:10px 14px}
.conv-item{border:1px solid #e2e8f0;border-radius:10px;margin-bottom:8px;overflow:hidden}
.conv-header{padding:11px 14px;background:#fafafa;display:flex;align-items:center;gap:10px;cursor:pointer;user-select:none;transition:background .1s}
.conv-header:hover{background:#f1f5f9}
.av{width:38px;height:38px;border-radius:50%;background:#dbeafe;color:#2563eb;font-size:14px;font-weight:700;display:flex;align-items:center;justify-content:center;flex-shrink:0;overflow:hidden}
.av img{width:38px;height:38px;border-radius:50%;object-fit:cover}
.conv-info{flex:1;min-width:0}
.conv-name{font-size:13px;font-weight:600;color:#1e293b}
.conv-occ{font-size:11px;color:#94a3b8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:1px}
.conv-right{display:flex;align-items:center;gap:8px;flex-shrink:0}
.chev{font-size:10px;color:#94a3b8;transition:transform .2s}
.conv-body{display:none;padding:14px;background:#fff;border-top:1px solid #f1f5f9;max-height:380px;overflow-y:auto}
.conv-body.open{display:block}
.msg-row{display:flex;gap:8px;margin-bottom:10px;align-items:flex-start}
.msg-row.sent{flex-direction:row-reverse}
.msg-av{width:28px;height:28px;border-radius:50%;background:#f1f5f9;color:#64748b;font-size:10px;font-weight:700;display:flex;align-items:center;justify-content:center;flex-shrink:0;margin-top:2px}
.msg-bubble{max-width:70%;padding:8px 12px;border-radius:12px;font-size:12px;line-height:1.55}
.msg-row.received .msg-bubble{background:#f1f5f9;color:#1e293b;border-bottom-left-radius:3px}
.msg-row.sent .msg-bubble{background:#eff6ff;color:#1e40af;border-bottom-right-radius:3px}
.msg-meta{font-size:10px;color:#94a3b8;margin-bottom:3px}
.auto-tag{color:#7c3aed;font-weight:600}
#loading{position:fixed;inset:0;background:rgba(255,255,255,.9);display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:999;gap:14px}
.spinner{width:42px;height:42px;border:3px solid #e2e8f0;border-top-color:#2563eb;border-radius:50%;animation:spin .75s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.load-txt{font-size:14px;color:#64748b;font-weight:500}
#err{background:#fef2f2;border:1px solid #fecaca;color:#dc2626;padding:14px 18px;border-radius:10px;margin-bottom:18px;font-size:13px;display:none}
</style>
</head>
<body>

<div id="loading">
  <div class="spinner"></div>
  <div class="load-txt">Fetching live data from Aimfox...</div>
</div>

<div class="topbar">
  <div class="logo">Aimfox <span>Dashboard</span></div>
  <div class="topbar-right">
    <div class="last-updated" id="last-updated"></div>
    <span class="cached-badge" id="cached-badge" style="display:none">Cached</span>
    <button class="refresh-btn" id="refresh-btn" onclick="loadData()">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
      Refresh
    </button>
  </div>
</div>

<div class="main">
  <div id="err"></div>

  <!-- Account dropdown filter -->
  <div class="filter-bar">
    <span class="filter-lbl">Filter by Account</span>
    <div class="acc-dd" id="acc-dd">
      <div class="acc-trigger" id="acc-trigger">
        <div class="acc-tav" id="acc-tav"><span style="width:10px;height:10px;border-radius:50%;background:#22c55e;display:inline-block"></span></div>
        <span class="acc-tname" id="acc-tname">All Accounts</span>
        <svg class="dd-chev" id="dd-chev" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
      </div>
      <div class="acc-menu" id="acc-menu"></div>
    </div>
  </div>

  <!-- Stats cards -->
  <div class="stats-grid" id="stats-grid"></div>

  <!-- Conversations (right after stats) -->
  <div class="card">
    <div class="card-head">
      <h3>Conversations</h3>
      <span class="count-pill" id="conv-count"></span>
    </div>
    <div class="conv-list" id="conv-list"></div>
  </div>

  <!-- Campaigns -->
  <div class="card">
    <div class="card-head">
      <h3>Campaigns</h3>
      <span class="count-pill" id="camp-count"></span>
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
    <div class="card-head">
      <h3>Recent Lead Events</h3>
      <span class="count-pill" id="leads-count"></span>
    </div>
    <table>
      <thead><tr>
        <th>Event</th><th>Lead</th><th>Occupation</th>
        <th>Campaign</th><th>Account</th><th>Date</th>
      </tr></thead>
      <tbody id="leads-body"></tbody>
    </table>
  </div>
</div>

<script>
let D = null, activeAcc = 'all';

async function loadData() {
  const btn = document.getElementById('refresh-btn');
  btn.disabled = true;
  btn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="animation:spin .75s linear infinite"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg> Loading...';
  document.getElementById('loading').style.display = 'flex';
  document.getElementById('err').style.display = 'none';
  try {
    const r = await fetch('/api/data');
    if (!r.ok) throw new Error('HTTP ' + r.status);
    D = await r.json();
    if (D.error) throw new Error(D.error);
    render();
    document.getElementById('last-updated').textContent = 'Updated ' + new Date().toLocaleTimeString();
    const cb = document.getElementById('cached-badge');
    cb.style.display = D.cached ? 'inline-block' : 'none';
  } catch(e) {
    const eb = document.getElementById('err');
    eb.textContent = 'Error: ' + e.message;
    eb.style.display = 'block';
  } finally {
    document.getElementById('loading').style.display = 'none';
    btn.disabled = false;
    btn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg> Refresh';
  }
}

document.addEventListener('click', () => {
  document.getElementById('acc-menu')?.classList.remove('open');
  document.getElementById('acc-trigger')?.classList.remove('open');
  const chev = document.getElementById('dd-chev');
  if (chev) chev.style.transform = '';
});

function render() { renderDropdown(); renderStats(); renderConvos(); renderCampaigns(); renderLeads(); }

function renderDropdown() {
  const sel = String(activeAcc);
  // Build menu
  let opts = `<div class="acc-opt ${sel==='all'?'sel':''}" data-acc="all">
    <div class="acc-oav"><span style="width:10px;height:10px;border-radius:50%;background:#22c55e;display:inline-block"></span></div>
    <div class="acc-oinfo"><div class="acc-oname">All Accounts</div><div class="acc-osub">${D.accounts.length} accounts</div></div>
  </div>`;
  for (const a of D.accounts) {
    const aid = String(a.id);
    const init = (a.name||'?')[0].toUpperCase();
    const avHtml = a.picture
      ? `<img src="${a.picture}" onerror="this.style.display='none'">`
      : init;
    const unread = a.stats.unread_messages > 0 ? `<span class="unread-pill">${a.stats.unread_messages}</span>` : '';
    opts += `<div class="acc-opt ${sel===aid?'sel':''}" data-acc="${aid}">
      <div class="acc-oav">${avHtml}</div>
      <div class="acc-oinfo">
        <div class="acc-oname">${a.name}</div>
        <div class="acc-osub">${a.stats.active_conversations} convos &middot; ${a.stats.messages_sent} msgs sent</div>
      </div>
      ${unread}
    </div>`;
  }
  document.getElementById('acc-menu').innerHTML = opts;

  // Update trigger
  const tav = document.getElementById('acc-tav');
  const tname = document.getElementById('acc-tname');
  if (sel === 'all') {
    tav.innerHTML = `<span style="width:10px;height:10px;border-radius:50%;background:#22c55e;display:inline-block"></span>`;
    tname.textContent = 'All Accounts';
  } else {
    const acc = D.accounts.find(a => String(a.id) === sel);
    if (acc) {
      const init = (acc.name||'?')[0].toUpperCase();
      tav.innerHTML = acc.picture ? `<img src="${acc.picture}" style="width:26px;height:26px;border-radius:50%;object-fit:cover" onerror="this.parentElement.textContent='${init}'">` : init;
      tname.textContent = acc.name.split(' ').slice(0,2).join(' ');
    }
  }

  // Wire dropdown toggle (idempotent)
  const trigger = document.getElementById('acc-trigger');
  trigger.onclick = e => {
    e.stopPropagation();
    const menu = document.getElementById('acc-menu');
    const chev = document.getElementById('dd-chev');
    const isOpen = menu.classList.toggle('open');
    trigger.classList.toggle('open', isOpen);
    chev.style.transform = isOpen ? 'rotate(180deg)' : '';
  };
  document.getElementById('acc-menu').onclick = e => {
    e.stopPropagation();
    const opt = e.target.closest('[data-acc]');
    if (opt) {
      document.getElementById('acc-menu').classList.remove('open');
      document.getElementById('acc-trigger').classList.remove('open');
      document.getElementById('dd-chev').style.transform = '';
      setAcc(opt.dataset.acc);
    }
  };
}

function curStats() {
  if (activeAcc === 'all') return D.overall;
  return (D.accounts.find(a => String(a.id) === String(activeAcc)) || {stats: D.overall}).stats;
}

function renderStats() {
  const s = curStats();
  document.getElementById('stats-grid').innerHTML = `
    <div class="stat blue">
      <div class="stat-val">${(s.targets_sent||0).toLocaleString()}</div>
      <div class="stat-lbl">Requests Sent</div>
      <div class="stat-sub">${s.total_campaigns} campaign${s.total_campaigns!==1?'s':''}</div>
    </div>
    <div class="stat green">
      <div class="stat-val">${(s.accepted||0).toLocaleString()}</div>
      <div class="stat-lbl">Connections Accepted</div>
      <div class="stat-sub">Rate: ${s.accept_rate}</div>
    </div>
    <div class="stat purple">
      <div class="stat-val">${(s.messages_sent||0).toLocaleString()}</div>
      <div class="stat-lbl">Messages Sent</div>
      <div class="stat-sub">${s.active_conversations} active conversation${s.active_conversations!==1?'s':''}</div>
    </div>
    <div class="stat orange">
      <div class="stat-val">${(s.replies||0).toLocaleString()}</div>
      <div class="stat-lbl">Replies Received</div>
      <div class="stat-sub">Rate: ${s.reply_rate}</div>
    </div>`;
}

function fCamps() {
  if (activeAcc === 'all') return D.campaigns;
  return D.campaigns.filter(c => Array.isArray(c.owners) && c.owners.includes(activeAcc));
}
function fLeads() {
  if (activeAcc === 'all') return D.recent_leads;
  return D.recent_leads.filter(l => String(l.account_id) === String(activeAcc));
}
function fConvos() {
  if (activeAcc === 'all') return D.conversations;
  return D.conversations.filter(c => String(c.owner) === String(activeAcc));
}

const SB = {ACTIVE:'b-active',DONE:'b-done',INIT:'b-init',PAUSED:'b-paused'};
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}

function renderCampaigns() {
  const camps = fCamps();
  document.getElementById('camp-count').textContent = camps.length;
  document.getElementById('camp-body').innerHTML = camps.map(c=>`<tr>
    <td style="font-weight:500">${esc(c.name)}</td>
    <td><span class="badge ${SB[c.state]||'b-init'}">${c.state}</span></td>
    <td style="color:#64748b">${c.type}</td>
    <td><b>${(c.targets||0).toLocaleString()}</b></td>
    <td style="color:#16a34a;font-weight:700">${c.accepted_recent||0}</td>
    <td style="color:#2563eb;font-weight:700">${c.replies_recent||0}</td>
    <td style="color:#64748b;font-size:12px">${(c.owner_names||[]).join(', ')}</td>
    <td style="color:#94a3b8;font-size:12px">${c.created||''}</td>
  </tr>`).join('');
}

function renderLeads() {
  const leads = fLeads();
  document.getElementById('leads-count').textContent = leads.length;
  document.getElementById('leads-body').innerHTML = leads.map(l=>`<tr>
    <td><span class="badge ${l.transition==='accepted'?'b-accepted':'b-reply'}">${l.transition.toUpperCase()}</span></td>
    <td style="font-weight:600">${esc(l.target_name)}</td>
    <td style="color:#64748b;font-size:12px">${esc((l.target_occupation||'').slice(0,55))}</td>
    <td style="font-size:12px">${esc(l.campaign_name)}</td>
    <td style="color:#64748b;font-size:12px">${esc(l.account_name)}</td>
    <td style="color:#94a3b8;font-size:12px">${l.timestamp}</td>
  </tr>`).join('');
}

function renderConvos() {
  const convos = fConvos();
  document.getElementById('conv-count').textContent = convos.length;
  document.getElementById('conv-list').innerHTML = convos.map((conv,i) => {
    const init = (conv.lead_name||'?')[0].toUpperCase();
    const msgs = conv.messages.map(m => {
      const sent = m.automated;
      return `<div class="msg-row ${sent?'sent':'received'}">
        <div class="msg-av">${(m.sender||'?')[0].toUpperCase()}</div>
        <div>
          <div class="msg-meta">${esc(m.sender)}${m.automated?' <span class="auto-tag">[auto]</span>':''} · ${m.date}</div>
          <div class="msg-bubble">${esc(m.body)}</div>
        </div>
      </div>`;
    }).join('');
    return `<div class="conv-item">
      <div class="conv-header" onclick="toggleConv(${i})">
        <div class="av">${conv.lead_picture?`<img src="${conv.lead_picture}" onerror="this.parentElement.textContent='${init}'">`:init}</div>
        <div class="conv-info">
          <div class="conv-name">${esc(conv.lead_name)}</div>
          <div class="conv-occ">${esc((conv.lead_occupation||'').slice(0,65))}</div>
        </div>
        <div class="conv-right">
          ${conv.unread>0?`<span class="unread-pill">${conv.unread}</span>`:''}
          <span style="font-size:11px;color:#94a3b8">${conv.messages.length} msgs</span>
          <span style="font-size:11px;color:#64748b">${esc(conv.owner_name)}</span>
          <span class="chev" id="chev-${i}">▼</span>
        </div>
      </div>
      <div class="conv-body" id="cb-${i}">${msgs}</div>
    </div>`;
  }).join('');
}

function toggleConv(i) {
  const b = document.getElementById('cb-'+i), ch = document.getElementById('chev-'+i);
  b.classList.toggle('open');
  ch.style.transform = b.classList.contains('open') ? 'rotate(180deg)' : '';
}
function setAcc(id) { activeAcc = id; render(); }

loadData();
</script>
</body>
</html>"""

if __name__ == "__main__":
    log.info("Aimfox Live Dashboard -> http://localhost:%d", PORT)
    app.run(host="0.0.0.0", port=PORT, debug=False)
