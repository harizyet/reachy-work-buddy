#!/usr/bin/env python3
"""Temporary loopback OAuth transport for a self-hosted Reachy's Google Desktop client.

Run this once on the machine whose browser you use to reach Reachy, when the
Accounts page shows a "Connect Google" command for it. This script:

  1. binds a free port on 127.0.0.1,
  2. opens your browser to Google's consent screen,
  3. receives the single redirect Google sends back with an authorization
     code,
  4. hands that code (plus the loopback address Google sent it to) to your
     Reachy Hub over HTTPS, and
  5. exits.

It never sees your Google client secret or the PKCE verifier — those stay on
the Reachy server, which performs the actual token exchange. This script is
bootstrap transport only, not a long-running credential holder; nothing it
does or prints needs to be kept afterward.

Usage (the Accounts page prints the exact invocation for you):

    python3 google_auth_helper.py --hub-url https://reachy.example.org/hub \\
        --client-id ... --scope "..." --state ... --binding ... \\
        --code-challenge ...
"""
import argparse
import json
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hub-url", required=True, help="Reachy Hub base URL, e.g. https://reachy.example.org/hub")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--binding", required=True)
    parser.add_argument("--code-challenge", required=True)
    parser.add_argument("--code-challenge-method", default="S256")
    parser.add_argument("--timeout", type=int, default=300, help="Seconds to wait for the browser redirect")
    return parser.parse_args()


class CallbackHandler(BaseHTTPRequestHandler):
    result = None

    def do_GET(self):
        query = parse_qs(urlsplit(self.path).query)
        CallbackHandler.result = {
            "code": query.get("code", [None])[0],
            "error": query.get("error", [None])[0],
        }
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"<p>Reachy sign-in finished. You can close this tab.</p>")

    def log_message(self, *args):
        pass


def main():
    args = parse_args()
    server = HTTPServer(("127.0.0.1", 0), CallbackHandler)
    port = server.server_address[1]
    redirect_uri = f"http://127.0.0.1:{port}/"

    auth_url = AUTH_ENDPOINT + "?" + urlencode({
        "client_id": args.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent",
        "scope": args.scope,
        "state": args.state,
        "code_challenge": args.code_challenge,
        "code_challenge_method": args.code_challenge_method,
    })
    print(f"Opening your browser for Google sign-in. If it does not open, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    server.timeout = args.timeout
    server.handle_request()
    server.server_close()

    if CallbackHandler.result is None:
        print(f"Timed out after {args.timeout}s waiting for Google's redirect. Try Connect again.", file=sys.stderr)
        return 1

    payload = {
        "state": args.state,
        "binding": args.binding,
        "code": CallbackHandler.result["code"],
        "error": CallbackHandler.result["error"],
        "redirect_uri": redirect_uri,
    }
    complete_url = args.hub_url.rstrip("/") + "/settings/accounts/google/desktop/complete"
    request = Request(complete_url, data=json.dumps(payload).encode(),
                       headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=30) as response:
            json.loads(response.read())
    except HTTPError as exc:
        print(f"Reachy rejected the sign-in ({exc.code}): {exc.read().decode(errors='replace')}", file=sys.stderr)
        return 1
    except URLError as exc:
        print(f"Could not reach Reachy Hub at {args.hub_url}: {exc.reason}", file=sys.stderr)
        return 1

    if payload["error"] or not payload["code"]:
        print("Google sign-in was cancelled.", file=sys.stderr)
        return 1
    print("Google account connected. Return to the Accounts page.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
