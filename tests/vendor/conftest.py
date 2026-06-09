import pytest


@pytest.fixture(scope="session", autouse=True)
def _qt_offscreen_env():
    yield


@pytest.fixture(scope="session", autouse=True)
def _silence_benign_qt():
    yield


@pytest.fixture(autouse=True)
def _no_modal_dialogs():
    yield


@pytest.fixture(autouse=True)
def _close_top_levels():
    yield


@pytest.fixture(scope="session", autouse=True)
def _apply_common_seed():
    yield
