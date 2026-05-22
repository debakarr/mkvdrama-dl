"""Solver for cutw.in shortener.

Note: cutw.in redirects to ad landing pages (opera.com, masrawytrend.com,
clixvista.com), never to a real file host.  Skipped immediately — no
Playwright navigation attempted.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from drama_dl.redirect_solvers.base import RedirectSolver

logger = logging.getLogger(__name__)


class CutwSolver(RedirectSolver):
    """Solver for cutw.in shortener URLs.

    These always redirect to ad pages, never to real file hosts.  Returns
    ``None`` without attempting navigation.
    """

    @property
    def name(self) -> str:
        return "cutw.in solver"

    @property
    def domains(self) -> list[str]:
        return ["cutw.in"]

    async def resolve(
        self,
        page,
        url: str,
        status: Callable[[str], None] | None = None,
    ) -> str | None:
        """Resolve cutw.in URL — always returns ``None``.

        No Playwright navigation is attempted because cutw.in redirects
        to ad landing pages (opera.com, masrawytrend.com, clixvista.com),
        never to real file hosts.
        """

        def _status(msg: str) -> None:
            if status:
                status(msg)
            else:
                logger.debug(msg)

        _status("Not supported — redirects to ad landing pages")
        return None
