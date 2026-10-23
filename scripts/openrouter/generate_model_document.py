#!/usr/bin/env python3
"""Generate and validate Tokenlabs' OpenRouter provider model document.

Paid endpoints require explicit pricing. Only measured rate capacities should
be declared; free endpoints omit prices.
The output defaults to ``is_ready: false`` and requires an explicit ``--ready``
after all provider gates pass.
"""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import json
import pathlib
import re
import sys

from jsonschema import Draft202012Validator


MODEL_ID = "qwen/qwen3-30b-a3b-instruct-2507"
HF_BASE_ID = "Qwen/Qwen3-30B-A3B-Instruct-2507"
HF_SERVED_ID = "Qwen/Qwen3-30B-A3B-Instruct-2507-FP8"
MODEL_CREATED_EPOCH = 1753705516


def positive_decimal(value: str) -> str:
    if not re.fullmatch(r"\d+(?:\.\d+)?", value):
        raise argparse.ArgumentTypeError("use a non-scientific decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError("invalid decimal") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("price must be greater than zero")
    return value


def positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def country_code(value: str) -> str:
    value = value.upper()
    if not re.fullmatch(r"[A-Z]{2}", value):
        raise argparse.ArgumentTypeError("country must be a two-letter code")
    return value


def validate(document: dict, openapi_path: pathlib.Path) -> None:
    openapi = json.loads(openapi_path.read_text())
    if openapi.get("openapi") != "3.1.0":
        raise ValueError("expected an OpenAPI 3.1.0 provider schema")
    version = (openapi.get("info") or {}).get("version")
    if version != document["schema_version"]:
        raise ValueError(
            f"schema version mismatch: document={document['schema_version']}, "
            f"OpenAPI={version}"
        )
    root_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$ref": "#/components/schemas/ModelDocumentV2",
        "components": openapi["components"],
    }
    errors = sorted(
        Draft202012Validator(root_schema).iter_errors(document),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        details = "\n".join(
            f"- {'/'.join(map(str, error.absolute_path)) or '<root>'}: "
            f"{error.message}"
            for error in errors
        )
        raise ValueError(f"provider document failed schema validation:\n{details}")


def build_document(args: argparse.Namespace) -> dict:
    parameters = {
        "temperature": {"type": "range", "min": 0, "max": 2},
        "top_p": {"type": "range", "min": 0, "max": 1},
        "max_tokens": {
            "type": "integer",
            "min": 1,
            "max": args.max_output_tokens,
            "unit": "token",
        },
        "stop": {"type": "array", "max_items": 4},
        "seed": {"type": "integer"},
    }
    if args.tools:
        parameters.update(
            {
                "tools": {"type": "boolean"},
                "tool_choice": {"type": "unknown"},
            }
        )
    if args.structured_outputs:
        parameters["structured_outputs"] = {"type": "boolean"}

    document = {
        "schema_version": "2.4",
        "id": args.model_id,
        "name": args.name,
        "hugging_face_id": args.hf_model_id,
        "created": args.created,
        "quantization": args.quantization,
        "description": args.description,
        "input_modalities": [
            {
                "type": "text",
                "supported_inputs": {
                    "max_context_length": {
                        "value": args.max_context_tokens,
                        "unit": "token",
                    }
                },
                "pricing": [
                    {
                        "type": "prompt",
                        "unit": "token",
                        "cost_usd": args.prompt_price,
                    }
                ],
                "capacity": [
                    {
                        "type": "prompt",
                        "unit": "token",
                        "per": "minute",
                        "value": args.prompt_tpm,
                    }
                ],
            }
        ],
        "output_modalities": [
            {
                "type": "text",
                "max_length": {
                    "value": args.max_output_tokens,
                    "unit": "token",
                },
                "streaming": True,
                "supported_parameters": parameters,
                "pricing": [
                    {
                        "type": "completion",
                        "unit": "token",
                        "cost_usd": args.completion_price,
                    }
                ],
                "capacity": [
                    {
                        "type": "completion",
                        "unit": "token",
                        "per": "minute",
                        "value": args.completion_tpm,
                    }
                ],
            }
        ],
        "capacity": [
            {
                "type": "request",
                "unit": "request",
                "per": "minute",
                "value": args.requests_per_minute,
            },
            {
                "type": "concurrency",
                "unit": "request",
                "value": args.concurrency,
            },
        ],
        "is_ready": args.ready,
        "is_free": args.free,
        "openrouter": {"slug": args.openrouter_slug or args.model_id},
    }
    if args.tokenizer:
        document["tokenizer"] = args.tokenizer
    if args.country:
        document["datacenters"] = [
            {"country_code": args.country, "region": args.datacenter_region}
        ]
        document["deployment_region"] = args.deployment_region
    for modality, capacity in zip(
        (document["input_modalities"][0], document["output_modalities"][0]),
        (args.prompt_tpm, args.completion_tpm),
    ):
        if args.free:
            del modality["pricing"]
        if capacity is None:
            del modality["capacity"]
    if args.requests_per_minute is None:
        document["capacity"].pop(0)
    return document


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--model-id", default=MODEL_ID)
    parser.add_argument("--openrouter-slug")
    parser.add_argument("--hf-model-id", default=HF_BASE_ID)
    parser.add_argument("--name", default="Qwen: Qwen3 30B A3B Instruct 2507")
    parser.add_argument("--created", type=positive_integer, default=MODEL_CREATED_EPOCH)
    parser.add_argument("--quantization", choices=("nvfp4", "fp8", "bf16"), default="fp8")
    parser.add_argument("--tokenizer")
    parser.add_argument("--description", default=(
        f"Token Labs serves {HF_SERVED_ID} on one NVIDIA DGX Spark using vLLM."))
    parser.add_argument("--free", action="store_true")
    parser.add_argument("--prompt-price", type=positive_decimal)
    parser.add_argument("--completion-price", type=positive_decimal)
    parser.add_argument("--prompt-tpm", type=positive_integer)
    parser.add_argument("--completion-tpm", type=positive_integer)
    parser.add_argument(
        "--requests-per-minute", type=positive_integer
    )
    parser.add_argument("--concurrency", required=True, type=positive_integer)
    parser.add_argument("--max-context-tokens", type=positive_integer, default=32768)
    parser.add_argument("--max-output-tokens", type=positive_integer, default=8192)
    parser.add_argument("--country", type=country_code)
    parser.add_argument("--datacenter-region")
    parser.add_argument("--deployment-region")
    parser.add_argument(
        "--tools",
        action="store_true",
        help="declare only after the tool-call conformance gate passes",
    )
    parser.add_argument(
        "--structured-outputs",
        action="store_true",
        help="declare only after the structured-output gate passes",
    )
    parser.add_argument(
        "--ready",
        action="store_true",
        help="set only after capacity, conformance, quality, and soak gates pass",
    )
    return parser


def main() -> int:
    parser = argument_parser()
    args = parser.parse_args()

    if not args.schema.is_file():
        parser.error(f"schema does not exist: {args.schema}")
    if args.max_output_tokens > args.max_context_tokens:
        parser.error("max output cannot exceed max context")
    if args.free and (args.prompt_price is not None or args.completion_price is not None):
        parser.error("free endpoints must not declare prices")
    if not args.free and (args.prompt_price is None or args.completion_price is None):
        parser.error("paid endpoints require --prompt-price and --completion-price")
    location = (args.country, args.datacenter_region, args.deployment_region)
    if any(location) and not all(location):
        parser.error("provide country, datacenter region, and deployment region together")
    document = build_document(args)
    validate(document, args.schema)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"data": [document]}, indent=2) + "\n")
    print(
        f"validated OpenRouter schema {document['schema_version']}; "
        f"wrote {args.output}; is_ready={document['is_ready']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
