# Local Git workflow

The project folder is a local checkout connected to
https://github.com/kraekin/DKR-Workshop.git as `origin`. Local `main` follows
`origin/main`; setup retained the existing GitHub history instead of creating
an unrelated initial commit. GitHub was at `5c487f3` when fetched on 2026-10-30.

Changes and commits stay local until the user explicitly pushes them. Agents
must not push, create remote branches/PRs or publish changes without later
explicit authorization. Fetching downloads remote history and does not upload
local files.

From the project directory, inspect work with:

```powershell
git status
git diff
git log --oneline --decorate -8
git diff origin/main..HEAD --stat
```

Commit selected source changes locally with:

```powershell
git add -- src tests docs
git diff --cached
git commit -m "Describe the completed change"
```

Stage root documentation/configuration explicitly when needed. Review staged
changes before committing. Do not use a hard reset or clean to discard local
ROMs, projects, research or personal assets.

ROMs, `.dkrproj` files, research checkouts, environments/caches, build/dist output,
artifacts, root OBJ/MTL exports and `test tracks/` are ignored. The application
icon is tracked because it is already part of the public release. Ignored files
stay on disk; they are not included in commits.

The setup checkpoint preserves the existing local README, which differs from
the GitHub release README. In particular, the local guide does not contain the
screenshots added on GitHub. Review that documentation difference before a later
push; the original release README remains available in Git history.

When ready, the user can fetch and review ahead/behind status:

```powershell
git fetch origin
git status -sb
git log --oneline origin/main..HEAD
```

If the remote has advanced, reconcile its changes before publishing. The user
can then push explicitly with `git push origin main`. No push is part of setup.

Next creator-workflow scope: improve the existing Add Objects catalog visually,
then add complete object artwork export. Favorites, presets and reusable groups
are excluded.
