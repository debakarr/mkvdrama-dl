# Architecture — mkvdrama-dl

## Overview

```
User
  │ mkvdrama search/djl
  ▼
┌──────────────┐    ┌─────────────┐    ┌─────────────────┐
│  cli.py      │───▶│ mkvdrama_   │───▶│  shortener.py   │
│  (Click CLI) │    │ api.py      │    │  (Strategy)     │
│  Facade      │    │ (Facade)    │    │  Chain of Resp. │
└──────────────┘    └─────────────┘    └─────────────────┘
                          │
                          ▼
                    ┌─────────────┐
                    │  downloader │
                    │  .py        │
                    └─────────────┘
```

## Module responsibilities

| Module | Pattern | Role |
|--------|---------|------|
| `cli.py` | **Facade** | Single user-facing entry point. Delegates to API, never contains scraping logic. |
| `mkvdrama_api.py` | **Facade** | Hides all network complexity behind `MkvDramaApi`. Owns the gate/pass flow, HTML parsing, and _c/ link resolution. |
| `shortener.py` | **Strategy + Chain of Resp.** | Resolves ouo.io/filecrypt shorteners. Different resolvers can be swapped at runtime. |
| `downloader.py` | — | Pure functions to format and save episode output. No network I/O. |
| `models/` | **Data Transfer Object** | Pydantic models. No business logic. |

---

## 1. Gate/Pass Authentication (Template Method)

The mkvdrama.net download panel uses a custom anti-scraping protocol. The steps are always the same, making this a **Template Method** pattern:

```
POST /{slug}/_jfsc_je_lou     ───→  { gatePath, passPath, dec_key }
             │
POST {gatePath}                ───→  sets verification cookies
             │
POST {passPath}                ───→  { d, s }  (encrypted payload)
             │
AES-256-GCM decrypt(d, s, key) ───→  HTML with download links
```

**Why AES-256-GCM?** GCM is an *authenticated* encryption mode — it provides both confidentiality and integrity. The key is derived from `SHA-256('access-payload:' + gatePath)`, binding the decryption to the specific gate that was passed. This prevents replaying an encrypted payload from one drama onto another.

**Why Template Method?** The flow is fixed. The *concrete steps* (which slug, what cookie) vary per drama, but the *algorithm skeleton* is reused. Attempting to parallelise or skip steps would break the protocol.

---

## 2. Shortener Resolution (Strategy + Chain of Responsibility)

### Strategy pattern

Different resolution backends are encapsulated in interchangeable strategy classes:

```
ResolverStrategy (Protocol)
│
├── _PlaywrightResolver    — Full browser automation (ouo.io bypass)
├── FlareSolverrResolver   — HTTP API to headless browser service
├── NullResolver           — Pass-through (no-op)
│
└── CompositeResolver      — Chain of Responsibility wrapper
```

**Why Strategy?**
- You can swap resolvers without changing the caller (`resolve_shorteners()`)
- Testing: inject a mock resolver
- `NullResolver` is explicitly a **Null Object** — it avoids `if resolver is not None` checks everywhere

### Chain of Responsibility

The `CompositeResolver` chains strategies in priority order:

```
CompositeResolver
  │
  ├── _PlaywrightResolver    (try first)
  ├── FlareSolverrResolver   (fallback)
  │
  └── returns first success   OR  None
```

**Why Chain of Responsibility?**
- The exact resolution path depends on what's available (Playwright installed?, FlareSolverr configured?)
- New resolvers can be inserted without modifying existing code
- The chain is built at call time: users control priority via CLI flags

### Resolution chain (full picture)

```
_c/ link
  │  (cloudscraper GET → 307 redirect → ouo.io URL)
  ▼
ouo.io URL
  │  (_PlaywrightResolver → countdown → button → redirect)
  │  OR (FlareSolverrResolver → Puppeteer → solution URL)
  ▼
filecrypt.cc/Container/…   OR   direct download link
  │
  ├── extract_filecrypt_links()   (cloudscraper → bs4 → entry table)
  │     │
  │     └── DLC download + dcrypt.it POST → direct links
  │
  └── fallback: manual instructions (Cloudflare JS challenge)
```

---

