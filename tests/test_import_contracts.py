"""The import-linter contracts in pyproject.toml ([tool.importlinter]): no
import cycles between sibling modules or subpackages, and nothing outside
sec_agent.devtools imports it. Static imports only -- a dynamic import_module()
is invisible to them."""

import subprocess
import sys
import tomllib

import pytest
from importlinter.cli import EXIT_STATUS_SUCCESS

from sec_agent.config import PROJECT_ROOT

PYPROJECT = PROJECT_ROOT / "pyproject.toml"

# Read from the config, so a contract added there is gated with no test edit.
CONTRACT_IDS = [
    contract["id"]
    for contract in tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["importlinter"]["contracts"]
]

# lint_imports() puts the cwd on sys.path and reconfigures logging (which
# disables every existing logger), so it runs in a child process.
LINT = (
    "import sys\n"
    "from importlinter.cli import lint_imports\n"
    "sys.exit(lint_imports(config_filename=sys.argv[1], limit_to_contracts=(sys.argv[2],), no_cache=True))\n"
)


@pytest.mark.parametrize("contract", CONTRACT_IDS)
def test_import_contract_is_kept(contract):
    result = subprocess.run(
        [sys.executable, "-c", LINT, str(PYPROJECT), contract],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=120,
        check=False,
    )
    assert result.returncode == EXIT_STATUS_SUCCESS, result.stdout + result.stderr
