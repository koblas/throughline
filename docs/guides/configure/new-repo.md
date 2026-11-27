# How to start a new repo

`/pipeline:new-repo` writes the baseline a new repo starts from. It shows every file and label before writing, and never replaces an existing file without asking.

## 1. Run the command in the new repo

```
/pipeline:new-repo
```

Pass `product` or `infrastructure` to skip the first question.

## 2. Pick the kind of repo

| Kind | Gets |
|---|---|
| Both | The plugin enabled in `.claude/settings.json`, `.env` reads denied, a short `CLAUDE.md`, `SECURITY.md`, a CI workflow running the repo's verify commands, the labels in `plugins/pipeline/labels.json`, branch protection and the Project link |
| Product | Also `.claude/pipeline.json` (its surfaces, which the command asks for), `docs/product/`, `docs/specs/` and a `.claude/briefs/repo.md` skeleton |
| Infrastructure | No `.claude/pipeline.json`: the repo runs the Direct lane only, with issues for debt |

## 3. Review and confirm

Read each file and label the command lists, then confirm. For a product repo, finish the surfaces with [How to configure a repo](configure-a-repo.md).
