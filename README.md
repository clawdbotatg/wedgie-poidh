# poidh for wedgie

Browse live [poidh](https://poidh.xyz) bounties on a [wedgie](https://wedgie.dev). It shows open bounties on Ethereum, Base and Arbitrum: titles, ETH rewards, descriptions and details, and every claim on a bounty. You move through them with the joystick and buttons, and it is laid out for the 240x240 screen.

A wedgie has no internet of its own. On firmware 0.3.61+ an app can use its computer's: the wedgie's
page on wedgie.dev (open in a tab) fetches poidh's public feeds for it, through wedgie.dev's `net`
([wedgie.dev/code.md](https://wedgie.dev/code.md), "The internet"). No bridge, nothing to install. All data is
real and live. Nothing is hard-coded.

**Demo video (virtual wedgie):** [media/poidh-wedgie-demo.mp4](https://github.com/swiftbotlab/wedgie-poidh/raw/main/media/poidh-wedgie-demo.mp4)

| Bounties | A bounty | Its claims | One claim |
|---|---|---|---|
| ![list](media/screen-list.png) | ![bounty](media/screen-bounty.png) | ![claims](media/screen-claims.png) | ![claim](media/screen-claim.png) |

## Controls

| On the wedgie | What it does |
|---|---|
| Joystick up / down | move through the list, or scroll text |
| Joystick left / right | switch chain: All, Ethereum, Base, Arbitrum (on a text page: scroll 10 lines) |
| Green button (or press the joystick) | open the bounty, then its claims, then one claim |
| Red button | back |
| Grey button next to green | reload what's on screen from poidh |

In the list, `*` after the chain means the bounty already has claims. The top right shows the chain and your position (`Base 3/93`).

## What's in the repo

| Path | What |
|---|---|
| `wedgie.json` | the app's manifest (mod `poidh`, entry `run`, `"net": ["poidh.xyz", "api.coinbase.com"]`) |
| `poidh/poidh.py` | the wedgie app (MicroPython) |

## Install it

1. Plug the wedgie in and open https://wedgie.dev/connect in Chrome or Edge. Update its firmware if it asks
   (0.3.61 or newer).
2. Pick **Poidh Bounties** on the shelf and press the green button on the wedgie.
3. **Keep that wedgie.dev tab open.** It's the app's internet. Closed, the app says **No internet**.

Or in a terminal: `python3 wedgie.py use poidh`, then `python3 wedgie.py net` (stays running, is its internet)
([wedgie.py](https://wedgie.dev/wedgie.py) needs pyserial).

**On the virtual wedgie:** open https://wedgie.dev/virtual in Chrome. In another tab of the same browser, open
https://wedgie.dev/connect, pick the virtual wedgie (`EEE...`), install it and keep that tab open.

## How it works

The app asks for one screen of data at a time with `net.get(url, pick=...)`. The wedgie's page passes it to
wedgie.dev, which fetches it and sends back only the fields in `pick`, so every answer fits the wedgie's memory
(under 5 KB):

- **Bounties:** `https://poidh.xyz/bounties/data`, poidh's public feed of open bounties, newest first. The app
  first asks for every bounty's chain (`items.*.chainId`), then the 6 rows on screen.
- **Claims:** `claims.fetchBountyClaims`, the same tRPC call poidh.xyz uses on a bounty page.
- **The time:** `https://api.coinbase.com/v2/time`, once, for "posted 2 days ago" (a wedgie has no clock).
- The app turns wei into ETH, Unicode and Markdown into plain ASCII for the wedgie's font, and wraps text to
  29 columns. A description shows its first 1,500 characters.

## Security

- The app only reads public data. It never asks the wedgie's secure chip for anything and never signs.
- It can reach only the sites in its wedgie.json `"net"` (poidh.xyz, api.coinbase.com). wedgie.dev and
  `wedgie.py net` refuse anything else.
- It no longer reads USB itself (no `"usb": true`): the firmware answers USB as usual, so the lock, updates
  and every green-button question work as they do for any app.
- Everything fetched is treated as untrusted: reduced to printable ASCII, cut to fixed lengths, type-checked.

## License

MIT, by Swift Bot Labs. poidh data belongs to poidh and the people who post bounties and claims.
