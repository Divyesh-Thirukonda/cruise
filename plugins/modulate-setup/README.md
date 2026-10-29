# Modulate Setup for Codex

A local setup skill for Modulate's Mac companion, Raspberry Pi runtime, and browser connection. This plugin contains instructions and a read-only diagnostic helper. It does not install or launch Modulate automatically, include credentials, or grant macOS permissions.

## Use once

Paste [setup-prompt.txt](setup-prompt.txt) into Codex on the Mac you want to connect. The prompt works without installing the plugin.

## Keep the plugin

Unzip the download and open the `modulate-setup` folder in Codex. Ask:

> Inspect this plugin, install it with `python3 install.py --install`, then use $modulate-setup to connect my Mac and Raspberry Pi.

The script first checks the package. It copies only this plugin into `~/.codex/plugins/modulate-setup/0.1.0` and adds it to `~/.agents/plugins/marketplace.json`, preserving other entries. It does not enable the plugin or modify Codex permissions. Restart Codex, select **Modulate Setup** from the local Plugins source, and install/enable it. Then ask Codex to use `$modulate-setup`.

Running `python3 install.py` without `--install` prints the planned changes only. A different existing plugin at that path or a conflicting catalog entry is left untouched. The script prints the catalog backup path when it changes an existing catalog. Use Codex's normal uninstall/disable controls to remove access; the source files remain local.

The supported package format and local marketplace procedure are documented in [OpenAI's plugin packaging guide](https://developers.openai.com/plugins/build/plugins). This ZIP is a manually distributed local plugin, not a public-directory listing or signed native installer.

## What connection means

The current public dashboard serves a configured Modulate hub. The skill can recover that setup or help prepare a new local installation. A new independent Mac needs its own native companion, Pi enrollment and provider configuration; remote access needs a gateway/deployment the user owns or access supplied by the hub administrator. Downloading the plugin does not automatically join the public demo or provide API credits.
