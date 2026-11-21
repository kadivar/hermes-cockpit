---
name: test-plan
description: Plan a test run as a table of happy, unhappy and edge rows, wait for go, run it into the run folder, and write results the pages can read.
---

# Test plan

You prove the plan on your slot, the way a user would meet the change. A row is one thing a person does and one
thing they should see. You drive the product; you do not prove behaviour by reading code.

## 1. The plan

Read the ticket's plan (`cockpit plan show TASK-100`) and the pull request. Then write one table. Number the rows;
the numbers are how everyone refers to them afterwards.

| # | Kind | Scenario | Setup | Steps | Expected |
|---|---|---|---|---|---|
| 1 | happy | Export a list with rows | A project with three items | Open Exports, choose CSV, Download | A file with a header and three rows |
| 2 | unhappy | Export with an empty name | The same project | Clear the name, Download | The form says the name is required; no file |
| 3 | edge | Export a list with no rows | An empty project | Download | A file with the header only |
| 4 | edge | 👤 The file opens in a spreadsheet program | Row 1's file | Open it on your machine | Columns are split, no stray quotes |

- **happy:** the main path the ticket promised, and each variant the plan names.
- **unhappy:** what a user does wrong, and what the product refuses: missing input, wrong role, a second submit.
- **edge:** the limits: nothing, one, very many, very long, another language, a slow answer, an old record.
- **Setup** names real data to create for this run. Create fresh data; do not reuse another ticket's.
- **Expected** is something you can see or read, not "works".
- A row only a person can do (their own device, a mail that arrives) is marked 👤. It waits for the human's verdict.

Cover each part of the plan's After with at least one row, and each defect the ticket reported with the row that
would have caught it. Ten good rows beat forty thin ones.

Post the plan and wait for go:

```sh
cockpit test plan TASK-100 plan.md
```

Do not run before go when the card is a test kickoff. Do not add rows after go without saying so.

## 2. The run folder

Each run writes into its own folder. Ask for it; do not invent the name:

```sh
cockpit test run-dir TASK-100
```

Put everything of the run there:

- `test-results.md`: the results table (below).
- `test-data.md`: what you created for the run (records, accounts, files), so it can be found and removed.
- `evidence/`: one screenshot per verdict row, named for its row. Videos of failed rows go in `evidence/videos/`.

A second run gets a new folder. An earlier run's folder is never edited.

## 3. Running

1. Do each row's setup, then its steps, in the product, in a browser session of your own.
2. Compare what you see with Expected. Take the screenshot at the moment that shows the verdict.
3. Write the row's result at once. Do not batch verdicts at the end.
4. A row that fails is recorded once: `cockpit test fail TASK-100 3 "the file has no header"`. Then carry on with
   the next row; one failure does not end the run.
5. A row you cannot run (the environment is down, a login is missing) is `Blocked` with the reason. A row you have
   not reached is `Not run`.

Do not mark a row passed that you did not drive. Do not change Expected to match what you saw. Do not fix the
product: a failure is a result.

## 4. The results file

`test-results.md` starts with one of three lines, then the table:

- `Passed` when every row passed.
- `Failed` when a row failed.
- `In progress` while a row is open.

| # | Scenario | Result | Evidence | Note |
|---|---|---|---|---|
| 1 | Export a list with rows | ✅ Pass | `evidence/1-export-rows.png` | |
| 2 | Export with an empty name | ✅ Pass | `evidence/2-empty-name.png` | |
| 3 | Export a list with no rows | ❌ Fail | `evidence/3-no-rows.png` | The file is empty: no header row |
| 4 | 👤 Opens in a spreadsheet program | Not run | | waiting on the human |

- ✅ and ❌ are the marks the pages read. Use them in the Result cell of a row, and nowhere else in a row.
- A verdict row needs its screenshot. A row checked through an API keeps the call it made instead.
- A row another row already proves says `covered by row 1` and needs no screenshot.
- A 👤 row stays open until the human gives its verdict.
- A failed row's note says what was seen and what was expected, in one sentence a developer can act on.

The run is finished when no row is `Not run` or `Blocked` and every verdict has its proof.

## 5. Finish

1. Check the file against the folder: every evidence path exists, every row has a result.
2. Send the results to the ticket as an intent (skill `tracker-notes`). Do not post them yourself.
3. Complete the card with the run folder, the count of passed and failed rows, and each failure in one line.

Do not report a run as green with an open row. Do not delete a failed run's evidence.
