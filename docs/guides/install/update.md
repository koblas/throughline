# How to update the plugin

Claude Code compares the plugin's `version` with the installed copy to tell when it is out of date. Each release on [GitHub](https://github.com/koblas/throughline/releases) bumps it.

## 1. Refresh the marketplace

```
/plugin marketplace update throughline
```

## 2. Read what changed

The release notes are in [`CHANGELOG.md`](https://github.com/koblas/throughline/blob/main/CHANGELOG.md). A breaking change is listed under its release; below 1.0 it bumps the minor version.
