"""Solver for exe.io → exeygo.com redirect chain.

Note: exe.io/exeygo.com uses Cloudflare Turnstile after the first click,
which means these links cannot be resolved automatically.  Skipped
immediately — no Playwright navigation attempted.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from drama_dl.redirect_solvers.base import RedirectSolver

logger = logging.getLogger(__name__)


class ExeSolver(RedirectSolver):
    """Solver for exe.io and exeygo.com shortener URLs.

    These URLs require solving a Cloudflare Turnstile captcha after the
    first click, making them unresolvable automatically.  Returns ``None``
    without attempting navigation.
    """

    @property
    def name(self) -> str:
        return "exe.io/exeygo.com solver"

    @property
    def domains(self) -> list[str]:
        return ["exe.io", "exeygo.com"]

    async def resolve(
        self,
        page,
        url: str,
        status: Callable[[str], None] | None = None,
    ) -> str | None:
        """Resolve exe.io/exeygo.com URL — always returns ``None``.

        No Playwright navigation is attempted because these links require
        Turnstile captcha which cannot be solved automatically.
        """

        def _status(msg: str) -> None:
            if status:
                status(msg)
            else:
                logger.debug(msg)

        _status("Not supported — requires Cloudflare Turnstile captcha")
        return None
