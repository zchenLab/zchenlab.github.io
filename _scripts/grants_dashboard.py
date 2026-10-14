#!/usr/bin/env python3
"""
Build a dashboard of federal funding announcements in health economics,
health services research, health disparities and implementation science.

Why a generator rather than a live page: the Grants.gov search2 API only
accepts POST requests, which browsers block cross-origin from a page opened
off local disk. Python has no such restriction. So this script does the
fetching and writes a finished, self-contained HTML file you can open,
bookmark, mail to a colleague, or regenerate on a schedule.

    python3 grants_dashboard.py                  # titles only, about a minute
    python3 grants_dashboard.py --deep           # read full descriptions too, slower but far better recall
    python3 grants_dashboard.py --status posted  # drop forecasted announcements
    python3 grants_dashboard.py --out ~/Desktop/funding.html

Sources, both public and keyless:
  Grants.gov search2      https://grants.gov/api/api-guide
  NIH Guide RSS           https://grants.nih.gov/grants/guide/newsfeed/fundingopps.xml

Coverage note: NIH posts its NOFOs to Grants.gov, so they arrive through the
main query. NIH Guide *Notices* (NOT-xx-xxx policy changes, special emphasis
notices, notices of intent to publish) do not go to Grants.gov, and the RSS
feed carries only the newest one. For those, subscribe to the NIH Guide weekly
listserv; this dashboard shows whatever the feed holds and labels it clearly.
"""

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from datetime import date, datetime

SEARCH_URL = "https://api.grants.gov/v1/api/search2"
FETCH_URL = "https://api.grants.gov/v1/api/fetchOpportunity"
DETAIL_URL = "https://www.grants.gov/search-results-detail/{}"
NIH_RSS = "https://grants.nih.gov/grants/guide/newsfeed/fundingopps.xml"

# ---------------------------------------------------------------------------
# Scope. Edit these to change what the dashboard covers.
#   seeds   = what gets sent to Grants.gov. Its keyword search OR-matches every
#             word and has no phrase operator, so these only cast the net.
#   pattern = what actually decides whether an announcement belongs to a topic.
# ---------------------------------------------------------------------------
TOPICS = {
    "econ": {
        "label": "Health economics",
        "seeds": ["health economics", "cost effectiveness analysis", "economic evaluation health"],
        "pattern": re.compile(
            r"health econom|economic evaluation|cost[\s\-]?effectiveness|cost[\s\-]?benefit|"
            r"cost[\s\-]?utility|willingness to pay|economic burden|health care cost|healthcare cost|"
            r"value[\s\-]based (care|payment|purchasing)|payment model|health care financing", re.I),
    },
    "hsr": {
        "label": "Health services research",
        "seeds": ["health services research", "health care delivery", "quality of care"],
        "pattern": re.compile(
            r"health services research|care delivery|delivery system|quality of care|patient safety|"
            r"access to care|care coordination|health system|comparative effectiveness|"
            r"health care utilization|care transitions|learning health system", re.I),
    },
    "disp": {
        "label": "Health disparities & equity",
        "seeds": ["health disparities", "health equity", "minority health"],
        "pattern": re.compile(
            r"health disparit|health equity|health inequit|minority health|underserved|"
            r"social determinants|structural racism|rural health|tribal health|"
            r"populations? that experience|medically underserved", re.I),
    },
    "impl": {
        "label": "Implementation science",
        "seeds": ["implementation science", "dissemination implementation research", "evidence based practice uptake"],
        "pattern": re.compile(
            r"implementation science|implementation research|dissemination and implementation|"
            r"implementation strateg|de[\s\-]?implementation|scale[\s\-]?up|uptake of evidence|"
            r"evidence[\s\-]based (practice|intervention)|translat\w+ into practice|knowledge translation", re.I),
    },
}

