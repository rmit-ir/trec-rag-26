#!/usr/bin/env bash
set -euo pipefail

# Run from the repository root in the same shell that holds AWS credentials.
languages=(hebrew chinese vietnamese)
categories=(related-topic hypothetical negation modal-statement)
model="openai.gpt-oss-20b-1:0"
max_concurrency="${MAX_CONCURRENCY:-4}"
export AWS_REGION="${AWS_REGION:-ap-southeast-2}"

aws sts get-caller-identity >/dev/null

for language in "${languages[@]}"; do
  for category in "${categories[@]}"; do
    input_file="data/ragdoll-robustness/derived/ragdoll-inputs/distractors/${category}/${language}/2021.requests.jsonl"
    output_dir="evaluation-results/llm-judge-robustness/distractors/gpt-oss-20b/${category}/${language}"
    mkdir -p "$output_dir"

    echo "[$language/$category/2021] starting"
    uv run --project evaluation/ragdoll ragdoll umbrela judge \
      --provider amazon-bedrock \
      --model "$model" \
      --input-file "$input_file" \
      --output-file "$output_dir/2021.judgments.jsonl" \
      --raw-events-dir "$output_dir/2021.raw-events" \
      --max-concurrency "$max_concurrency" \
      --resume \
      2>&1 | tee "$output_dir/2021.log"
  done
done
