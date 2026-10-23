#!/usr/bin/env python3
"""Reject any candidate Terraform plan that updates or replaces existing resources."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--image", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    changes = plan.get("resource_changes", [])
    expected = {"random_password.upstream", "runpod_pod.model"}
    if {change["address"] for change in changes} != expected:
        raise SystemExit("Candidate plan must contain only its credential and new GPU pod")
    for change in changes:
        allowed = [["create"]]
        if change["address"] == "random_password.upstream":
            allowed.append(["no-op"])
        if change["change"]["actions"] not in allowed:
            raise SystemExit("Candidate plan must create the pod and leave any existing credential untouched")
    model = next(change for change in changes if change["address"] == "runpod_pod.model")
    after = model["change"]["after"]
    if after["name"] != args.name or after["image"] != args.image:
        raise SystemExit("Candidate name or image differs from the reviewed build")
    if "@sha256:" not in args.image:
        raise SystemExit("Candidate image must be pinned by digest")
    print(json.dumps({"passed": True, "create_only": True, "name": args.name, "image": args.image}))


if __name__ == "__main__":
    main()
