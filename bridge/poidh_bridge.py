#!/usr/bin/env python3
"""poidh bridge for wedgie: fetches live poidh bounties and claims and answers the wedgie's poidh app.

A wedgie has no internet. This script runs on the computer it is plugged into (or next to the virtual
wedgie at https://wedgie.dev/virtual), reads the app's requests and answers each with real poidh data,
already trimmed, cleaned to plain ASCII and wrapped for the 240x240 screen.

    python3 poidh_bridge.py serial [--port /dev/ttyACM0]   a real wedgie on USB
    python3 poidh_bridge.py virtual [--port 8765]          the virtual wedgie (with bridge/virtual-link.js)
    python3 poidh_bridge.py demo [chain]                   print what the wedgie would get (no device)

Python 3.8+, standard library only (on Windows the serial mode needs pyserial). Data sources:
  https://poidh.xyz/bounties/data                      open bounties on every chain (poidh's own feed)
  https://poidh.xyz/api/trpc/claims.fetchBountyClaims  a bounty's claims (what poidh.xyz itself calls)
"""
import argparse, glob, html, json, os, re, sys, threading, time, unicodedata
import urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

POIDH = "https://poidh.xyz"
CHAINS = {1: ("Ethereum", "mainnet"), 8453: ("Base", "base"), 42161: ("Arbitrum", "arbitrum")}
UA = "wedgie-poidh-bridge/1.0 (+https://github.com/swiftbotlab/wedgie-poidh)"
MAX_BODY = 4 * 1024 * 1024        # never read more than this from poidh in one response
MAX_PAGES = 6                     # 6 x 100 open bounties is far more than poidh has open at once
LIST_TTL = 60                     # seconds a fetched list stays fresh
CLAIMS_TTL = 60
COLS = 29                         # characters per line at the wedgie's scale 1
BIG = 14                          # characters per line at scale 2
MAX_LINE = 5000                   # bytes per JSON line to the wedgie (its reader drops lines over 6 KB)
MAX_DESC_LINES = 90
MAX_IN = 2048                     # a request from the wedgie is tiny; longer lines are ignored
PER_MAX = 8

INK, MUTED, GREEN, RED = 0, 1, 2, 3


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


# ---- fetching ---------------------------------------------------------------------------------------

def get_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if r.status != 200:
            raise IOError("HTTP %d" % r.status)
        data = r.read(MAX_BODY + 1)
    if len(data) > MAX_BODY:
        raise IOError("response too big")
    return json.loads(data.decode("utf-8"))


class Poidh:
    """Live poidh data with a short cache, so scrolling doesn't hammer poidh.xyz."""

    def __init__(self):
        self.lock = threading.Lock()
        self.list_at = 0.0
        self.bounties = []          # open bounties on the three chains, newest first
        self.claims = {}            # (chain, id) -> (fetched_at, [claims])

    def open_bounties(self, force=False):
        with self.lock:
            if not force and self.bounties and time.time() - self.list_at < LIST_TTL:
                return self.bounties
            out, cursor = [], None
            for _ in range(MAX_PAGES):
                q = {"limit": 100}
                if cursor:
                    q["cursor"] = cursor
                d = get_json(POIDH + "/bounties/data?" + urllib.parse.urlencode(q))
                items = d.get("items") if isinstance(d, dict) else None
                if not isinstance(items, list):
                    raise IOError("unexpected poidh answer")
                for b in items:
                    if isinstance(b, dict) and b.get("chainId") in CHAINS and isinstance(b.get("id"), int):
                        out.append(b)
                cursor = d.get("nextCursor")
                if not cursor or not isinstance(cursor, (int, str)):
                    break
            self.bounties, self.list_at = out, time.time()
            log("poidh: %d open bounties (%s)" % (len(out), ", ".join(
                "%s %d" % (CHAINS[c][0], sum(1 for b in out if b["chainId"] == c)) for c in CHAINS)))
            return out

    def bounty(self, chain, bid):
        for b in self.open_bounties():
            if b["chainId"] == chain and b["id"] == bid:
                return b
        for b in self.open_bounties(force=True):
            if b["chainId"] == chain and b["id"] == bid:
                return b
        return None

    def bounty_claims(self, chain, bid, force=False):
        key = (chain, bid)
        with self.lock:
            hit = self.claims.get(key)
            if hit and not force and time.time() - hit[0] < CLAIMS_TTL:
                return hit[1]
        out, cursor = [], None
        for _ in range(5):                      # up to 500 claims
            inp = {"bountyId": bid, "chainId": chain, "limit": 100}
            if cursor:
                inp["cursor"] = cursor
            url = POIDH + "/api/trpc/claims.fetchBountyClaims?input=" + urllib.parse.quote(json.dumps({"json": inp}))
            d = get_json(url)
            data = (((d or {}).get("result") or {}).get("data") or {}).get("json") or {}
            items = data.get("items")
            if not isinstance(items, list):
                raise IOError("unexpected poidh claims answer")
            out.extend(c for c in items if isinstance(c, dict) and isinstance(c.get("id"), int))
            cursor = data.get("nextCursor")
            if not isinstance(cursor, int):
                break
        with self.lock:
            if len(self.claims) > 200:
                self.claims.clear()
            self.claims[key] = (time.time(), out)
        return out


