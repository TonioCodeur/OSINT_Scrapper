# Third-party licences

**OSINT_scrapper's own source code is licensed under the MIT License.** That covers everything under
`src/`, `tests/` and `docs/` in this repository.

It depends on third-party components with their own licences. This file lists them, and states — as
concretely as it can, without pretending to be legal advice — what obligations they place on you.

Every licence below was checked against the package's own published metadata on **2026-07-27**. Version
numbers are the ones current on that date; the versions this repository actually resolves are recorded in
the committed `uv.lock`, which is the authority. If you upgrade a dependency across a major version,
re-check its licence rather than assuming this file is still accurate.

---

## The short version

If you **use** this application — run it, crawl with it, export from it — you have nothing to do. Every
component here permits that freely.

If you **redistribute** it — ship it to colleagues, publish a build, bundle it into a product — one
component imposes real obligations: **Qt, via PySide6, under the LGPLv3.** Section 2 explains exactly what
they are and, just as importantly, what they are not.

---

## 1. Runtime dependencies

### Direct

| Package | Licence | Notes |
|---|---|---|
| **PySide6** 6.11.1 | `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`, or a commercial licence from the Qt Company | **This project uses it under the LGPLv3.** See §2 |
| **requests** 2.34.2 | Apache License 2.0 | |
| **beautifulsoup4** 4.15.0 | MIT | |
| **phonenumbers** 9.0.35 | Apache License 2.0 | Python port of Google's libphonenumber |
| **email-validator** 2.3.0 | The Unlicense (public domain dedication) | |
| **openpyxl** 3.1.5 | MIT | |

### Transitive

Pulled in automatically by the packages above. Listed because a redistributed build contains them.

| Package | Licence | Pulled in by |
|---|---|---|
| **PySide6-Essentials** 6.11.1 | `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`, or a commercial licence from the Qt Company | `PySide6` — **this is the wheel that contains the Qt Essentials shared libraries** (`QtCore`, `QtGui`, `QtWidgets`). It is the artifact §2 is about |
| **PySide6-Addons** 6.11.1 | `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`, or a commercial licence from the Qt Company | `PySide6` — installed unconditionally with the meta-package. This project imports **no** add-on module (§3.1 obligation 4), but the libraries are present in an installed tree and are therefore listed |
| **shiboken6** 6.11.1 | `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` | `PySide6` — the binding runtime; same terms, same choice |
| **urllib3** 2.7.0 | MIT | `requests` |
| **certifi** 2026.7.22 | **MPL-2.0** | `requests` |
| **charset-normalizer** 3.4.9 | MIT | `requests` |
| **idna** 3.18 | BSD-3-Clause | `requests`, `email-validator` |
| **soupsieve** 2.9.1 | MIT | `beautifulsoup4` |
| **dnspython** 2.8.0 | ISC | `email-validator` |
| **et-xmlfile** | MIT | `openpyxl` |

**A note on `certifi`.** It is Mozilla Public License 2.0, not MIT — the only permissive-but-weak-copyleft
component in the tree. MPL-2.0 is file-level copyleft: if you *modify* certifi's own files you must publish
those files under the MPL. Using it unmodified, which is what happens here, carries no obligation beyond
retaining its notice.

**A note on `email-validator`.** The Unlicense is a public-domain dedication and imposes nothing at all.
It is listed for completeness, not because it asks anything of you.

## 2. Qt and PySide6 — the LGPLv3, precisely

PySide6 and shiboken6 are published by the Qt Company under a choice of licences:
`LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`, plus a separate commercial licence.

**This project makes that choice explicitly: it uses PySide6, shiboken6 and the Qt libraries they ship
under the LGPL version 3.** The GPL options are available but not taken; taking one would relicense this
MIT-licensed application, which is precisely the outcome the choice of binding was made to avoid (§4).

### What the LGPLv3 asks of you when you redistribute

Verified against the Qt Company's published LGPL obligations, 2026-07-27. Paraphrased for this project's
specific situation; the licence text itself governs.

1. **Keep Qt dynamically linked.** The LGPLv3 lets you keep your own application's code under your own
   terms precisely because Qt is a separate, replaceable library. A normal `pip install` produces exactly
   that: Qt arrives as shared libraries inside the `PySide6` package, loaded at runtime. Nothing in this
   repository vendors, statically links or rewrites them.
2. **Let your users replace it.** They must be able to swap in their own build of Qt and run your
   application against it. Again, a normal Python installation satisfies this by construction — the
   libraries are files on disk in a directory the user controls.
3. **Provide the licence text, and say that Qt is used.** The application's **Help → About** dialog states
   that it uses Qt through PySide6 under the LGPLv3 and links to this file. If you redistribute, carry
   both forward.
4. **Provide the corresponding source of the library**, including any modifications you make to it. This
   project makes none. If you patch Qt or PySide6, you must publish those patched sources under the LGPL.
5. **Do not restrict these freedoms downstream.** You cannot add terms that take them away from whoever
   you hand the application to.

### What the LGPLv3 does *not* ask of you

