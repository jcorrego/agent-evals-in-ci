import json
import threading
import time
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from agent_evals.evaluate import evaluate_dataset, load_dataset, main
from agent_evals.judge import OpenAIJudge
from agent_evals.models import EvaluationCase


@pytest.fixture
def provider():
    requests = []
    responses = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            requests.append(
                (self.path, self.headers.get("Authorization"), json.loads(self.rfile.read(length)))
            )
            status, payload = responses.pop(0)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if status == 302:
                self.send_header("Location", "http://example.test/steal")
            self.end_headers()
            with suppress(BrokenPipeError):
                self.wfile.write(json.dumps(payload).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1/chat/completions", requests, responses
    server.shutdown()
    thread.join()
    server.server_close()


def reply(findings, *, usage=None, finish_reason="stop"):
    return {
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": {"content": json.dumps({"findings": findings})},
            }
        ],
        "usage": usage or {"prompt_tokens": 100, "completion_tokens": 20},
    }


def judge(provider, **kwargs):
    url, _, _ = provider
    return OpenAIJudge(api_key="test-only", api_url=url, retry_delay=0, **kwargs)


def test_structured_response_records_provenance_usage_and_disagreement(provider):
    _, requests, responses = provider
    responses.append(
        (
            200,
            reply(
                [
                    {
                        "finding_type": "PII_LEAKAGE",
                        "severity": "blocking",
                        "evidence": "identifier present",
                    }
                ]
            ),
        )
    )
    case = EvaluationCase("safe", "No issue. [source:synthetic]", frozenset())
    result = evaluate_dataset([case], judge(provider))
    row = result["cases"][0]
    assert row["deterministic_findings"] == []
    assert row["judge_findings"][0]["finding_type"] == "PII_LEAKAGE"
    assert row["disagreement"] == {"deterministic_only": [], "judge_only": ["PII_LEAKAGE"]}
    assert row["judge"]["status"] == "ok"
    assert row["judge"]["usage"] == {"prompt_tokens": 100, "completion_tokens": 20}
    assert row["judge"]["latency_ms"] >= 0
    assert row["judge"]["estimated_cost_usd"] is not None
    assert row["judge"]["actual_cost_usd"] is None
    assert result["judge_metrics"]["false_positives"] == 1
    assert result["metrics"]["false_positives"] == 0
    path, auth, payload = requests[0]
    assert path == "/v1/chat/completions" and auth == "Bearer test-only"
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert payload["model"] == result["judge_config"]["model"]
    assert result["judge_config"]["prompt_version"] and result["judge_config"]["schema_version"]
    assert "test-only" not in json.dumps(result)


@pytest.mark.parametrize(
    "body",
    [
        reply([{"finding_type": "UNKNOWN", "severity": "blocking", "evidence": "x"}]),
        reply([{"finding_type": "PII_LEAKAGE", "severity": "warning", "evidence": "x"}]),
        reply(
            [
                {
                    "finding_type": "PII_LEAKAGE",
                    "severity": "blocking",
                    "evidence": "avery@example.test",
                }
            ]
        ),
        reply(
            [{"finding_type": "PII_LEAKAGE", "severity": "blocking", "evidence": "x", "extra": 1}]
        ),
        reply([], finish_reason="length"),
        {"choices": [{"message": {"refusal": "no"}, "finish_reason": "stop"}]},
        reply([], usage={"prompt_tokens": True, "completion_tokens": 10}),
    ],
)
def test_invalid_provider_output_is_not_a_clean_judgment(provider, body):
    provider[2].append((200, body))
    result = evaluate_dataset([EvaluationCase("x", "[source:x]", frozenset())], judge(provider))
    assert result["cases"][0]["judge"]["status"] == "invalid_response"
    assert result["cases"][0]["judge_findings"] is None
    assert result["judge_metrics"] is None


def test_transient_error_retries_then_succeeds(provider):
    provider[2].extend([(429, {"error": "limited"}), (503, {"error": "down"}), (200, reply([]))])
    result = evaluate_dataset([EvaluationCase("x", "[source:x]", frozenset())], judge(provider))
    assert len(provider[1]) == 3
    assert result["cases"][0]["judge"]["attempts"] == 3
    assert result["cases"][0]["judge"]["status"] == "ok"


