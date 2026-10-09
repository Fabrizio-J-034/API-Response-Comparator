#!/usr/bin/env python3
"""
Node -> Java response compare, local edition.

Run:   python3 migration_compare.py            (opens http://localhost:8765)
       python3 migration_compare.py 9000       (custom port)

No third-party packages needed. Paste a JSON response OR a curl command for
each side; the server runs the curl for you (so internal APIs, auth headers,
cookies etc. all work) and feeds the response into the comparison.
"""
import json, re, shlex, ssl, sys, time, webbrowser, base64
import urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765

# ---------------------------------------------------------------- curl parsing
def parse_curl(cmd: str):
    cmd = cmd.strip()
    cmd = re.sub(r"\\\r?\n", " ", cmd)   # bash line continuation
    cmd = re.sub(r"\^\r?\n", " ", cmd)   # cmd.exe line continuation
    cmd = re.sub(r"`\r?\n", " ", cmd)    # PowerShell line continuation
    toks = shlex.split(cmd, posix=True)
    if toks and toks[0].lower() == "curl":
        toks = toks[1:]
    if not toks:
        raise ValueError("Empty curl command.")

    method, headers, data, url, insecure, auth = None, {}, None, None, False, None
    takes_arg = {"-o", "--output", "-e", "--referer", "-m", "--max-time", "--connect-timeout",
                 "-w", "--write-out", "-x", "--proxy", "-c", "--cookie-jar", "--cacert", "--cert", "--key"}
    i = 0
    while i < len(toks):
        t = toks[i]
        def nxt():
            nonlocal i
            i += 1
            if i >= len(toks):
                raise ValueError(f"Option {t} is missing its value.")
            return toks[i]
        if t in ("-X", "--request"):
            method = nxt().upper()
        elif t.startswith("-X") and len(t) > 2:
            method = t[2:].upper()
        elif t in ("-H", "--header"):
            h = nxt(); k, _, v = h.partition(":"); headers[k.strip()] = v.strip()
        elif t in ("-d", "--data", "--data-raw", "--data-binary", "--data-ascii", "--data-urlencode"):
            d = nxt()
            data = d if data is None else data + "&" + d
        elif t in ("-u", "--user"):
            auth = nxt()
        elif t in ("-k", "--insecure"):
            insecure = True
        elif t == "--url":
            url = nxt()
        elif t in ("-A", "--user-agent"):
            headers["User-Agent"] = nxt()
        elif t in ("-b", "--cookie"):
            headers["Cookie"] = nxt()
        elif t in takes_arg:
            nxt()
        elif t.startswith("-"):
            pass  # -s, -L, -v, -i, --compressed, --location ... ignored
        else:
            url = t if url is None else url
        i += 1

    if not url:
        raise ValueError("No URL found in the curl command.")
    if not re.match(r"^https?://", url, re.I):
        url = "http://" + url
    if method is None:
        method = "POST" if data is not None else "GET"
    if auth:
        headers["Authorization"] = "Basic " + base64.b64encode(auth.encode()).decode()
    if data is not None and not any(k.lower() == "content-type" for k in headers):
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    return dict(method=method, url=url, headers=headers, data=data, insecure=insecure)


def run_curl(cmd: str):
    spec = parse_curl(cmd)
    body = spec["data"].encode("utf-8") if spec["data"] is not None else None
    headers = {k: v for k, v in spec["headers"].items() if k.lower() != "accept-encoding"}
    req = urllib.request.Request(spec["url"], data=body, headers=headers, method=spec["method"])
    ctx = ssl.create_default_context()
    if spec["insecure"]:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    ms = int((time.time() - t0) * 1000)
    text = raw.decode("utf-8", errors="replace")
    try:
        text = json.dumps(json.loads(text), indent=4, ensure_ascii=False)
        is_json = True
    except Exception:
        is_json = False
    return dict(status=status, ms=ms, body=text, json=is_json, method=spec["method"], url=spec["url"])