PAGE, MAX_PAGES, PAUSE = 100, 10, 0.3


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def post(url, payload, attempts=3):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"})
    for i in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            if i == attempts - 1:
                raise RuntimeError(f"{url}: {e}") from e
            time.sleep(2 * (i + 1))


def search(keyword, statuses):
    out, start = [], 0
    for _ in range(MAX_PAGES):
        r = post(SEARCH_URL, {"keyword": keyword, "oppStatuses": statuses,
                              "rows": PAGE, "startRecordNum": start})
        if r.get("errorcode", 0) != 0:
            print(f"    ! {r.get('msg')}", file=sys.stderr)
            break
        data = r.get("data") or {}
        hits = data.get("oppHits") or []
        out += hits
        start += PAGE
        if not hits or start >= data.get("hitCount", 0):
            break
        time.sleep(PAUSE)
    return out


def describe(opp_id):
    try:
        r = post(FETCH_URL, {"opportunityId": int(opp_id)}, attempts=2)
    except Exception:
        return ""
    d = r.get("data") or {}
    blk = d.get("synopsis") or d.get("forecast") or {}
    raw = " ".join(filter(None, [blk.get("synopsisDesc"), blk.get("forecastDesc")]))
    return html.unescape(re.sub(r"<[^>]+>", " ", raw))


def nih_guide():
    """Whatever the NIH Guide feed is currently carrying."""
    try:
        with urllib.request.urlopen(NIH_RSS, timeout=30) as r:
            root = ET.fromstring(r.read())
    except Exception as e:
        print(f"  NIH Guide feed unavailable: {e}", file=sys.stderr)
        return []
    items = []
    for it in root.iterfind(".//item"):
        t = (it.findtext("title") or "").strip()
        blob = (it.findtext("description") or "") + " " + (it.findtext("link") or "")
        m = re.search(r"\b((?:NOT|PA|PAR|RFA)-[A-Z]{2}-\d{2}-\d{3})\b", blob)
        items.append({
            "id": "nih:" + t[:60],
            "title": t,
            "number": m.group(1) if m else "",
            "agency": "NIH Guide",
            "status": "guide",
            "doctype": "notice",
            "open": "", "close": "", "days": None, "aln": "",
            "url": (it.findtext("link") or "").replace("http://", "https://"),
            "blurb": (it.findtext("description") or "").strip(),
            "topics": [k for k, v in TOPICS.items() if v["pattern"].search(t)],
        })
    return items


# ---------------------------------------------------------------------------
# Shaping
# ---------------------------------------------------------------------------

def parse_date(s):
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except (ValueError, TypeError):
            pass
    return None


