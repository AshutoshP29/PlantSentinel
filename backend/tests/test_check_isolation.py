import check_isolation

REACH = [("ollama", "ollama", 11434)]
BLOCK = [("outside", "example.com", 443)]


def test_isolated_when_only_internal_hosts_connect() -> None:
    assert check_isolation.run(REACH, BLOCK, connect=lambda host, _port: host == "ollama")


def test_fails_when_an_external_host_connects() -> None:
    assert not check_isolation.run(REACH, BLOCK, connect=lambda _host, _port: True)


def test_fails_when_an_internal_host_is_down() -> None:
    assert not check_isolation.run(REACH, BLOCK, connect=lambda _host, _port: False)
