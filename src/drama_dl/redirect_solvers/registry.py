"""Registry for redirect solvers."""
from __future__ import annotations

from drama_dl.redirect_solvers.base import RedirectSolver

_registry: dict[str, RedirectSolver] = {}


def register_solver(solver: RedirectSolver) -> None:
    """Register a redirect solver instance."""
    for domain in solver.domains:
        _registry[domain] = solver


def get_solver(url: str) -> RedirectSolver | None:
    """Get the appropriate solver for a URL."""
    for domain, solver in _registry.items():
        if domain in url:
            return solver
    return None


def list_solvers() -> list[RedirectSolver]:
    """List all registered solvers."""
    return list(set(_registry.values()))


def clear_registry() -> None:
    """Clear all registered solvers (useful for testing)."""
    _registry.clear()
