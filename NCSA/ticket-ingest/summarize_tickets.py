import os
from pathlib import Path

from llmflux.slurm import SlurmRunner
from llmflux.core.config import Config, EngineConfig

cwd = Path.cwd().resolve()

(cwd / "logs").mkdir(exist_ok=True)
(cwd / "data").mkdir(exist_ok=True)
(cwd / "models").mkdir(exist_ok=True)
(cwd / "data" / "input").mkdir(parents=True, exist_ok=True)
(cwd / "data" / "output").mkdir(parents=True, exist_ok=True)
os.environ["LLMFLUX_LOGS_DIR"] = str(cwd / "logs")
os.environ["LLMFLUX_DATA_DIR"] = str(cwd / "data")
os.environ["LLMFLUX_MODELS_DIR"] = str(cwd / "models")

config = Config()
slurm_config = config.get_slurm_config()
slurm_config.account = "bfzk-delta-gpu"
slurm_config.partition = "gpuA100x4"
slurm_config.time = "06:00:00"
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
    input_path=str(cwd / "data" / "input" / "Delta-25.jsonl"),
    output_path=str(cwd / "data" / "output" / "Delta-25-results.json"),
    model="Qwen3-8B",
    batch_size=4,
)

print(f"Job submitted with ID: {job_id}")