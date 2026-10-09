import re
from pathlib import Path

WORKFLOWS = sorted(Path(__file__).resolve().parent.parent.glob(".github/workflows/*.yml"))


def _text(name):
    return (Path(__file__).resolve().parent.parent / ".github/workflows" / name).read_text(encoding="utf-8")


def test_no_workflow_uses_pull_request_target_or_prints_a_secret():
    assert WORKFLOWS
    for w in WORKFLOWS:
        text = w.read_text(encoding="utf-8")
        assert "pull_request_target" not in text, w
        assert not re.search(r"echo[^\n]*secrets\.", text), w


def test_generate_workflow_keeps_inputs_out_of_shell_and_the_token_out_of_the_pr_step():
    text = _text("generate.yml")
    assert "workflow_dispatch:" in text and "\n  push:" not in text and "pull_request:" not in text   # only by hand
    # `${{ inputs.* }}` may appear only on `env:`/`if:` lines, never inside a run script
    runs = re.findall(r"run: \|\n((?:\s{10,}.*\n)+)", text)
    assert runs and not any("${{" in block for block in runs)
    # the Hugging Face token is given to the preflight and generate steps only
    steps = re.split(r"\n      - ", text)
    with_token = [s.split("\n", 1)[0] for s in steps if "secrets.HF_TOKEN" in s]
    assert len(with_token) == 2 and all(("Preflight" in s or "Generate summaries" in s) for s in with_token), with_token
    assert "geocode" in text and "zoning" in text and "parcel" not in text.split("on:\n", 1)[1].replace("never runs the", "")


def test_generate_workflow_refuses_private_paths_and_caps_spend():
    text = _text("generate.yml")
    assert "private/" in text and "<= 5" in text and "--max-usd" in text


def test_watch_workflow_is_read_only_apart_from_issues_and_uses_no_secrets():
    text = _text("watch_minutes.yml")
    assert "schedule:" in text and "workflow_dispatch:" in text and "pull_request" not in text
    assert "contents: read" in text and "issues: write" in text and "contents: write" not in text
    assert "secrets." not in text.replace("github.token", "") and "HF_TOKEN" not in text
    runs = re.findall(r"run: \|\n((?:\s{10,}.*\n)+)", text)
    assert runs and not any("${{" in block for block in runs)
    assert "echo_montolieu.watch" in text and "sync" not in text.split("on:\n", 1)[1].replace("# ", "").split("jobs:")[1]
