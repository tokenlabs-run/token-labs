#!/usr/bin/env python3
"""Validate every requested point and export Pareto membership and chart data."""
import argparse
import csv
import json
import math
import pathlib
from run_matrix import MODEL, COMBOS, CONCURRENCIES, BACKENDS, validate


def main():
    p = argparse.ArgumentParser()
    p.add_argument('root', type=pathlib.Path)
    p.add_argument('--output', type=pathlib.Path, required=True)
    p.add_argument('--allow-partial', action='store_true')
    a = p.parse_args()
    combos, missing, rows = {}, [], []
    for isl, osl in COMBOS:
        label = f'ISL{isl}/OSL{osl}'
        combos[label] = {}
        for fw in BACKENDS:
            combos[label][fw] = []
            for c in CONCURRENCIES:
                name = f'isl{isl}-osl{osl}__{fw}-c{c}'
                source = a.root / name / 'profile_export_aiperf.json'
                if not source.is_file():
                    missing.append(name)
                    continue
                d = validate(source, max(4, c*2), osl, isl)
                def stat(key, kind='avg'):
                    val = (d.get(key) or {}).get(kind)
                    if val is None:
                        raise ValueError(f'{name}: missing {key}.{kind}')
                    number = float(val)
                    if not math.isfinite(number) or number < 0:
                        raise ValueError(f"{name}: invalid {key}.{kind}: {val}")
                    return number
                row = dict(framework=fw, concurrency=c, req_isl=isl, req_osl=osl,
                           tput_total=stat('output_token_throughput'),
                           tput_per_user=stat('output_token_throughput_per_user'),
                           ttft_p50=stat('time_to_first_token','p50'),
                           ttft_p95=stat('time_to_first_token','p95'),
                           itl_p50=stat('inter_token_latency','p50'),
                           req_latency_p50=stat('request_latency','p50'),
                           isl=stat('input_sequence_length'), osl=stat('output_sequence_length'),
                           requests=max(4,c*2), errors=0, source=str(source))
                combos[label][fw].append(row)
                rows.append(row)
        candidates = [r for group in combos[label].values() for r in group]
        def dominates(other, row):
            return (other['tput_total'] >= row['tput_total'] and
                    other['tput_per_user'] >= row['tput_per_user'] and
                    (other['tput_total'] > row['tput_total'] or
                     other['tput_per_user'] > row['tput_per_user']))
        for row in candidates:
            row['pareto'] = not any(dominates(other,row) for other in candidates)
            row['framework_pareto'] = not any(dominates(other,row) for other in candidates
                                             if other['framework']==row['framework'])
    if missing and not a.allow_partial:
        raise SystemExit('Incomplete matrix: '+', '.join(missing))
    provenance_path = a.root.parent / "provenance.json"
    provenance = json.loads(provenance_path.read_text())
    payload = dict(model=MODEL,
                   experiment_class='single-replica-control',
                   replicas_per_arm=1,
                   claim_scope=('Per-replica capacity and orchestration/frontend overhead only; '
                                'not multi-replica routing or scaling.'),
                   provenance=provenance, complete=not missing, expected_points=42,
                   measured_points=len(rows), missing=missing,
                   measured_requests=sum(r["requests"] for r in rows),
                   measured_output_tokens=sum(r["requests"] * r["req_osl"] for r in rows),
                   methodology='Streaming completions; fixed OSL, ignore_eos=true; '
                   'two measured waves, minimum four requests; prefix cache off. '
                   'llm-d modelservice sidecar versus Dynamo frontend; EPP bypassed. '
                   'Exactly one model replica per arm on one Spark; no node-swap control. '
                   'Single-replica control only; not a multi-replica routing or scaling result.',
                   combos=combos)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(payload, indent=2)+'\n')
    if rows:
        with a.output.with_suffix('.csv').open('w', newline='') as f:
            writer=csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
            writer.writeheader()
            writer.writerows(rows)
    print(f'{len(rows)}/42 valid points; saved {a.output}')


if __name__=='__main__':
    main()
