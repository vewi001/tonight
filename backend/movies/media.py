from __future__ import annotations

import hashlib
import html
from pathlib import Path

from backend.config import ASSET_ROOT, ROOT

PALETTES = [
    ("#ff5d6c", "#6b183f"), ("#ff8a4c", "#4d1834"), ("#e84b8a", "#291546"),
    ("#8a5cff", "#171d4f"), ("#ffbf4b", "#642c24"), ("#46c2b3", "#143d45"),
]


def local_media(movie_id: str, kind: str) -> Path | None:
    directory = ROOT / "data" / ("posters" if kind == "poster" else "backdrops")
    for extension in (".jpg", ".jpeg", ".png", ".webp"):
        path = directory / f"{movie_id}{extension}"
        if path.exists():
            return path
    return None


def genre_art(genres: list[str]) -> Path | None:
    """Original local key art used when a film has no provider poster cached."""
    genre_set = set(genres)
    if "sci-fi" in genre_set or "фэнтези" in genre_set:
        name = "cinema-sci-fi.png"
    elif {"детектив", "триллер", "загадка", "хоррор"} & genre_set:
        name = "cinema-mystery.png"
    else:
        name = "cinema-warm.png"
    path = (ASSET_ROOT / "assets" / "art" / name) if ASSET_ROOT != ROOT else (ROOT / "data" / "art" / name)
    return path if path.exists() else None


def _motif(genres: list[str], width: int, height: int, digest: int) -> str:
    genre_set = set(genres)
    if "sci-fi" in genre_set:
        stars = "".join(
            f'<circle cx="{(digest * (i + 7) * 17) % width}" cy="{(digest * (i + 3) * 11) % height}" r="{1 + i % 3}" fill="#fff" opacity=".{3 + i % 6}"/>'
            for i in range(28)
        )
        return stars + f'<circle cx="{width*.73}" cy="{height*.28}" r="{min(width,height)*.18}" fill="#fff" opacity=".11"/><ellipse cx="{width*.73}" cy="{height*.28}" rx="{min(width,height)*.28}" ry="{min(width,height)*.07}" fill="none" stroke="#fff" stroke-width="5" opacity=".16"/>'
    if {"детектив", "триллер", "загадка"} & genre_set:
        return f'<g fill="none" stroke="#fff" opacity=".13"><circle cx="{width*.73}" cy="{height*.3}" r="{min(width,height)*.19}" stroke-width="10"/><line x1="{width*.84}" y1="{height*.43}" x2="{width*.98}" y2="{height*.59}" stroke-width="18" stroke-linecap="round"/></g><path d="M0 {height*.22} L{width} 0 L{width} {height*.18} L0 {height*.42}Z" fill="#000" opacity=".13"/>'
    if "романтика" in genre_set:
        return f'<circle cx="{width*.68}" cy="{height*.26}" r="{min(width,height)*.2}" fill="#fff" opacity=".09"/><circle cx="{width*.82}" cy="{height*.35}" r="{min(width,height)*.16}" fill="#fff" opacity=".07"/>'
    if {"боевик", "приключения"} & genre_set:
        lines = "".join(f'<line x1="{width*(.45+i*.08)}" y1="0" x2="{width*(.12+i*.08)}" y2="{height*.62}" stroke="#fff" stroke-width="{4+i*2}" opacity=".{8+i}"/>' for i in range(5))
        return f'<g>{lines}</g>'
    if {"комедия", "семейный", "мультфильм"} & genre_set:
        return f'<circle cx="{width*.72}" cy="{height*.28}" r="{min(width,height)*.23}" fill="#fff" opacity=".10"/><path d="M{width*.58} {height*.29} Q{width*.72} {height*.43} {width*.86} {height*.29}" fill="none" stroke="#fff" stroke-width="10" stroke-linecap="round" opacity=".18"/>'
    return f'<rect x="{width*.56}" y="{height*.12}" width="{width*.34}" height="{height*.34}" rx="28" fill="none" stroke="#fff" stroke-width="8" opacity=".11"/><line x1="{width*.56}" y1="{height*.25}" x2="{width*.9}" y2="{height*.25}" stroke="#fff" stroke-width="5" opacity=".09"/>'


def placeholder_svg(movie_id: str, title: str, year: int, genres: list[str] | None = None, wide: bool = False) -> str:
    digest = int(hashlib.sha256(movie_id.encode()).hexdigest()[:4], 16)
    start, end = PALETTES[digest % len(PALETTES)]
    width, height = (1280, 720) if wide else (600, 900)
    safe_title = html.escape(title)
    title_size = 78 if wide else 54
    motif = _motif(genres or [], width, height, digest)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">
    <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{start}"/><stop offset="1" stop-color="{end}"/></linearGradient>
    <filter id="n"><feTurbulence baseFrequency=".8" numOctaves="3" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/><feComponentTransfer><feFuncA type="table" tableValues="0 .08"/></feComponentTransfer></filter></defs>
    <rect width="100%" height="100%" fill="url(#g)"/><rect width="100%" height="100%" filter="url(#n)" opacity=".45"/>
    {motif}
    <text x="{width*.09}" y="{height*.16}" fill="#fff" opacity=".68" font-family="Arial" font-size="24" letter-spacing="8">TONIGHT</text>
    <foreignObject x="{width*.09}" y="{height*.54}" width="{width*.82}" height="{height*.38}"><div xmlns="http://www.w3.org/1999/xhtml" style="font:800 {title_size}px/1.02 Arial;color:white;letter-spacing:-2px">{safe_title}<div style="font:400 24px Arial;opacity:.72;margin-top:22px">{year} · оригинальная локальная обложка</div></div></foreignObject>
    </svg>'''

