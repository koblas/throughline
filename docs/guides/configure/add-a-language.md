# How to add a language

`go` and `ts` are built in. For any other language, the repo supplies an adapter: a command that answers the plugin's adapter protocol.

## 1. Write the adapter

The adapter is called as `<adapter…> <op>` from the repo root, with one JSON object on stdin and one on stdout. It must answer `describe`; `coverage` and `absence` are optional. [A language adapter](../../examples/language-adapter.md) is a complete Python one to start from.

## 2. Name it on the surface

Set `language` to the language's name and `adapter` to the command:

```json
"language": "python",
"adapter": ["python3", ".claude/scripts/py-adapter.py"]
```

`adapter` is refused on a `go` or `ts` surface, and required on any other.

## 3. Write the phase steps

Give the surface `phase` steps that lint and test it. A step may use `{files}` (the surface's changed files) and `{report}` (a scratch directory the test step writes and the adapter's `coverage` reads). Add `test_one`, taking `{file}` and `{name}`, so a scenario's acceptance test can run alone.

## 4. Name the reviewers

The plugin's `test-reviewer` reviews Go tests. Name the repo's own correctness and test reviewers for the surface: [How to add a reviewer](add-a-reviewer.md).

## 5. Check it

Run the phase on the surface by name:

```bash
scripts/check.py phase --surface py
```

An operation the adapter does not offer prints `skipped`. An adapter that fails fails the phase.
