from hztz.core.repo import build_repo_context, build_tree, detect_stack, detect_test_framework


def test_stack_from_package_json(tmp_path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    assert "node" in detect_stack(tmp_path)


def test_pytest_from_tests_and_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[project]\ndependencies=['pytest']\n", encoding="utf-8"
    )
    (tmp_path / "tests").mkdir()
    assert detect_test_framework(tmp_path, "python") == "pytest"


def test_jest_from_spec_ts(tmp_path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.spec.ts").write_text("test", encoding="utf-8")
    assert detect_test_framework(tmp_path, "node") == "jest"


def test_go_test_from_filename(tmp_path):
    (tmp_path / "go.mod").write_text("module example\n", encoding="utf-8")
    (tmp_path / "lib_test.go").write_text("package lib\n", encoding="utf-8")
    assert detect_test_framework(tmp_path, "go") == "go test"


def test_rspec_from_spec_dir(tmp_path):
    (tmp_path / "Gemfile").write_text("gem 'rspec'\n", encoding="utf-8")
    (tmp_path / "spec").mkdir()
    assert detect_test_framework(tmp_path, "ruby") == "rspec"


def test_tree_skips_ignored_dirs(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "main.py").write_text("x", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "leftpad").mkdir()
    (tmp_path / ".git").mkdir()
    (tmp_path / ".hz").mkdir()
    (tmp_path / "venv").mkdir()
    text = build_tree(tmp_path)
    assert "main.py" in text
    assert "node_modules" not in text
    assert ".git" not in text
    assert ".hz" not in text
    assert "venv" not in text


def test_greenfield_has_no_context(tmp_path):
    (tmp_path / "notes.txt").write_text("hi", encoding="utf-8")
    assert build_repo_context(tmp_path) is None
