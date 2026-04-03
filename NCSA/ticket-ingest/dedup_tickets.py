import os
import re
import json
import argparse
from pathlib import Path

from llmflux.slurm import SlurmRunner
from llmflux.core.config import Config, EngineConfig

DEDUP_SYSTEM_PROMPT = """\
You are a deduplication assistant for HPC (High Performance Computing) support Q&A pairs.

You will be given a single question-and-answer pair. Your task is to assign a concise,
normalized topic key that captures the *core underlying issue*, such that semantically
similar or duplicate questions map to the same key — even if phrased differently.

Your output should prioritize abstraction over surface wording.

Core Guidelines:
- Focus on the *root problem*, not the specific wording or context
- Generalize across similar scenarios (e.g., "A100", "V100", "GPU node" → "gpu")
- Ignore irrelevant details like usernames, project names, file paths, or IDs
- Prefer stable HPC concepts (e.g., slurm, job scheduling, modules, storage, mpi)

Formatting Rules:
- Output MUST be:
  - 3 to 8 words
  - all lowercase
  - hyphen-separated (kebab-case)
- No punctuation, no extra text, no explanations
- Use consistent terminology across outputs

Normalization Heuristics:
- Scheduler-related issues → include "slurm" (or relevant scheduler)
- Job submission issues → use terms like "submit", "job", "script"
- Resource requests → use "gpu", "cpu", "memory", "node"
- Environment issues → use "module", "conda", "environment"
- File/data issues → use "storage", "filesystem", "quota"
- Performance/debugging → use "performance", "error", "crash", "timeout"

Deduplication Intent:
- Questions that *mean the same thing* should produce the *same key*
- Avoid overly specific keys that fragment similar issues
- Avoid overly vague keys that collapse unrelated issues

Good vs Bad Examples:

Q: How do I request an A100 GPU for my job?
A: Use the gpuA100x4 partition in your sbatch script...
Output: request-gpu-node-slurm

Q: My sbatch job is stuck in pending state due to resources
Output: slurm-job-pending-resources

Q: How do I load Python 3.10 on the cluster?
Output: load-python-module

Q: My job crashes with out-of-memory error
Output: job-out-of-memory-error

Bad Outputs (avoid):
- too specific: "request-a100-gpu-on-delta-cluster"
- too vague: "job-issue"
- wrong format: "Request GPU Node Slurm"
- includes explanation: "request-gpu-node-slurm because user asked about GPUs"

Final Instruction:
Return ONLY the topic key, nothing else.
"""


def parse_args():
    p = argparse.ArgumentParser(description="Deduplicate summarized Q/A ticket pairs")
    p.add_argument("-i", "--input", required=True, help="Path to summarize_tickets output JSON")
    p.add_argument("-o", "--output", required=True, help="Path to write deduplicated Q/A JSON")
    return p.parse_args()


def extract_qa_pairs(input_path: str) -> list[dict]:
    with open(input_path) as f:
        results = json.load(f)

    pairs = []
    for item in results:
        try:
            content = item["output"]["choices"][0]["message"]["content"]
            # Strip <think>...</think> block if present
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
            pairs.append({
                "custom_id": item["input"]["custom_id"],
                "content": content
            })
        except (KeyError, IndexError):
            continue
    return pairs


def write_topic_prompts(pairs: list[dict], prompts_path: str):
    with open(prompts_path, "w") as f:
        for pair in pairs:
            f.write(json.dumps({
                "custom_id": pair["custom_id"],
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "messages": [
                        {"role": "system", "content": DEDUP_SYSTEM_PROMPT},
                        {"role": "user", "content": pair["content"]}
                    ],
                    "temperature": 0.0,
                    "max_tokens": 20
                }
            }) + "\n")


def dedup_by_topic(pairs: list[dict], topic_results_path: str) -> list[dict]:
    with open(topic_results_path) as f:
        topic_results = json.load(f)

    # Build custom_id -> topic key map
    topic_map = {}
    for item in topic_results:
        try:
            topic = item["output"]["choices"][0]["message"]["content"].strip()
            topic = re.sub(r"<think>.*?</think>", "", topic, flags=re.DOTALL).strip()
            topic_map[item["input"]["custom_id"]] = topic
        except (KeyError, IndexError):
            continue

    # Keep first Q/A seen per topic
    seen_topics = {}
    for pair in pairs:
        topic = topic_map.get(pair["custom_id"], pair["custom_id"])
        if topic not in seen_topics:
            seen_topics[topic] = pair

    return list(seen_topics.values())


def main():
    args = parse_args()

    cwd = Path.cwd().resolve()
    (cwd / "logs").mkdir(exist_ok=True)
    (cwd / "data" / "dedup").mkdir(parents=True, exist_ok=True)
    (cwd / "models").mkdir(exist_ok=True)

    os.environ["LLMFLUX_LOGS_DIR"] = str(cwd / "logs")
    os.environ["LLMFLUX_DATA_DIR"] = str(cwd / "data")
    os.environ["LLMFLUX_MODELS_DIR"] = str(cwd / "models")

    prompts_path = str(cwd / "data" / "dedup" / "topic_prompts.jsonl")
    topic_results_path = str(cwd / "data" / "dedup" / "topic_results.json")
    output_path = args.output

    print("Extracting Q/A pairs...")
    pairs = extract_qa_pairs(args.input)
    print(f"Loaded {len(pairs)} Q/A pairs")

    print("Writing topic-labeling prompts...")
    write_topic_prompts(pairs, prompts_path)
    print(f"Wrote {len(pairs)} prompts to {prompts_path}")

    # If topic results already exist (rerun), skip Slurm submission
    if Path(topic_results_path).exists():
        print(f"Topic results already found at {topic_results_path}, skipping Slurm job.")
    else:
        print("Submitting topic-labeling job to Slurm...")
        config = Config()
        slurm_config = config.get_slurm_config()
        slurm_config.account = "bfzk-delta-gpu"
        slurm_config.partition = "gpuA100x4"
        slurm_config.time = "02:00:00"
        slurm_config.mem = "32GB"
        slurm_config.gpus_per_node = 1
        slurm_config.nodes = 1
        slurm_config.cpus_per_task = 8

        runner = SlurmRunner(
            config=slurm_config,
            workspace=str(cwd),
            engine_config=EngineConfig(engine="vllm", home=str(cwd / ".vllm")),
        )

        job_id = runner.run(
            input_path=prompts_path,
            output_path=topic_results_path,
            model="Qwen3-8B",
            batch_size=4,
        )
        print(f"Job submitted: {job_id}")
        print(f"Once the Slurm job completes, rerun this script to finish deduplication:")
        print(f"  python3 dedup_tickets.py -i {args.input} -o {output_path}")
        return

    print("Deduplicating...")
    deduped = dedup_by_topic(pairs, topic_results_path)
    print(f"Reduced {len(pairs)} -> {len(deduped)} unique Q/A pairs")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(deduped, f, indent=2)
    print(f"Saved to {output_path}")


if __name__ == "__main__":
    main()