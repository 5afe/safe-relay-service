# Releasing `safe-relay-service`

Use this checklist to create a new release of `safe-relay-service` and distribute the Docker image to our private DigitalOcean registry and [DockerHub](https://hub.docker.com/u/joincircles). All steps are intended to be run from the root directory of the repository.

## Creating a new release

1. Make sure you are currently on the `main` branch, otherwise run `git checkout main`.
2. `git pull` to make sure you haven’t missed any last-minute commits. After this point, nothing else is making it into this version.
3. Read the git history since the last release, for example via `git --no-pager log --oneline --no-decorate v4.1.9^..origin/main` (replace `v4.1.9` with the last published version).
4. Condense the list of changes into something user-readable and write it into the `CHANGELOG.md` file with the release date and version, following the specification here on [how to write a changelog](https://keepachangelog.com/en/1.0.0/). Make sure you add references to the regarding PRs and issues.
5. Commit the `CHANGELOG.md` changes you've just made.
6. Create a git based on [semantic versioning](https://semver.org/) using `git tag vX.X.X`.
7. `git push origin main --tags` to push the tag to GitHub.
8. [Create](https://github.com/CirclesUBI/safe-relay-service/releases/new) a new release on GitHub, select the tag you've just pushed under *"Tag version"* and use the same for the *"Release title"*. For *"Describe this release"* copy the same information you've entered in `CHANGELOG.md` for this release. See examples [here](https://github.com/CirclesUBI/safe-relay-service/releases).

## Building and uploading Docker image to registry

All tagged GitHub commits should be uploaded to our private DigitalOcean registry and the public DockerHub registry automatically by the [tagbuild.yaml](https://github.com/CirclesUBI/safe-relay-service/blob/main/.github/workflows/tagbuild.yml) GitHub Action.

After the action was completed successfully you can now use the uploaded Docker image to deploy it.

## Deploy release

### `circles-docker`

For local development we use the [circles-docker](https://github.com/CirclesUBI/circles-docker) repository. To use the new version of `safe-relay-service` please update the following configuration [here](https://github.com/CirclesUBI/circles-docker/blob/main/docker-compose.relayer-pull.yml) and commit the update to the `circles-docker` repository.

Rebuild your environment via `make build` to use the updated version in your local development setup. Consult the `README.md` in the repository to read more about this.

### `circles-iac`

The official `staging` and `production` servers of Circles are maintained via the [circles-iac](https://github.com/CirclesUBI/circles-iac) repository. Both environments have separate version configurations. You will need to change the version for [staging](https://github.com/CirclesUBI/circles-iac/blob/main/helm/circles-infra-suite/values-staging.yaml) and [production](https://github.com/CirclesUBI/circles-iac/blob/main/helm/circles-infra-suite/values-production.yaml) in the regarding `imageTag` fields. Commit the change to the `circles-iac` repository.

Deploy the release via `helm` to the regarding Kubernetes cluster on DigitalOcean. Consult the `README.md` in the repository to read more about how deploy on Kubernetes.
