---
sidebar_position: 2
---

# Viewing 3D (PotPlayer / Bino / VLC)

StereoSpot can open 3D video in an external player for the best anaglyph experience. This page explains the **"Open in 3D player"** flow and how to get the most out of your glasses.

## How it works

When you click **"Open in 3D player"** (on the dashboard, job list, or job detail page), you are taken to a launch page. The site then tries to open your player automatically via a custom link (`pot3d://...`). If that does not work, the launch page shows OS-specific options: download the **3D Linker** setup (Windows) or download the **playlist (M3U)** and open it in Bino or VLC (macOS/Linux).

- The link points to an **M3U playlist** (one video or all your completed videos). The player fetches the playlist and then streams the video from StereoSpot.
- No long URLs are sent to the player—only the playlist URL—so everything works even with long-lived presigned links.

## Windows (PotPlayer)

1. **Install PotPlayer** from the official site if you have not already.
2. **Install the 3D Linker once:** On the launch page, if the player did not open automatically, click **"Download 3D Linker (EXE)"**. Run the installer; it registers the `pot3d://` protocol and configures PotPlayer to open with anaglyph (Dubois) mode.
3. **Use "Open in 3D player"** from the dashboard or any job. The browser will ask to open the application; confirm, and PotPlayer will start with the correct 3D settings.

If the player still does not open, allow the browser to open the application when prompted, or run the 3D Linker installer again.

## macOS / Linux (Bino or VLC)

PotPlayer is not available on these platforms. Use **Bino 3D** or **VLC** instead:

1. **Install** [Bino 3D](https://bino3d.org/) or VLC.
2. On the launch page, click **"Download playlist (M3U)"**.
3. **Open the downloaded file** in Bino or VLC. The player will stream the video from StereoSpot.

## Tips for better 3D

- **Dark room:** Anaglyph glasses work best with minimal ambient light to avoid reflections and ghosting.
- **Dubois mode:** PotPlayer and Bino support the Dubois anaglyph method, which reduces ghosting. The 3D Linker and launch flow use it by default where possible.
- **Inverted depth:** If the 3D effect looks inside-out, swap left/right: in PotPlayer use **Alt+F1**; in Bino use the option to swap eyes.
- **Ghosting or color fringing:** Slightly reduce saturation or adjust hue in the player (e.g. Q/W in PotPlayer). Clean the glasses and avoid bright light behind the screen.
- **Comfort:** Do not set parallax too high; if your eyes strain, reduce depth in the player settings.

## Troubleshooting

| Issue | What to try |
|-------|-------------|
| "Open in 3D player" does nothing | Install the 3D Linker (Windows) or download the M3U and open it in Bino/VLC. Allow the browser to open the application when prompted. |
| Player opens but no video | Check your internet connection; the playlist points to streams that require network access. |
| Video is flat / no 3D | Enable 3D / anaglyph mode in the player (e.g. PotPlayer: Video → 3D mode → Anaglyph). |
| Playlist expires | Links in the playlist are valid for several hours. If they expire, open the launch page again to get a fresh playlist. |
