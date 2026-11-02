"""Train optional synthetic CPU platform models from configured demo tables."""
from __future__ import annotations

import argparse
import json

from config_loader import load_config
from platform_models import train_models


def main() -> int:
    parser = argparse.ArgumentParser(description="Train synthetic SEM and Trend classifiers")
    parser.add_argument("--config", required=True, help="base YAML config")
    parser.add_argument("--overlay", required=True, help="explicit demo/test YAML overlay")
    args = parser.parse_args()
    settings = load_config(args.config, args.overlay)
    print(json.dumps(train_models(settings), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
