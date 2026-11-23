import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import iniciar_laboratorio as launcher


@pytest.mark.parametrize("code", [10048, 10013])
def test_windows_port_unavailable_moves_to_fallback(monkeypatch, code):
    occupied, available = Mock(), Mock()
    occupied.bind.side_effect = OSError(code, "Puerto ocupado o reservado")
    monkeypatch.setattr(launcher.socket, "socket", Mock(side_effect=[occupied, available]))

    assert launcher.reserve_listener() is available
    occupied.bind.assert_called_once_with(("127.0.0.1", 8001))
    occupied.close.assert_called_once()
    available.bind.assert_called_once_with(("127.0.0.1", 8002))
    available.listen.assert_called_once()
    available.close.assert_not_called()
