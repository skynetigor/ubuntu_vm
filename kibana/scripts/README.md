# kibana/scripts

Build scripts that take Kibana from source to a compiled distribution. Run them in order: `clone` → `bootstrap` → `compile`.

Each script reads `kibana/.env` automatically and writes a `.{stage}commit` marker to `dist/kibana/` on success. Subsequent runs skip the stage if the cloned repo's HEAD matches the stored commit.

## Scripts

### `clone.sh`
Clones or updates the Kibana source repository.

- **First run:** clones `KIBANA_FORK` at `KIBANA_BRANCH` into `dist/kibana/src/`
- **Subsequent runs:** fetches the branch tip from the remote; skips if already at that commit, pulls if there are new commits
- **Broken clone detection:** if `dist/kibana/src/` exists but is not a valid git repo (interrupted clone), it is deleted and re-cloned

### `bootstrap.sh`
Installs Kibana's dependencies.

- Activates the Node version from `.nvmrc` via NVM
- Runs `yarn kbn bootstrap`
- Pre-populates platform Node binaries required by the build (`darwin-arm64`, `linux-x64`)

### `compile.sh`
Builds the Kibana distribution.

- Activates the Node version from `.nvmrc` via NVM
- Runs `node scripts/build` with flags that skip archives, OS packages, and CDN assets
- Moves the output to `dist/kibana/dist/`
- Updates `NODE_VERSION` in `kibana/.env` so docker-compose can pass it as a build arg

### `setup-root.sh`
Sourced by `bootstrap.sh` and `compile.sh`. When running as root, wraps `yarn` to inject `--allow-root` into all `kbn` subcommands automatically.

### `install.sh`
Local machine dependency checker and installer. Verifies git, curl, python3, NVM, Node, yarn, and Docker are present; installs any that are missing. Safe to run on macOS and Linux.

## Commit caching

Each stage writes its commit hash to a marker file:

| Stage | Marker file |
|---|---|
| clone | `dist/kibana/.clonecommit` |
| bootstrap | `dist/kibana/.bootstrapcommit` |
| compile | `dist/kibana/.compilecommit` |

To force a stage to re-run, delete its marker file.
