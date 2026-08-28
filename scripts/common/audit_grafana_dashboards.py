#!/usr/bin/env python3
"""Audit every Grafana dashboard by running its panel queries against Prometheus.

Answers "which dashboards actually show data?" with evidence rather than by
clicking through 30 dashboards. For each panel target it substitutes template
variables with permissive wildcards, runs an instant query, and records whether
any series came back.

A panel that returns nothing here will render "No data" in the UI. A dashboard
where every panel is empty is a candidate for deletion or archival.

usage: audit_grafana_dashboards.py [--grafana URL] [--ds-id N] [--json out.json]
"""

import argparse
import base64
import json
import re
import sys
import urllib.parse
import urllib.request

DEFAULT_GRAFANA = "http://admin:changeme@192.168.1.206"

_AUTH_HEADER = None


def split_credentials(url):
    """urllib will not accept user:pass inline in a URL, so hoist it to a header."""
    global _AUTH_HEADER
    parts = urllib.parse.urlsplit(url)
    if parts.username:
        creds = f"{parts.username}:{parts.password or ''}".encode()
        _AUTH_HEADER = "Basic " + base64.b64encode(creds).decode()
        netloc = parts.hostname + (f":{parts.port}" if parts.port else "")
        parts = parts._replace(netloc=netloc)
    return urllib.parse.urlunsplit(parts)


def http_get(url, timeout=30):
    req = urllib.request.Request(url)
    if _AUTH_HEADER:
        req.add_header("Authorization", _AUTH_HEADER)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def strip_vars(expr):
    """Make a dashboard expression runnable outside its template context.

    Grafana substitutes $var at render time; Prometheus rejects it. Regex
    matchers (=~"$job") tolerate ".*", so widen those. Interval macros become a
    fixed window. Anything still containing a $ is reported as unrunnable rather
    than silently counted as empty -- those two outcomes mean different things.
    """
    e = expr
    e = e.replace("$__rate_interval", "5m").replace("$__interval", "5m")
    e = e.replace("$__range", "1h")
    # =~"$var" / =~"[[var]]"  ->  =~".*"
    e = re.sub(r'=~\s*"\$__?\w+"', '=~".*"', e)
    e = re.sub(r'=~\s*"\[\[\w+\]\]"', '=~".*"', e)
    e = re.sub(r'=~\s*"\$\w+"', '=~".*"', e)
    # ="$var" -> drop the matcher entirely (cannot guess a value)
    e = re.sub(r'\w+\s*=\s*"\$\w+"\s*,?', "", e)
    e = re.sub(r",\s*}", "}", e)
    e = re.sub(r"{\s*}", "", e)
    return e


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grafana", default=DEFAULT_GRAFANA)
    ap.add_argument("--ds-id", default="2", help="Prometheus datasource id")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    base = split_credentials(args.grafana).rstrip("/")
    prom = f"{base}/api/datasources/proxy/{args.ds_id}/api/v1/query"

    dashboards = http_get(f"{base}/api/search?type=dash-db&limit=200")
    report = []

    for d in dashboards:
        uid, title = d.get("uid"), d.get("title")
        try:
            full = http_get(f"{base}/api/dashboards/uid/{uid}")["dashboard"]
        except Exception as e:
            report.append({"uid": uid, "title": title, "error": str(e)[:120]})
            continue

        # Two schemas in play. Modern dashboards put everything under "panels"
        # (row panels nest their children). Dashboards imported from older
        # grafana.com revisions -- which is most of the kube-prometheus-stack
        # set -- use a top-level "rows" list instead, and reading only "panels"
        # silently reports them as having zero queries.
        def walk(nodes):
            out = []
            for n in nodes or []:
                out.append(n)
                out.extend(walk(n.get("panels")))
            return out

        panels = walk(full.get("panels"))
        for row in full.get("rows") or []:
            panels.extend(walk(row.get("panels")))

        with_data, empty, unrunnable, total = [], [], [], 0
        for p in panels:
            ptitle = p.get("title") or "(untitled)"
            for t in (p.get("targets") or []):
                expr = (t.get("expr") or "").strip()
                if not expr:
                    continue
                total += 1
                q = strip_vars(expr)
                if "$" in q:
                    unrunnable.append(ptitle)
                    continue
                try:
                    url = prom + "?" + urllib.parse.urlencode({"query": q})
                    res = http_get(url, timeout=25)
                    if res.get("data", {}).get("result"):
                        with_data.append(ptitle)
                    else:
                        empty.append(ptitle)
                except Exception:
                    unrunnable.append(ptitle)

        report.append({
            "uid": uid,
            "title": title,
            "targets": total,
            "with_data": len(with_data),
            "empty": len(empty),
            "unrunnable": len(unrunnable),
            "empty_panels": sorted(set(empty)),
        })

    report.sort(key=lambda r: (r.get("with_data", 0) / max(r.get("targets", 1), 1), r.get("title", "")))

    print(f"{'data/targets':>13}  {'uid':36} title")
    for r in report:
        if "error" in r:
            print(f"{'ERR':>13}  {r['uid']:36} {r['title']}  ({r['error']})")
            continue
        frac = f"{r['with_data']}/{r['targets']}"
        flag = "  <-- DEAD" if r["with_data"] == 0 and r["targets"] else ""
        print(f"{frac:>13}  {r['uid']:36} {r['title']}{flag}")

    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nwrote {args.json}", file=sys.stderr)


if __name__ == "__main__":
    main()
