import signal

import pytest

from assistant.__main__ import main


@pytest.fixture
def restore_sigint():
    old = signal.getsignal(signal.SIGINT)
    yield
    signal.signal(signal.SIGINT, old)


def test_ctrl_c_at_startup(restore_sigint):
    out = []

    def start():
        raise KeyboardInterrupt

    assert main(start, out.append) == 0
    assert out == ["Arrivederci!"]


def test_exit_code_from_start(restore_sigint):
    assert main(lambda: 1, print) == 1


def test_late_ctrl_c_ignored_after_exit(restore_sigint):
    main(lambda: 0, print)
    assert signal.getsignal(signal.SIGINT) is signal.SIG_IGN
