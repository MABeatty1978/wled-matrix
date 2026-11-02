# WLED Matrix

Custom firmware effects and Home Assistant automations for an 8x32 WLED matrix on an ESP8266 (NodeMCU).

- **Tempest Weather:** animated weather icon plus cycling temperature, high/low, wind and humidity pages from a Tempest weather station.
- **Scoreboard:** home logo on the left, away logo on the right, scores in the middle, fed by the [Team Tracker](https://github.com/vasqued2/ha-teamtracker) integration. Shown from 1 hour before a game until 1 hour after it ends, then the weather display returns.

## Layout

| Path | What it is |
| --- | --- |
| `firmware/matrix_fx/` | WLED usermod with both effects |
| `firmware/platformio_override.ini` | Build settings; points WLED at the usermod |
| `firmware/wled-tweaks.patch` | Small edits to WLED itself: version label 16.0.1, development banner hidden |
| `home-assistant/wled_matrix.yaml` | Home Assistant package for the weather display and scoreboard |
| `scoreboard/make_logo_pack.py` | Builds 8x8 team logo packs and uploads them to WLED |
| `scoreboard/overrides/` | Hand-drawn 8x8 logos that replace the automatic ones |

## Building the firmware

Built against WLED `main` at commit `fce41f2`. Keep this repo next to the WLED clone:

```
<folder>/WLED-src      WLED clone
<folder>/wled-matrix   this repo
```

```sh
git clone https://github.com/wled/WLED.git WLED-src
cd WLED-src
git checkout fce41f2
git apply ../wled-matrix/firmware/wled-tweaks.patch
cp ../wled-matrix/firmware/platformio_override.ini .
npm install
pio run -e nodemcuv2_weather
```

The firmware is written to `build_output/release/WLED_16.0.1_ESP8266.bin`. Flash it from WLED's web page (Config > Security & Updates > Manual OTA update).

Installing a WLED update offered by Home Assistant or the WLED app replaces this firmware and removes both effects.

## Logo packs

Requires `pip install pillow numpy`.

```sh
cd scoreboard
python make_logo_pack.py nfl nba mlb ncaaf ahl --upload 192.168.87.80
```

League codes match Team Tracker's `league` attribute, lower-cased. `ncaaf` is trimmed to Division 1 (FBS + FCS). AHL teams and logos come from HockeyTech, using the public key bundled with Team Tracker; HockeyTech lists no team colors, so those are taken from each logo. Each run writes `packs/sb_<league>.bin` and a `packs/preview_<league>.png` sheet to review.

To replace a logo that doesn't read well at 8x8, draw an 8x8 PNG (black or transparent = off), save it as `overrides/<league>/<ABBR>.png`, and run the tool again.

A team missing from its league's pack shows the first two letters of its abbreviation in place of a logo.

## Home Assistant

Everything Home Assistant needs is in one package, `home-assistant/wled_matrix.yaml`: the weather display, the
scoreboard, the `rest_command` that drives the matrix, and sensors that look up the Tempest Weather and Scoreboard
effect IDs by name. Copy it to `/config/packages/`, with this in `configuration.yaml`:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Then, in `wled_matrix.yaml`:

1. Replace the Tempest and weather entity IDs with yours (listed at the top of the file).
2. List your Team Tracker sensors in the `WLED Scoreboard` sensor, highest priority first.

**Keep it to this one file.** Don't recreate any of these automations or scripts in the Home Assistant UI or
`automations.yaml`; this file is the only copy. Automations from a package show as read-only in the UI, so edit the
file, commit it, and copy it to `/config/packages/` again.

### Weather display

Every 2 minutes, and whenever the weather changes, the package sends the Tempest Weather effect a Segment Name like:

```
CLOUD:58*F|68/45|N 0|H 70%
```

Condition prefixes: `SUN`, `PCLOUD`, `CLOUD`, `RAIN1`..`RAIN5`, `STORM1`..`STORM5`, `SNOW1`..`SNOW5`, `WIND`,
`NIGHT` (clear night, moon) and `NIGHTP` (partly cloudy night, moon behind a cloud). Partly cloudy becomes `NIGHTP`
while the sun is below the horizon. Firmware older than `NIGHTP` shows the plain moon for it. The ESP8266 keeps only
32 characters, so trailing pages that don't fit are dropped.

Weather updates pause while a game is on the scoreboard; when the game window ends the scoreboard hands the matrix
straight back to the weather display.
