"""Reviewed public deployment used by setup and the fixed provider transport.

Keep this origin explicit: neither environment input nor model output may expand
the destination for credentials. Host and Pi use the same URL contract.
"""

PUBLIC_ORIGIN = "https://modulate-connect.vercel.app"
CONNECT_URL = PUBLIC_ORIGIN + "/connect"
CONNECT_HOST = "modulate-connect.vercel.app"
CONNECT_LABEL = CONNECT_HOST + "/connect"
GATEWAY_URL = PUBLIC_ORIGIN + "/api/modulate-provider"
