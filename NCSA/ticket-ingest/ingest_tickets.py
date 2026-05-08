#!/usr/bin/env python3
"""
ingest_tickets.py - Unified ticket ingestion pipeline

Takes a CSV of new tickets and an existing Q/A pairs JSON, then:
  1. Prepares prompts from new tickets
  2. Summarizes new tickets into Q/A pairs via llmflux (Slurm)
  3. Deduplicates the new Q/A pairs
  4. Merges with existing Q/A pairs
  5. Re-clusters all pairs (reusing existing cluster definitions if available)
  6. Saves the updated Q/A pairs

Usage:
    python3 ingest_tickets.py \
        --new-csv dtsup_january26.csv \
        --existing-pairs /path/to/clustered.json \
        --output /path/to/updated_clustered.json \
        [--cluster-defs /path/to/cluster_definitions.json] \
        [--work-dir data/runs/jan26]

Environment variables required:
    NCSA_LLM_URL            - Illinois Chat API base URL
    ILLINOIS_CHAT_API_KEY   - Illinois Chat API key
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

TOPIC_SYSTEM_PROMPT = """\
You will be given a Q&A pair. Your job is to assign it a short, normalized topic key
that captures the core issue — generalized enough that near-duplicate questions map
to the same key.

Rules:
- The topic key must be 3-8 words, lowercase, hyphen-separated (e.g. "submit-gpu-job-slurm")
- Ignore surface differences in phrasing — focus on the underlying issue
- Do not include user-specific details, ticket IDs, or project names
- Output ONLY the topic key, nothing else

Example:
Q: How do I request an A100 GPU for my job?
A: Use the gpuA100x4 partition in your sbatch script...
Output: request-gpu-node-slurm
"""

CLUSTER_SYSTEM_PROMPT = """\
You are organizing HPC support topics into high-level clusters.

Given a list of topic keys, create 10-20 broad clusters that cover all the topics.
Each cluster should have a short, descriptive name (3-6 words, lowercase, hyphen-separated).
Each topic must appear in exactly one cluster.

Respond ONLY with a JSON object mapping cluster names to arrays of topic keys.

Example:
{
  "job-submission-and-scheduling": ["submit-gpu-job-slurm", "sbatch-array-jobs", ...],
  "account-and-access-management": ["reset-user-password", "request-new-account", ...]
}
"""

ASSIGN_SYSTEM_PROMPT = """\
You are assigning an HPC support Q/A pair to one of several predefined clusters.

