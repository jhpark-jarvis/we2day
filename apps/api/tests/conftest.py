import pytest
from database_fixture import temporary_database


def pytest_addoption(parser):
    parser.addoption("--database", action="store_true", help="Test SQL in a disposable Docker DB")


@pytest.fixture(scope="session")
def database_url(request):
    if not request.config.getoption("--database"):
        pytest.skip("Use --database to run PostgreSQL/RLS/concurrency tests in Docker")
    with temporary_database() as (dsn, _):
        yield dsn
