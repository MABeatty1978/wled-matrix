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
| `home-assistant/` | Home Assistant packages for the weather and scoreboard |
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
python make_logo_pack.py nfl nba mlb ncaaf --upload 192.168.87.80
```

League codes match Team Tracker's `league` attribute, lower-cased. `ncaaf` is trimmed to Division 1 (FBS + FCS). Each run writes `packs/sb_<league>.bin` and a `packs/preview_<league>.png` sheet to review.

To replace a logo that doesn't read well at 8x8, draw an 8x8 PNG (black or transparent = off), save it as `overrides/<league>/<ABBR>.png`, and run the tool again.

AHL logos aren't available yet. Until then, AHL games show the first two letters of each team's abbreviation in place of a logo.

## Home Assistant

Copy both files in `home-assistant/` to `/config/packages/`, with this in `configuration.yaml`:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Then:

1. In `tempest_wled.yaml`, replace the Tempest and weather entity IDs with yours.
2. In `scoreboard_wled.yaml`, list your Team Tracker sensors in priority order.

`scoreboard_wled.yaml` depends on `tempest_wled.yaml`; the weather package works on its own.
