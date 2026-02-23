"""LinkedIn OAuth 2.0 Setup — run once locally on your Mac.

Usage:
    python scripts/linkedin_auth.py

What it does:
    1. Prints the LinkedIn authorization URL
    2. You open it in your browser and approve
    3. LinkedIn redirects to the webhook URL with a code in the URL
    4. You paste that full redirect URL here
    5. Script exchanges the code, fetches your person URN, prints .env lines
    6. You add those lines to EC2 .env and restart Nova

Requirements:
    - LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET in .env (or enter below)
    - https://webhook.amplify-pixels.com/linkedin/callback registered as
      a redirect URI in your LinkedIn Developer App
      (Auth tab → OAuth 2.0 settings → Redirect URLs)

Run every ~60 days to refresh the token.
"""

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

# ── Load .env ─────────────────────────────────────────────────────────────────
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

# ── Credentials ───────────────────────────────────────────────────────────────
CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID", "").strip() or input("LinkedIn Client ID: ").strip()
CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET", "").strip() or input("LinkedIn Client Secret: ").strip()

BASE_URL = os.getenv("NOVA_BASE_URL", "https://webhook.amplify-pixels.com").rstrip("/")
REDIRECT_URI = f"{BASE_URL}/linkedin/callback"
SCOPE = "w_member_social"

# ── Step 1: Print auth URL ────────────────────────────────────────────────────
params = urllib.parse.urlencode({
    "response_type": "code",
    "client_id": CLIENT_ID,
    "redirect_uri": REDIRECT_URI,
    "state": "nova_linkedin_setup",
    "scope": SCOPE,
})
auth_url = f"https://www.linkedin.com/oauth/v2/authorization?{params}"

print()
print("=" * 65)
print("Step 1: Open this URL in your browser and approve access:")
print("=" * 65)
print(f"\n  {auth_url}\n")
print("After approving, your browser will redirect to:")
print(f"  {REDIRECT_URI}?code=...")
print("(The page may show an error or timeout — that's fine.)")
print()

# ── Step 2: User pastes the redirect URL ─────────────────────────────────────
print("=" * 65)
print("Step 2: Paste the full redirect URL from your browser address bar:")
print("=" * 65)
redirect_url = input("\nPaste URL here: ").strip()

parsed = urllib.parse.urlparse(redirect_url)
code = urllib.parse.parse_qs(parsed.query).get("code", [""])[0]

if not code:
    print(f"\nERROR: No 'code' found in URL: {redirect_url}")
    raise SystemExit(1)

print(f"\n  Code extracted: {code[:20]}...")

# ── Step 3: Exchange code for token ──────────────────────────────────────────
print("\nExchanging code for access token...")
token_data = urllib.parse.urlencode({
    "grant_type": "authorization_code",
    "code": code,
    "redirect_uri": REDIRECT_URI,
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
}).encode()

req = urllib.request.Request(
    "https://www.linkedin.com/oauth/v2/accessToken",
    data=token_data,
    method="POST",
    headers={"Content-Type": "application/x-www-form-urlencoded"},
)
with urllib.request.urlopen(req, timeout=15) as resp:
    token_resp = json.loads(resp.read())

access_token = token_resp.get("access_token", "")
if not access_token:
    print(f"\nERROR: Token exchange failed:\n{json.dumps(token_resp, indent=2)}")
    raise SystemExit(1)

expires_days = token_resp.get("expires_in", 0) // 86400
print(f"  Token received (expires in {expires_days} days)")

# ── Step 4: Fetch person URN ──────────────────────────────────────────────────
print("Fetching LinkedIn person ID...")
person_id = ""
try:
    req = urllib.request.Request(
        "https://api.linkedin.com/v2/me?projection=(id)",
        headers={
            "Authorization": f"Bearer {access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        me_data = json.loads(resp.read())
    person_id = me_data.get("id", "")
except Exception as e:
    print(f"  Could not fetch person ID automatically: {e}")

# ── Step 5: Print results ─────────────────────────────────────────────────────
print()
print("=" * 65)
print("Add these lines to your EC2 .env file:")
print("=" * 65)
print(f"\nLINKEDIN_CLIENT_ID={CLIENT_ID}")
print(f"LINKEDIN_CLIENT_SECRET={CLIENT_SECRET}")
print(f"LINKEDIN_ACCESS_TOKEN={access_token}")
if person_id:
    print(f"LINKEDIN_PERSON_URN=urn:li:person:{person_id}")
else:
    print("LINKEDIN_PERSON_URN=urn:li:person:YOUR_ID_HERE")
    print()
    print("Get your person ID manually:")
    print(f'  curl -H "Authorization: Bearer {access_token}" \\')
    print('    "https://api.linkedin.com/v2/me?projection=(id)"')
print()
print("Then restart Nova:  sudo systemctl restart digital-twin")
print(f"Token expires in {expires_days} days — re-run this script to refresh.")
print("=" * 65)
