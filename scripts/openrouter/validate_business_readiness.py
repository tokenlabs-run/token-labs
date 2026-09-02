#!/usr/bin/env python3
"""Validate a private OpenRouter business-readiness manifest without exposing it."""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

REQUIRED_TEXT = {
    "legal_entity": ("registered_name", "entity_type", "jurisdiction", "registration_number", "formation_date", "registered_address", "evidence_reference"),
    "authority": ("authorized_representative_name", "authorized_representative_title", "approval_evidence_reference"),
    "tax_and_banking": ("payout_currency", "evidence_reference"),
    "domain": ("primary_domain", "website_url", "provider_contact", "legal_contact", "privacy_contact", "evidence_reference"),
    "policies": ("privacy_policy_url", "terms_url", "data_policy_url", "approval_evidence_reference"),
    "openrouter": ("display_name", "desired_slug", "hq_location", "inference_location", "approval_evidence_reference"),
}
REQUIRED_TRUE = {
    "tax_and_banking": ("tax_registration_confirmed", "business_bank_account_confirmed"),
    "domain": ("domain_control_confirmed", "mailboxes_monitored_confirmed", "dns_tls_email_auth_confirmed"),
    "policies": ("legal_review_confirmed", "operational_controls_confirmed"),
    "openrouter": ("commercial_terms_approved", "application_submission_approved"),
}
PLACEHOLDER = re.compile(r"(^|\W)(todo|tbd|unknown|placeholder|replace me)(\W|$)", re.I)


def validate(document):
    errors = []
    if not isinstance(document, dict):
        return ["root must be a JSON object"]
    if document.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    for section, fields in REQUIRED_TEXT.items():
        values = document.get(section)
        if not isinstance(values, dict):
            errors.append(f"{section} must be an object")
            continue
        for field in fields:
            value = values.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{section}.{field} is required")
            elif PLACEHOLDER.search(value):
                errors.append(f"{section}.{field} contains a placeholder")
    for section, fields in REQUIRED_TRUE.items():
        values = document.get(section)
        if isinstance(values, dict):
            for field in fields:
                if values.get(field) is not True:
                    errors.append(f"{section}.{field} must be explicitly true")
    domain = document.get("domain", {})
    if isinstance(domain, dict):
        primary_domain = domain.get("primary_domain")
        if isinstance(primary_domain, str):
            primary_domain = primary_domain.strip().lower().rstrip(".")
            if "://" in primary_domain or "/" in primary_domain or "@" in primary_domain or "." not in primary_domain:
                errors.append("domain.primary_domain must be a bare DNS domain")
        website_url = domain.get("website_url")
        if isinstance(website_url, str) and isinstance(primary_domain, str):
            parsed = urlparse(website_url)
            if parsed.scheme != "https" or parsed.hostname not in {primary_domain, f"www.{primary_domain}"}:
                errors.append("domain.website_url must be HTTPS on the verified primary domain")
        for field in ("provider_contact", "legal_contact", "privacy_contact"):
            value = domain.get(field)
            if isinstance(value, str) and isinstance(primary_domain, str) and not value.lower().endswith(f"@{primary_domain}"):
                errors.append(f"domain.{field} must use the verified primary domain")
    policies = document.get("policies", {})
    if isinstance(policies, dict):
        for field in ("privacy_policy_url", "terms_url", "data_policy_url"):
            value = policies.get(field)
            if isinstance(value, str):
                parsed = urlparse(value)
                primary_domain = domain.get("primary_domain") if isinstance(domain, dict) else None
                allowed_hosts = {primary_domain, f"www.{primary_domain}"} if isinstance(primary_domain, str) else set()
                if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
                    errors.append(f"policies.{field} must be HTTPS on the verified primary domain")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    try:
        document = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read manifest: {exc}", file=sys.stderr)
        return 2
    errors = validate(document)
    if errors:
        print(f"business readiness: {len(errors)} blocker(s)")
        for error in errors:
            print(f"- {error}")
        return 0 if args.allow_incomplete else 1
    print("business readiness: complete; human submission approval is recorded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
