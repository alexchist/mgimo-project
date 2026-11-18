# Third-party notices

No third-party source code is vendored into the Strategist core.

- Ouroboros by Anton Razzhigaev (MIT; [source and licence at the inspected revision](https://github.com/razzant/ouroboros/blob/4be731ffcd2990acff55fb746b0daa073c22d5af/LICENSE)) informed the project constitution, decision loop, separation of memory from evidence, meeting agenda and advisory review. The Strategist instructions are independently worded for product decisions; the original Ouroboros prompts and runtime are not bundled. See the [design mapping and source texts](docs/architecture.md#что-взято-из-ouroboros).

- GitHub Spec Kit (`github/spec-kit`, commit `e210504aa09c9273a38bba665b12b8088468c96f`) was inspected under the MIT License for a documented process comparison. Its command files are not redistributed here.
- `pdftotext` from Poppler is invoked as an external executable when available and is not bundled.
- Python is required from the user's environment; no Python packages are vendored.
- External research pages retain their respective rights. Research notes contain links and limited paraphrase, not copies of books.
- The demo includes an archived GOV.UK Service Manual page, [Measuring completion rate](https://www.gov.uk/service-manual/measuring-success/measuring-completion-rate), retrieved 17 November 2026, and its text extraction (`examples/demo/sources/`, S-006). © Crown copyright. **Contains public sector information licensed under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).** The publication copy removes the response-specific CSRF meta token; the source index records that transformation and both hashes. No official endorsement is implied; the licence's exceptions remain applicable.
- `examples/web-smoke/` includes the example.com demonstration page and extraction as an HTTP-import test, not as product-market evidence. All other case documents and interviews are explicitly synthetic.

The project owner has not yet selected a license for the original Strategist core. See `docs/research/contest-and-legal.md` before distribution or contest submission.

