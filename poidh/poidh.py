# poidh for wedgie: browse live poidh bounties (Ethereum, Base, Arbitrum) and their claims.
#
# A wedgie has no internet of its own. Firmware 0.3.61+ gives an app its computer's: `import net`, and its
# page on wedgie.dev (open in a tab) or `wedgie.py net` fetches for it, only from the sites wedgie.json
# lists ("net": poidh.xyz for the bounties, api.coinbase.com for the time: a wedgie has no clock).
# https://wedgie.dev/code.md, "The internet". Each answer must fit in 5 KB, so every request picks
# only the fields this screen shows (pick).
#
# Controls: joystick up/down moves, left/right changes chain (list) or pages (text), green (or a press
# of the joystick) opens, red goes back, the grey button next to green (X) reloads.
import time, gc
import lcd as L
import ui
import net
from ui import WHITE, INK, MUTED, GREEN_D, RED

PER = 6                             # rows per list page
COLS = 29                           # characters across at scale 1 (4 px margins)
BIG = 14                            # characters across at scale 2
DESC = 1500                         # characters of a description (an answer must fit in 5 KB)
SEL = L.color(236, 237, 238)        # the selected row's background
LINE = L.color(216, 217, 218)
CHAINS = ((0, "All"), (1, "Ethereum"), (8453, "Base"), (42161, "Arbitrum"))
SLUG = {1: "mainnet", 8453: "base", 42161: "arbitrum"}
POIDH = "https://poidh.xyz"
FEED = POIDH + "/bounties/data?limit=100"   # open bounties, newest first, 100 a page (nextCursor)
FRESH = 60000                       # ms the list of every open bounty's chain stays fresh

d = None
keys = None
want = False                        # a fetch is under way (its screen shows "Getting it")
err = None
dirty = True

view = "list"                       # list | bounty | claims | claim
chain_i = 0
sel = 0                             # list: index across all pages
lst = None                          # {"page", "total", "items"} of the list page on screen
bounty = None                       # the bounty open: {"hasClaims", "body"}
scroll = 0
csel = 0
cl = None                           # claims page
claim = None
idx = None                          # every open bounty: (its feed page's url, its place there, its chain)
idx_at = 0
clock = None                        # unix seconds minus ticks_ms // 1000 (api.coinbase.com/v2/time)


# ---- poidh's data, through net ---------------------------------------------------------------------

def index(force=False):
    global idx, idx_at
    if idx is not None and not force and time.ticks_diff(time.ticks_ms(), idx_at) < FRESH:
        return idx
    out, url = [], FEED
    for _ in range(4):
        r = net.get(url, pick={"c": "items.*.chainId", "n": "nextCursor"})
        for k, c in enumerate(r["c"] or ()):
            c = int(c)
            if c in SLUG:
                out.append((url, k, c))
        if not r["n"]:
            break
        url = FEED + "&cursor=" + str(r["n"])
    idx, idx_at = out, time.ticks_ms()
    return out


def forget():
    global idx
    idx = None


def now():
    global clock
    if clock is None:
        clock = int(net.get("https://api.coinbase.com/v2/time", pick="data.epoch")) - time.ticks_ms() // 1000
    return clock + time.ticks_ms() // 1000


def claims_url(ch, bid):
    q = '{"json":{"bountyId":%d,"chainId":%d,"limit":100}}' % (bid, ch)
    for a, b in (("{", "%7B"), ("}", "%7D"), ('"', "%22"), (":", "%3A"), (",", "%2C")):
        q = q.replace(a, b)
    return POIDH + "/api/trpc/claims.fetchBountyClaims?input=" + q


CL = "result.data.json.items"
FIX = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "...",
       "×": "x", "•": "*", " ": " ", "→": "->", "·": "*", "€": "EUR", "£": "GBP"}


