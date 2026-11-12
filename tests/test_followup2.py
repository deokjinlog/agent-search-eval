import math
import re
import zlib
from collections import Counter

from ase.followup2 import arm_summary
from ase.rewrite import PROMPT, command, parse_terms
from ase.vector import chunks, rank_files, rrf


def test_rewrite_prompt_has_no_tools_and_question():
    cmd = command("haiku", "로컬 서버 자동채움")
    assert cmd[cmd.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in cmd and "--no-session-persistence" in cmd
    assert "로컬 서버 자동채움" in cmd[2] and "{question}" in PROMPT


def test_parse_terms_takes_last_line_without_fences():
    assert parse_terms("```\nautofill serve_local\n```") == "autofill serve_local"
    assert parse_terms("설명 한 줄\n`fill_form bridge.js`") == "fill_form bridge.js"
    assert parse_terms("") == ""


def test_chunks_cover_tail_and_carry_path():
    text = "\n".join(f"line{i}" for i in range(130))
    cs = chunks("a.py", text, size=60, stride=40)
    assert len(cs) == 3 and all(c.startswith("a.py\n") for c in cs)
    assert cs[-1].endswith("line129") and "line70" in cs[-1]
    assert chunks("empty.py", "") == ["empty.py"]


def _fake_embed(texts):
    """단어 해시 bag-of-words를 정규화한 가짜 임베딩 (테스트용, crc32라 실행마다 같음)."""
    out = []
    for t in texts:
        v = [0.0] * 1024
        for w, c in Counter(re.findall(r"\w+", t.lower())).items():
            v[zlib.crc32(w.encode()) % 1024] += c
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / n for x in v])
    return out


def test_rank_files_uses_best_chunk():
    texts = {"a.py": "def autofill(): pass", "b.py": "def unrelated(): pass\n" * 200}
    ranked = rank_files("autofill", texts, _fake_embed)
    assert ranked[0][0] == "a.py"


def test_rrf_rewards_agreement():
    assert rrf([["a", "b", "c"], ["b", "a", "d"]])[:2] == ["a", "b"]
    assert set(rrf([["a"], ["d"]])) == {"a", "d"}


def test_arm_summary_slices_and_diff():
    golden = [{"qid": "q1", "has_identifier": True}, {"qid": "q2", "has_identifier": False}]
    base = {"q1": 1.0, "q2": 0.0}
    rows = [
        {"qid": "q1", "run": 1, "submit_recall": 1.0, "precision": 0.2, "submitted": ["a"] * 5},
        {"qid": "q2", "run": 1, "submit_recall": 1.0, "precision": 0.2, "submitted": ["a"] * 5},
        {"qid": "q1", "run": 2, "submit_recall": 1.0, "precision": 0.2, "submitted": ["a"] * 5},
        {"qid": "q2", "run": 2, "submit_recall": 0.0, "precision": 0.0, "submitted": ["a"] * 5},
    ]
    s = arm_summary(golden, base, rows)
    assert math.isclose(s["submit_recall"], 0.75)
    assert math.isclose(s["slices"]["no_identifier"]["arm"], 0.5)
    assert math.isclose(s["vs_bm25_top5"]["mean"], 0.25)
    assert s["run_means"] == [1.0, 0.5]
