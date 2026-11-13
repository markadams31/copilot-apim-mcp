# /// script
# requires-python = ">=3.12"
# dependencies = ["msal==1.39.0"]
# ///
"""Check that an agent's app refuses public-client sign-in (the "anyone could mint its token" hole).

    uv run scripts/public-client-check.py [--profile rapid] [employee-assistant]

Needs a person: it starts a device-code sign-in as the agent's app, and YOU complete it in a browser
(with MFA if your tenant asks). Run it with `allow_test_sign_in` left at its default, false.

Prediction, written before the run: Entra ID accepts the device-code request, you sign in, and the
token request is then refused because the app is not a public client (invalid_client, AADSTS7000218).
If a token is issued, the agent's identity is NOT a boundary and the check fails.
"""

import sys

import msal
from tf import outputs

out = outputs()
agent = sys.argv[1] if len(sys.argv) > 1 else "employee-assistant"
client_id = out["agents"][agent]["client_id"]
app = msal.PublicClientApplication(
    client_id, authority=f"https://login.microsoftonline.com/{out['tenant_id']}"
)
flow = app.initiate_device_flow(scopes=[f"api://{out['api_client_id']}/Tools.Read"])
if "user_code" not in flow:
    print(
        f"PASS  refused at the device-code request: {flow.get('error_description')}",
        flush=True,
    )
    sys.exit(0)

print(f"\n{flow['message']}\n", flush=True)
result = app.acquire_token_by_device_flow(flow)
if "access_token" in result:
    print(
        f"FAIL  a token was issued as {agent}: public-client sign-in is ON for its app"
    )
    sys.exit(1)
refused = result.get("error") == "invalid_client" or "7000218" in str(
    result.get("error_description")
)
print(
    f"{'PASS' if refused else 'INCONCLUSIVE'}  {result.get('error')}: {result.get('error_description')}"
)
sys.exit(0 if refused else 2)
