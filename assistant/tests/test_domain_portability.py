"""app/domain/ must stay movable (see docs/ARCHITECTURE.md).

The booking state machine, the availability rules, the capacity lock and the
payment/refund arithmetic are *platform* logic: a customer booking from the
Laqta dashboard should be held to the same rules as one booking through the
assistant. They live in this repo only because Laqta has no booking concept
yet and the assistant is the sole consumer today.

That deferral stays cheap only while the move is a file copy. So the
boundary is enforced here rather than trusted:

  * app/domain/ may import app/config, specific app/models modules, and
    itself. Nothing else under app/.
  * Not even the app.models *package* — its __init__ imports every model,
    including assistant-only tables, so depending on it means depending on
    this repo's aggregate model API.
  * app/assistant_domain/ is deliberately out of scope here. It is pure (see
    test_domain_purity) but assistant-only, and is not going to Laqta.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ASSISTANT_DIR = Path(__file__).resolve().parent.parent
DOMAIN_DIR = ASSISTANT_DIR / "app" / "domain"
DOMAIN_FILES = sorted(DOMAIN_DIR.rglob("*.py"))

# Exactly the platform logic. If a file appears here that is not on this
# list, either it is misplaced or the list is out of date — both worth a
# failing test.
PLATFORM_MODULES = {
    "__init__.py",
    "availability.py",
    "booking_state.py",
    "capacity.py",
    "payment.py",
}

# What platform logic may know about: the policy numbers and the data model.
# Both move with it.
ALLOWED_ROOTS = ("app.config", "app.models", "app.domain")

# The package itself, as opposed to app.models.booking and friends.
FORBIDDEN_EXACT = {"app", "app.models"}

# The assistant's own layers, named so a failure says what was reached into.
ASSISTANT_LAYERS = (
    "app.tools",
    "app.agent",
    "app.identity",
    "app.kb",
    "app.laqta",
    "app.cli",
    "app.assistant_domain",
)


def module_of(path: Path) -> tuple[str, ...]:
    """('app', 'domain', 'capacity') for app/domain/capacity.py."""
    return path.relative_to(ASSISTANT_DIR).with_suffix("").parts


def app_imports(path: Path, source: str) -> set[str]:
    """Every `app.*` module this file imports, relative imports resolved."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                package = list(module_of(path)[:-1])
                if node.level > 1:
                    package = package[: -(node.level - 1)]
                found.add(".".join(package + ([node.module] if node.module else [])))
            elif node.module:
                found.add(node.module)
    return {name for name in found if name == "app" or name.startswith("app.")}


def is_allowed(module: str) -> bool:
    if module in FORBIDDEN_EXACT:
        return False
    return any(module == root or module.startswith(f"{root}.") for root in ALLOWED_ROOTS)


def test_there_are_domain_files_to_check():
    assert DOMAIN_FILES


def test_domain_holds_only_platform_logic():
    assert {str(path.relative_to(DOMAIN_DIR)) for path in DOMAIN_FILES} == PLATFORM_MODULES


@pytest.mark.parametrize("path", DOMAIN_FILES, ids=lambda p: str(p.relative_to(DOMAIN_DIR)))
def test_domain_imports_only_models_and_config(path: Path):
    for module in sorted(app_imports(path, path.read_text(encoding="utf-8"))):
        assert is_allowed(module), (
            f"{path.relative_to(ASSISTANT_DIR)} imports {module}, which would stop "
            "app/domain/ from moving into the Laqta API as a file copy"
        )


def test_the_models_package_itself_is_off_limits():
    """`from app.models import Booking` works, but ties the domain to this
    repo's __init__, which imports kb_chunks, tickets and the rest."""
    assert not is_allowed("app.models")
    assert is_allowed("app.models.booking")
    for path in DOMAIN_FILES:
        assert "app.models" not in app_imports(path, path.read_text(encoding="utf-8"))


def test_no_domain_file_reaches_into_an_assistant_layer():
    offenders = {
        str(path.relative_to(ASSISTANT_DIR)): sorted(
            module
            for module in app_imports(path, path.read_text(encoding="utf-8"))
            if module.startswith(ASSISTANT_LAYERS)
        )
        for path in DOMAIN_FILES
    }
    assert not {path: found for path, found in offenders.items() if found}


def test_the_check_would_catch_a_violation():
    """A control: an AST walker that silently returns nothing would make
    every test above pass for the wrong reason."""
    source = (
        "from app.tools.registry import ok\n"
        "import app.laqta.mock\n"
        "from app.assistant_domain.confirmation import prepare\n"
        "from app.models import Booking\n"
        "from app.models.booking import Booking\n"
        "from app.config import Policy\n"
        "from .availability import check\n"
    )
    found = app_imports(DOMAIN_DIR / "fake.py", source)

    assert found == {
        "app.tools.registry",
        "app.laqta.mock",
        "app.assistant_domain.confirmation",
        "app.models",
        "app.models.booking",
        "app.config",
        "app.domain.availability",
    }
    assert {module for module in found if not is_allowed(module)} == {
        "app.tools.registry",
        "app.laqta.mock",
        "app.assistant_domain.confirmation",
        "app.models",
    }
