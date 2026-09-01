# Local parameter candidate packages

Place user-supplied `parameter_candidates.json` packages anywhere below this
directory. AureaSim discovers packages recursively and only offers a package
when its recorded baseline SHA-256 matches the active project's baseline.

The package contents are local evidence and are intentionally ignored by Git.
Set `AUREASIM_CANDIDATE_PACKAGES_DIR` to use another directory.
