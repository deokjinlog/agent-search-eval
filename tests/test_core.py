from pathlib import Path

from ase.bm25 import BM25, tokenize
from ase.golden import is_code, question_text
from ase.report import bootstrap, compare
from ase.score import classify, parse_submission, path_listed, rel


def test_tokenize_korean_bigrams_and_split_identifiers():
    toks = tokenize("감사의견 parseAuditOpinion stlm_dt")
    assert {"감사", "사의", "의견"} <= set(toks)
    assert {"parseauditopinion", "parse", "audit", "opinion"} <= set(toks)
    assert "stlm" in toks and "dt" in toks


def test_bm25_ranks_matching_document_first():
    docs = {
        "a.py": tokenize("def 감사의견(): pass"),
        "b.py": tokenize("def 재무제표(): pass"),
        "c.py": tokenize("print('hello')"),
    }
    ranked = BM25(docs).rank(tokenize("감사의견 연도 분리"))
    assert ranked[0][0] == "a.py" and ranked[0][1] > 0


def test_is_code_excludes_tests_and_docs():
    assert is_code("src/pkg/flags.py") and is_code("web/index.html")
    assert not is_code("tests/test_flags.py") and not is_code("pkg/flags_test.py")
    assert not is_code("README.md") and not is_code("test_cases.py")


def test_question_text_strips_conventional_prefix():
    assert question_text("fix(law): 조문가지번호를 키에 넣는다") == ("조문가지번호를 키에 넣는다", "fix")
    assert question_text("그냥 쓴 제목") == ("그냥 쓴 제목", None)


def test_parse_submission_takes_last_string_array():
    text = '중간에 [1, 2]도 있고\n```json\n["src/a.py", "web/b.html"]\n```'
    assert parse_submission(text) == ["src/a.py", "web/b.html"]
    assert parse_submission("답 없음") == []
    assert parse_submission("최종: []") == []


def test_rel_strips_snapshot_prefix_and_dot():
    root = Path("/x/snapshots/q1")
    assert rel("/x/snapshots/q1/src/a.py", root) == "src/a.py"
    assert rel("./src/a.py", root) == "src/a.py"
    assert rel("/src/a.py", root) == "src/a.py"


def test_classify_query_origin():
    q = "감사의견 연도 분리"
    assert classify(["감사의견"], q, "", "") == "issue"
    assert classify(["stlm_dt"], q, "", "... stlm_dt = row['stlm_dt'] ...") == "obs"
    assert classify(["stlm_dt"], q, '{"pattern": "stlm_dt"}', "stlm_dt") == "guess"
    assert classify(["audit"], q, "", "") == "guess"
    assert classify([], q, "", "") == "none"


def test_bootstrap_is_deterministic_and_brackets_mean():
    diffs = [0.0, 0.5, 1.0, -0.5, 0.25]
    lo, hi = bootstrap(diffs)
    assert bootstrap(diffs) == [lo, hi]
    assert lo <= sum(diffs) / len(diffs) <= hi
    c = compare([0.1, 0.0, -0.2])
    assert (c["wins"], c["ties"], c["losses"]) == (1, 1, 1)


def test_path_listed_matches_whole_path_lines():
    text = "Found 2 files\nsrc/pkg/flags.py\nsrc/pkg/flags_test.py\nweb/index.html:12:  autofill()"
    assert path_listed("src/pkg/flags.py", text)
    assert path_listed("web/index.html", text)
    assert not path_listed("pkg/flags.py.bak", text)
    assert not path_listed("src/pkg/flag.py", text)
