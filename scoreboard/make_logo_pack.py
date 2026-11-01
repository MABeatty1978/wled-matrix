#!/usr/bin/env python3
"""Build 8x8 team logo packs for the WLED Scoreboard effect.

Downloads team logos and colors from ESPN, shrinks each logo to 8x8 for the LED matrix,
and writes one pack per league (packs/sb_<league>.bin) plus a preview sheet
(packs/preview_<league>.png).

  python make_logo_pack.py nfl nba                      build packs and previews
  python make_logo_pack.py nfl --upload 192.168.87.80   also upload to WLED
  python make_logo_pack.py epl=soccer/eng.1             any ESPN league as code=sport/league

League codes must match Team Tracker's `league` attribute, lower-cased (nfl, ncaaf, nba, ...).

Hand-drawn logos: save an 8x8 PNG as overrides/<league>/<ABBR>.png (black or transparent = off).
It replaces the automatic conversion for that team on the next run.

Requires: pip install pillow numpy
"""
import argparse
import datetime
import io
import json
import os
import re
import struct
import sys
import urllib.request
import uuid

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SIZE = 8

# Team Tracker league code -> ESPN sport/league path
LEAGUES = {
    "nfl": "football/nfl",
    "ncaaf": "football/college-football",
    "nba": "basketball/nba",
    "wnba": "basketball/wnba",
    "ncaam": "basketball/mens-college-basketball",
    "ncaaw": "basketball/womens-college-basketball",
    "mlb": "baseball/mlb",
    "nhl": "hockey/nhl",
    "mls": "soccer/usa.1",
    "nwsl": "soccer/usa.nwsl",
}

# Leagues ESPN doesn't cover, read from HockeyTech like Team Tracker does:
# league code -> (client code, public key bundled with Team Tracker)
HOCKEYTECH = {
    "ahl": ("ahl", "50c2cd9b5e18e390"),
}
HOCKEYTECH_URL = "https://lscluster.hockeytech.com/feed/index.php"

# Leagues trimmed to ESPN groups (college lists otherwise include every division)
GROUPS = {
    "ncaaf": [80, 81],  # Division 1: FBS + FCS
}

# Score increase that earns a (small, big) celebration; 255 = never
CELEBRATE = {
    "football": (2, 6),     # field goal / safety small, touchdown big
    "basketball": (3, 255), # three-pointers blink, nothing big
    "baseball": (1, 1),
    "hockey": (1, 1),
    "soccer": (1, 1),
}