def text(v, n=4000):
    """Anything from poidh -> plain ASCII for the wedgie's font, markdown marks dropped."""
    v = "" if v is None else str(v)
    out = []
    for ch in v[:n]:
        if ch == "\n" or " " <= ch <= "~":
            out.append(ch)
        elif ch == "\t":
            out.append(" ")
        elif ch in FIX:
            out.append(FIX[ch])
    v = "".join(out).replace("**", "").replace("__", "").replace("`", "")
    lines = []
    for l in v.split("\n"):
        l = l.strip()
        while l.startswith("#") or l.startswith(">"):
            l = l[1:].strip()
        if l[:2] in ("- ", "+ "):
            l = "* " + l[2:]
        lines.append(" ".join(l.split()))
    return "\n".join(lines).strip()


def wrap(v, n=COLS):
    """Words into lines of at most n characters; long words (URLs, addresses) are cut."""
    lines = []
    for para in v.split("\n"):
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
    """wei (a string or int) -> "0.0045 ETH", in whole numbers (a wedgie's floats are 32-bit)."""
    try:
        w = int(wei)
    except (TypeError, ValueError):
        return "? ETH"
    if w <= 0:
        return "0 ETH" if w == 0 else "? ETH"
    i, f = w // 10 ** 18, str(w % 10 ** 18)
    if i >= 100:
        return "%d ETH" % i
    f = (("0" * (18 - len(f))) + f)[:3 if i else 6].rstrip("0")
    if not i and not f:
        return "<0.000001 ETH"
    return ("%d.%s" % (i, f) if f else "%d" % i) + " ETH"


