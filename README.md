# book-translator

Multi-pass literary book translator. EPUB in, translated EPUB out, an LLM doing the work a
professional translator does: macro analysis and style sheet, scene-level drafting, blind
cadence polish, fidelity gate, deterministic QA.

**Status:** design. Decisions are recorded, and no pipeline code exists yet. Start with
[`docs/history.md`](docs/history.md), [`GLOSSARY.md`](GLOSSARY.md) and [`docs/adr/`](docs/adr/).

## Layout

- `docs/history.md`: how the project started
- `docs/research/`: the two research reports behind the design
- `docs/reference/`: condensed external standards (ePubLibre)
- `docs/adr/`, `GLOSSARY.md`: decisions and vocabulary
- `src/book_translator/` — package (Python 3.12, `uv`)

## Installing a release

> No release has been cut yet. Releases start once the release workflow is enabled (it is held
> back in `docs/agents/pending/` until the agent-PR approval step exists).

Releases are cut by release-please: a merged `feat:` or `fix:` commit opens a release PR, and
merging it tags `vX.Y.Z` and creates the GitHub Release. Tags cannot be moved or deleted, and
each new tag is checked automatically (a `release-verify` run on every tag creation).

```
uv tool install git+https://github.com/gczobel/book-translator@vX.Y.Z
```

The expected commit is the **merge commit of the release PR** titled `chore: release X.Y.Z`
on `main`, authored by the maintenance bot from a `release-please--branches--main` branch.
Check that the tag points at it before installing:

```
git ls-remote https://github.com/gczobel/book-translator 'refs/tags/vX.Y.Z*'
gh api repos/gczobel/book-translator/commits/vX.Y.Z/pulls --jq '.[] | [.number, .title, .user.id, .head.ref]'
```

The tag's commit hash is the first line of the first command (for an annotated tag, the line ending
`^{}`); the second should list one pull request, titled `chore: release X.Y.Z`, with user ID
`361970745` and a head branch starting `release-please--branches--`. If a `release-tag-unverified`
issue is open, do not install that tag.

## Installing epubcheck

`book-translator export` validates the result with [epubcheck](https://www.w3.org/publishing/epubcheck/),
which needs Java. From a checkout of this repository, install the pinned release:

```
scripts/install-epubcheck            # installs under ~/.local; pass a PREFIX to choose another
```

It downloads the version in `scripts/epubcheck.pin`, refuses to install unless the sha256 matches,
unpacks it to `PREFIX/share/epubcheck/<version>/` and writes the wrapper `PREFIX/bin/epubcheck`,
which `export` finds on `PATH`. To use a different install, set `EPUBCHECK` to a command or to the
`epubcheck.jar` path. To change the pinned version, edit `scripts/epubcheck.pin` (version and
checksum together); CI can read the same file with `. scripts/epubcheck.pin`.

## Dev

```
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```