def fetch(url, cache_dir=None):
    path = None
    if cache_dir:
        path = os.path.join(cache_dir, url.split("://", 1)[1].replace("/", "_").replace("?", "_"))
        if os.path.exists(path):
            with open(path, "rb") as f:
                return f.read()
    req = urllib.request.Request(url, headers={"User-Agent": "wled-scoreboard-pack"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    if path:
        os.makedirs(cache_dir, exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
    return data


def hockeytech_teams(client_code, key):
    """Current regular-season teams; colors come from the logos since HockeyTech has none."""
    base = f"{HOCKEYTECH_URL}?feed=modulekit&key={key}&client_code={client_code}&fmt=json"
    seasons = json.loads(fetch(base + "&view=seasons"))["SiteKit"]["Seasons"]
    season = next(s for s in seasons if s["career"] == "1" and s["playoff"] == "0")
    raw = json.loads(fetch(base + f"&view=teamsbyseason&season_id={season['season_id']}&lang=en"))["SiteKit"]["Teamsbyseason"]
    return [{"abbr": t["code"].upper(), "name": t.get("name", t["code"]), "color": None, "alt": None,
             "logo": t.get("team_logo_url")} for t in raw if t.get("code")]


def espn_group_ids(sport_league, groups):
    sport, league = sport_league.split("/")
    year = datetime.date.today().year
    for season in (year, year - 1):
        ids = set()
        for g in groups:
            url = (f"https://sports.core.api.espn.com/v2/sports/{sport}/leagues/{league}"
                   f"/seasons/{season}/types/2/groups/{g}/teams?limit=500")
            for item in json.loads(fetch(url)).get("items", []):
                m = re.search(r"/teams/(\d+)", item["$ref"])
                if m:
                    ids.add(m.group(1))
        if ids:
            return ids
    return set()


def espn_teams(sport_league, cache_dir, groups=None):
    url = f"https://site.api.espn.com/apis/site/v2/sports/{sport_league}/teams?limit=1000"
    data = json.loads(fetch(url))
    raw = [entry["team"] for entry in data["sports"][0]["leagues"][0]["teams"]]
    if groups:
        ids = espn_group_ids(sport_league, groups)
        raw = [t for t in raw if t["id"] in ids]
        for team_id in sorted(ids - {t["id"] for t in raw}):
            detail = json.loads(fetch(f"https://site.api.espn.com/apis/site/v2/sports/{sport_league}/teams/{team_id}"))
            raw.append(detail["team"])
    teams = []
    for t in raw:
        logos = {tuple(sorted(l.get("rel", []))): l["href"] for l in t.get("logos", [])}
        logo = logos.get(("dark", "full")) or logos.get(("default", "full"))
        if not logo and t.get("logos"):
            logo = t["logos"][0]["href"]
        teams.append({
            "abbr": t["abbreviation"].upper(),
            "name": t.get("displayName", t["abbreviation"]),
            "color": t.get("color"),
            "alt": t.get("alternateColor"),
            "logo": logo,
        })
    return teams


# ---------- 8x8 conversion ----------

def load_square(png_bytes):
    """Crop transparent padding and center the logo on a square canvas."""
    im = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    a = np.array(im)
    ys, xs = np.nonzero(a[:, :, 3] > 24)
    if len(xs):
        im = im.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
    w, h = im.size
    side = max(w, h)
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sq.paste(im, ((side - w) // 2, (side - h) // 2))
    return sq


def palette_of(sq, k=6):
    rgba = np.array(sq.resize((128, 128), Image.LANCZOS))
    opaque = rgba[rgba[:, :, 3] > 200][:, :3]
    if len(opaque) == 0:
        return np.array([[1.0, 1.0, 1.0]], np.float32)
    q = Image.fromarray(opaque.reshape(1, -1, 3)).quantize(k, method=Image.Quantize.MEDIANCUT)
    qi = np.array(q).ravel()
    n = int(qi.max()) + 1
    pal = np.array(q.getpalette()[: n * 3]).reshape(-1, 3)
    counts = np.bincount(qi, minlength=n)
    return pal[counts > counts.sum() * 0.03].astype(np.float32) / 255


def lift(rgb, floor=0.45):
    """Raise dark-but-colored pixels so they survive LED gamma; near-black becomes off."""
    mx = rgb.max(-1, keepdims=True)
    dark = (mx > 0.06) & (mx < floor)
    out = np.where(dark, rgb * (floor / np.maximum(mx, 1e-6)), rgb)
    out[mx[..., 0] <= 0.06] = 0
    return out


def to_8x8(png_bytes, k=6):
    """Light the cells the logo covers most (tracking its real ink area), each in the
    palette color that wins a vote weighted toward rarer accent colors."""
    sq = load_square(png_bytes)
    pal = palette_of(sq, k)
    n = 32
    big = np.array(sq.resize((SIZE * n, SIZE * n), Image.LANCZOS)).astype(np.float32) / 255
    cl = big.reshape(SIZE, n, SIZE, n, 4).swapaxes(1, 2).reshape(SIZE, SIZE, n * n, 4)
    cov = cl[..., 3].mean(2)
    target = int(np.clip(round(cov.sum() * 1.25), 6, 64))
    thresh = max(np.sort(cov.ravel())[::-1][target - 1], 0.12)
    lit = cov >= min(thresh, 0.5)
    idx = ((cl[..., None, :3] - pal[None, None, None]) ** 2).sum(-1).argmin(-1)
    opaque = cl[..., 3] > 0.5
    glob = np.bincount(idx[opaque], minlength=len(pal)).astype(np.float32)
    weight = 1 / np.sqrt(np.maximum(glob / max(glob.sum(), 1), 0.02))
    ink = cl[..., 3] > 0.15
    out = np.zeros((SIZE, SIZE, 3), np.float32)
    for y in range(SIZE):
        for x in range(SIZE):
            if lit[y, x] and ink[y, x].any():
                votes = np.bincount(idx[y, x][ink[y, x]], minlength=len(pal))
                out[y, x] = pal[(votes * weight).argmax()]
    return (lift(out) * 255).round().astype(np.uint8)


def load_override(path):
    im = Image.open(path).convert("RGBA")
    if im.size != (SIZE, SIZE):
        im = im.resize((SIZE, SIZE), Image.NEAREST)
    a = np.array(im).astype(np.uint16)
    rgb = (a[..., :3] * a[..., 3:4] // 255).astype(np.uint8)
    return rgb


def led_color(hexstr):
    if not hexstr or len(hexstr) != 6:
        return None
    rgb = np.array([int(hexstr[i:i + 2], 16) for i in (0, 2, 4)], np.float32)
    if rgb.max() < 40:
        return None  # black is invisible on LEDs
    if rgb.max() < 140:
        rgb *= 140 / rgb.max()
    return tuple(int(v) for v in rgb.round())


def logo_colors(png_bytes):
    """Two most common colorful logo colors as hex strings, for teams without listed colors."""
    rgba = np.array(load_square(png_bytes).resize((128, 128), Image.LANCZOS))
    px = rgba[rgba[:, :, 3] > 200][:, :3].astype(np.int32)
    colorful = px[(px.max(1) - px.min(1)) > 40]
    if len(colorful) == 0:
        return None, None
    q = Image.fromarray(colorful.astype(np.uint8).reshape(1, -1, 3)).quantize(4, method=Image.Quantize.MEDIANCUT)
    qi = np.array(q).ravel()
    pal = np.array(q.getpalette()[: (int(qi.max()) + 1) * 3]).reshape(-1, 3)
    order = np.argsort(np.bincount(qi))[::-1]
    hexes = ["%02x%02x%02x" % tuple(pal[i]) for i in order[:2]]
    return hexes[0], hexes[1] if len(hexes) > 1 else None


def team_colors(team):
    c1 = led_color(team["color"]) or led_color(team["alt"]) or (255, 255, 255)
    c2 = led_color(team["alt"]) or (255, 255, 255)
    if c2 == c1:
        c2 = (255, 255, 255)
    return c1, c2


# ---------- pack, preview, upload ----------

def write_pack(path, teams, small, big):
    teams = [t for t in teams if 0 < len(t["abbr"]) <= 6]
    with open(path, "wb") as f:
        f.write(b"SB1" + struct.pack("<HBBB", len(teams), small, big, 0))
        for t in teams:
            f.write(t["abbr"].encode("ascii", "replace").ljust(6, b"\0"))
        for t in teams:
            f.write(bytes(t["c1"]) + bytes(t["c2"]) + t["px"].tobytes())
    return len(teams)


def led_tile(px, scale=10):
    tile = Image.new("RGB", (SIZE * scale, SIZE * scale), (14, 14, 18))
    dr = ImageDraw.Draw(tile)
    r = scale * 0.42
    for y in range(SIZE):
        for x in range(SIZE):
            c = tuple(int(v) for v in px[y, x])
            if max(c) < 8:
                c = (30, 30, 36)
            cx, cy = x * scale + scale / 2, y * scale + scale / 2
            dr.ellipse((cx - r, cy - r, cx + r, cy + r), fill=c)
    return tile


def write_preview(path, league, teams):
    font = ImageFont.load_default()
    scale, cols = 10, 8
    tw = SIZE * scale
    cw, ch = tw + 22, tw + 30
    rows = (len(teams) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cw + 12, rows * ch + 34), (8, 8, 10))
    dr = ImageDraw.Draw(sheet)
    dr.text((8, 8), f"{league.upper()}  ({len(teams)} teams)   * = hand-drawn override", fill=(220, 220, 220), font=font)
    for i, t in enumerate(teams):
        x0, y0 = 8 + (i % cols) * cw, 30 + (i // cols) * ch
        sheet.paste(led_tile(t["px"], scale), (x0, y0))
        dr.rectangle((x0, y0 + tw + 4, x0 + 8, y0 + tw + 12), fill=t["c1"])
        dr.rectangle((x0 + 9, y0 + tw + 4, x0 + 17, y0 + tw + 12), fill=t["c2"])
        dr.text((x0 + 22, y0 + tw + 2), t["abbr"] + (" *" if t["override"] else ""), fill=(230, 230, 230), font=font)
    sheet.save(path)


def upload(host, local_path, remote_name):
    boundary = uuid.uuid4().hex
    with open(local_path, "rb") as f:
        payload = f.read()
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"data\"; filename=\"/{remote_name}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"http://{host}/upload", data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read().decode(errors="replace").strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("leagues", nargs="+", help="league codes (nfl, nba, ...) or code=sport/league")
    ap.add_argument("--out", default=os.path.join(HERE, "packs"))
    ap.add_argument("--overrides", default=os.path.join(HERE, "overrides"))
    ap.add_argument("--cache", default=os.path.join(HERE, ".cache"), help="downloaded logo cache")
    ap.add_argument("--upload", metavar="WLED_HOST", help="upload packs to this WLED device")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    for spec in args.leagues:
        code, _, path = spec.partition("=")
        code = code.lower()
        if code in HOCKEYTECH and not path:
            small, big = CELEBRATE["hockey"]
            teams = hockeytech_teams(*HOCKEYTECH[code])
            print(f"{code}: {len(teams)} teams from HockeyTech")
        else:
            path = path or LEAGUES.get(code)
            if not path:
                sys.exit(f"Unknown league '{code}'. Use code=sport/league, e.g. epl=soccer/eng.1")
            small, big = CELEBRATE.get(path.split("/")[0], (1, 255))
            teams = espn_teams(path, args.cache, GROUPS.get(code))
            print(f"{code}: {len(teams)} teams from ESPN ({path})")
        for t in teams:
            if t["color"] is None and t["logo"]:
                try:
                    t["color"], t["alt"] = logo_colors(fetch(t["logo"], args.cache))
                except Exception:
                    pass
            t["c1"], t["c2"] = team_colors(t)
            ov = os.path.join(args.overrides, code, t["abbr"] + ".png")
            t["override"] = os.path.exists(ov)
            if t["override"]:
                t["px"] = load_override(ov)
            elif t["logo"]:
                try:
                    t["px"] = to_8x8(fetch(t["logo"], args.cache))
                except Exception as e:  # keep going; the effect falls back to letters
                    print(f"  {t['abbr']}: logo failed ({e})")
                    t["px"] = np.zeros((SIZE, SIZE, 3), np.uint8)
            else:
                t["px"] = np.zeros((SIZE, SIZE, 3), np.uint8)
        teams.sort(key=lambda t: t["abbr"])

        pack = os.path.join(args.out, f"sb_{code}.bin")
        n = write_pack(pack, teams, small, big)
        write_preview(os.path.join(args.out, f"preview_{code}.png"), code, teams)
        print(f"  wrote {pack} ({n} teams, {os.path.getsize(pack)} bytes) and preview_{code}.png")
        if args.upload:
            status, text = upload(args.upload, pack, f"sb_{code}.bin")
            print(f"  uploaded to {args.upload}: {status} {text}")


if __name__ == "__main__":
    main()
