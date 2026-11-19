# nice client stats

How fast the [nice-number](https://nicenumbers.net) search client has become since January 2023, build by build.
Every client build is compiled from its own source and timed on the same CPU core, so the charts show the software
getting faster, not the hardware.

**Dashboard: https://wasabipesto-bot.github.io/nice-client-stats/**

## Layout

| path | what |
|---|---|
| `data/commits.csv` | every measured build: repository, commit, date, why it was picked, toolchain, binary size, build time, sha256 |
| `data/runs/*.jsonl.gz` | raw measurement records, one file per measurement run (format: [data/README.md](data/README.md)) |
| `data/validation.csv` | each (build, mode, base) result's verdict against a reference run |
| `site/` | `build.py` turns `data/` into the dashboard in `site/out/` |
| `harness/` | the measurement harness: builds clients, runs them against a mock server, records results ([harness/README.md](harness/README.md)) |

## Building the dashboard

```sh
uv run site/build.py        # writes site/out/index.html and the CSV downloads
```

The GitHub Actions workflow runs the same command on every push to `main` and publishes `site/out/` to GitHub Pages.
Nothing else is needed: the page is rebuilt entirely from `data/`.

## Adding a measurement run

Measuring takes a dedicated machine and several hours to days, so it is done by hand; see
[harness/README.md](harness/README.md). The result is a new `data/runs/<run>.jsonl.gz` plus appended rows in
`data/commits.csv` and `data/validation.csv` (written by `harness/finish_run.py`). Commit those and push; CI
re-renders the dashboard.

## License

MIT. The measured clients are from [wasabipesto/nice](https://github.com/wasabipesto/nice),
[wasabipesto/nice-rust](https://github.com/wasabipesto/nice-rust) and
[wasabipesto/nice-client-py](https://github.com/wasabipesto/nice-client-py).
