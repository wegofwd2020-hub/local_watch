"""The deploy units, the launchd plist and mambakkam-ingest-render.sh all
invoke `.venv/bin/local_watch`. That executable only exists if pyproject
declares a console script, and nothing else in the suite notices if the
entry point is dropped or its target renamed — the failure surfaces on a
real machine at install time instead.
"""
import importlib
import pathlib
import tomllib

PYPROJECT = tomllib.loads((pathlib.Path(__file__).parent.parent / "pyproject.toml").read_text())


def test_a_local_watch_console_script_is_declared():
    assert "local_watch" in PYPROJECT["project"]["scripts"]


def test_the_console_script_target_is_importable_and_callable():
    module_name, _, func_name = PYPROJECT["project"]["scripts"]["local_watch"].partition(":")
    func = getattr(importlib.import_module(module_name), func_name)
    assert callable(func)


def test_a_build_backend_is_pinned():
    # Without an explicit build-system, pip falls back to setuptools' flat
    # layout auto-discovery, which refuses to build this repo at all: it sees
    # local_watch/, tests/, fixtures/, deploy/ and docs/ as competing
    # top-level packages and errors out.
    assert PYPROJECT["build-system"]["build-backend"]


def test_packages_are_declared_explicitly():
    packages = PYPROJECT["tool"]["setuptools"]["packages"]
    assert "local_watch" in packages and "local_watch.collectors" in packages


def test_wegofwd_llm_is_requested_with_the_anthropic_extra():
    """agent._default_provider() builds an "anthropic" provider, which
    wegofwd-llm only supports when its `anthropic` extra pulls in the SDK.
    Without the extra the provider raises LLMConfigurationError, recommend()
    swallows it, and every report silently falls back to rules-only text —
    which is exactly what happened on the first real deploy.
    """
    deps = PYPROJECT["project"]["dependencies"]
    llm = [d for d in deps if "wegofwd-llm" in d]
    assert llm, "wegofwd-llm dependency missing"
    assert "wegofwd-llm[anthropic]" in llm[0], llm[0]
