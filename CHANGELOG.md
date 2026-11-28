# Changelog

## [0.6.0](https://github.com/koblas/throughline/compare/v0.5.0...v0.6.0) (2026-11-28)


### Features

* **diff-coverage:** judge TypeScript from the command line ([e4ec3aa](https://github.com/koblas/throughline/commit/e4ec3aa78f245eb903a7cd3c9583dc2464827487))
* **diff-coverage:** judge TypeScript from the command line ([548703b](https://github.com/koblas/throughline/commit/548703b969f6eaeb68dd798730318ab14cc36575)), closes [#31](https://github.com/koblas/throughline/issues/31)
* **pipeline:** write issue bodies as headed sections, not 500-char lines ([a9df522](https://github.com/koblas/throughline/commit/a9df5222e03e5f8958c284e9696984466e2703f4))
* **pipeline:** write issue bodies as headed sections, not 500-char lines ([1c15685](https://github.com/koblas/throughline/commit/1c156856e193b022af0a32b6a4d510ecb4e831de))

## [0.5.0](https://github.com/koblas/throughline/compare/v0.4.0...v0.5.0) (2026-11-27)


### ⚠ BREAKING CHANGES

* **check:** move checks.reason_parity and checks.error_allowlist into the repo as scripts run from a surface's `phase` list, with `{base}` and `{to}`, and delete the `checks` keys from .claude/pipeline.json.
* **pipeline:** a repo whose reviewers or architect relied on the built-in lists (storage.md, navigation.md, proof.md for correctness) must add a briefs map to .claude/pipeline.json.

### Features

* **check:** run a repo's own diff checks as phase steps ([1b66f2d](https://github.com/koblas/throughline/commit/1b66f2d138937ae3b17600bcddfb610ec67cb2cf))
* **metrics:** log check wall-clock and compare each feature with the pre-rollout baseline ([eac3a28](https://github.com/koblas/throughline/commit/eac3a28583cd6381aa0111f475f0edee2a77d1f9))
* **metrics:** log check wall-clock and compare each feature with the pre-rollout baseline ([8dd386e](https://github.com/koblas/throughline/commit/8dd386e7d1cf38303d13241260153bc95a8ca7f2))
* **new-repo:** start a repo brief, and say at session start when one is missing ([c54283d](https://github.com/koblas/throughline/commit/c54283dbaf9f333ed5f358ddf0fed0aa104399a6))
* **pipeline:** a feature that edits its own language adapter stops for a person ([7b12a57](https://github.com/koblas/throughline/commit/7b12a5739f7488c5d45f28146d02fb406c6eba6c))
* **pipeline:** adapter surfaces in the gate, spec-check and the end-to-end test ([17b1ba7](https://github.com/koblas/throughline/commit/17b1ba7cf43f598fc26ff68e7a8a0a326864dd45))
* **pipeline:** keep found work durable and stop on spec/GitHub disagreement ([5ba6e5b](https://github.com/koblas/throughline/commit/5ba6e5b2f22d70be1e02e60ccc80f710378ec993))
* **pipeline:** keep issue drafts outside the worktree ([3294678](https://github.com/koblas/throughline/commit/3294678cff16eef9a387c8ad2ef0ca036af9a90e))
* **pipeline:** language adapters for languages the plugin does not ship ([c695986](https://github.com/koblas/throughline/commit/c695986149039fab650a8e981b6e38586604a5fa))
* **pipeline:** language adapters for repo-supplied languages in config, phase and next ([95e3f66](https://github.com/koblas/throughline/commit/95e3f6609231ff9d38b03abef0677c8b7c75abcc))
* **pipeline:** name each agent's extra briefs in the repo config ([cf26a3b](https://github.com/koblas/throughline/commit/cf26a3ba5d9450f34b3d9e8cb714aad29178dcbd))
* **pipeline:** spell out the debt command, drop declined drafts, record folds ([6afc5dc](https://github.com/koblas/throughline/commit/6afc5dc9666cf8085ebfbd0580f0e63dd15680ca))
* **pipeline:** stop when GitHub closed a scenario the spec says is unbuilt ([0ea5bc2](https://github.com/koblas/throughline/commit/0ea5bc26222ee3b65709f81ecdbafd7680477ec1))
* **runner:** file a finished feature's issue drafts when the repo allows it ([891d25c](https://github.com/koblas/throughline/commit/891d25c8d093f03ff8b7624a9b28db88b9920d34))
* **session-context:** list unfiled issue drafts at session start ([bb454ae](https://github.com/koblas/throughline/commit/bb454aece3c6c8f493fc77eb9aafd273d621fc3d))


### Performance

* **tests:** run the suite in parallel and skip the needless mutation repair ([96312d4](https://github.com/koblas/throughline/commit/96312d4e4755a97cd37b0116118a7d3eaa263743))
* **tests:** run the suite in parallel and skip the needless mutation repair ([84d9799](https://github.com/koblas/throughline/commit/84d9799437e72874de456c0cd058f3b3834ca11d))

## [0.4.0](https://github.com/koblas/throughline/compare/v0.3.0...v0.4.0) (2026-11-27)


### Features

* **config:** gate keys optional in single-session mode ([52d7d62](https://github.com/koblas/throughline/commit/52d7d622eeefaa840e1cd2c6b7f83355dad5d5d8))
* **config:** gate keys optional in single-session mode ([45faec5](https://github.com/koblas/throughline/commit/45faec56a66f6e4a11de0c28204cd5d3f1354fbe))
* **coverage:** add TS diff coverage and phase checks run by next ([181b01b](https://github.com/koblas/throughline/commit/181b01b3623aebc9d4c08e028a3239c183657cb8))
* **coverage:** TS diff coverage and phase checks run by next ([d4c4590](https://github.com/koblas/throughline/commit/d4c4590d1fbe57a42eb204f6761911b8c9149648))
* **gate:** blockers and majors only, every finding listed, post-review, screen check ([468b670](https://github.com/koblas/throughline/commit/468b6705ab5e50c7884e8d3c5d08d4bf8014874e))
* **gate:** blockers and majors only, every finding listed, post-review, screen check ([916be79](https://github.com/koblas/throughline/commit/916be7925c676d86ef8d24f4ec48717016d9bfab))
* **new-repo:** add CI checks, .env denials, docs/specs and branch protection ([54a830e](https://github.com/koblas/throughline/commit/54a830ebddcc49483b6dc245a316591b032e4971))
* **new-repo:** CI checks, .env denials, docs/specs and branch protection ([dd2bd3a](https://github.com/koblas/throughline/commit/dd2bd3ae807e596480540953b7cff7bed1b2bd40))
* **not-built:** check marks after next closes an issue and on product-spec edits ([8025a99](https://github.com/koblas/throughline/commit/8025a9991c06c8ad0a866d4005998c7e30769d20))
* **not-built:** check marks after next closes an issue and on product-spec edits ([92e2295](https://github.com/koblas/throughline/commit/92e229519490927d0d1a6aa47c2233e010a98578))
* **pipeline:** lane labels, claim, Found in, PR closes issues, idea adoption, process review ([0518853](https://github.com/koblas/throughline/commit/0518853050cf2d18a817ca9744c34ffa8f49922a))
* **pipeline:** lane labels, claim, Found in, PR closes issues, idea adoption, process review ([9aac25d](https://github.com/koblas/throughline/commit/9aac25db62defe30948e66ca2ed32afa45d9bac7))
* **spec-check:** check cited symbols and require a recorded approval ([f36b259](https://github.com/koblas/throughline/commit/f36b2592e2edf8d3f1746bcef6022309bf10e057))
* **spec-check:** check cited symbols and require a recorded approval ([c883ae0](https://github.com/koblas/throughline/commit/c883ae0ab5a3d229f212e28270c39d27258ad387))


### Bug Fixes

* **check:** fail coverage when the test step writes no profile ([6eefd32](https://github.com/koblas/throughline/commit/6eefd3208386223fe7ecc7df2dad04c1046d586c))
* **check:** fail coverage when the test step writes no profile ([9777a35](https://github.com/koblas/throughline/commit/9777a3527a1aa221c0993939cd1f8423407d6149))
* **pipeline:** draft found debt as an issue, not a STATE.md line ([3e812e9](https://github.com/koblas/throughline/commit/3e812e99f96d088a749373d30258dff0a8a90515))
* **pipeline:** draft found debt as an issue, not a STATE.md line ([40258bc](https://github.com/koblas/throughline/commit/40258bc3aa4e7869c3ae2f7b4e23c9fd08aeb2a4))

## [0.3.0](https://github.com/koblas/throughline/compare/v0.2.0...v0.3.0) (2026-11-27)


### Features

* **pipeline:** single-session mode, /pipeline:retro and a Why line on issues ([a8ea23e](https://github.com/koblas/throughline/commit/a8ea23e81487e867acc1c5f4c026ceb5083e3454))
* **pipeline:** single-session mode, /pipeline:retro and a Why line on issues ([b6382bb](https://github.com/koblas/throughline/commit/b6382bbaeff20e25b388133e40425c787a32a5fd))

## [0.2.0](https://github.com/koblas/throughline/compare/v0.1.0...v0.2.0) (2026-11-26)


### Features

* **new-repo:** bootstrap a new repository's baseline ([40cb782](https://github.com/koblas/throughline/commit/40cb78205ff33235bb2a2456dad94a2dffe4f46b))
* **new-repo:** bootstrap a new repository's baseline ([a15887e](https://github.com/koblas/throughline/commit/a15887e1f1ad987521d241be97e2953c4c98a646))

## 0.1.0 (2026-11-26)


### Features

* move the pipeline plugin from content_buddy ([a31d7b2](https://github.com/koblas/throughline/commit/a31d7b2070a392f304838751358930c17c69114a))