Given a list of cluster names and a Q/A pair, respond ONLY with the cluster name
that best fits the Q/A pair. Do not explain your choice.
"""

def get_client():
    from openai import OpenAI
    base_url = os.environ.get("NCSA_LLM_URL")
    api_key = os.environ.get("ILLINOIS_CHAT_API_KEY")
    if not base_url or not api_key:
        raise EnvironmentError("NCSA_LLM_URL and ILLINOIS_CHAT_API_KEY must be set.")
    return OpenAI(base_url=base_url, api_key=api_key)


def strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def run_prep(new_csv: str, prompts_path: str):
    print(f"\n[Step 1] Preparing prompts from {new_csv}")
    result = subprocess.run(
        [sys.executable, "prep_tickets.py", "-i", new_csv, "-o", prompts_path],
        check=True
    )
    count = sum(1 for _ in open(prompts_path))
    print(f"  Wrote {count} prompts to {prompts_path}")

def run_summarize(prompts_path: str, raw_results_path: str):
    from llmflux.slurm import SlurmRunner
    from llmflux.core.config import Config, EngineConfig

    print(f"\n[Step 2] Summarizing tickets via llmflux (Slurm)")
    if Path(raw_results_path).exists():
        print(f"  Results already found at {raw_results_path}, skipping.")
        return

    cwd = Path.cwd().resolve()
    (cwd / "logs").mkdir(exist_ok=True)
    (cwd / "models").mkdir(exist_ok=True)
    os.environ["LLMFLUX_LOGS_DIR"] = str(cwd / "logs")
    os.environ["LLMFLUX_DATA_DIR"] = str(cwd / "data")
    os.environ["LLMFLUX_MODELS_DIR"] = str(cwd / "models")

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
        input_path=str(Path(prompts_path).resolve()),
        output_path=str(Path(raw_results_path).resolve()),
        model="Qwen3-8B",
        batch_size=4,
    )
    print(f"  Job submitted with ID: {job_id}")
    print(f"  Waiting for Slurm job to finish...")
    while not Path(raw_results_path).exists():
        time.sleep(30)
        print(f"  Still waiting...")
    print(f"  Results ready at {raw_results_path}")

def extract_qa_pairs(raw_results_path: str) -> list[dict]:
    print(f"\n[Step 3] Extracting Q/A pairs from summarize output")
    with open(raw_results_path) as f:
        results = json.load(f)

    pairs = []
    for item in results:
        try:
            content = item["output"]["choices"][0]["message"]["content"]
            content = strip_think(content)
            pairs.append({
                "custom_id": item["input"]["custom_id"],
                "content": content
            })
        except (KeyError, IndexError):
            continue

    print(f"  Extracted {len(pairs)} Q/A pairs")
    return pairs

def label_topics(pairs: list[dict], topics_cache_path: str) -> dict:
    if Path(topics_cache_path).exists():
        print(f"  Loading cached topic labels from {topics_cache_path}")
        with open(topics_cache_path) as f:
            return json.load(f)

    print(f"  Labeling {len(pairs)} Q/A pairs with topic keys...")
    client = get_client()
    topic_map = {}

    for i, pair in enumerate(pairs):
        try:
            response = client.chat.completions.create(
                model="Qwen/Qwen3-VL-32B-Instruct",
                max_tokens=20,
                temperature=0.0,
                messages=[
                    {"role": "system", "content": TOPIC_SYSTEM_PROMPT},
                    {"role": "user", "content": pair["content"]}
                ]
            )
            topic = strip_think(response.choices[0].message.content)
            topic_map[pair["custom_id"]] = topic
        except Exception as e:
            print(f"  Warning: failed to label {pair['custom_id']}: {e}")
            topic_map[pair["custom_id"]] = pair["custom_id"]

        if (i + 1) % 50 == 0:
            print(f"  Labeled {i + 1}/{len(pairs)}...")
            time.sleep(1)

    Path(topics_cache_path).parent.mkdir(parents=True, exist_ok=True)
    with open(topics_cache_path, "w") as f:
        json.dump(topic_map, f, indent=2)
    print(f"  Saved topic labels to {topics_cache_path}")
    return topic_map


def dedup_new_pairs(pairs: list[dict], topic_map: dict) -> list[dict]:
    seen = {}
    for pair in pairs:
        topic = topic_map.get(pair["custom_id"], pair["custom_id"])
        if topic not in seen:
            seen[topic] = pair
    deduped = list(seen.values())
    print(f"  Deduplicated: {len(pairs)} → {len(deduped)} unique Q/A pairs")
    return deduped


def run_dedup(new_pairs: list[dict], topics_cache_path: str) -> list[dict]:
    print(f"\n[Step 4] Deduplicating {len(new_pairs)} new Q/A pairs")
    topic_map = label_topics(new_pairs, topics_cache_path)
    return dedup_new_pairs(new_pairs, topic_map), topic_map

def merge_pairs(existing_pairs: list[dict], new_deduped: list[dict]) -> list[dict]:
    print(f"\n[Step 5] Merging pairs")
    existing_ids = {p["custom_id"] for p in existing_pairs}
    truly_new = [p for p in new_deduped if p["custom_id"] not in existing_ids]
    merged = existing_pairs + truly_new
    print(f"  Existing: {len(existing_pairs)}, New (not already present): {len(truly_new)}, Total: {len(merged)}")
    return merged


def generate_clusters(client, topic_labels: dict) -> dict:
    unique_topics = list(set(topic_labels.values()))
    print(f"  Asking LLM to cluster {len(unique_topics)} unique topic keys...")
    response = client.chat.completions.create(
        model="Qwen/Qwen3-VL-32B-Instruct",
        max_tokens=2000,
        temperature=0.0,
        messages=[
            {"role": "system", "content": CLUSTER_SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(unique_topics)}
        ]
    )
    raw = strip_think(response.choices[0].message.content)
    raw = re.sub(r"```json|```", "", raw).strip()
    return json.loads(raw)


def build_topic_to_cluster(clusters: dict) -> dict:
    topic_to_cluster = {}
    for cluster_name, topics in clusters.items():
        for topic in topics:
            topic_to_cluster[topic] = cluster_name
    return topic_to_cluster


def assign_cluster_fallback(client, qa_content: str, cluster_names: list[str]) -> str:
    cluster_list = "\n".join(cluster_names)
    response = client.chat.completions.create(
        model="Qwen/Qwen3-VL-32B-Instruct",
        max_tokens=20,
        temperature=0.0,
        messages=[
            {"role": "system", "content": ASSIGN_SYSTEM_PROMPT},
            {"role": "user", "content": f"Clusters:\n{cluster_list}\n\nQ/A pair:\n{qa_content}"}
        ]
    )
    result = strip_think(response.choices[0].message.content)
    # Return closest matching cluster name or first if no match
    for name in cluster_names:
        if name.lower() in result.lower() or result.lower() in name.lower():
            return name
    return cluster_names[0]


def run_cluster(
    all_pairs: list[dict],
    topic_map: dict,
    cluster_defs_path,
    output_cluster_defs_path: str
) -> list[dict]:
    print(f"\n[Step 6] Clustering {len(all_pairs)} Q/A pairs")
    client = get_client()


    if cluster_defs_path and Path(cluster_defs_path).exists():
        print(f"  Loading existing cluster definitions from {cluster_defs_path}")
        with open(cluster_defs_path) as f:
            clusters = json.load(f)
    else:
        print("  No existing cluster definitions found — generating new ones")
        clusters = generate_clusters(client, topic_map)

    cluster_names = list(clusters.keys())
    print(f"  Using {len(cluster_names)} clusters: {cluster_names}")
    Path(output_cluster_defs_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_cluster_defs_path, "w") as f:
        json.dump(clusters, f, indent=2)
    print(f"  Saved cluster definitions to {output_cluster_defs_path}")

    topic_to_cluster = build_topic_to_cluster(clusters)
    fallback_count = 0
    for pair in all_pairs:
        if pair.get("cluster") and pair["custom_id"] not in topic_map:
            continue
        topic = topic_map.get(pair["custom_id"])
        if topic and topic in topic_to_cluster:
            pair["cluster"] = topic_to_cluster[topic]
        else:
            pair["cluster"] = assign_cluster_fallback(client, pair["content"], cluster_names)
            fallback_count += 1

    if fallback_count:
        print(f"  Used fallback assignment for {fallback_count} pairs")
    counts = Counter(p.get("cluster", "unassigned") for p in all_pairs)
    print("\n  Cluster summary:")
    for cluster, count in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"    {cluster}: {count}")
    return all_pairs

def parse_args():
    p = argparse.ArgumentParser(description="Unified ticket ingestion pipeline")
    p.add_argument("--new-csv", required=True, help="Path to CSV of new Jira tickets")
    p.add_argument("--existing-pairs", required=True, help="Path to existing clustered Q/A pairs JSON")
    p.add_argument("--output", required=True, help="Path to write updated Q/A pairs JSON")
    p.add_argument("--cluster-defs", default=None, help="Path to existing cluster definitions JSON (optional)")
    p.add_argument("--work-dir", default=None, help="Directory for intermediate files (default: next to output)")
    return p.parse_args()

def main():
    args = parse_args()
    work_dir = Path(args.work_dir) if args.work_dir else Path(args.output).parent / "run_tmp"
    work_dir.mkdir(parents=True, exist_ok=True)

    prompts_path = str(work_dir / "new_prompts.jsonl")
    raw_results_path = str(work_dir / "new_raw_results.json")
    topics_cache_path = str(work_dir / "new_topic_labels.json")
    output_cluster_defs = str(Path(args.output).parent / "cluster_definitions.json")

    print(f"Work directory: {work_dir}")
    print(f"Output: {args.output}")
    run_prep(args.new_csv, prompts_path)
    run_summarize(prompts_path, raw_results_path)
    new_pairs = extract_qa_pairs(raw_results_path)
    if not new_pairs:
        print("No Q/A pairs extracted. Check the summarize output.")
        sys.exit(1)
    new_deduped, new_topic_map = run_dedup(new_pairs, topics_cache_path)
    print(f"\n  Loading existing pairs from {args.existing_pairs}")
    with open(args.existing_pairs) as f:
        existing_pairs = json.load(f)
    all_pairs = merge_pairs(existing_pairs, new_deduped)
    all_pairs = run_cluster(all_pairs, new_topic_map, args.cluster_defs, output_cluster_defs)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(all_pairs, f, indent=2)
    print(f"\nSaved {len(all_pairs)} Q/A pairs to {args.output}")
    print("Done.")


if __name__ == "__main__":
    main()