def collect(statuses, deep):
    pool = {}
    for key, cfg in TOPICS.items():
        print(f"Grants.gov · {cfg['label']}")
        for seed in cfg["seeds"]:
            hits = search(seed, statuses)
            print(f"    {seed!r} -> {len(hits)}")
            for h in hits:
                pool.setdefault(str(h.get("id")), h)
            time.sleep(PAUSE)
    print(f"\n{len(pool)} unique opportunities retrieved.")

    descs = {}
    if deep:
        print(f"Reading descriptions ({len(pool)} requests, a few minutes)…")
        for n, oid in enumerate(pool, 1):
            descs[oid] = describe(oid)
            if n % 25 == 0:
                print(f"    {n}/{len(pool)}")
            time.sleep(PAUSE)

    today, rows = date.today(), []
    for oid, h in pool.items():
        title = h.get("title") or ""
        desc = descs.get(oid, "")
        hits = [k for k, v in TOPICS.items() if v["pattern"].search(title + " " + desc)]
        if not hits:
            continue
        close = parse_date(h.get("closeDate") or "")
        rows.append({
            "id": oid,
            "title": title,
            "number": h.get("number") or "",
            "agency": h.get("agency") or h.get("agencyCode") or "Unknown",
            "status": (h.get("oppStatus") or "").lower(),
            "doctype": (h.get("docType") or "").lower(),
            "open": h.get("openDate") or "",
            "close": h.get("closeDate") or "",
            "days": (close - today).days if close else None,
            "aln": ", ".join(h.get("alnist") or []),
            "url": DETAIL_URL.format(oid),
            "blurb": re.sub(r"\s+", " ", desc)[:600],
            "topics": hits,
        })

    print(f"{len(rows)} match a topic.\nNIH Guide feed…")
    guide = [g for g in nih_guide() if g["topics"] or True]
    print(f"    {len(guide)} item(s)")
    rows += guide

    rows.sort(key=lambda r: (r["days"] is None, r["days"] if r["days"] is not None else 0))
    return rows


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Funding Watch · health systems research</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;500;700&family=Spectral:wght@400;600&display=swap" rel="stylesheet">
<style>
:root{
  color-scheme:light;
  --paper:#E6EAE8;--card:#FCFDFC;--sunk:#DDE3E0;--ink:#16211D;--muted:#5B6A65;
  --rule:#C3CDC8;--rule-soft:#D7DEDB;
  --posted:#2A6679;--forecasted:#A85C13;--closed:#6B7A75;--guide:#5B2E63;--urgent:#B41E45;
  box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px);
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  color-scheme:dark;
  --paper:#0F1614;--card:#17211E;--sunk:#1D2825;--ink:#DEE7E3;--muted:#93A39D;
  --rule:#2C3A36;--rule-soft:#232F2C;
  --posted:#79BBD2;--forecasted:#E0A05C;--closed:#8A9995;--guide:#C79BD0;--urgent:#F0718F;}}
:root[data-theme="dark"]{color-scheme:dark;
  --paper:#0F1614;--card:#17211E;--sunk:#1D2825;--ink:#DEE7E3;--muted:#93A39D;
  --rule:#2C3A36;--rule-soft:#232F2C;
  --posted:#79BBD2;--forecasted:#E0A05C;--closed:#8A9995;--guide:#C79BD0;--urgent:#F0718F;}
*,*::before,*::after{box-sizing:inherit}
html{scroll-padding-top:env(safe-area-inset-top,0px);-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);font-family:"Public Sans",system-ui,sans-serif;
  font-size:15px;line-height:1.5;font-variant-numeric:tabular-nums}
h1,h2,h3{font-family:Spectral,Georgia,serif;font-weight:600;margin:0;line-height:1.2}
a{color:inherit}
:focus-visible{outline:2px solid var(--posted);outline-offset:2px}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
.wrap{max-width:1180px;margin:0 auto;padding:0 20px 80px}
.mast{display:flex;flex-wrap:wrap;gap:16px;align-items:flex-end;justify-content:space-between;
  padding:28px 0 16px;border-bottom:2px solid var(--ink)}
.mast h1{font-size:30px;letter-spacing:-.01em}
.mast .back{display:inline-block;margin-bottom:6px;font-size:13px;color:var(--muted);text-decoration:none}
.mast .back:hover{color:var(--ink);text-decoration:underline}
.mast p{margin:4px 0 0;color:var(--muted);font-size:13.5px;max-width:56ch}
button,select,input[type=search]{font:inherit;font-size:13.5px;color:var(--ink);background:var(--card);
  border:1px solid var(--rule);border-radius:3px;padding:6px 9px}
button{cursor:pointer}button:hover{border-color:var(--ink)}
.status{display:flex;flex-wrap:wrap;gap:4px 20px;padding:14px 0;border-bottom:1px solid var(--rule);
  font-size:13.5px;color:var(--muted)}
.status b{color:var(--ink);font-weight:700}
.rail-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin:30px 0 12px}
.rail-head h2{font-size:21px}.rail-head span{font-size:12.5px;color:var(--muted)}
.rail{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(238px,268px);gap:10px;
  overflow-x:auto;overscroll-behavior-x:contain;padding-bottom:10px;scroll-snap-type:x proximity}