## 3. CLI Architecture (Facade)

`cli.py` follows the **Click group/subcommand** pattern recommended by the Click authors (v8.3+):

```
mkvdrama                   ← group
├── search <query>         ← subcommand
├── dl <url_or_query>      ← subcommand
│   ├── --episode          ← quality filter (before resolution)
│   ├── --quality          ← resolution filter (before resolution)
│   ├── --resolve          ← enable Playwright resolution
│   ├── --flaresolverr     ← alternative resolution backend
│   └── --output-dir       ← save links to files
└── --verbose / --version  ← shared options
```

**Why filter before resolution?** Episodes and quality are filtered *before* shortener resolution — this minimises the number of URLs that need the slow (10–12 s) Playwright bypass.

**Why no `print()`?** All user-facing output uses `click.echo()` and `click.style()`. This ensures:
- Consistent formatting (no mixed `print`/`echo`)
- Colored error messages via `click.ClickException`
- Proper Unicode handling on Windows terminals
- Testability via `CliRunner`

**Why not Rich/tqdm?** No additional dependency. The `\r` line-overwrite pattern is portable and lightweight for the number of URLs typically resolved (< 50).

---

## 4. Data Models (DTO Pattern)

Pydantic models act as **Data Transfer Objects** — they carry data across module boundaries without business logic:

```
Search (RootModel[list[DramaInfo]])   ← API response wrapper
DramaInfo                              ← search result item
Drama                                  ← full drama metadata + episodes
Episode                                ← single episode + links
DownloadLink                           ← single download URL + metadata
```

**Why `RootModel` for Search?** So that `Search` behaves like a list (`__iter__`, `__getitem__`, `__len__`, `__bool__`) while still being a Pydantic model that can be validated.

**Why empty-string defaults instead of `None`?** Empty strings are falsy and naturally compose with boolean checks. They also avoid the `str | None` type-narrowing dance in template/formatting code.

---

## 5. Error Handling Philosophy

| Layer | Strategy | Example |
|-------|----------|---------|
| **CLI** | `click.ClickException` | Invalid episode range, no search results |
| **API** | Graceful `None` return + `logger.warning` | Gate/pass failure, decryption failure |
| **Network** | `try/except` with explicit exception types | `requests.RequestException`, `json.JSONDecodeError` |
| **Playwright** | `KeyboardInterrupt` handler | Ctrl+C during long resolution |

**Why not propagate exceptions through the CLI?** Network errors (Cloudflare, timeouts, 502s) are expected in this domain, not exceptional. The code degrades gracefully — showing partial results where possible and explaining *why* something failed.

---

## 6. Security Considerations

- **AES-256-GCM** — authenticated encryption prevents tampering with download panel payloads
- **Cloudscraper** — mimics browser TLS fingerprints for Cloudflare JS challenge bypass
- **No API keys stored in code** — `MKVDRAMA_COOKIE` read from env only
- **Playwright in headless mode** — no visible browser window; all temp data cleaned up
- **oii.la is skipped** — multi-page redirect chain is unreliable and could lead to malicious ad pages

---

## 7. Omitted Patterns (and why)

| Pattern | Considered for | Rejected because |
|---------|---------------|------------------|
| **Singleton** | Cloudscraper session | Single instance per command is sufficient; no need to enforce globally |
| **Factory** | Building resolvers | `CompositeResolver.__init__` accepts strategies directly — simple and testable |
| **Decorator** | Adding caching to resolvers | URL resolution is already cheap; caching adds complexity for minimal gain |
| **Command** | Episodes/quality filters | Simple list comprehensions are clearer than command objects for data transforms |

---

## 8. File Inventory

```
src/mkvdrama_downloader/
├── __init__.py           ← version string only
├── cli.py                ← Click CLI (Facade)
├── mkvdrama_api.py       ← mkvdrama.net API client (Facade + Template Method)
├── shortener.py          ← URL resolution (Strategy + Chain of Resp.)
├── downloader.py         ← Output formatting (pure functions)
└── models/
    ├── __init__.py        ← docstring only
    ├── drama.py           ← DownloadLink, Episode, Drama
    └── search.py          ← DramaInfo, Search
```
