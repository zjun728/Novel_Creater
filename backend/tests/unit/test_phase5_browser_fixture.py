import pytest

from backend.config import current_runtime_configuration, RuntimeConfigurationError
from backend.scripts import prepare_phase5_browser_db as fixture


@pytest.mark.asyncio
@pytest.mark.parametrize('verify', [False, True])
async def test_phase5_cli_owns_runtime_configuration_until_pool_is_closed(monkeypatch, verify):
    events = []
    database = 'novel_creator_test_' + 'a' * 32
    for name, value in {'MYSQL_HOST': '127.0.0.1', 'MYSQL_PORT': '3307',
                        'MYSQL_USER': 'test', 'MYSQL_PASSWORD': 'test', 'MYSQL_DB': database}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr('sys.argv', ['phase5', '--database', database] + (['--verify-postconditions'] if verify else []))

    async def operation(name):
        assert current_runtime_configuration().mysql_pool_options()['db'] == database
        events.append('verify' if verify else 'prepare')

    async def close():
        current_runtime_configuration()
        events.append('close')

    monkeypatch.setattr(fixture, 'prepare', operation)
    monkeypatch.setattr(fixture, 'verify_postconditions', operation)
    monkeypatch.setattr(fixture, 'close_pool', close)
    await fixture.main()
    assert events == ['verify' if verify else 'prepare', 'close']
    with pytest.raises(RuntimeConfigurationError):
        current_runtime_configuration()