# ---- text for a 240x240 screen ------------------------------------------------------------------------

_MAP = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "...",
        "×": "x", "•": "*", " ": " ", "→": "->", "←": "<-", "·": "*", "≥": ">=",
        "≤": "<=", "«": '"', "»": '"', "€": "EUR", "£": "GBP"}


def ascii_text(s, limit=6000):
    """Any text from poidh -> plain printable ASCII (the wedgie's font), markdown links reduced to their
    text, no control characters. Always a str, never longer than limit."""
    if not isinstance(s, str):
        s = "" if s is None else str(s)
    s = s[:limit * 2]
    s = html.unescape(s)
    s = "".join(_MAP.get(ch, ch) for ch in s)
    s = unicodedata.normalize("NFKD", s)
    s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", s)            # images
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"\1", s)  # [text](url) -> text
    s = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", s)                 # headings
    s = re.sub(r"(\*\*|__|`+)", "", s)                          # bold, code
    s = re.sub(r"(?m)^\s*[-*+]\s+", "* ", s)                    # bullets
    s = re.sub(r"(?m)^\s*>\s?", "", s)                          # quotes
    out = []
    for ch in s:
        o = ord(ch)
        if ch == "\n" or 32 <= o < 127:
            out.append(ch)
        elif ch == "\t":
            out.append(" ")
    s = "".join(out)
    s = re.sub(r"[ ]{2,}", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()[:limit]


def wrap(s, n=COLS):
    """Words into lines of at most n characters; long words (URLs, addresses) are cut."""
    lines = []
    for para in s.split("\n"):
        para = para.strip()
        if not para:
            if lines and lines[-1]:
                lines.append("")
            continue
        cur = ""
        for w in para.split(" "):
            while len(w) > n:
                if cur:
                    lines.append(cur)
                    cur = ""
                lines.append(w[:n])
                w = w[n:]
            if not w:
                continue
            if cur and len(cur) + 1 + len(w) > n:
                lines.append(cur)
                cur = w
            else:
                cur = (cur + " " + w) if cur else w
        if cur:
            lines.append(cur)
    while lines and not lines[-1]:
        lines.pop()
    return lines


def eth(wei):
    try:
        w = int(wei)
    except (TypeError, ValueError):
        return "? ETH"
    if w < 0:
        return "? ETH"
    v = w / 1e18
    if v == 0:
        return "0 ETH"
    if v >= 100:
        t = "%.0f" % v
    elif v >= 1:
        t = ("%.3f" % v).rstrip("0").rstrip(".")
    else:
        t = ("%.6f" % v).rstrip("0").rstrip(".")
        if t == "0":
            t = "<0.000001"
    return t + " ETH"


def ago(ts):
    try:
        dt = max(0, int(time.time() - float(ts)))
    except (TypeError, ValueError):
        return ""
    if dt < 3600:
        return "%dm" % max(1, dt // 60)
    if dt < 86400:
        return "%dh" % (dt // 3600)
    if dt < 86400 * 60:
        return "%dd" % (dt // 86400)
    return "%dmo" % (dt // (86400 * 30))


def ago_words(ts):
    a = ago(ts)
    if not a:
        return "a while"
    n, unit = int(a.rstrip("mhdo")), a.lstrip("0123456789")
    word = {"m": "minute", "h": "hour", "d": "day", "mo": "month"}[unit]
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def short_addr(a):
    a = a if isinstance(a, str) else ""
    if re.fullmatch(r"0x[0-9a-fA-F]{40}", a):
        return a[:6] + ".." + a[-4:]
    return ascii_text(a, 13) or "?"


def usd(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    if f != f or f < 0:
        return ""
    return ("$%.2f" % f) if f < 1000 else ("$%s" % format(int(f), ","))


# ---- answers ------------------------------------------------------------------------------------------

def as_int(v, lo, hi, default=None):
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        return default
    return v


def answer(p, m):
    """One request from the wedgie (a dict) -> the answer dict, or None if it isn't ours."""
    if m.get("type") != "poidh_want":
        return None
    rid = as_int(m.get("rid"), 0, 2 ** 31)
    if rid is None:
        return None
    what = m.get("what")
    try:
        if what == "list":
            return dict(list_page(p, m), type="poidh", rid=rid)
        if what == "bounty":
            return dict(bounty_page(p, m), type="poidh", rid=rid)
        if what == "claims":
            return dict(claims_page(p, m), type="poidh", rid=rid)
        if what == "claim":
            return dict(claim_page(p, m), type="poidh", rid=rid)
        return {"type": "poidh", "rid": rid, "error": "unknown request"}
    except Exception as e:                      # network down, poidh changed: say so on the screen
        log("error answering %s: %r" % (what, e))
        return {"type": "poidh", "rid": rid, "error": "poidh unreachable: %s" % ascii_text(type(e).__name__, 40)}


def list_page(p, m):
    chain = as_int(m.get("chain"), 0, 2 ** 32, 0)
    page = as_int(m.get("page"), 0, 10000, 0)
    per = as_int(m.get("per"), 1, PER_MAX, 6)
    if chain and chain not in CHAINS:
        return {"error": "unknown chain"}
    bs = [b for b in p.open_bounties(force=(page == 0 and m.get("fresh") is True))
          if not chain or b["chainId"] == chain]
    items = []
    for b in bs[page * per:(page + 1) * per]:
        items.append({
            "ch": b["chainId"], "id": b["id"],
            "t": ascii_text(b.get("title"), 60) or "(untitled)",
            "a": eth(b.get("amount")),
            "c": CHAINS[b["chainId"]][0] + (" *" if b.get("hasClaims") else ""),
            "ago": ago(b.get("createdAt")),
        })
    return {"page": page, "total": len(bs), "items": items}


def bounty_page(p, m):
    chain = as_int(m.get("chain"), 1, 2 ** 32)
    bid = as_int(m.get("id"), 0, 10 ** 9)
    if chain not in CHAINS or bid is None:
        return {"error": "bad bounty"}
    b = p.bounty(chain, bid)
    if not b:
        return {"error": "bounty is no longer open"}
    claims = p.bounty_claims(chain, bid) if b.get("hasClaims") else []
    accepted = sum(1 for c in claims if c.get("isAccepted"))
    body = []
    title = ascii_text(b.get("title"), 120) or "(untitled)"
    t2 = wrap(title, BIG)
    if len(t2) <= 3:
        body += [[x, INK, 2] for x in t2]
    else:
        body += [[x, INK, 1] for x in wrap(title)[:5]]
    body.append(["-", MUTED, 1])
    body.append([eth(b.get("amount")), GREEN, 2])
    u = usd(b.get("priceUsd"))
    kind = "open bounty" if b.get("isMultiplayer") else "solo bounty"
    body.append([("%s  %s" % (u, kind)) if u else kind, MUTED, 1])
    body.append(["by " + short_addr(b.get("issuer")), MUTED, 1])
    body.append(["posted %s ago" % ago_words(b.get("createdAt")), MUTED, 1])
    body.append(["poidh id %d, on-chain %s" % (bid, b.get("onChainId", "?")), MUTED, 1])
    if claims:
        body.append(["%d claim%s%s" % (len(claims), "" if len(claims) == 1 else "s",
                                         ", %d accepted" % accepted if accepted else ""), GREEN, 1])
    else:
        body.append(["no claims yet", MUTED, 1])
    if b.get("deadline"):
        body.append(["deadline set", MUTED, 1])
    body.append(["-", MUTED, 1])
    desc = wrap(ascii_text(b.get("description"), 4000)) or ["(no description)"]
    if len(desc) > MAX_DESC_LINES:
        desc = desc[:MAX_DESC_LINES] + ["... more on poidh.xyz"]
    body += [[x, INK, 1] for x in desc]
    body.append(["-", MUTED, 1])
    body.append(["poidh.xyz/%s/bounty/%d" % (CHAINS[chain][1], bid), MUTED, 1])
    return fit({"hasClaims": bool(claims), "n": len(claims), "body": body})


def claims_page(p, m):
    chain = as_int(m.get("chain"), 1, 2 ** 32)
    bid = as_int(m.get("id"), 0, 10 ** 9)
    page = as_int(m.get("page"), 0, 10000, 0)
    per = as_int(m.get("per"), 1, PER_MAX, 6)
    if chain not in CHAINS or bid is None:
        return {"error": "bad bounty"}
    cs = p.bounty_claims(chain, bid)
    items = []
    for c in cs[page * per:(page + 1) * per]:
        items.append({"id": c["id"], "t": ascii_text(c.get("title"), 60) or "(untitled)",
                      "st": "accepted" if c.get("isAccepted") else "claim",
                      "by": short_addr(c.get("issuer")), "ago": ""})
    return {"page": page, "total": len(cs), "items": items}


def claim_page(p, m):
    chain = as_int(m.get("chain"), 1, 2 ** 32)
    bid = as_int(m.get("id"), 0, 10 ** 9)
    cid = as_int(m.get("claim"), 0, 10 ** 9)
    if chain not in CHAINS or bid is None or cid is None:
        return {"error": "bad claim"}
    c = next((x for x in p.bounty_claims(chain, bid) if x["id"] == cid), None)
    if not c:
        return {"error": "claim not found"}
    body = [[x, INK, 1] for x in wrap(ascii_text(c.get("title"), 120) or "(untitled)")[:4]]
    body.append(["ACCEPTED, paid out" if c.get("isAccepted") else "waiting for the issuer",
                 GREEN if c.get("isAccepted") else MUTED, 1])
    body.append(["by " + short_addr(c.get("issuer")), MUTED, 1])
    body.append(["claim id %d/%s" % (cid, c.get("onChainId", "?")), MUTED, 1])
    body.append(["-", MUTED, 1])
    desc = wrap(ascii_text(c.get("description"), 3000)) or ["(no description)"]
    if len(desc) > MAX_DESC_LINES:
        desc = desc[:MAX_DESC_LINES] + ["... more on poidh.xyz"]
    body += [[x, INK, 1] for x in desc]
    url = c.get("url") if isinstance(c.get("url"), str) else ""
    if url.startswith("https://"):
        body.append(["-", MUTED, 1])
        body.append(["proof:", MUTED, 1])
        body += [[x, MUTED, 1] for x in wrap(ascii_text(url, 200))[:4]]
    return fit({"body": body})


def fit(d):
    """Keep an answer under the wedgie's line limit by dropping description lines from the end."""
    while len(json.dumps(d)) > MAX_LINE and len(d.get("body", ())) > 12:
        d["body"] = d["body"][:-6] + [["... more on poidh.xyz", MUTED, 1]]
    return d


def handle_line(p, raw):
    """A line from the wedgie -> answer line (str) or None. Lines that aren't our JSON are the wedgie's
    logs and are ignored."""
    if not raw or len(raw) > MAX_IN:
        return None
    raw = raw.strip()
    if not raw.startswith("{"):
        return None
    try:
        m = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(m, dict):
        return None
    if m.get("type") == "ready":
        log("wedgie ready, running", ascii_text(m.get("running"), 20))
        return json.dumps({"type": "poidh_hi"})
    a = answer(p, m)
    if a is None:
        return None
    log("-> %s %s" % (m.get("what"), ascii_text(json.dumps({k: m[k] for k in ("chain", "id", "page", "claim") if k in m}), 80)))
    line = json.dumps(a, separators=(",", ":"))
    if len(line) > MAX_LINE + 1000:
        line = json.dumps({"type": "poidh", "rid": a.get("rid"), "error": "too big"})
    return line


# ---- a real wedgie on USB serial ----------------------------------------------------------------------

def find_port():
    pats = ["/dev/serial/by-id/*wedgie*", "/dev/serial/by-id/*MicroPython*", "/dev/ttyACM*", "/dev/cu.usbmodem*"]
    for pat in pats:
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[0]
    return None


class PosixSerial:
    def __init__(self, path):
        import termios, tty
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY)
        tty.setraw(self.fd)
        a = termios.tcgetattr(self.fd)
        a[4] = a[5] = termios.B115200
        a[6][termios.VMIN] = 0
        a[6][termios.VTIME] = 1            # reads return after 0.1 s with nothing
        termios.tcsetattr(self.fd, termios.TCSANOW, a)

    def read(self):
        return os.read(self.fd, 4096)

    def write(self, b):
        while b:
            n = os.write(self.fd, b)
            b = b[n:]


class PySerial:
    def __init__(self, path):
        import serial                       # pip install pyserial (Windows)
        self.s = serial.Serial(path, 115200, timeout=0.1)

    def read(self):
        return self.s.read(4096)

    def write(self, b):
        self.s.write(b)


def run_serial(p, port):
    port = port or find_port()
    if not port:
        sys.exit("no wedgie found: plug it in, or pass --port (e.g. /dev/ttyACM0, /dev/cu.usbmodem1101, COM5)")
    while True:
        try:
            dev = PosixSerial(port) if os.name == "posix" else PySerial(port)
        except OSError as e:
            log("can't open %s (%s); retrying. Close wedgie.dev tabs that hold the port." % (port, e))
            time.sleep(2)
            continue
        log("bridge on %s" % port)
        dev.write(b'{"type":"poidh_hi"}\n')
        buf = b""
        try:
            while True:
                chunk = dev.read()
                if not chunk:
                    continue
                buf += chunk
                if len(buf) > 65536:                # a runaway line: drop it
                    buf = buf[-MAX_IN:]
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    out = handle_line(p, line.decode("utf-8", "replace"))
                    if out:
                        dev.write(out.encode() + b"\n")
        except OSError as e:                        # unplugged: wait for it to come back
            log("wedgie gone (%s); waiting" % e)
            time.sleep(2)


# ---- the virtual wedgie (browser) --------------------------------------------------------------------

ALLOWED_ORIGINS = ("https://wedgie.dev", "https://www.wedgie.dev")


class Link(BaseHTTPRequestHandler):
    """POST /io {"rx": [lines from the wedgie]} -> {"tx": [lines for it]}. Only from wedgie.dev pages,
    only on 127.0.0.1. virtual-link.js (in the wedgie.dev tab) carries the lines to the virtual wedgie."""
    server_version = "poidh-bridge"
    poidh = None
    timeout = 10                    # seconds a client may take to send its request
    port = 8765

    def host_ok(self):
        """DNS rebinding guard: only requests addressed to this machine by its loopback name."""
        return self.headers.get("Host", "") in ("127.0.0.1:%d" % self.port, "localhost:%d" % self.port)

    def log_message(self, *a):
        pass

    def cors(self):
        o = self.headers.get("Origin", "")
        if o in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", o)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Private-Network", "true")
        return o in ALLOWED_ORIGINS

    def do_OPTIONS(self):
        self.send_response(204 if self.host_ok() and self.headers.get("Origin", "") in ALLOWED_ORIGINS else 403)
        self.cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        body = b"poidh bridge for wedgie is running. Paste bridge/virtual-link.js into a wedgie.dev tab.\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/io" or not self.host_ok() or self.headers.get("Origin", "") not in ALLOWED_ORIGINS:
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            n = -1
        if not 0 <= n <= 65536:
            self.send_response(413)
            self.cors()
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        try:
            m = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            rx = m.get("rx") if isinstance(m, dict) else None
            rx = [x for x in rx if isinstance(x, str)][:50] if isinstance(rx, list) else []
        except ValueError:
            rx = []
        tx = []
        for line in rx:
            out = handle_line(self.poidh, line)
            if out:
                tx.append(out)
        body = json.dumps({"tx": tx}).encode()
        self.send_response(200)
        self.cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_virtual(p, port):
    Link.poidh, Link.port = p, port
    srv = ThreadingHTTPServer(("127.0.0.1", port), Link)
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "virtual-link.js")
    log("bridge listening on http://127.0.0.1:%d (wedgie.dev pages only)" % port)
    log("now paste %s into the DevTools console of your https://wedgie.dev/virtual tab" % here)
    srv.serve_forever()


def demo(p, chain):
    a = answer(p, {"type": "poidh_want", "rid": 1, "what": "list", "chain": chain, "page": 0, "per": 6})
    print(json.dumps(a, indent=1))
    if a.get("items"):
        b = a["items"][0]
        d = answer(p, {"type": "poidh_want", "rid": 2, "what": "bounty", "chain": b["ch"], "id": b["id"]})
        for r in d.get("body", []):
            print(("  " if r[2] == 1 else "##") + r[0])
        print("line bytes:", len(json.dumps(d)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    s = sub.add_parser("serial", help="a real wedgie on USB")
    s.add_argument("--port", help="its serial port (default: found by name)")
    v = sub.add_parser("virtual", help="the virtual wedgie in your browser")
    v.add_argument("--port", type=int, default=8765)
    dm = sub.add_parser("demo", help="print what the wedgie would get")
    dm.add_argument("chain", nargs="?", type=int, default=0)
    a = ap.parse_args()
    p = Poidh()
    if a.mode == "serial":
        run_serial(p, a.port)
    elif a.mode == "virtual":
        if not 1024 <= a.port <= 65535:
            sys.exit("--port must be 1024-65535")
        run_virtual(p, a.port)
    else:
        demo(p, a.chain)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