Worth stating plainly, because LGPL obligations are routinely overstated:

- **It does not make your own code GPL, or LGPL, or anything.** This application stays MIT. So would your
  own additions, under whatever licence you pick. That asymmetry is the entire reason the LGPL exists and
  the entire reason PySide6 was chosen over PyQt6.
- **It does not require you to publish your application's source.** Only the *library's* source, and only
  the corresponding version of it — which for an unmodified pip-installed Qt means pointing at the
  upstream release.
- **It does not restrict what you use the application for**, commercially or otherwise.

### The one thing to be careful about: frozen binaries

**Bundling this application into a single-file executable — PyInstaller with `--onefile`, Nuitka in
standalone mode, or anything else that statically links or fuses Qt into one artifact — is a
licence-relevant change.** Under the LGPLv3 you would then owe your users the *installation information*
needed to relink the application against a modified Qt, which is a meaningfully harder obligation than
"ship the libraries next to the executable".

The project's own specification (`docs/SPEC.md` §3.1) treats packaging as a decision that must come back
to that section before being made. If you are about to freeze a build, read the LGPLv3 first, and prefer a
one-directory layout where the Qt shared libraries remain separate, replaceable files.

### Qt modules used

`QtCore`, `QtGui` and `QtWidgets` — Qt Essentials, all under the LGPLv3 in the open-source offering. No
add-on modules are used. **Not every Qt module carries the same terms**, so if you extend this application
with one, check that module's licence before you do.

## 3. Development-only dependencies

These are installed by `uv sync --extra dev` (or `pip install -e ".[dev]"`). They are build and test tools
and are **not** part of a redistributed application, so they carry no distribution obligation.

| Package | Licence |
|---|---|
| **pytest** | MIT |
| **pytest-qt** 4.5.0 | MIT |
| **ruff** | MIT |
| **mypy** | MIT |

## 4. Why PySide6 and not PyQt6

Recorded here because it is a licensing decision, not a technical one, and anyone auditing this file will
want the reasoning rather than the conclusion.

Both are healthy, actively released Qt 6 bindings with Windows wheels for `win_amd64` and `win_arm64`
(verified 2026-07-27: PySide6 6.11.1 released 2026-05-13; PyQt6 6.11.0 released 2026-03-30). They are
close enough technically that the choice turned entirely on licensing.

**PyQt6 is not available under the LGPL.** Riverbank Computing state it directly: *"PyQt is dual licensed
on all supported platforms under the GNU GPL v3 and the Riverbank Commercial License"*, and *"Unlike Qt,
PyQt is not available under the LGPL."* Linking an MIT-licensed application against PyQt6 under the GPLv3
would relicense the distributed work as GPLv3 — changing what this repository is — and the alternative is
buying a commercial licence, which is not a cost a small tool should carry.

**PySide6 offers the LGPLv3**, which permits an MIT application to use dynamically linked Qt. That settled
it. The secondary benefits — it is the Qt Company's own binding, it tracks Qt's release schedule, it ships
`.pyi` type stubs and maintains a documented mypy-correctness effort — made the choice comfortable rather
than merely acceptable.

## 5. Data and specifications referenced

Not dependencies, but this project implements behaviour defined by public specifications, and both its
documentation and its test fixtures paraphrase them. Cited for accuracy, not because they impose terms:

- **RFC 9309** — Robots Exclusion Protocol. The `robots.txt` decision table follows it, with one
  deliberate, documented divergence on ambiguous outcomes (see the README).
- **RFC 9116** — `security.txt`. Field names and the parser's size limits are taken from it directly.
- **The Sitemaps protocol** (sitemaps.org) — element names and limits. This project applies stricter
  limits than the protocol permits.
- **RFC 4180** — CSV. The CSV exports follow it, with a UTF-8 BOM added so that Excel reads accented
  values correctly.

## 6. Obtaining licence texts

Full licence texts are distributed inside each installed package. After `uv sync` or `pip install`, look
in your environment's `site-packages` directory: most packages ship a `LICENSE`, `LICENSE.txt` or
`licenses/` file, and PySide6 ships the LGPLv3 and GPL texts alongside the Qt libraries themselves.

Canonical copies:

| Licence | Text |
|---|---|
| MIT | <https://opensource.org/license/mit> |
| Apache License 2.0 | <https://www.apache.org/licenses/LICENSE-2.0> |
| BSD-3-Clause | <https://opensource.org/license/bsd-3-clause> |
| ISC | <https://opensource.org/license/isc-license-txt> |
| MPL-2.0 | <https://www.mozilla.org/MPL/2.0/> |
| The Unlicense | <https://unlicense.org/> |
| LGPL-3.0 | <https://www.gnu.org/licenses/lgpl-3.0.html> |
| GPL-3.0 | <https://www.gnu.org/licenses/gpl-3.0.html> |

---

*This file is a good-faith summary written to be useful and accurate. It is not legal advice. If you are
redistributing this application commercially, or freezing it into a binary, read the LGPLv3 yourself or
ask someone qualified.*
