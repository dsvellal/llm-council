#!/usr/bin/env python3
"""
Query a non-Claude model via AWS Bedrock and return its response text.

Usage:
    python bedrock_query.py --model <model_id> --prompt <prompt_text>

Returns the response text to stdout.

To list available models in your account:
    aws bedrock list-foundation-models --query 'modelSummaries[*].modelId'
"""

import argparse
import json
import sys

import boto3


# ---------------------------------------------------------------------------
# Available non-Claude Bedrock models (as of mid-2026).
# Verify / update with: aws bedrock list-foundation-models
# ---------------------------------------------------------------------------
#
# Meta Llama 3
#   meta.llama3-70b-instruct-v1:0
#   meta.llama3-8b-instruct-v1:0
#   meta.llama3-1-405b-instruct-v1:0
#   meta.llama3-1-70b-instruct-v1:0
#   meta.llama3-1-8b-instruct-v1:0
#   meta.llama3-2-90b-instruct-v1:0
#   meta.llama3-2-11b-instruct-v1:0
#   meta.llama3-2-3b-instruct-v1:0
#   meta.llama3-2-1b-instruct-v1:0
#
# Mistral
#   mistral.mistral-large-2402-v1:0
#   mistral.mistral-large-2407-v1:0
#   mistral.mistral-7b-instruct-v0:2
#   mistral.mixtral-8x7b-instruct-v0:1
#
# Amazon Titan
#   amazon.titan-text-premier-v1:0
#   amazon.titan-text-express-v1
#   amazon.titan-text-lite-v1
#
# Cohere
#   cohere.command-r-plus-v1:0
#   cohere.command-r-v1:0
#   cohere.command-text-v14
# ---------------------------------------------------------------------------


def query_bedrock(model_id: str, prompt: str) -> str:
    client = boto3.client("bedrock-runtime")

    # The Bedrock Converse API works across model families with a unified interface.
    response = client.converse(
        modelId=model_id,
        messages=[
            {
                "role": "user",
                "content": [{"text": prompt}],
            }
        ],
    )

    output = response["output"]["message"]["content"]
    return "".join(block["text"] for block in output if "text" in block)


def main():
    parser = argparse.ArgumentParser(description="Query a Bedrock model")
    parser.add_argument("--model", required=True, help="Bedrock model ID")
    parser.add_argument("--prompt", required=True, help="Prompt text")
    args = parser.parse_args()

    try:
        result = query_bedrock(args.model, args.prompt)
        print(result)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
