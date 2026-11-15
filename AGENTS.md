# Notes for agents (and people)

This is the one rules file for every agent, Claude Code included. Do not add a `CLAUDE.md` or `CLAUDE.local.md`: Claude Code would read only that file and skip this one, so a test fails if either exists.

Read first:

- [README.md](README.md): what taneko does and how to use it.
- [ARCHITECTURE.md](ARCHITECTURE.md): stages and layers. The tests check the layer rules.
- [ROADMAP.md](ROADMAP.md): the **next-up list** (what to work on, in order) and the decision record. Do not argue a recorded decision again; propose a new one.

## Changes

- Docs and small changes go straight to `main`.
- Code goes to a branch first. Fast-forward `main` to it only when CI is green.
- Open a pull request only for outside contributors, a review by another model, or a release record.
- Commit messages: `area: what changed for the user`. Add `Closes #N` when a commit finishes an issue.
- Code limits are in the ROADMAP decision record: 2,000 lines (hard cap 2,500), 400 per file, 80 per function, and the standard library only, except in `taneko/workers/`.

## Issues

An issue is work we will do and must not forget. Fix things now when you can; record decisions in ROADMAP; keep "maybe some day" ideas out of issues.

**Open an issue** only when it will not be done in this sitting, and it is one of these:

1. A bug a user can hit: wrong output, a crash, a hang, lost data. If it is not verified, label it `question` and say so.
2. Work that needs several steps, or a design choice first.
3. Work put off until something happens. Write the trigger in the issue.
4. A report or request from a user.

**Do not open an issue for:**

| Case | Instead |
|---|---|
| Done now (one commit, under about 30 minutes) | Commit it; explain in the message |
| Typos, wording, formatting, docs out of date | Fix it |
| A decision | ROADMAP decision record (open issues only for the work it causes) |
| An idea with no user and no trigger, or nothing we will do within a month | One line under "之后" in ROADMAP |
| The same problem as an open issue | Comment on that issue |
| A question or a discussion | Talk it through; record the result |
| A security hole | A private GitHub security advisory, never a public issue |
| Business or private matters | Never on GitHub |

**Every issue has** one problem (split anything one branch cannot finish), evidence (`file:line`, command output, or "not verified"), a "done when" check you can run, and one label: `bug`, `enhancement` or `question`.

### Brakes

Issues must not pile up faster than they are fixed.

1. **At most 7 open issues.** To open one, close one first, or move the least important one into ROADMAP "之后" and close it. Only a severe bug (lost data, a crash) may go over the limit, and it goes first in the next-up list.
2. **One order, one place.** The next-up list at the top of ROADMAP gives the order. Issues hold the details, not the order.
3. **Agents report first.** Agents list what they find in the chat; the owner decides what becomes an issue. An agent opens at most 2 issues in one session without asking.
4. **Watch the flow.** Once a week, count issues opened and closed. After two weeks with more opened than closed, the next week only fixes.

Before starting work, spend a few minutes on the list: close what is out of date, and fix the order.
