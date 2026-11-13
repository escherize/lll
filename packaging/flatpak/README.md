# Flatpak bundles

The Flatpak packages the `lll` command, including its server and browser board.
It does not add a desktop window or application-menu launcher. Its application
ID is `io.github.escherize.lll`.

## Install and run

On a Linux desktop with Flatpak installed, add the runtime source once:

```sh
flatpak remote-add --user --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
```

Download the `.flatpak` bundle matching your machine from the
[GitHub release](https://github.com/escherize/lll/releases): `x86_64` for
Intel/AMD, `aarch64` for ARM64. Install the downloaded file:

```sh
flatpak install --user ./lll-VERSION-x86_64.flatpak
flatpak run io.github.escherize.lll --version
flatpak run io.github.escherize.lll --help
```

The bundle names its runtime source, so installation can also install the
required Freedesktop Platform runtime. The application itself is distributed
through GitHub releases. Flathub's
[submission requirements](https://docs.flathub.org/docs/for-app-authors/requirements)
currently exclude console software; there is no Flathub application listing.

To start a persistent local board without access to your project files:

```sh
flatpak run io.github.escherize.lll new "My board" --no-open
```

Open the private sign-in URL printed in the terminal. Keep that terminal
running while using the board. Running the same command again reopens its
saved data. Browser auto-opening depends on a working desktop portal; the
printed URL also works when a portal is unavailable.

## Project files and credentials

The default sandbox has network access for shared boards and the local server.
It has no general access to host project files or credentials. Configuration
and named-board data are kept in the app's private XDG directories under
`~/.var/app/io.github.escherize.lll/`. Your native installation's saved login
is separate; sign in or accept your board invitation inside the Flatpak.

To work with a repository's `.lll.toml`, explicitly grant that directory and
select it as the working directory (run this from the project root):

```sh
flatpak run --filesystem="$PWD" --cwd="$PWD" io.github.escherize.lll issue list
```

That grant allows reads and writes within the selected directory. It is scoped
to this invocation. Avoid granting your whole home directory just to read one
project's configuration. Linked Git worktrees may also need access to their
main repository; a worktree directory alone does not include its Git metadata.

Host tools such as Git and `gh`, host credential stores and installed coding
agents are not included in the package. Commands that invoke those tools
(including branch and PR helpers) should use the native `lll` installation.
Ordinary board, issue, finding and decision commands use the embedded client.

## Updates

Download and install the newer release's bundle with `flatpak install --user`.
Application data is retained. These bundles do not configure an application
update repository, so `flatpak update` does not fetch newer `lll` releases.
Flatpak can still update the shared runtime.

## Build and verify

On Linux, install `flatpak`, Python 3 and the Freedesktop Platform `25.08`
runtime for the target architecture. No compiler SDK is needed: packaging
copies an already built release binary into the application.

```sh
flatpak remote-add --user --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak install --user flathub org.freedesktop.Platform//25.08
python3 scripts/build_flatpak.py --binary ./lll-linux-amd64 --arch x86_64 \
  --version 1.6.1 --date 2026-11-11 --output ./lll-1.6.1-x86_64.flatpak
flatpak install --user ./lll-1.6.1-x86_64.flatpak
flatpak run io.github.escherize.lll --version
```

Use `--arch aarch64` with `lll-linux-arm64` on ARM64. The packager rejects a
binary for the wrong architecture and refuses to overwrite an existing bundle.
The caller supplies the release date rather than the current build date.

The `Flatpak bundles` GitHub workflow verifies downloaded binaries against
GitHub's published SHA-256 digests, builds and installs each architecture on a
matching Linux runner, checks the installed version and embedded skill, and
validates AppStream metadata before uploading the bundles. Tagged releases
invoke this workflow after publishing the binaries. Its manual `tag` input
can package an existing release without publishing a new CLI version.
