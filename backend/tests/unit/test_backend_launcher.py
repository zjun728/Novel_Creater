from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = REPOSITORY_ROOT / "start_backend.bat"


def test_backend_launcher_runs_package_entrypoint_from_repository_root():
    lines = [line.strip() for line in LAUNCHER.read_text(encoding="utf-8").splitlines()]
    lowered = [line.lower() for line in lines]
    commands = [line for line in lowered if "-m uvicorn" in line]

    assert 'cd /d "%~dp0"' in lowered
    assert 'cd /d "%~dp0backend"' not in lowered
    assert len(commands) == 2
    assert all(
        "-m uvicorn backend.main:app --host 127.0.0.1 --port 8000" in command
        for command in commands
    )
    assert all("uvicorn main:app" not in command for command in commands)
