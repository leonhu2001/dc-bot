from pathlib import Path


def test_deploy_health_wait_is_configurable_and_long_enough() -> None:
    script = Path("scripts/deploy_main.sh").read_text(encoding="utf-8")

    assert 'HEALTH_ATTEMPTS="${DEPLOY_HEALTH_ATTEMPTS:-45}"' in script
    assert 'HEALTH_INTERVAL="${DEPLOY_HEALTH_INTERVAL_SECONDS:-1}"' in script
    assert 'HEALTH_CURL_TIMEOUT="${DEPLOY_HEALTH_CURL_TIMEOUT_SECONDS:-3}"' in script
    assert 'for attempt in $(seq 1 "$HEALTH_ATTEMPTS")' in script
    assert 'after $HEALTH_ATTEMPTS attempts' in script
    assert 'seq 1 15' not in script