def test_judge_miss_does_not_mask_blocking_rule(provider):
    provider[2].append((200, reply([])))
    case = EvaluationCase("x", "avery@example.test [source:x]", frozenset({"PII_LEAKAGE"}))
    result = evaluate_dataset([case], judge(provider))
    assert result["metrics"]["true_positives"] == 1
    assert result["judge_metrics"]["false_negatives"] == 1
    assert result["cases"][0]["disagreement"]["deterministic_only"] == ["PII_LEAKAGE"]


def test_cli_success_against_fake_http_provider(provider, tmp_path: Path, monkeypatch):
    provider[2].append((200, reply([])))
    dataset = tmp_path / "cases.json"
    dataset.write_text(
        json.dumps(
            {"cases": [{"case_id": "safe", "agent_output": "[source:x]", "expected_findings": []}]}
        )
    )
    output = tmp_path / "result.json"
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setattr(
        "sys.argv",
        [
            "agent-evals",
            "--dataset",
            str(dataset),
            "--output",
            str(output),
            "--judge",
            "openai",
            "--api-url",
            provider[0],
            "--retry-delay",
            "0",
        ],
    )
    main()
    artifact = json.loads(output.read_text())
    assert artifact["cases"][0]["judge"]["status"] == "ok"
    assert artifact["judge_metrics"]["recall"] == 1.0


def test_non_retryable_client_error(provider):
    provider[2].append((401, {"error": "bad key"}))
    result = judge(provider).review("[source:x]")
    assert result.status == "rejected" and result.attempts == 1
    assert len(provider[1]) == 1


def test_redirect_does_not_forward_credential(provider):
    provider[2].append((302, {"notice": "redirect"}))
    result = judge(provider).review("[source:x]")
    assert result.status == "rejected" and result.attempts == 1
    assert len(provider[1]) == 1


def test_timeout_is_bounded(provider):
    _, requests, _ = provider

    # A separate server can intentionally stall without blocking the normal fixture.
    class SlowHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append("slow")
            time.sleep(0.08)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), SlowHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = OpenAIJudge(
            api_key="test-only",
            api_url=f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
            timeout=0.01,
            retries=1,
            retry_delay=0,
        ).review("[source:x]")
        assert result.status == "unavailable" and result.attempts == 2
        assert requests.count("slow") == 2
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_rejects_non_loopback_plaintext_endpoint():
    with pytest.raises(ValueError, match="HTTPS"):
        OpenAIJudge(api_key="test-only", api_url="http://example.test/v1/chat/completions")


def test_provider_unavailable_cannot_erase_deterministic_violation(provider):
    provider[2].extend([(503, {}), (503, {}), (503, {})])
    result = evaluate_dataset(
        [EvaluationCase("x", "avery@example.test [source:x]", frozenset({"PII_LEAKAGE"}))],
        judge(provider),
    )
    assert result["metrics"]["true_positives"] == 1
    assert result["cases"][0]["observed_findings"] == ["PII_LEAKAGE"]
    assert result["cases"][0]["judge"]["status"] == "unavailable"
    assert result["judge_metrics"] is None


def test_cli_writes_failure_artifact_then_exits_nonzero(provider, tmp_path: Path, monkeypatch):
    provider[2].extend([(503, {}), (503, {}), (503, {})])
    dataset = tmp_path / "cases.json"
    dataset.write_text(
        json.dumps(
            {"cases": [{"case_id": "x", "agent_output": "[source:x]", "expected_findings": []}]}
        )
    )
    output = tmp_path / "result.json"
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setattr(
        "sys.argv",
        [
            "agent-evals",
            "--dataset",
            str(dataset),
            "--output",
            str(output),
            "--judge",
            "openai",
            "--api-url",
            provider[0],
            "--retry-delay",
            "0",
        ],
    )
    with pytest.raises(SystemExit, match="2"):
        main()
    assert json.loads(output.read_text())["cases"][0]["judge"]["status"] == "unavailable"


def test_baseline_never_calls_provider_and_reference_labels_are_comparable(provider):
    cases = load_dataset(Path(__file__).parents[1] / "evals/golden.json")
    result = evaluate_dataset(cases)
    assert result["metrics"]["true_positives"] == 4
    assert result["judge_metrics"] is None
    assert provider[1] == []
