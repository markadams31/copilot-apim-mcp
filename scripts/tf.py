"""Terraform outputs for the chosen deployment profile, shared by the scripts.

The profile comes from `--profile secure|rapid` on the command line (removed from sys.argv, so scripts
parse their own arguments as before), else the CONTOSO_PROFILE environment variable, else secure.
"""

import json
import os
import subprocess
import sys
from functools import cache
from pathlib import Path

PROFILES = ("secure", "rapid")


def _take_profile() -> str:
    if "--profile" in sys.argv:
        i = sys.argv.index("--profile")
        if i + 1 >= len(sys.argv):
            sys.exit("--profile needs a value: secure or rapid")
        profile = sys.argv[i + 1]
        del sys.argv[i : i + 2]
    else:
        profile = os.environ.get("CONTOSO_PROFILE", "secure")
    if profile not in PROFILES:
        sys.exit(f"unknown profile {profile!r}: use secure or rapid")
    return profile


PROFILE = _take_profile()
PROFILE_DIR = Path(__file__).resolve().parent.parent / "infra" / "profiles" / PROFILE


@cache
def outputs() -> dict:
    """All of the profile's Terraform outputs, as plain values."""
    raw = subprocess.check_output(
        ["terraform", f"-chdir={PROFILE_DIR}", "output", "-json"], text=True
    )
    values = {k: v["value"] for k, v in json.loads(raw).items()}
    if not values:
        sys.exit(
            f"the {PROFILE} profile has no outputs: is it deployed? (terraform -chdir={PROFILE_DIR} apply)"
        )
    return values


def output(name: str):
    return outputs()[name]
