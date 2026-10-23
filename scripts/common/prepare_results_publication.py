#!/usr/bin/env python3
"""Copy compact pending reports for publication, preserving raw source artifacts.

Dry-run is the default. --apply writes sanitized copies and a manifest into a
separate checkout. It never changes the source checkout or contacts a cluster.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


REPORT_NAMES = {
    "summary.json", "verification-summary.json", "conclusion.json", "report.json",
    "quality.json", "features.json", "codex.json", "api-conformance.json", "conformance.json",
}
PATTERNS = [
    re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----.*?-----END (?:[A-Z ]+ )?PRIVATE KEY-----", re.S),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\b(?:gh[pousr]_|github_pat_|hf_|rpa_)[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"(?i)(?<=Bearer )[A-Za-z0-9_.=-]{20,}"),
    re.compile(r"(?<=://)[^\s/:@]+:[^\s/@]+(?=@)"),
]
ASSIGNMENT = re.compile(
    r'''(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|secret[_-]?access[_-]?key|secret[_-]?key|client[_-]?secret|upstream[_-]?key|password|authorization)["']?\s*[:=]\s*["'])([^"'\r\n]{12,})(["'])'''
)
CREDENTIAL_FIELDS = {
    "apikey", "accesstoken", "refreshtoken", "secretaccesskey", "secretkey",
    "clientsecret", "upstreamkey", "password", "authorization", "bearertoken",
    "runpodapikey", "tokenlabsapikey", "tokenlabsupstreamkey", "hftoken",
}


def sanitize_json(value):
    count = 0
    if isinstance(value, list):
        result = []
        for item in value:
            cleaned, found = sanitize_json(item)
            result.append(cleaned)
            count += found
        return result, count
    if not isinstance(value, dict):
        return value, count
    env_secret = re.sub(r"[^a-z]", "", str(value.get("name", "")).lower()) in CREDENTIAL_FIELDS
    result = {}
    for key, item in value.items():
        normalized = re.sub(r"[^a-z]", "", key.lower())
        secret = normalized in CREDENTIAL_FIELDS or key == "value" and env_secret
        if secret and isinstance(item, str) and item and item != "[REDACTED]":
            result[key] = "[REDACTED]"
            count += 1
        else:
            result[key], found = sanitize_json(item)
            count += found
    return result, count


def sanitize(text):
    count = 0
    for pattern in PATTERNS:
        text, found = pattern.subn("[REDACTED]", text)
        count += found

    def assignment(match):
        nonlocal count
        value = match[2]
        if (re.fullmatch(r"[A-Z][A-Z0-9_]*", value)
                or any(marker in value.lower() for marker in
                       ["redacted", "replace", "example", "placeholder", "${", "$env", "os.environ", "args."])
                or not (any(c.isalpha() for c in value) and any(c.isdigit() for c in value))):
            return match[0]
        count += 1
        return match[1] + "[REDACTED]" + match[3]

    return ASSIGNMENT.sub(assignment, text), count


def pending(source):
    names = set()
    for command in (["diff", "--name-only", "HEAD", "--", "results/"],
                    ["ls-files", "--others", "--exclude-standard", "--", "results/"]):
        names.update(subprocess.check_output(["git", "-C", str(source), *command], text=True).splitlines())
    return sorted(names)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    source, destination = args.source.resolve(), args.destination.resolve()
    if source == destination:
        parser.error("Use a separate destination checkout to preserve raw source files")
    published, excluded = [], []
    for name in pending(source):
        path = source / name
        if path.is_symlink() or not path.is_file():
            excluded.append({"path": name, "reason": "not a regular report"})
            continue
        size = path.stat().st_size
        selected = (path.suffix.lower() in {".md", ".csv"} or path.name.lower() in REPORT_NAMES
                    or path.suffix == ".json" and any(term in path.name.lower()
                        for term in ["conformance", "quality", "overload", "capacity", "verification"]))
        if not selected or "/scripts/" in name or size > 250_000:
            excluded.append({"path": name, "reason": "raw artifact or outside compact report policy", "bytes": size})
            continue
        original = path.read_text()
        json_redactions = 0
        prepared = original
        if path.suffix == ".json":
            data = json.loads(original)
            if isinstance(data, dict) and any(key in data for key in
                    ["apiVersion", "kind", "items", "stdout", "stderr", "command"]):
                excluded.append({"path": name, "reason": "raw snapshot or command capture", "bytes": size})
                continue
            data, json_redactions = sanitize_json(data)
            if json_redactions:
                prepared = json.dumps(data, indent=2) + "\n"
        sanitized, redactions = sanitize(prepared)
        redactions += json_redactions
        if path.suffix == ".json":
            json.loads(sanitized)
        row = {"path": name, "bytes": len(sanitized.encode()), "redactions": redactions,
               "source_sha256": hashlib.sha256(original.encode()).hexdigest(),
               "published_sha256": hashlib.sha256(sanitized.encode()).hexdigest()}
        published.append(row)
        if args.apply:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(sanitized)
    manifest = {"policy": "compact reports only; raw source artifacts are never modified",
                "scope": "Files pending in the source checkout. Existing destination files are not removed.",
                "published": published, "excluded_from_this_pass": excluded}
    if args.apply:
        target = destination / "results/publication-manifest-2026-10-23.json"
        target.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"apply": args.apply, "reports": len(published),
                      "bytes": sum(row["bytes"] for row in published),
                      "redactions": sum(row["redactions"] for row in published),
                      "raw_files_kept_local": len(excluded)}))


if __name__ == "__main__":
    main()
