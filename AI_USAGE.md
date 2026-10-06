# AI_USAGE.md  (DRAFT - review, correct and complete the [bracketed] parts before submitting)

## Tools used
- **Claude (Anthropic)** - generated the first version of the code, tests and documentation.
- [Add any other tool you used, or delete this line.]

## What it was used for
Project structure, HTTP client with retry/backoff, scrapers for both sites, cleaning/validation/dedup
logic, a local mock site + pytest suite, README.

## Representative prompts
- [Paste the real prompt you gave, e.g. "Here is my assignment ... build the project."]
- [Add follow-ups you actually sent.]

## AI-assisted parts
Essentially all files were AI-generated as a first draft: `scrapers/*`, `processing/*`, `pipeline.py`,
`main.py`, `config.py`, `models.py`, `tests/*`, `README.md`.
[State which parts YOU then changed or wrote yourself.]

## Issues found in the AI output during review
- Several expected counts in the first version of the integration tests were wrong (the code was right,
  my arithmetic in the test was not): quotes yield 5 collected / 1 rejected / 1 duplicate / 3 final.
  Fixed after a test run showed the mismatch.
- The AI environment could not reach the live websites (blocked), so the scrapers' selectors were written
  from knowledge of the sites' HTML and checked only against a mock. [Record here anything that differed
  when YOU ran against the live sites, e.g. selector fixes, counts.]
- [Add anything else you found.]

## How the solution was tested and verified
- `python -m pytest` -> unit tests (cleaning, validation, dedup, HTTP retry/backoff/robots) and integration
  tests (pagination, relative links, flaky 500 retry, 404 detail pages, duplicates, bad values, one source down,
  flag mode) against a local mock site: 52 passed.
- [Live verification - fill in after you run `python main.py`: e.g. books collected = ?, quotes collected = ?
  (the sites list 1000 books and 100 quotes), spot-checked N records against the website, compared
  summary counts with the CSV row count.]
