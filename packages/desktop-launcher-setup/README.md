# desktop-launcher-setup

Builds the **3D Linker for PotPlayer** Windows setup EXE. The installer registers the `pot3d://` URL protocol so that links from the Stereo-Spot web UI open in PotPlayer with the correct 3D (anaglyph Dubois) settings.

## What it does

- Registers `pot3d://` in the Windows registry.
- When the user clicks "Open in 3D player" on the site, the browser sends a URL like `pot3d://your-domain.com/playlist/abc.m3u`.
- The handler runs PowerShell to replace `pot3d://` with `https://` and launches PotPlayer with that M3U URL and `/3dmode anaglyph_red_cyan_dubois`.

## Build

From the repo root:

```bash
nx run desktop-launcher-setup:build
```

Requires Docker. The artifact is written to `packages/desktop-launcher-setup/dist/3d_setup.exe`. The web-ui Docker build depends on this target and copies the EXE into the app image so it can be served at `/setup/windows`.

## References

- [amake/innosetup](https://hub.docker.com/r/amake/innosetup) – Inno Setup in Docker (Wine) for building Windows installers on Linux.
