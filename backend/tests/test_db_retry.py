import asyncpg
import pytest

from app.db import retry_on_disconnect


@retry_on_disconnect
class Flaky:
    def __init__(self, failures: list[BaseException]):
        self.failures, self.calls = list(failures), 0

    async def query(self, x):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return x * 2

    async def _private(self):
        raise asyncpg.exceptions.ConnectionDoesNotExistError("x")


async def test_retries_once_on_a_dropped_connection():
    f = Flaky([asyncpg.exceptions.ConnectionDoesNotExistError("closed mid-operation")])
    assert await f.query(21) == 42
    assert f.calls == 2


async def test_gives_up_after_one_retry():
    drop = asyncpg.exceptions.ConnectionDoesNotExistError
    f = Flaky([drop("a"), drop("b")])
    with pytest.raises(drop):
        await f.query(1)
    assert f.calls == 2


async def test_other_errors_are_not_retried():
    f = Flaky([asyncpg.exceptions.UniqueViolationError("dup")])
    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        await f.query(1)
    assert f.calls == 1


async def test_private_methods_are_left_alone():
    with pytest.raises(asyncpg.exceptions.ConnectionDoesNotExistError):
        await Flaky([])._private()
