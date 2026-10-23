from typer.testing import CliRunner

from hztz.cli.main import app

runner = CliRunner()


def test_init_path(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    result = runner.invoke(app, ["init", "--path"])
    assert result.exit_code == 0
    assert "config.json" in result.output


def test_init_show_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    result = runner.invoke(app, ["init", "--show"])
    assert result.exit_code == 0
    assert "файл ещё не создан" in result.output


def test_audit_without_config_exits_2(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    spec = tmp_path / "spec.md"
    spec.write_text("Сделать быстро и красиво.", encoding="utf-8")
    result = runner.invoke(app, ["audit", str(spec)])
    assert result.exit_code == 2
    assert "hz init" in result.output
