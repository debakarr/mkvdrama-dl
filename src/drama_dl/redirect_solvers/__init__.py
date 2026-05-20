"""Redirect solvers for shortener URLs.

Modular architecture where each shortener domain has its own solver
that knows how to navigate its specific redirect chain.
"""
from __future__ import annotations

from drama_dl.redirect_solvers.base import RedirectSolver
from drama_dl.redirect_solvers.cutw_solver import CutwSolver
from drama_dl.redirect_solvers.exe_solver import ExeSolver
from drama_dl.redirect_solvers.ouo_solver import OuoSolver
from drama_dl.redirect_solvers.registry import get_solver, list_solvers, register_solver

# Register all solvers
register_solver(ExeSolver())
register_solver(CutwSolver())
register_solver(OuoSolver())

__all__ = [
    "RedirectSolver",
    "CutwSolver",
    "ExeSolver",
    "OuoSolver",
    "get_solver",
    "list_solvers",
    "register_solver",
]
