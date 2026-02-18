#!/usr/bin/env python3
"""Quick test script for X posting. Run on EC2 to verify credentials."""

import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv('X_API_KEY')
api_secret = os.getenv('X_API_SECRET')
access_token = os.getenv('X_ACCESS_TOKEN')
access_token_secret = os.getenv('X_ACCESS_TOKEN_SECRET')

print("=== X Credential Check ===")
print(f"X_API_KEY:            {'SET (' + api_key[:8] + '...)' if api_key else 'MISSING'}")
print(f"X_API_SECRET:         {'SET (' + api_secret[:8] + '...)' if api_secret else 'MISSING'}")
print(f"X_ACCESS_TOKEN:       {'SET (' + access_token[:8] + '...)' if access_token else 'MISSING'}")
print(f"X_ACCESS_TOKEN_SECRET: {'SET (' + access_token_secret[:8] + '...)' if access_token_secret else 'MISSING'}")

missing = [k for k, v in {
    'X_API_KEY': api_key,
    'X_API_SECRET': api_secret,
    'X_ACCESS_TOKEN': access_token,
    'X_ACCESS_TOKEN_SECRET': access_token_secret
}.items() if not v]

if missing:
    print(f"\n❌ Missing credentials: {', '.join(missing)}")
    print("Add them to .env and try again.")
    exit(1)

print("\n=== Testing X API v2 POST /2/tweets ===")

from requests_oauthlib import OAuth1Session

oauth = OAuth1Session(
    api_key,
    client_secret=api_secret,
    resource_owner_key=access_token,
    resource_owner_secret=access_token_secret
)

# Test post
import json
payload = {"text": "Test post from Digital Twin bot 🤖 (will delete)"}

print(f"Posting: {payload['text']}")
resp = oauth.post("https://api.x.com/2/tweets", json=payload)

print(f"\nStatus: {resp.status_code}")
print(f"Response: {json.dumps(resp.json(), indent=2)}")

if resp.status_code in (200, 201):
    tweet_id = resp.json().get("data", {}).get("id")
    print(f"\n✅ Tweet posted! ID: {tweet_id}")
    print(f"View at: https://x.com/i/status/{tweet_id}")

    # Offer to delete
    answer = input("\nDelete this test tweet? (y/n): ").strip().lower()
    if answer == 'y':
        del_resp = oauth.delete(f"https://api.x.com/2/tweets/{tweet_id}")
        print(f"Delete status: {del_resp.status_code}")
        if del_resp.status_code == 200:
            print("✅ Test tweet deleted.")
        else:
            print(f"❌ Delete failed: {del_resp.text}")
else:
    print(f"\n❌ Post failed!")
    print("Common causes:")
    print("  - 401: Wrong credentials or OAuth 1.0a not enabled")
    print("  - 403: App doesn't have Write permissions")
    print("  - 429: Rate limited")
