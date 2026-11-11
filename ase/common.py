"""골든셋 읽기, 기준 시점 스냅샷 만들기, 파일 집합 지표."""

from __future__ import annotations

import io
import json
import subprocess
import tarfile
from pathlib import Path

from .golden import is_code

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / "snapshots"
REPOS = ROOT.parent / "deokjinlog"


def load_golden(path: Path | str = ROOT / "data" / "golden.jsonl") -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def snapshot(q: dict, repos_dir: Path = REPOS) -> Path:
    """부모 커밋 시점의 파일만 풀어 둔다. .git이 없으니 에이전트가 미래 커밋을 볼 수 없다."""
    dest = SNAPSHOTS / q["qid"]
    if dest.exists():
        return dest
    data = subprocess.run(
        ["git", "-C", str(repos_dir / q["repo"]), "archive", "--format=tar", q["base"]],
        check=True, capture_output=True,
    ).stdout
    dest.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(dest, filter="data")
    return dest


def code_files(root: Path) -> list[str]:
    """답이 될 수 있는 파일: 테스트가 아닌 코드 파일 (golden.is_code와 같은 기준)."""
    return sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and is_code(p.relative_to(root).as_posix())
    )


def recall(found: set[str], gold: set[str]) -> float:
    return len(found & gold) / len(gold) if gold else 0.0


def precision(found: set[str], gold: set[str]) -> float:
    return len(found & gold) / len(found) if found else 0.0
