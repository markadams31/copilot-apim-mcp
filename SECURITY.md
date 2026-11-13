# Security policy

This repository is a proof of concept, not a supported product. It deploys real Azure and Power
Platform resources, so treat any copy of it with the care you'd give infrastructure code.

## Reporting a vulnerability

Report a vulnerability in this repository's code, policies or documentation **privately**, using
GitHub's private vulnerability reporting (Security tab → Report a vulnerability). Please don't open a
public issue for it. Include what you found, where, and how to reproduce it.

There is no service-level agreement, but reports are welcome and will be read.

## What is in scope

- The API Management policies, the Terraform and the backend code, where a flaw would let an agent,
  a user or a client reach data or tools it shouldn't.
- Documentation that tells a reader to do something unsafe.

The gaps this project already knows about are listed in
[docs/testing.md](docs/testing.md#evidence-gaps), [docs/security.md](docs/security.md) and
[docs/governance.md](docs/governance.md#known-governance-gaps).

## Before you deploy a copy

- Never commit `terraform.tfstate`, `terraform.tfvars` or `.msal_cache.json`. They hold secrets and
  tenant identifiers, and `.gitignore` excludes them.
- The `rapid` profile has public endpoints and is for development only. `allow_test_sign_in` weakens
  the agent boundary while it is on, so turn it off after a test run.