# ---------------------------------------------------------------- HTTP server
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, ctype, payload: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", HTML.encode("utf-8"))
        else:
            self._send(404, "text/plain", b"not found")

    def do_POST(self):
        if self.path != "/run":
            return self._send(404, "text/plain", b"not found")
        n = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(n) or b"{}")
            result = run_curl(payload.get("curl", ""))
        except Exception as e:
            result = dict(error=f"{type(e).__name__}: {e}")
        self._send(200, "application/json; charset=utf-8", json.dumps(result).encode("utf-8"))


# ---------------------------------------------------------------- UI
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Node → Java response compare</title>
<style>
:root{
  --bg:#eef2f6; --panel:#ffffff; --ink:#172230; --ink-2:#5b6b7d; --line:#d5dde6; --line-2:#e7ecf1;
  --code-bg:#f6f8fa; --focus:#2f6fdd;
  --remove:#b3263a; --remove-bg:#fbeaed; --add:#1f7a45; --add-bg:#e6f4ec;
  --change:#9a5b00; --change-bg:#fff2dc; --other:#4a5566; --other-bg:#eceff3;
  --sans:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --bg:#141a22; --panel:#1b232e; --ink:#e6ebf1; --ink-2:#9aa8b8; --line:#2d3947; --line-2:#26303c;
    --code-bg:#121820; --focus:#6ea0ff;
    --remove:#ff8a9a; --remove-bg:#3a1c23; --add:#7bd49a; --add-bg:#173125;
    --change:#f3c16a; --change-bg:#3b2d14; --other:#b7c1cd; --other-bg:#232c37;
  }
  :root:not([data-theme="light"]) .pill b{color:#111}
}
:root[data-theme="dark"]{
  --bg:#141a22; --panel:#1b232e; --ink:#e6ebf1; --ink-2:#9aa8b8; --line:#2d3947; --line-2:#26303c;
  --code-bg:#121820; --focus:#6ea0ff;
  --remove:#ff8a9a; --remove-bg:#3a1c23; --add:#7bd49a; --add-bg:#173125;
  --change:#f3c16a; --change-bg:#3b2d14; --other:#b7c1cd; --other-bg:#232c37;
}
:root[data-theme="dark"] .pill b{color:#111}
.theme{display:inline-flex;border:1px solid var(--line);border-radius:7px;overflow:hidden;margin-left:auto}
.theme button{border:0;background:none;padding:4px 10px;font-size:13px;cursor:pointer;color:var(--ink-2)}
.theme button.on{background:var(--ink);color:var(--bg)}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:15px;line-height:1.5}
button,textarea,input{font:inherit;color:inherit}
:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
.wrap{max-width:1240px;margin:0 auto;padding:28px 20px 60px}
header{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:8px 24px;margin-bottom:22px}
h1{font-size:22px;font-weight:600;margin:0;letter-spacing:-.01em}
header p{margin:0;color:var(--ink-2);max-width:62ch}
.inputs{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media (max-width:820px){.inputs{grid-template-columns:1fr}}
.pane{background:var(--panel);border:1px solid var(--line);border-radius:10px;display:flex;flex-direction:column;overflow:hidden}
.pane-head{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:8px 10px 8px 14px;border-bottom:1px solid var(--line-2)}
.pane-head strong{font-weight:600}
.pane-head span{color:var(--ink-2);font-size:13px;margin-left:6px}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:7px;overflow:hidden}
.seg button{border:0;background:none;padding:4px 10px;font-size:13px;cursor:pointer;color:var(--ink-2)}
.seg button.on{background:var(--ink);color:var(--bg)}
.pane textarea{border:0;resize:vertical;min-height:280px;padding:12px 14px;font-family:var(--mono);font-size:12.5px;line-height:1.5;background:var(--code-bg);color:var(--ink);width:100%;tab-size:2}
.pane textarea::placeholder{color:var(--ink-2)}
.pane textarea.hide{display:none}
.curl-bar{display:none;align-items:center;gap:10px;padding:8px 14px;border-top:1px solid var(--line-2);font-size:13px;color:var(--ink-2)}
.curl-bar.show{display:flex}
.curl-bar .status{margin-left:auto;font-family:var(--mono);font-size:12px}
.status.ok{color:var(--add)} .status.bad{color:var(--remove)}
.err{padding:8px 14px;font-size:13px;color:var(--remove);background:var(--remove-bg);border-top:1px solid var(--line-2);display:none;white-space:pre-wrap;font-family:var(--mono)}
.err.show{display:block}
.bar{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin:16px 0 26px}
.btn{border:1px solid var(--line);background:var(--panel);border-radius:8px;padding:8px 14px;cursor:pointer;font-weight:500}
.btn:hover{border-color:var(--ink-2)}
.btn:disabled{opacity:.5;cursor:default}
.btn.primary{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.btn.small{padding:4px 10px;font-size:13px}
.bar label{display:flex;align-items:center;gap:6px;color:var(--ink-2);font-size:14px;margin-left:auto;cursor:pointer}
.bar .hint{color:var(--ink-2);font-size:13px;flex-basis:100%}
.summary{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:18px}
.pill{display:inline-flex;align-items:center;gap:8px;border-radius:999px;padding:5px 12px 5px 8px;font-size:13.5px;border:1px solid var(--line);background:var(--panel)}
.pill b{display:inline-flex;min-width:22px;height:22px;align-items:center;justify-content:center;border-radius:999px;font-weight:600;font-size:12.5px;color:#fff}
.pill.remove b{background:var(--remove)} .pill.add b{background:var(--add)} .pill.change b{background:var(--change)} .pill.other b{background:var(--other)}
.pill.zero{opacity:.55}
.results{display:grid;gap:14px}
.section{background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--c);border-radius:10px;overflow:hidden}
.section.remove{--c:var(--remove);--cbg:var(--remove-bg)} .section.add{--c:var(--add);--cbg:var(--add-bg)}
.section.change{--c:var(--change);--cbg:var(--change-bg)} .section.other{--c:var(--other);--cbg:var(--other-bg)}
.sec-head{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;gap:12px}
.sec-head h2{font-size:15px;font-weight:600;margin:0;color:var(--c)}
.sec-head small{color:var(--ink-2);font-weight:400;margin-left:8px}
.lines{border-top:1px solid var(--line-2);background:var(--code-bg);padding:6px 0}
.line{display:grid;grid-template-columns:1fr auto;align-items:start;gap:12px;padding:5px 14px;font-family:var(--mono);font-size:12.5px;line-height:1.55}
.line:hover{background:var(--cbg)}
.line pre{margin:0;white-space:pre-wrap;word-break:break-word}
.line .arrow{color:var(--ink-2)} .line .exp{color:var(--c)}
.meta{font-family:var(--sans);font-size:12px;color:var(--ink-2)}
.meta button{border:0;background:none;padding:0;color:var(--ink-2);cursor:pointer;text-decoration:underline dotted;font-size:12px}
.paths{display:none;grid-column:1/-1;font-family:var(--mono);font-size:11.5px;color:var(--ink-2);padding:2px 0 4px 14px;border-left:2px solid var(--line)}
.line.open .paths{display:block}
.empty{padding:10px 14px;color:var(--ink-2);font-size:14px;border-top:1px solid var(--line-2)}
.placeholder{color:var(--ink-2);padding:26px 0;text-align:center}
.toast{position:fixed;left:50%;bottom:20px;transform:translateX(-50%);background:var(--ink);color:var(--bg);padding:8px 14px;border-radius:8px;font-size:13.5px;opacity:0;transition:opacity .2s;pointer-events:none}
.toast.show{opacity:1}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Node → Java response compare</h1>
    <p>For each side, paste the JSON response or a curl command. Curl runs on this machine, so internal URLs and auth headers work. Node is the expected result; the report says what Java must change.</p>
    <div class="theme" id="theme" aria-label="Theme"><button data-t="light">Light</button><button data-t="system">System</button><button data-t="dark">Dark</button></div>
  </header>

  <div class="inputs">
    <div class="pane" data-side="node">
      <div class="pane-head"><div><strong>Node</strong><span>expected</span></div>
        <div class="seg"><button data-mode="json" class="on">JSON</button><button data-mode="curl">curl</button></div></div>
      <textarea class="json" spellcheck="false" placeholder='{ "id": 1, ... }'></textarea>
      <textarea class="curl hide" spellcheck="false" placeholder="curl 'https://node.internal/api/buying-groups/1' -H 'Authorization: Bearer ...'"></textarea>
      <div class="curl-bar"><button class="btn small fetch">Run curl</button><span class="status"></span></div>
      <div class="err"></div>
    </div>
    <div class="pane" data-side="java">
      <div class="pane-head"><div><strong>Java</strong><span>actual, under test</span></div>
        <div class="seg"><button data-mode="json" class="on">JSON</button><button data-mode="curl">curl</button></div></div>
      <textarea class="json" spellcheck="false" placeholder='{ "id": 1, ... }'></textarea>
      <textarea class="curl hide" spellcheck="false" placeholder="curl 'https://java.internal/api/buying-groups/1' -H 'Authorization: Bearer ...'"></textarea>
      <div class="curl-bar"><button class="btn small fetch">Run curl</button><span class="status"></span></div>
      <div class="err"></div>
    </div>
  </div>

  <div class="bar">
    <button class="btn primary" id="compareBtn">Compare</button>
    <button class="btn" id="fetchAllBtn">Run both curls &amp; compare</button>
    <button class="btn" id="copyBtn" disabled>Copy report</button>
    <button class="btn" id="clearBtn">Clear</button>
    <label><input type="checkbox" id="showOther"> Also show value mismatches (ids, timestamps, text)</label>
    <span class="hint">Ctrl/⌘ + Enter compares. After a curl runs, its response is placed in the JSON tab so you can inspect or edit it.</span>
  </div>

  <div class="summary" id="summary"></div>
  <div class="results" id="results"><div class="placeholder">Provide both responses and press Compare.</div></div>
</div>
<div class="toast" id="toast"></div>

<script>
(function(){
  const $ = id => document.getElementById(id);
  function applyTheme(t){
    if (t==='system') document.documentElement.removeAttribute('data-theme'); else document.documentElement.dataset.theme=t;
    $('theme').querySelectorAll('button').forEach(b=>b.classList.toggle('on', b.dataset.t===t));
    try{ localStorage.setItem('mig-theme', t); }catch(e){}
  }
  $('theme').addEventListener('click', e=>{ if (e.target.dataset.t) applyTheme(e.target.dataset.t); });
  (function(){ let t='system'; try{ t=localStorage.getItem('mig-theme')||'system'; }catch(e){} applyTheme(t); })();
  const results=$('results'), summary=$('summary'), copyBtn=$('copyBtn'), showOther=$('showOther');
  let lastReport = null;

  // ---------- panes ----------
  const panes = {};
  document.querySelectorAll('.pane').forEach(p=>{
    const side = p.dataset.side;
    const o = panes[side] = {
      el:p, json:p.querySelector('.json'), curl:p.querySelector('.curl'), bar:p.querySelector('.curl-bar'),
      status:p.querySelector('.status'), err:p.querySelector('.err'), fetch:p.querySelector('.fetch'),
      seg:p.querySelectorAll('.seg button'), mode:'json'
    };
    o.seg.forEach(b=>b.addEventListener('click',()=>setMode(side,b.dataset.mode)));
    o.fetch.addEventListener('click',()=>runCurl(side));
    o.json.addEventListener('input',()=>save());
    o.curl.addEventListener('input',()=>save());
  });

  function setMode(side, mode){
    const o = panes[side]; o.mode = mode;
    o.seg.forEach(b=>b.classList.toggle('on', b.dataset.mode===mode));
    o.json.classList.toggle('hide', mode!=='json');
    o.curl.classList.toggle('hide', mode!=='curl');
    o.bar.classList.toggle('show', mode==='curl');
    save();
  }

  function setErr(side, msg){ const e=panes[side].err; e.textContent=msg||''; e.classList.toggle('show', !!msg); }

  async function runCurl(side){
    const o = panes[side];
    const cmd = o.curl.value.trim();
    setErr(side, '');
    if (!cmd){ setErr(side, 'Paste a curl command first.'); return false; }
    o.fetch.disabled = true; o.status.className='status'; o.status.textContent='running…';
    try{
      const r = await fetch('/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({curl:cmd})});
      const d = await r.json();
      if (d.error){ o.status.className='status bad'; o.status.textContent='failed'; setErr(side, d.error); return false; }
      o.json.value = d.body;
      const ok = d.status>=200 && d.status<300;
      o.status.className = 'status '+(ok?'ok':'bad');
      o.status.textContent = d.method+' '+d.status+' · '+d.ms+' ms'+(d.json?'':' · not JSON');
      if (!d.json) setErr(side, 'Response is not JSON. Status '+d.status+'. Check the JSON tab for the raw body.');
      save();
      return d.json;
    }catch(e){
      o.status.className='status bad'; o.status.textContent='failed'; setErr(side, 'Could not reach the local server: '+e.message); return false;
    }finally{ o.fetch.disabled=false; }
  }

  // ---------- comparison ----------
  const kind = v => v===null ? 'null' : Array.isArray(v) ? 'array' : typeof v;
  const lastKey = path => { const m = path.match(/([^.\[\]]+)(\[\d+\])*$/); return m ? m[1] : path; };

  function compare(node, java){
    const r = { remove:[], add:[], nullToEmpty:[], nullToZero:[], nullToFalse:[], nullToObject:[], other:[] };
    walk(node, java, '$', r); return r;
  }
  function walk(n, j, path, r){
    const kn = kind(n), kj = kind(j);
    if (kn==='object' && kj==='object'){
      for (const k of Object.keys(j)) if (!(k in n)) r.remove.push({key:k, path:path+'.'+k, value:j[k]});
      for (const k of Object.keys(n)) if (!(k in j)) r.add.push({key:k, path:path+'.'+k, value:n[k]});
      for (const k of Object.keys(n)) if (k in j) walk(n[k], j[k], path+'.'+k, r);
      return;
    }
    if (kn==='array' && kj==='array'){
      const len = Math.max(n.length, j.length);
      for (let i=0;i<len;i++){
        const p = path+'['+i+']';
        if (i>=j.length) r.add.push({key:lastKey(path)+'['+i+']', path:p, value:n[i]});
        else if (i>=n.length) r.remove.push({key:lastKey(path)+'['+i+']', path:p, value:j[i]});
        else walk(n[i], j[i], p, r);
      }
      return;
    }
    if (kj==='null' && kn!=='null'){
      const item = {key:lastKey(path), path, value:null, expected:n};
      if (kn==='string') r.nullToEmpty.push(item);
      else if (kn==='number') r.nullToZero.push(item);
      else if (kn==='boolean') r.nullToFalse.push(item);
      else r.nullToObject.push(item);
      return;
    }
    if (kn!==kj){ r.other.push({key:lastKey(path), path, value:j, expected:n, note:'type: '+kj+' → '+kn}); return; }
    if (kn!=='object' && kn!=='array' && n!==j) r.other.push({key:lastKey(path), path, value:j, expected:n});
  }
  function group(items){
    const map = new Map();
    for (const it of items){
      const id = it.key+'\u0000'+JSON.stringify(it.value)+'\u0000'+JSON.stringify(it.expected ?? '\u0001');
      if (!map.has(id)) map.set(id, {...it, paths:[]});
      map.get(id).paths.push(it.path);
    }
    return [...map.values()];
  }

  // ---------- rendering ----------
  const fmt = v => JSON.stringify(v, null, 4);
  const esc = s => s.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
  function lineText(g, mode){
    if (mode==='keyval') return '"'+g.key+'": '+fmt(g.value)+',';
    if (mode==='nullchange') return '"'+g.key+'": null,';
    return '"'+g.key+'": '+fmt(g.value)+'  →  '+fmt(g.expected);
  }
  const SECTIONS = [
    {id:'remove',      cls:'remove', title:'Remove the below fields',             mode:'keyval',     sub:'present in Java, missing in Node'},
    {id:'add',         cls:'add',    title:'Add the below fields',                mode:'keyval',     sub:'present in Node, missing in Java'},
    {id:'nullToEmpty', cls:'change', title:'Change from null to empty string ""', mode:'nullchange'},
    {id:'nullToZero',  cls:'change', title:'Change from null to 0',               mode:'nullchange'},
    {id:'nullToFalse', cls:'change', title:'Change from null to false',           mode:'nullchange'},
    {id:'nullToObject',cls:'change', title:'Change from null to object / array',  mode:'nullchange', optionalWhenEmpty:true},
    {id:'other',       cls:'other',  title:'Other value mismatches',              mode:'diff',       toggle:true},
  ];
  function pill(cls,label,n){ return '<span class="pill '+cls+(n?'':' zero')+'"><b>'+n+'</b>'+label+'</span>'; }

  function render(res){
    const groups = {};
    for (const s of SECTIONS) groups[s.id] = group(res[s.id]);
    lastReport = buildReport(groups);
    const changeN = groups.nullToEmpty.length+groups.nullToZero.length+groups.nullToFalse.length+groups.nullToObject.length;
    summary.innerHTML = pill('remove','to remove',groups.remove.length)+pill('add','to add',groups.add.length)+
      pill('change','null fixes',changeN)+(showOther.checked?pill('other','value mismatches',groups.other.length):'');
    let html = '';
    for (const s of SECTIONS){
      const g = groups[s.id];
      if (s.toggle && !showOther.checked) continue;
      if (s.optionalWhenEmpty && !g.length) continue;
      html += '<section class="section '+s.cls+'"><div class="sec-head"><h2>'+esc(s.title)+(s.sub?'<small>'+esc(s.sub)+'</small>':'')+'</h2>'+
        (g.length?'<button class="btn small" data-copy="'+s.id+'">Copy</button>':'')+'</div>';
      if (!g.length){ html += '<div class="empty">Nothing here. Java matches Node for this check.</div>'; }
      else {
        html += '<div class="lines">';
        for (const item of g){
          let body;
          if (s.mode==='keyval') body = '<pre>"'+esc(item.key)+'": '+esc(fmt(item.value))+',</pre>';
          else if (s.mode==='nullchange') body = '<pre>"'+esc(item.key)+'": null, <span class="arrow">→</span> <span class="exp">'+esc(fmt(item.expected))+'</span></pre>';
          else body = '<pre>"'+esc(item.key)+'": '+esc(fmt(item.value))+' <span class="arrow">→</span> <span class="exp">'+esc(fmt(item.expected))+'</span>'+(item.note?' <span class="arrow">('+esc(item.note)+')</span>':'')+'</pre>';
          const n = item.paths.length;
          html += '<div class="line">'+body+'<div class="meta"><button type="button" data-toggle>'+(n===1?'1 place':n+' places')+'</button></div>'+
            '<div class="paths">'+item.paths.map(esc).join('<br>')+'</div></div>';
        }
        html += '</div>';
      }
      html += '</section>';
    }
    results.innerHTML = html; copyBtn.disabled = false;
    results.querySelectorAll('[data-toggle]').forEach(b=>b.addEventListener('click',e=>e.target.closest('.line').classList.toggle('open')));
    results.querySelectorAll('[data-copy]').forEach(b=>b.addEventListener('click',()=>{
      const s = SECTIONS.find(x=>x.id===b.dataset.copy);
      copyText(s.title+':\n'+groups[s.id].map(g=>lineText(g,s.mode)).join('\n'));
    }));
  }
  function buildReport(groups){
    const out = [];
    for (const s of SECTIONS){
      if (s.toggle && !showOther.checked) continue;
      const g = groups[s.id]; if (!g.length) continue;
      out.push(s.title+':'); out.push(g.map(x=>lineText(x,s.mode)).join('\n')); out.push('');
    }
    return out.length ? out.join('\n').trim() : 'No differences found. Java response matches Node response.';
  }

  // ---------- actions ----------
  function parse(side){
    const o = panes[side]; setErr(side,'');
    const txt = o.json.value.trim();
    if (!txt){ setErr(side, o.mode==='curl' ? 'Run the curl first (or paste the JSON in the JSON tab).' : 'Paste a JSON response here.'); return undefined; }
    try { return JSON.parse(txt); }
    catch(e){ setErr(side,'Not valid JSON: '+e.message); return undefined; }
  }
  function run(){
    const n = parse('node'), j = parse('java');
    if (n===undefined || j===undefined) return;
    render(compare(n, j)); save();
  }
  async function fetchAll(){
    const sides = ['node','java'].filter(s=>panes[s].mode==='curl' || panes[s].curl.value.trim());
    if (!sides.length){ toast('No curl commands to run — switch a pane to the curl tab.'); return; }
    const ok = await Promise.all(sides.map(runCurl));
    if (ok.every(Boolean)) run();
  }
  function save(){
    try{ localStorage.setItem('mig-state', JSON.stringify({
      node:{json:panes.node.json.value, curl:panes.node.curl.value, mode:panes.node.mode},
      java:{json:panes.java.json.value, curl:panes.java.curl.value, mode:panes.java.mode}})); }catch(e){}
  }
  function copyText(t){ navigator.clipboard.writeText(t).then(()=>toast('Copied')).catch(()=>toast('Copy failed, select the text manually')); }
  let tt; function toast(m){ const el=$('toast'); el.textContent=m; el.classList.add('show'); clearTimeout(tt); tt=setTimeout(()=>el.classList.remove('show'),1800); }

  $('compareBtn').addEventListener('click', run);
  $('fetchAllBtn').addEventListener('click', fetchAll);
  copyBtn.addEventListener('click', ()=> lastReport && copyText(lastReport));
  showOther.addEventListener('change', ()=>{ if(lastReport) run(); });
  $('clearBtn').addEventListener('click', ()=>{
    for (const s of ['node','java']){ panes[s].json.value=''; panes[s].curl.value=''; panes[s].status.textContent=''; setErr(s,''); }
    results.innerHTML='<div class="placeholder">Provide both responses and press Compare.</div>';
    summary.innerHTML=''; copyBtn.disabled=true; lastReport=null;
    try{ localStorage.removeItem('mig-state'); }catch(e){}
  });
  document.addEventListener('keydown', e=>{ if ((e.ctrlKey||e.metaKey) && e.key==='Enter'){ e.preventDefault(); run(); } });

  try{
    const st = JSON.parse(localStorage.getItem('mig-state')||'null');
    if (st) for (const s of ['node','java']){ panes[s].json.value=st[s].json||''; panes[s].curl.value=st[s].curl||''; setMode(s, st[s].mode||'json'); }
  }catch(e){}
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"Node → Java compare running at {url}  (Ctrl+C to stop)")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
