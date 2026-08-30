"""显式准备命令;不由运行时加载器调用。"""

import argparse
from pathlib import Path

import httpx

from baseline_agent.knowledge_embedding import verify_model_directory
from baseline_agent.rag_eval_v1 import load_rag_eval_v1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    protocol = load_rag_eval_v1().protocol.model
    with httpx.Client(follow_redirects=True, timeout=120) as client:
        for name in protocol.files:
            target = args.directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            response = client.get(
                f"https://huggingface.co/{protocol.name}/resolve/{protocol.revision}/{name}"
            )
            response.raise_for_status()
            target.write_bytes(response.content)
    verify_model_directory(args.directory)
    print(f"已校验离线模型 revision={protocol.revision}")


if __name__ == "__main__":
    main()
