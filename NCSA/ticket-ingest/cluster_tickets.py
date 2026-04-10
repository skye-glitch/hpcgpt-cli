import os
import re
import json
import argparse
from pathlib import Path
from openai import OpenAI

CLUSTER_SYSTEM_PROMPT = """\
You are an expert at organizing HPC support topics into logical groups.

You will be given a list of topic keys, each representing a unique HPC support issue.
Your job is to group them into high-level clusters that a user would find intuitive.

Rules:
- Create between 8 and 15 clusters
- Each cluster name must be 2-5 words, lowercase, hyphen-separated (e.g. "gpu-job-submission")
- Every topic key must be assigned to exactly one cluster
- Choose cluster names that are meaningful to HPC users
- Output ONLY valid JSON in this exact format, nothing else:

{
  "clusters": {
    "cluster-name-1": ["topic-key-1", "topic-key-2", ...],
    "cluster-name-2": ["topic-key-3", ...]
  }
}
"""

ASSIGN_SYSTEM_PROMPT = """\
You are an HPC support classifier.

You will be given a Q/A pair and a list of cluster names.
Assign the Q/A pair to the single most appropriate cluster.

Output ONLY the cluster name, nothing else.
"""


def parse_args():
    p = argparse.ArgumentParser(description="Group Q/A ticket pairs into topic clusters")
    p.add_argument("-i", "--input", required=True, help="Path to deduplicated Q/A JSON")
    p.add_argument("-t", "--topics", required=True, help="Path to topic_labels.json from dedup step")
    p.add_argument("-o", "--output", required=True, help="Path to write clustered Q/A JSON")
    return p.parse_args()


def get_client():
    base_url = os.environ.get("NCSA_LLM_URL")
    api_key = os.environ.get("ILLINOIS_CHAT_API_KEY")
    if not base_url or not api_key:
        raise EnvironmentError("NCSA_LLM_URL and ILLINOIS_CHAT_API_KEY must be set.")
    return OpenAI(base_url=base_url, api_key=api_key)


def generate_clusters(client, topic_labels: dict) -> dict:
    """Ask the LLM to group all topic keys into named clusters."""
    unique_topics = sorted(set(topic_labels.values()))
    topic_list = "\n".join(unique_topics)

    print(f"Asking LLM to cluster {len(unique_topics)} unique topic keys...")

    response = client.chat.completions.create(
        model="Qwen/Qwen3-VL-32B-Instruct",
        max_tokens=4000,
        temperature=0.2,
        messages=[
            {"role": "system", "content": CLUSTER_SYSTEM_PROMPT},
            {"role": "user", "content": f"Here are the topic keys to cluster:\n\n{topic_list}"}
        ]
    )

    content = response.choices[0].message.content.strip()
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

    content = re.sub(r"```json|```", "", content).strip()

    data = json.loads(content)
    return data["clusters"]


def build_topic_to_cluster(clusters: dict) -> dict:
    """Invert cluster map: topic_key -> cluster_name."""
    mapping = {}
    for cluster_name, topics in clusters.items():
        for topic in topics:
            mapping[topic] = cluster_name
    return mapping


def assign_cluster_fallback(client, qa_content: str, cluster_names: list) -> str:
    """Fallback: ask LLM to assign a Q/A directly to a cluster if its topic wasn't in the map."""
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
    result = response.choices[0].message.content.strip()
    result = re.sub(r"<think>.*?</think>", "", result, flags=re.DOTALL).strip()
    return result


def main():
    args = parse_args()

    print("Loading Q/A pairs...")
    with open(args.input) as f:
        pairs = json.load(f)
    print(f"Loaded {len(pairs)} Q/A pairs")

    print("Loading topic labels...")
    with open(args.topics) as f:
        topic_labels = json.load(f)

    client = get_client()

    clusters = generate_clusters(client, topic_labels)
    cluster_names = list(clusters.keys())
    print(f"LLM created {len(cluster_names)} clusters: {cluster_names}")


    cluster_def_path = str(Path(args.output).parent / "cluster_definitions.json")
    with open(cluster_def_path, "w") as f:
        json.dump(clusters, f, indent=2)
    print(f"Saved cluster definitions to {cluster_def_path}")


    topic_to_cluster = build_topic_to_cluster(clusters)

    print("Assigning Q/A pairs to clusters...")
    fallback_count = 0
    for pair in pairs:
        cid = pair["custom_id"]
        topic = topic_labels.get(cid)
        if topic and topic in topic_to_cluster:
            pair["cluster"] = topic_to_cluster[topic]
        else:
            pair["cluster"] = assign_cluster_fallback(client, pair["content"], cluster_names)
            fallback_count += 1

    print(f"Used fallback assignment for {fallback_count} pairs")

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(pairs, f, indent=2)
    print(f"Saved clustered Q/A pairs to {args.output}")

    from collections import Counter
    counts = Counter(p["cluster"] for p in pairs)
    print("\nCluster summary:")
    for cluster, count in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {cluster}: {count}")


if __name__ == "__main__":
    main()