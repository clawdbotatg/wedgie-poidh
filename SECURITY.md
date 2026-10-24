# Security

The security notes are in the [README](README.md#security). Short version: the bridge only reads public poidh data over HTTPS. It holds no keys and listens only on 127.0.0.1 for wedgie.dev pages. Everything it fetches is size-capped and reduced to plain ASCII before it reaches the wedgie.

To report a problem, open an issue on this repo. If the details should stay private, ask in the issue for a private way to send them.
