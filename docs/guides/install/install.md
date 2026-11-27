# How to install the plugin

Install `pipeline` from the `throughline` marketplace, either for yourself or for everyone who works in a repo.

=== "For yourself"

    In Claude Code:

    ```
    /plugin marketplace add koblas/throughline
    /plugin install pipeline@throughline
    ```

=== "For a repo"

    Add the marketplace and enable the plugin in the repo's `.claude/settings.json`:

    ```json
    {
      "extraKnownMarketplaces": {
        "throughline": { "source": { "source": "github", "repo": "koblas/throughline" } }
      },
      "enabledPlugins": { "pipeline@throughline": true }
    }
    ```

## Next

The pipeline does nothing in a repo until the repo describes its surfaces: [How to configure a repo](../configure/configure-a-repo.md), or [How to start a new repo](../configure/new-repo.md) for one with nothing in it yet.