def usd(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    if f != f or f < 0:
        return ""
    if f < 1000:
        return "$%.2f" % f
    i, out = str(int(f)), ""
    while len(i) > 3:
        out, i = "," + i[-3:] + out, i[:-3]
    return "$" + i + out


def ago(ts):
    try:
        dt = max(0, now() - int(ts))
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
    n = int(a.rstrip("mhdo"))
    word = {"m": "minute", "h": "hour", "d": "day", "mo": "month"}[a[len(str(n)):]]
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def short_addr(a):
    a = a if isinstance(a, str) else ""
    if len(a) == 42 and a.startswith("0x"):
        return a[:6] + ".." + a[-4:]
    return text(a, 13) or "?"


def name(ch):
    for c, n in CHAINS:
        if c == ch:
            return n
    return "?"


def list_page(chain, page):
    rows = [x for x in index() if not chain or x[2] == chain]
    mine = rows[page * PER:(page + 1) * PER]
    got = {}
    for url in set(x[0] for x in mine):     # one request per feed page (two at most)
        ks = [x[1] for x in mine if x[0] == url]
        r = net.get(url, pick={str(k): "items.%d.{id,chainId,title,amount,hasClaims,createdAt}" % k for k in ks})
        for k in ks:
            got[(url, k)] = r[str(k)]
    items = []
    for x in mine:
        b = got.get((x[0], x[1])) or {}
        ch = int(b.get("chainId") or x[2])
        items.append({"ch": ch, "id": int(b.get("id") or 0), "at": (x[0], x[1]),
                      "t": text(b.get("title"), 60) or "(untitled)", "a": eth(b.get("amount")),
                      "c": name(ch) + (" *" if b.get("hasClaims") else ""), "ago": ago(b.get("createdAt"))})
    return {"page": page, "total": len(rows), "items": items}


def bounty_page(at, ch, bid):
    url, k = at
    r = net.get(url, pick={"b": "items.%d.{id,title,amount,priceUsd,issuer,createdAt,onChainId,hasClaims,isMultiplayer,deadline}" % k,
                           "d": "items.%d.description.0:%d" % (k, DESC)})
    b = r["b"] or {}
    if int(b.get("id") or -1) != bid:
        raise net.Error("the list changed: {k} reload")
    n = acc = 0
    if b.get("hasClaims"):
        a = net.get(claims_url(ch, bid), pick=CL + ".*.isAccepted") or ()
        n, acc = len(a), sum(1 for x in a if x)
    body = []
    title = text(b.get("title"), 120) or "(untitled)"
    t2 = wrap(title, BIG)
    if len(t2) <= 3:
        body += [[x, 0, 2] for x in t2]
    else:
        body += [[x, 0, 1] for x in wrap(title)[:5]]
    body.append(["-", 1, 1])
    body.append([eth(b.get("amount")), 2, 2])
    u, kind = usd(b.get("priceUsd")), "open bounty" if b.get("isMultiplayer") else "solo bounty"
    body.append([("%s  %s" % (u, kind)) if u else kind, 1, 1])
    body.append(["by " + short_addr(b.get("issuer")), 1, 1])
    body.append(["posted %s ago" % ago_words(b.get("createdAt")), 1, 1])
    body.append(["poidh id %d, on-chain %s" % (bid, b.get("onChainId", "?")), 1, 1])
    body.append(["%d claim%s%s" % (n, "" if n == 1 else "s", ", %d accepted" % acc if acc else ""), 2, 1] if n
                else ["no claims yet", 1, 1])
    if b.get("deadline"):
        body.append(["deadline set", 1, 1])
    body.append(["-", 1, 1])
    desc = r["d"] or ""
    body += [[x, 0, 1] for x in (wrap(text(desc)) or ["(no description)"])]
    if len(desc) >= DESC:
        body.append(["... more on poidh.xyz", 1, 1])
    body.append(["-", 1, 1])
    body.append(["poidh.xyz/%s/bounty/%d" % (SLUG.get(ch, "base"), bid), 1, 1])
    return {"hasClaims": n > 0, "body": body}


def claims_page(ch, bid, page):
    r = net.get(claims_url(ch, bid), pick={"n": CL + ".*.isAccepted",
                                           "r": CL + ".%d:%d.{id,title,isAccepted,issuer}" % (page * PER, (page + 1) * PER)})
    items = [{"id": int(c.get("id") or 0), "k": page * PER + i, "t": text(c.get("title"), 60) or "(untitled)",
              "st": "accepted" if c.get("isAccepted") else "claim", "by": short_addr(c.get("issuer")), "ago": ""}
             for i, c in enumerate(r["r"] or ())]
    return {"page": page, "total": len(r["n"] or ()), "items": items}


def claim_page(ch, bid, k, cid):
    r = net.get(claims_url(ch, bid), pick={"c": CL + ".%d.{id,title,isAccepted,issuer,onChainId,url}" % k,
                                           "d": CL + ".%d.description.0:%d" % (k, DESC)})
    c = r["c"] or {}
    if int(c.get("id") or -1) != cid:
        raise net.Error("the claims changed: {k} reload")
    body = [[x, 0, 1] for x in wrap(text(c.get("title"), 120) or "(untitled)")[:4]]
    body.append(["ACCEPTED, paid out" if c.get("isAccepted") else "waiting for the issuer", 2 if c.get("isAccepted") else 1, 1])
    body.append(["by " + short_addr(c.get("issuer")), 1, 1])
    body.append(["claim id %d/%s" % (cid, c.get("onChainId", "?")), 1, 1])
    body.append(["-", 1, 1])
    desc = r["d"] or ""
    body += [[x, 0, 1] for x in (wrap(text(desc)) or ["(no description)"])]
    if len(desc) >= DESC:
        body.append(["... more on poidh.xyz", 1, 1])
    url = c.get("url") if isinstance(c.get("url"), str) else ""
    if url.startswith("https://"):
        body.append(["-", 1, 1])
        body.append(["proof:", 1, 1])
        body += [[x, 1, 1] for x in wrap(text(url, 200))[:4]]
    return {"body": body}


def load(fn, *a):
    """Fetch one screen's data: its "Getting it" screen first, then the answer, or err on the screen."""
    global want, err, dirty
    want, err = True, None
    draw()
    r = None
    try:
        r = fn(*a)
    except net.Error as e:
        err = str(e)[:120]
    except (KeyError, TypeError, ValueError, AttributeError) as e:     # poidh answered something new
        err = "poidh changed: " + type(e).__name__
    want, dirty = False, True
    gc.collect()
    return r


# ---- drawing --------------------------------------------------------------------------------------

def s(v, n=COLS):
    v = str(v) if v is not None else ""
    return v if len(v) <= n else v[:n - 1] + "~"


def header(left, right=""):
    d.fill(WHITE)
    d.big_text(s(left, 14), 4, 4, INK, 2)
    if right:
        r = s(right, 14)
        d.text(r, ui.right() - 8 * len(r), 9, MUTED)
    for i, c in enumerate((ui.GREEN, ui.GREY, RED)):
        d.fill_rect(0, 24 + i * 3, 240, 2, c)


def footer(hint):
    d.hline(0, 220, 240, LINE)
    ui.say(d, hint, 227, MUTED)


def status_line(y=120):
    if err and err.startswith("no internet"):
        ui.say(d, "No internet", y, RED)
        ui.say(d, "open this wedgie's page", y + 16, MUTED)
        ui.say(d, "on wedgie.dev", y + 28, MUTED)
        ui.say(d, "{k} try again", y + 46, MUTED)
    elif err:
        for i, x in enumerate(wrap(err)[:3]):
            ui.say(d, x, y + 14 * i, RED)
        ui.say(d, "{k} try again", y + 46, MUTED)
    else:
        ui.say(d, "Getting it from poidh", y, MUTED)


def rows(items, start, cur, line1, line2):
    y = 34
    for i, it in enumerate(items):
        on = start + i == cur
        if on:
            d.fill_rect(0, y, 240, 30, INK)
        a, b, c = line2(it)
        d.text(s(line1(it)), 4, y + 4, WHITE if on else INK)
        d.text(a, 4, y + 17, ui.GREEN if on else GREEN_D)
        if b:
            d.text(s(b, COLS - len(a) - 1), 4 + 8 * (len(a) + 1), y + 17, LINE if on else MUTED)
        if c:
            d.text(c, 236 - 8 * len(c), y + 17, LINE if on else MUTED)
        if not on:
            d.hline(0, y + 30, 240, LINE)
        y += 31


def draw_list():
    name = CHAINS[chain_i][1]
    total = lst.get("total", 0) if lst else 0
    header("poidh", ("< %s >" % name) if not lst else "%s %d/%d" % (name, min(sel + 1, total), total))
    if lst and not want and not err:
        if not lst["items"]:
            ui.say(d, "No open bounties", 110, INK)
            ui.say(d, "on %s right now" % name, 126, MUTED)
        else:
            rows(lst["items"], lst["page"] * PER, sel, lambda b: b["t"], lambda b: (b["a"], b["c"], b["ago"]))
    else:
        status_line()
    footer("{g} open  < > chain  {k} reload")


def draw_text(head, right, body, hint):
    """A page of text rows [text, color, scale]; scroll moves through them."""
    header(head, right)
    if body is None:
        status_line()
    else:
        y = 36
        for r in body[scroll:]:
            h = 16 * r[2] if r[2] > 1 else 13
            if y + h > 218:
                break
            col = (INK, MUTED, GREEN_D, RED)[r[1]]
            if r[2] > 1:
                d.big_text(s(r[0], 29 // r[2]), 4, y, col, r[2])
            elif r[0] == "-":
                d.hline(4, y + 5, 232, LINE)
            else:
                d.text(s(r[0]), 4, y, col)
            y += h
        if len(body) > 1 and (scroll > 0 or y > 205):
            n = len(body)
            top = 36 + 180 * scroll // n
            d.fill_rect(237, top, 3, max(8, 180 * 12 // n), MUTED)
    footer(hint)


def draw():
    if view == "list":
        draw_list()
    elif view == "bounty":
        b = bounty if bounty and not want and not err else None
        draw_text(name(bounty_key[0]), "#%d" % bounty_key[1], b and b["body"],
                  "{g} claims  {r} back" if b and b.get("hasClaims") else "{r} back  ^ v scroll")
    elif view == "claims":
        total = cl.get("total", 0) if cl else 0
        header("Claims", ("%d/%d" % (min(csel + 1, total), total)) if cl and total else "#%d" % bounty_key[1])
        if cl and not want and not err:
            if not cl["items"]:
                ui.say(d, "No claims yet", 110, INK)
                ui.say(d, "be the first on poidh.xyz", 126, MUTED)
            else:
                rows(cl["items"], cl["page"] * PER, csel, lambda c: c["t"], lambda c: (c["st"], c["by"], c["ago"]))
        else:
            status_line()
        footer("{g} open  {r} back")
    elif view == "claim":
        c = claim if claim and not want and not err else None
        draw_text("Claim", "#%d" % claim_id, c and c["body"], "{r} back  ^ v scroll")
    d.show()




# ---- moving around --------------------------------------------------------------------------------

def load_list():
    global lst
    lst = load(list_page, CHAINS[chain_i][0], sel // PER)


def load_bounty():
    global bounty
    bounty = load(bounty_page, bounty_at, bounty_key[0], bounty_key[1])


def load_claims():
    global cl
    cl = load(claims_page, bounty_key[0], bounty_key[1], csel // PER)


def load_claim():
    global claim
    claim = load(claim_page, bounty_key[0], bounty_key[1], claim_k, claim_id)


def key(k):
    global view, chain_i, sel, lst, scroll, csel, cl, bounty, bounty_key, bounty_at, claim, claim_id, claim_k, dirty
    dirty = True
    if k == "X":                                       # reload what's on screen
        if view == "list":
            forget()
            load_list()
        elif view == "bounty":
            load_bounty()
        elif view == "claims":
            load_claims()
        else:
            load_claim()
        return
    if view == "list":
        if k in ("left", "right"):
            chain_i = (chain_i + (1 if k == "right" else -1)) % len(CHAINS)
            sel, lst = 0, None
            load_list()
        elif lst and lst["items"]:
            total = lst.get("total", 0)
            if k in ("up", "down"):
                n = sel + (1 if k == "down" else -1)
                if 0 <= n < total:
                    page = sel // PER
                    sel = n
                    if n // PER != page:
                        load_list()
            elif k in ("A", "press"):
                i = sel - lst["page"] * PER
                if 0 <= i < len(lst["items"]):
                    b = lst["items"][i]
                    bounty_key, bounty_at = (b["ch"], b["id"]), b["at"]
                    view, bounty, scroll = "bounty", None, 0
                    load_bounty()
    elif view in ("bounty", "claim"):
        body = (bounty if view == "bounty" else claim) or {}
        n = len(body.get("body") or ())
        if k in ("up", "down", "left", "right"):
            step = 1 if k in ("up", "down") else 10
            scroll = max(0, min(max(0, n - 10), scroll + (step if k in ("down", "right") else -step)))
        elif k == "Y":
            if view == "bounty":
                view, bounty = "list", None
                if not lst:
                    load_list()
            else:
                view, claim = "claims", None
                if not cl:
                    load_claims()
        elif k in ("A", "press") and view == "bounty" and bounty and bounty.get("hasClaims"):
            view, csel, cl = "claims", 0, None
            load_claims()
    elif view == "claims":
        if k == "Y":
            view, cl = "bounty", None
            if not bounty:
                load_bounty()
        elif cl and cl["items"]:
            total = cl.get("total", 0)
            if k in ("up", "down"):
                n = csel + (1 if k == "down" else -1)
                if 0 <= n < total:
                    page = csel // PER
                    csel = n
                    if n // PER != page:
                        load_claims()
            elif k in ("A", "press"):
                i = csel - cl["page"] * PER
                if 0 <= i < len(cl["items"]):
                    claim_id, claim_k = cl["items"][i]["id"], cl["items"][i]["k"]
                    view, claim, scroll = "claim", None, 0
                    load_claim()


bounty_key = (0, 0)
bounty_at = None
claim_id = claim_k = 0


def run():
    global d, keys, dirty
    d = L.LCD()
    keys = L.Keys()
    load_list()
    while True:
        for k in keys.pressed():
            key(k)
        if dirty:
            dirty = False
            draw()
        time.sleep_ms(30)
