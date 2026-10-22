#!/usr/bin/env python3
"""Render one public aggregate report into the benchmark site and portal."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import shutil

SLUG = 'qwen38-nvfp4-2026-10-21'
TITLE = 'Qwen3.8-27B: MTP3, EAGLE4, DFlash2 and OpenJet'


def select(row, fields):
    return {key: row[key] for key in fields if key in row}


def table(rows, columns):
    header = ''.join('<th scope="col">' + html.escape(label) + '</th>' for _, label in columns)
    body = []
    for row in rows:
        cells = []
        for key, _ in columns:
            value = row.get(key, '')
            if isinstance(value, float):
                value = f'{value:,.2f}'
            cells.append('<td>' + html.escape(str(value)) + '</td>')
        body.append('<tr>' + ''.join(cells) + '</tr>')
    return '<div class="scroll"><table><thead><tr>' + header + '</tr></thead><tbody>' + ''.join(body) + '</tbody></table></div>'


def insert_section(path, key, fragment, marker):
    text = path.read_text()
    start, end = f'<!-- BEGIN {key} -->', f'<!-- END {key} -->'
    block = start + '\n' + fragment + '\n' + end
    if start in text:
        first = text.index(start)
        last = text.index(end, first) + len(end)
        text = text[:first] + block + text[last:]
    else:
        if text.count(marker) != 1:
            raise ValueError('Missing or ambiguous insertion marker: ' + str(path))
        text = text.replace(marker, block + '\n' + marker, 1)
    path.write_text(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path, help='Compact inference-platform benchmark publication')
    parser.add_argument('--site', required=True, type=Path, help='Token Labs docs directory')
    parser.add_argument('--portal', required=True, type=Path, help='inference-portal/portal directory')
    args = parser.parse_args()
    source, site, portal = args.source.resolve(), args.site.resolve(), args.portal.resolve()
    manifest = json.loads((source / 'MANIFEST.json').read_text())['file_sha256']
    for relative, expected in manifest.items():
        if hashlib.sha256((source / relative).read_bytes()).hexdigest() != expected:
            raise ValueError('Source publication checksum mismatch: ' + relative)
    data = json.loads((source / 'measurements.json').read_text())
    # An allowlist keeps provider IDs, endpoints, credentials, request content and
    # local absolute paths out of the public export.
    agent_fields = ['config_id', 'series', 'concurrency', 'requests', 'raw_span_output_tok_s',
                    'decode_tok_s_user', 'ttft_p95_ms', 'request_latency_p95_ms',
                    'zero_request_errors', 'native_aggregate_comparable', 'raw_span_delta_percent']
    synthetic_fields = ['config_id', 'input_target', 'output_tokens', 'concurrency', 'valid_runs',
                        'median_raw_span_tok_s', 'observed_range_tok_s', 'median_run_ttft_p95_ms',
                        'median_run_e2e_p95_ms', 'median_run_decode_tok_s_per_user', 'delta_percent']
    public = select(data, ['generated_at_utc', 'model', 'model_revision', 'hardware',
                           'candidate_gpu_count', 'production_modified', 'model_variants'])
    public.update(study=SLUG, status='experimentation-ended-no-production-promotion',
                  source_measurements_sha256=manifest['measurements.json'],
                  agentx=[select(row, agent_fields) for row in data['agentx']['results']],
                  synthetic=[select(row, synthetic_fields) for row in data['synthetic_capacity']['rows']],
                  configurations=[])
    for entry in data['applied_configurations']:
        record = select(entry, ['config_id', 'config_sha', 'runtime_sha', 'setup_sha', 'serve_sha',
                               'model', 'model_revision', 'image', 'framework_source_patch',
                               'pilot_status', 'api_passed', 'valid_capacity_points'])
        config = source / 'configs' / entry['config_id'] / 'serving.json'
        if not config.is_file():
            raise ValueError('Missing applied serving configuration: ' + str(config))
        record['serving'] = select(json.loads(config.read_text()), ['model', 'revision', 'served_model',
            'framework', 'frontend_args', 'worker_args', 'engine_args', 'model_file', 'model_sha256',
            'structured_output_default_thinking'])
        public['configurations'].append(record)
    dest = site / 'results' / SLUG
    dest.mkdir(parents=True, exist_ok=True)
    export = json.dumps(public, indent=2) + '\n'
    if '/home/' in export or 'proxy.runpod.net' in export:
        raise ValueError('Private path or provider endpoint in public data')
    (dest / 'summary.json').write_text(export)
    graph_names = sorted(p.name for p in (source / 'graphs').iterdir() if p.suffix in ['.png', '.svg', '.pdf'])
    for name in graph_names:
        if name.endswith('.svg'):
            # Matplotlib emits trailing spaces inside multiline path attributes.
            # Removing them preserves the SVG while keeping Git checks clean.
            svg = (source / 'graphs' / name).read_text()
            (dest / name).write_text('\n'.join(line.rstrip() for line in svg.splitlines()) + '\n')
        else:
            shutil.copyfile(source / 'graphs' / name, dest / name)
    nvfp4 = [row for row in public['agentx'] if row['series'] == 'candidate-loopback-agentx64k']
    gguf = [row for row in public['agentx'] if row['series'] == 'candidate-loopback-agentx64k-gguf-openjet']
    columns = [('config_id', 'Configuration'), ('concurrency', 'Sessions'), ('requests', 'Requests'),
               ('raw_span_output_tok_s', 'Output tok/s'), ('decode_tok_s_user', 'Decode tok/s/user'),
               ('ttft_p95_ms', 'p95 TTFT, ms'), ('request_latency_p95_ms', 'p95 completion, ms')]
    synthetic_columns = [('config_id', 'Configuration'), ('concurrency', 'Concurrency'),
                         ('valid_runs', 'Runs'), ('median_raw_span_tok_s', 'Output tok/s'),
                         ('median_run_decode_tok_s_per_user', 'Decode tok/s/user')]
    figures = []
    for name in graph_names:
        if not name.endswith('.png'):
            continue
        label = ('Synthetic 1K input / 1K output' if name.startswith('synthetic') else
                 'OpenJet / Unsloth GGUF, separate model family' if 'gguf' in name else
                 'AgentX NVFP4, ' + name.split('-agentx')[0].replace('-', ' '))
        stem = name[:-4]
        figures.append(f'<figure><h3>{html.escape(label)}</h3><a href="{stem}.svg"><img loading="lazy" src="{name}" alt="{html.escape(label)}: throughput versus per-user speed"></a><figcaption>Measured points with requested concurrency labels. <a href="{stem}.svg">SVG</a> · <a href="{stem}.pdf">PDF</a></figcaption></figure>')
    configs = ''.join('<details><summary>' + html.escape(row['config_id']) + '</summary><pre>' +
                      html.escape(json.dumps(row, indent=2)) + '</pre></details>' for row in public['configurations'])
    page = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>''' + TITLE + ''' | Token Labs benchmarks</title><style>
:root{color-scheme:light dark}body{font:16px/1.6 system-ui,sans-serif;max-width:1160px;margin:auto;padding:28px}a{color:#1786d4}h1{line-height:1.2}.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%}th,td{padding:10px;text-align:left;border-bottom:1px solid #8885}th{white-space:nowrap}img{width:100%;height:auto}figure{margin:36px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:16px;background:#8881}details{margin:12px 0}.decision{border-left:4px solid #1786d4;padding:8px 20px}
</style></head><body><main><p>Token Labs · Inference benchmark campaign · October 21–22, 2026 UTC</p><h1>''' + TITLE + '''</h1>
<p class="decision"><strong>Retain baseline MTP3.</strong> It led the measured NVFP4 AgentX c32 series at 171.19 output tokens/s. No tested configuration demonstrated a better overall AgentX result. The experiment has ended; the tuning Pod was deleted and production was unchanged.</p>
<p>One 96GB RTX PRO 6000 Blackwell Server Edition, one model worker. NVFP4 target: <code>nvidia/Qwen3.8-27B-NVFP4</code>, revision <code>482ca0f3832238542f8f5295dde86b5f22711d80</code>. These are single-worker serving measurements, not distributed scheduling or a public API capacity guarantee.</p>
<h2>AgentX trace replay, NVFP4</h2><p>AgentX 1.0.7, streaming <code>/v1/chat/completions</code>, Weka062126 corpus, whole-session 64K filter, seed 42, temperature 0, ignore_eos, 900-second profile and 300-second grace. Client requested 32 sessions. Raw request-span output throughput includes agent waits and excludes final idle drain accounting. Native drain-inclusive aggregates are not interchangeable with this metric.</p>
''' + table(nvfp4, columns) + '''<p>These are single runs without a calibrated noise floor. Cache history, runtime changes and API repairs limit attribution to individual knobs. This is the best measured configuration for this trace, not a global optimum or production release qualification.</p>
<h2>OpenJet and Unsloth GGUF, separate comparison</h2><p>Unsloth UD-Q4_K_XL uses a different quantization and engine. OpenJet executes one request at a time even when AgentX requests 32 sessions. Its high per-stream decode speed does not establish high concurrent aggregate throughput. The trial passed ten quality checks and four long-context canaries; complete API conformance was not established.</p>
''' + table(gguf, columns) + '''<h2>Synthetic capacity, separate workload</h2><p>Streaming 1,024-token input and 1,024-token output, 120 seconds per point, seed 42, fresh prefix. maxseq16 improved c16/c32 short-workload output throughput by about 58%, while its AgentX throughput declined 6.04% and p95 completion latency increased. Select using the workload actually served. Synthetic decode and AgentX decode use different definitions.</p>
''' + table(public['synthetic'], synthetic_columns) + '''<h2>Throughput versus interactivity, every measured variation</h2><p>Each figure preserves workload and transport boundaries. Sparse results show measured points; they do not establish a complete Pareto frontier. Repeated synthetic points use observed ranges, not confidence intervals.</p>''' + ''.join(figures) + '''<h2>Exact applied settings and coverage</h2><p>Failed and unmeasured attempts are retained in the coverage records below. Pilot and API status are separate from measured throughput; a failed follow-up does not erase an earlier valid result. Framework patches are identified. Runtime digests, source hashes and serving flags are retained; credentials and raw request content are excluded.</p>''' + configs + '''<h2>Data and reproduction</h2><p><a href="summary.json">Aggregate data and exact settings, JSON</a> · <a href="SHA256SUMS">File checksums</a></p><p>The complete local campaign, raw exports, original commands, client lock and detailed setup are retained in the inference-platform repository workspace under <code>results/2026-10-21-qwen38-nvfp4-optimization</code>. Raw artifacts are not included in this public aggregate bundle. No new experiment or GPU is needed to publish this report.</p></main></body></html>'''
    (dest / 'index.html').write_text(page)
    sums = ''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n'
                   for p in sorted(dest.iterdir()) if p.is_file() and p.name != 'SHA256SUMS')
    (dest / 'SHA256SUMS').write_text(sums)
    portal_dest = portal / 'static' / 'benchmarks' / SLUG
    shutil.copytree(dest, portal_dest, dirs_exist_ok=True)
    section = f'<section class="section" id="{SLUG}"><h2>{TITLE}</h2><p>One RTX PRO 6000 Server Edition. Baseline MTP3 led the measured AgentX c32 series at 171.19 output tok/s. Synthetic capacity and OpenJet GGUF are separate comparisons. Experiments ended; production unchanged.</p><p><a href="results/{SLUG}/index.html">Full report, every measured variation, graphs and settings →</a></p></section>'
    insert_section(site / 'benchmark-results.html', SLUG, section,
                   '<!-- ── Summary Stats ────────────────────────────────────── -->')
    card = f'<a class="run control" href="results/{SLUG}/index.html"><div class="meta">2026-10-21 · Single GPU · AgentX and synthetic workloads</div><h3>{TITLE}</h3><p>Baseline retained. Compare measured throughput, latency, exact settings and separate GGUF results.</p><span class="open">Open results and graphs →</span></a>'
    insert_section(site / 'labs.html', SLUG, card,
                   '<a class="run control" href="benchmark-results.html#mi300x-qwen38">')
    print(json.dumps({'site_report': str(dest / 'index.html'), 'portal_report': str(portal_dest / 'index.html'),
                      'applied_configurations': len(public['configurations']), 'graphs': len(figures)}, indent=2))


if __name__ == '__main__':
    main()
