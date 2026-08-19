"""Tests for the key probe behind the launch desk.

The prober is injected, so nothing here touches the network: the point under test
is the cache discipline and the reporting, not the providers themselves.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from entities.llm_configs import LLM_SET, ProviderSpec
from web.app import create_app
from web.probe import ProbeCache
from web.schemas import ProviderHealth


class CountingProber:
    """google answers, everyone else is out of credits."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, spec: ProviderSpec) -> ProviderHealth:
        self.calls += 1
        if spec.name == "google":
            return ProviderHealth(name=spec.name, model_id=spec.model_id, ok=True)
        return ProviderHealth(
            name=spec.name, model_id=spec.model_id, ok=False, error="402 Payment Required"
        )


def probing_client(tmp_path: Path, prober: CountingProber, ttl_s: float = 600.0) -> TestClient:
    client = TestClient(create_app(runs_root=tmp_path))
    client.app.state.key_probe = ProbeCache(ttl_s=ttl_s, prober=prober)
    return client


def test_the_probe_says_who_can_answer_and_why_not(tmp_path: Path) -> None:
    client = probing_client(tmp_path, CountingProber())

    report = client.get("/api/providers").json()

    by_name = {p["name"]: p for p in report["providers"]}
    assert set(by_name) == {spec.name for spec in LLM_SET}
    assert by_name["google"]["ok"] is True and by_name["google"]["error"] is None
    assert by_name["cerebras"]["ok"] is False
    assert "402" in by_name["cerebras"]["error"]


def test_a_fresh_probe_is_not_repeated(tmp_path: Path) -> None:
    prober = CountingProber()
    client = probing_client(tmp_path, prober)

    client.get("/api/providers")
    client.get("/api/providers")

    assert prober.calls == len(LLM_SET), "the second look reads the cache"


def test_refresh_asks_again(tmp_path: Path) -> None:
    prober = CountingProber()
    client = probing_client(tmp_path, prober)

    client.get("/api/providers")
    client.get("/api/providers", params={"refresh": "true"})

    assert prober.calls == 2 * len(LLM_SET)


def test_a_stale_probe_asks_again_by_itself(tmp_path: Path) -> None:
    prober = CountingProber()
    client = probing_client(tmp_path, prober, ttl_s=0.0)

    client.get("/api/providers")
    client.get("/api/providers")

    assert prober.calls == 2 * len(LLM_SET)