.rail::-webkit-scrollbar{height:8px}.rail::-webkit-scrollbar-thumb{background:var(--rule);border-radius:4px}
.dl{scroll-snap-align:start;display:flex;flex-direction:column;gap:7px;background:var(--card);
  border:1px solid var(--rule-soft);border-left:4px solid var(--posted);border-radius:3px;
  padding:12px 13px;text-decoration:none;min-height:134px}
.dl.soon{border-left-color:var(--urgent)}
.dl .days{font-size:22px;font-weight:700;line-height:1;letter-spacing:-.02em}
.dl.soon .days{color:var(--urgent)}
.dl .days small{font-size:11.5px;font-weight:500;color:var(--muted);margin-left:5px;letter-spacing:0}
.dl .ttl{font-family:Spectral,Georgia,serif;font-size:14.5px;line-height:1.3;
  display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.dl .meta{margin-top:auto;font-size:11.5px;color:var(--muted);line-height:1.35}
.panels{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:22px;margin-top:34px}
@media (max-width:860px){.panels{grid-template-columns:1fr}}
.panel{background:var(--card);border:1px solid var(--rule-soft);border-radius:3px;padding:16px 18px}
.panel h3{font-size:16.5px;margin-bottom:3px}
.panel .sub{font-size:12.5px;color:var(--muted);margin:0 0 14px}
table.matrix{width:100%;border-collapse:collapse;font-size:12.5px}
table.matrix th{font-weight:500;color:var(--muted);text-align:right;padding:5px 6px;font-size:11.5px}
table.matrix th.lbl{text-align:left;font-weight:400;color:var(--ink);font-size:12.5px;width:48%}
table.matrix td{text-align:right;padding:0}
table.matrix tr+tr th.lbl,table.matrix tr+tr td{border-top:1px solid var(--rule-soft)}
.cell{width:100%;border:0;background:transparent;text-align:right;padding:6px;color:var(--ink);border-radius:2px}
.cell[data-n="0"]{color:var(--rule)}.cell:hover:not([data-n="0"]){background:var(--sunk)}
.cell.on{background:var(--ink);color:var(--paper)}
.bars{display:grid;gap:7px}
.bar{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:center;font-size:12.5px}
.bar .n{color:var(--muted)}
.bar .track{height:16px;background:var(--sunk);border-radius:2px;overflow:hidden;position:relative}
.bar .fill{height:100%;background:var(--posted)}
.bar .nm{position:absolute;left:6px;top:0;line-height:16px;font-size:11.5px;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis;max-width:calc(100% - 12px);mix-blend-mode:difference;color:#fff}
.filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:34px;padding:14px 0;
  border-top:2px solid var(--ink);border-bottom:1px solid var(--rule)}
.filters input[type=search]{flex:1 1 220px;min-width:160px}
.chk{display:inline-flex;align-items:center;gap:6px;font-size:13px;color:var(--muted);cursor:pointer}
.spacer{flex:1 1 auto}
.ledger{margin:0;padding:0;list-style:none}
.op{border-bottom:1px solid var(--rule-soft);padding:15px 0}
.op-top{display:flex;gap:12px;align-items:baseline}
.tag{flex:0 0 auto;font-size:10.5px;font-weight:700;padding:2px 6px;border-radius:2px;
  border:1px solid currentColor;white-space:nowrap;text-transform:capitalize}
.tag.posted{color:var(--posted)}.tag.forecasted{color:var(--forecasted)}
.tag.closed,.tag.archived{color:var(--closed)}.tag.guide{color:var(--guide)}
.op h4{margin:0;font-family:Spectral,Georgia,serif;font-size:17px;font-weight:600;line-height:1.3}
.op h4 a{text-decoration:none;background:linear-gradient(var(--rule),var(--rule)) 0 100%/100% 1px no-repeat}
.op h4 a:hover{background-image:linear-gradient(var(--ink),var(--ink))}
.op-meta{display:flex;flex-wrap:wrap;gap:3px 14px;margin-top:6px;font-size:12.5px;color:var(--muted)}
.op-meta .due{color:var(--urgent);font-weight:500}
.blurb{margin:9px 0 0;font-family:Spectral,Georgia,serif;font-size:14.5px;line-height:1.6;max-width:76ch;
  display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.topics{display:flex;flex-wrap:wrap;gap:6px;margin-top:9px}
.topics span{font-size:11px;color:var(--muted);border:1px solid var(--rule-soft);border-radius:2px;padding:1px 6px}
.note{font-size:13px;color:var(--muted);padding:20px 0;max-width:64ch}
footer{margin-top:50px;padding-top:18px;border-top:1px solid var(--rule);font-size:12.5px;
  color:var(--muted);max-width:72ch}
</style></head><body><div class="wrap">

<header class="mast">
  <div>
    <a class="back" href="/tools/">&larr; Tools · zhuochen.org</a>
    <h1>Funding Watch</h1>
    <p>Federal announcements in health economics, health services research, health disparities
       and implementation science.</p>
  </div>
  <button id="theme">Dark</button>
</header>

<div class="status" id="status"></div>

<div class="rail-head"><h2>Closing soonest</h2><span id="railNote"></span></div>
<div class="rail" id="rail"></div>

<div class="panels">
  <section class="panel">
    <h3>Topics</h3>
    <p class="sub">An announcement can sit in more than one. Click a number to filter.</p>
    <div id="matrix"></div>
  </section>
  <section class="panel">
    <h3>Funders</h3>
    <p class="sub">Where these announcements come from.</p>
    <div class="bars" id="agencies"></div>
  </section>
</div>

<div class="filters">
  <input type="search" id="q" placeholder="Search titles and summaries" aria-label="Search">
  <select id="fStatus" aria-label="Status">
    <option value="">Any status</option><option value="posted">Posted</option>
    <option value="forecasted">Forecasted</option><option value="guide">NIH Guide</option>
  </select>
  <select id="fAgency" aria-label="Funder"><option value="">Any funder</option></select>
  <label class="chk"><input type="checkbox" id="fOpen"> Deadline still ahead</label>
  <span class="spacer"></span>
  <button id="csv">Download CSV</button>
</div>

<p class="note" id="count"></p>
<ul class="ledger" id="ledger"></ul>

<footer>
  Built __BUILT__ from Grants.gov search2 and the NIH Guide RSS feed, both public and keyless.
  Topic tags are assigned by keyword matching when this file was generated, not by the funders —
  a first pass, not a classification of record. Grants.gov carries NIH NOFOs but not NIH Guide
  Notices; for those, subscribe to the NIH Guide weekly listserv. Re-run the script to refresh.
</footer>
</div>

<script>
const ROWS = __DATA__;
const TOPICS = __TOPICS__;
const $ = id => document.getElementById(id);
let sel = null;

const link = u => /^https?:\/\//i.test(u || "") ? esc(u) : "#";
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

function visible(){
  const q = $("q").value.trim().toLowerCase(), st = $("fStatus").value,
        ag = $("fAgency").value, open = $("fOpen").checked;
  return ROWS.filter(r => {
    if (sel && !r.topics.includes(sel)) return false;
    if (st && r.status !== st) return false;
    if (ag && r.agency !== ag) return false;
    if (open && !(r.days !== null && r.days >= 0)) return false;
    if (q && !((r.title + " " + r.blurb + " " + r.number).toLowerCase().includes(q))) return false;
    return true;
  });
}

function renderStatus(){
  const open = ROWS.filter(r => r.days !== null && r.days >= 0);
  const soon = open.filter(r => r.days <= 30).length;
  const fc = ROWS.filter(r => r.status === "forecasted").length;
  $("status").innerHTML =
    `<span><b>${ROWS.length}</b> announcements</span>` +
    `<span><b>${open.length}</b> with a deadline ahead, <b>${soon}</b> within 30 days</span>` +
    `<span><b>${fc}</b> forecasted</span>` +
    `<span>built ${esc("__BUILT__")}</span>`;
}

function renderRail(){
  const open = ROWS.filter(r => r.days !== null && r.days >= 0)
                   .sort((a,b) => a.days - b.days).slice(0,24);
  $("railNote").textContent = open.length ? "Scroll for more." : "";
  if (!open.length){ $("rail").innerHTML = `<p class="note">No deadlines ahead in this set.</p>`; return; }
  $("rail").innerHTML = open.map(r => `
    <a class="dl ${r.days <= 30 ? "soon" : ""}" href="${link(r.url)}" target="_blank" rel="noopener">
      <span class="days">${r.days}<small>${r.days === 1 ? "day left" : "days left"}</small></span>
      <span class="ttl">${esc(r.title)}</span>
      <span class="meta">${esc(r.agency)}<br>${r.number ? esc(r.number) + " · " : ""}closes ${esc(r.close)}</span>
    </a>`).join("");
}

function renderMatrix(){
  const cols = [["posted","Posted"],["forecasted","Forecast"],["guide","Guide"]];
  const rows = Object.entries(TOPICS).map(([k,label]) => {
    const ds = ROWS.filter(r => r.topics.includes(k));
    return {k, label, total: ds.length, counts: cols.map(c => ds.filter(d => d.status === c[0]).length)};
  }).sort((a,b) => b.total - a.total);
  const peak = Math.max(1, ...rows.flatMap(r => r.counts));
  $("matrix").innerHTML = `<table class="matrix">
    <tr><th class="lbl"></th>${cols.map(c => `<th>${c[1]}</th>`).join("")}<th>All</th></tr>
    ${rows.map(r => `<tr><th class="lbl">${esc(r.label)}</th>
      ${r.counts.map((n,i) => `<td><button class="cell" data-n="${n}" data-k="${r.k}"
        style="${n ? `background:color-mix(in srgb, var(--${cols[i][0]}) ${Math.round(8+32*n/peak)}%, transparent)` : ""}"
        ${n ? "" : "disabled"}>${n || "·"}</button></td>`).join("")}
      <td><button class="cell${sel === r.k ? " on" : ""}" data-n="${r.total}" data-k="${r.k}"><b>${r.total}</b></button></td>
    </tr>`).join("")}</table>`;
  $("matrix").querySelectorAll(".cell").forEach(b => b.onclick = () => {
    sel = sel === b.dataset.k ? null : b.dataset.k;
    renderMatrix(); renderLedger();
  });
}

function renderAgencies(){
  const freq = new Map();
  ROWS.forEach(r => freq.set(r.agency, (freq.get(r.agency) || 0) + 1));
  const top = [...freq].sort((a,b) => b[1] - a[1]).slice(0,12);
  const peak = top.length ? top[0][1] : 1;
  $("agencies").innerHTML = top.map(([a,n]) => `
    <div class="bar"><div class="track"><div class="fill" style="width:${(100*n/peak).toFixed(1)}%"></div>
      <span class="nm">${esc(a)}</span></div><span class="n">${n}</span></div>`).join("");
  $("fAgency").innerHTML = `<option value="">Any funder</option>` +
    [...freq].sort((a,b) => b[1]-a[1]).map(([a,n]) => `<option value="${esc(a)}">${esc(a)} (${n})</option>`).join("");
}

function renderLedger(){
  const rows = visible();
  $("count").innerHTML = `Showing <b>${rows.length}</b> of ${ROWS.length}` +
    (sel ? ` · <b>${esc(TOPICS[sel])}</b> <button id="clr" style="border:0;background:none;text-decoration:underline;color:var(--muted);padding:0 0 0 4px">clear</button>` : "");
  if ($("clr")) $("clr").onclick = () => { sel = null; renderMatrix(); renderLedger(); };
  if (!rows.length){ $("ledger").innerHTML = `<li class="op"><p class="note">Nothing matches.</p></li>`; return; }
  $("ledger").innerHTML = rows.map(r => {
    const meta = [r.number, r.agency, r.aln ? "ALN " + r.aln : "", r.open ? "opens " + r.open : ""]
      .filter(Boolean).map(s => `<span>${esc(s)}</span>`).join("");
    const due = r.days === null ? "" :
      `<span class="${r.days >= 0 && r.days <= 30 ? "due" : ""}">${r.days >= 0
        ? `closes ${esc(r.close)} (${r.days}d)` : `closed ${esc(r.close)}`}</span>`;
    return `<li class="op">
      <div class="op-top"><span class="tag ${esc(r.status)}">${esc(r.status === "guide" ? "NIH Guide" : r.status)}</span>
      <h4><a href="${link(r.url)}" target="_blank" rel="noopener">${esc(r.title)}</a></h4></div>
      <div class="op-meta">${meta}${due}</div>
      ${r.blurb ? `<p class="blurb">${esc(r.blurb)}</p>` : ""}
      ${r.topics.length ? `<div class="topics">${r.topics.map(t => `<span>${esc(TOPICS[t])}</span>`).join("")}</div>` : ""}
    </li>`;
  }).join("");
}

$("csv").onclick = () => {
  const rows = visible();
  const head = ["number","title","agency","status","open","close","days","aln","topics","url"];
  const esc2 = v => `"${String(v ?? "").replace(/"/g,'""')}"`;
  const body = rows.map(r => head.map(k =>
    esc2(k === "topics" ? r.topics.map(t => TOPICS[t]).join("; ") : r[k])).join(","));
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([head.join(",") + "\n" + body.join("\n")], {type:"text/csv"}));
  a.download = "funding-watch.csv"; a.click(); URL.revokeObjectURL(a.href);
};
$("theme").onclick = () => {
  const dark = document.documentElement.getAttribute("data-theme") === "dark"
    || (!document.documentElement.hasAttribute("data-theme") && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.setAttribute("data-theme", dark ? "light" : "dark");
  $("theme").textContent = dark ? "Dark" : "Light";
};
["fStatus","fAgency","fOpen"].forEach(id => $(id).onchange = renderLedger);
let t; $("q").oninput = () => { clearTimeout(t); t = setTimeout(renderLedger, 180); };

renderStatus(); renderRail(); renderMatrix(); renderAgencies(); renderLedger();
</script></body></html>
"""


def write_page(rows, path):
    page = (TEMPLATE
            # "<\/" keeps a stray "</script>" in a title or summary from ending the script block.
            .replace("__DATA__", json.dumps(rows).replace("</", "<\\/"))
            .replace("__TOPICS__", json.dumps({k: v["label"] for k, v in TOPICS.items()}))
            .replace("__BUILT__", date.today().strftime("%d %B %Y")))
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--deep", action="store_true",
                    help="read each full description, not just the title — much better recall, several minutes")
    ap.add_argument("--status", default="forecasted|posted",
                    help="pipe-separated: forecasted, posted, closed, archived")
    ap.add_argument("--out", default="funding-watch.html")
    ap.add_argument("--no-open", action="store_true", help="don't launch a browser when finished")
    args = ap.parse_args()

    rows = collect(args.status, args.deep)
    if not rows:
        print("\nNothing matched. Try --deep, or widen --status.")
        return
    write_page(rows, args.out)
    full = os.path.abspath(args.out)
    print(f"\nWrote {len(rows)} announcements to {full}")
    if not args.no_open:
        webbrowser.open("file://" + full)


if __name__ == "__main__":
    main()
