# Modulate Setup

A portable setup skill for connecting a preloaded Modulate gadget to its Mac companion and browser. Your coding agent works on the Mac. The gadget handles its own enrollment through its setup screen; customers do not need a Pi terminal or Raspberry Pi Connect account. This download contains instructions and a read-only diagnostic helper. It does not install or launch Modulate automatically, include credentials, or grant macOS permissions.

## Use with your coding agent

Unzip the download and open the `modulate-setup` folder in your coding agent on the Mac you want to connect. Ask:

> Read skills/modulate-setup/SKILL.md and follow it to connect this Mac to my preloaded Modulate. Reuse my active installation and guide me through the gadget's on-screen pairing flow without a Pi shell.

You can also paste [setup-prompt.txt](setup-prompt.txt) directly into your coding agent without downloading or installing anything. The prompt links to the same published skill.

To keep the skill for later, optionally install it using your agent's supported skill mechanism. Reading the Markdown works without a native plugin adapter. Your agent needs access to local files and commands to do the software setup; a chat-only agent can explain the steps but cannot install it for you.

<details>
<summary>Optional technical adapter: Codex local plugin</summary>

The included `.codex-plugin/plugin.json`, `agents/openai.yaml` and `install.py` are an optional Codex-specific adapter, not a universal plugin installer. Other agents should use the portable skill above or their own supported installation method.

For this adapter, ask Codex to inspect the package and run `python3 install.py --install`. It copies only this package into `~/.codex/plugins/modulate-setup/0.2.0` and adds it to `~/.agents/plugins/marketplace.json`, preserving other entries. It does not enable the plugin or modify permissions. Restart Codex, select **Modulate Setup** from the local Plugins source, and install/enable it. Then use `$modulate-setup`.

Running `python3 install.py` without `--install` prints the planned changes only. A different existing plugin at that path or a conflicting catalog entry, including an older version's registration, is left untouched for review. The script prints the catalog backup path when it changes an existing catalog. Use Codex's normal uninstall/disable controls to remove access; the source files remain local.

The format and local marketplace procedure are documented in [OpenAI's plugin packaging guide](https://developers.openai.com/plugins/build/plugins). This is a manually distributed local adapter, not a public-directory listing or signed native installer.

</details>

## What connection means

The current public dashboard serves a configured Modulate hub. A new independent Mac needs its own native companion, device enrollment and provider configuration; remote access needs a gateway/deployment the user owns or access supplied by the hub administrator. Downloading the plugin does not automatically join the public demo or provide API credits.

The preloaded device must include the enrollment service from this release. Older devices that only say “Enroll this Pi once” need a factory software update; the skill reports that gap instead of assuming developer shell access. A blank Raspberry Pi is a separate developer-kit installation, not this customer flow. The device and Mac must have a network route to each other; a preloaded image alone does not configure a customer's Wi-Fi.
