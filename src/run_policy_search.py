"""Search policy notices independently of report generation."""

import argparse
import json
from pathlib import Path

from src.services import search_policies


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    result = search_policies(json.loads(args.input.read_text(encoding="utf-8")))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"[ok] 정책 검색 저장: storage/generated_reports/v2/{result['run_id']}")


if __name__ == "__main__":
    main()
