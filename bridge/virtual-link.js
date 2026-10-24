// poidh for wedgie: the link between the VIRTUAL wedgie and poidh_bridge.py.
//
// The virtual wedgie (https://wedgie.dev/virtual) has a USB serial port that only wedgie.dev tabs of the
// same browser can open (a BroadcastChannel). Paste this whole file into the DevTools console of the
// wedgie.dev/virtual tab (F12 -> Console) while `python3 poidh_bridge.py virtual` runs. It opens the
// virtual wedgie's port and carries lines between it and the bridge on http://127.0.0.1:8765.
// Nothing else: no data leaves your computer except the bridge's own requests to poidh.xyz.
// Stop it: reload the tab, or run  poidhLink.stop()
(() => {
  const BRIDGE = "http://127.0.0.1:8765/io";
  if (window.poidhLink) window.poidhLink.stop();
  const ch = new BroadcastChannel("wedgie-emu");
  const enc = new TextEncoder(), dec = new TextDecoder();
  let port = null, me = null, unlock = null, rxText = "", out = [], busy = false, alive = true;
  const say = (...a) => console.log("%cpoidh link", "color:#168c34;font-weight:bold", ...a);

  function send(line) {
    if (!port || !me) return;
    const b = enc.encode(line + "\n");
    for (let i = 0; i < b.length; i += 256) ch.postMessage({ t: "tx", id: port, from: me, data: b.slice(i, i + 256) });
  }

  async function open(id) {
    if (me) return;
    const mine = crypto.randomUUID();
    await new Promise((held) => navigator.locks.request("wedgie-emu-port-" + mine, () => new Promise((r) => { unlock = r; held(); })));
    const ok = await new Promise((res) => {
      const t = setTimeout(() => { ch.removeEventListener("message", f); res(false); }, 2000);
      const f = (e) => {
        const m = e.data;
        if (m.id !== id || m.to !== mine || (m.t !== "opened" && m.t !== "refused")) return;
        clearTimeout(t); ch.removeEventListener("message", f); res(m.t === "opened");
      };
      ch.addEventListener("message", f);
      ch.postMessage({ t: "open", id, from: mine });
    });
    if (!ok) { unlock && unlock(); unlock = null; say("port busy: close other wedgie.dev tabs (e.g. /connect), then run it again"); return; }
    port = id; me = mine; rxText = "";
    say("connected to virtual wedgie", id);
    send('{"type":"poidh_hi"}');
  }

  function drop() {
    if (me) ch.postMessage({ t: "close", id: port, from: me });
    me = null; port = null;
    unlock && unlock(); unlock = null;
  }

  async function flush() {
    if (busy || !out.length) return;
    busy = true;
    const rx = out.splice(0, 50);
    try {
      const r = await fetch(BRIDGE, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rx }) });
      const j = await r.json();
      for (const line of (j.tx || [])) if (typeof line === "string" && line.length < 6000) send(line);
    } catch (e) {
      say("bridge not reachable at " + BRIDGE + " - is `python3 poidh_bridge.py virtual` running?", e.message);
    }
    busy = false;
  }

  function onMsg(e) {
    const m = e.data || {};
    if ((m.t === "here" && m.usb) || (m.t === "usb" && m.up)) { if (!me) setTimeout(() => open(m.id), 300); }
    else if ((m.t === "usb" && !m.up) || m.t === "bye") { if (m.id === port) { say("wedgie unplugged; waiting"); me = null; port = null; unlock && unlock(); unlock = null; } }
    else if (m.t === "rx" && m.to === me && me) {
      rxText += dec.decode(m.data, { stream: true });
      if (rxText.length > 65536) rxText = rxText.slice(-4096);
      let i;
      while ((i = rxText.indexOf("\n")) >= 0) {
        const line = rxText.slice(0, i).trim(); rxText = rxText.slice(i + 1);
        if (line.startsWith("{") && line.length < 2048 && (line.includes('"poidh_want"') || line.includes('"ready"'))) out.push(line);
      }
      flush();
    }
  }
  ch.addEventListener("message", onMsg);
  const tick = setInterval(() => { if (!me) ch.postMessage({ t: "who" }); flush(); }, 1500);
  ch.postMessage({ t: "who" });
  window.poidhLink = { stop() { alive = false; clearInterval(tick); drop(); ch.removeEventListener("message", onMsg); ch.close(); say("stopped"); } };
  say("looking for the virtual wedgie...");
})();
