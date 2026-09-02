FROM vllm/vllm-openai-cpu:v0.27.1
USER root
COPY container/compliance /opt/compliance
ENV PYTHONPATH=/opt
ARG BASELINE_SBOM_FILE
ARG TARGETARCH
ARG ADD_DENIED_PROBE=false
RUN if [ "$ADD_DENIED_PROBE" = "true" ]; then \
    python3 -c 'import pathlib,sysconfig; p=pathlib.Path(sysconfig.get_paths()["purelib"])/"dynamo_compliance_probe-1.0.dist-info"; p.mkdir(); (p/"METADATA").write_text("Metadata-Version: 2.1\nName: dynamo-compliance-probe\nVersion: 1.0\nLicense: GPL-3.0-only\n")'; \
    fi
RUN mkdir -p /legal && \
    if [ -n "${VIRTUAL_ENV:-}" ]; then PKG_ARG="--venv ${VIRTUAL_ENV}"; else PKG_ARG="--site-packages $(python3 -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"; fi && \
    python3 -m compliance.generators --ecosystem python,dpkg ${PKG_ARG} \
    --output-dir /legal --policy /opt/compliance/policy/licenses.toml \
    ${BASELINE_SBOM_FILE:+--subtract-sbom /opt/compliance/base_sboms/${BASELINE_SBOM_FILE}-${TARGETARCH}.cdx.json}
RUN python3 -m compliance.policy.validate --policy /opt/compliance/policy/licenses.toml --input /legal/osrb-deps.csv
