from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from .config import THUMBNAIL_CACHE_DIR

THUMB_MAX_WIDTH = 2800
THUMB_MAX_QUALITY = 95
THUMB_CACHE_VERSION = "v2"


def remap_ws_clients(
    existing_clients: dict[str, set[Any]],
    projects: dict[str, dict[str, Any]],
) -> dict[str, set[Any]]:
    """Preserve websocket client sets for projects that still exist."""
    return {slug: existing_clients.get(slug, set()) for slug in projects.keys()}


def resolve_active_project_slug(
    projects: dict[str, dict[str, Any]],
    install_state: dict[str, Any],
    slugify_fn: Callable[[str], str],
) -> str | None:
    active_slug = str(install_state.get("active_project_slug", "")).strip()
    if active_slug and active_slug in projects:
        return active_slug

    active_name = str(install_state.get("active_project_name", "")).strip()
    if active_name:
        by_name = slugify_fn(active_name)
        if by_name in projects:
            return by_name
        for slug, proj in projects.items():
            if str(proj.get("name", "")).strip().lower() == active_name.lower():
                return slug

    if projects:
        return next(iter(sorted(projects.keys())))
    return None


def resolve_project_change_context(
    path: Path,
    projects: dict[str, dict[str, Any]],
    store_path: Path,
    project_dir_slug_index: dict[str, str],
    slugify_fn: Callable[[str], str],
) -> tuple[str | None, tuple[str, ...]]:
    """
    Resolve changed filesystem path to (project slug, project-relative parts).
    """
    for slug, proj in projects.items():
        proj_root_raw = proj.get("path")
        proj_root = Path(str(proj_root_raw)) if isinstance(proj_root_raw, str) and proj_root_raw else None
        if not proj_root:
            continue
        try:
            rel_parts = path.relative_to(proj_root).parts
            if rel_parts:
                return slug, rel_parts
        except ValueError:
            continue

    try:
        rel_parts = path.relative_to(store_path).parts
    except ValueError:
        return None, ()

    if len(rel_parts) < 2:
        return None, ()

    project_dir_name = rel_parts[0]
    slug = project_dir_slug_index.get(project_dir_name, slugify_fn(project_dir_name))
    if slug in projects:
        return slug, tuple(rel_parts[1:])
    return None, ()


def page_event_from_change(path_name: str, project_rel_parts: tuple[str, ...], page_name: str) -> dict[str, str]:
    if path_name == "pass1.json":
        return {"type": "page_added", "page": page_name}
    if path_name == "pass2.json" and len(project_rel_parts) >= 4:
        return {"type": "region_complete", "page": page_name, "region": project_rel_parts[3]}
    if path_name == "page.png":
        return {"type": "page_image_ready", "page": page_name}
    return {"type": "page_updated", "page": page_name}


def clamp_thumb_params(width: int, quality: int) -> tuple[int, int]:
    return max(200, min(int(width), THUMB_MAX_WIDTH)), max(40, min(int(quality), THUMB_MAX_QUALITY))


def _cached_or_render_jpeg(
    *,
    image_path: Path,
    cache_path: Path,
    target_width: int,
    target_quality: int,
) -> bytes:
    if cache_path.exists() and cache_path.stat().st_mtime >= image_path.stat().st_mtime:
        return cache_path.read_bytes()

    img = Image.open(image_path)
    render_width = min(target_width, img.width)
    w_ratio = render_width / img.width
    new_height = int(img.height * w_ratio)
    img = img.resize((render_width, new_height), Image.LANCZOS)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    buf = io.BytesIO()
    img.save(
        buf,
        format="JPEG",
        quality=target_quality,
        optimize=True,
        progressive=True,
        subsampling=0,
    )
    data = buf.getvalue()
    cache_path.parent.mkdir(exist_ok=True)
    cache_path.write_bytes(data)
    return data


def page_thumbnail_cache_path(page_dir: Path, width: int, quality: int) -> tuple[Path, Path, int, int]:
    png_path = page_dir / "page.png"
    target_width, target_quality = clamp_thumb_params(width, quality)
    cache_dir = page_dir / THUMBNAIL_CACHE_DIR
    cache_key = f"thumb_{THUMB_CACHE_VERSION}_{target_width}q{target_quality}.jpg"
    return png_path, cache_dir / cache_key, target_width, target_quality


def get_page_thumbnail(page_dir: Path, width: int = 800, quality: int = 80) -> bytes | None:
    png_path, cache_path, target_width, target_quality = page_thumbnail_cache_path(page_dir, width, quality)
    if not png_path.exists():
        return None
    try:
        return _cached_or_render_jpeg(
            image_path=png_path,
            cache_path=cache_path,
            target_width=target_width,
            target_quality=target_quality,
        )
    except Exception:
        return None


def generated_image_thumb_cache_path(
    *,
    image_path: Path,
    cache_dir: Path,
    width: int,
    quality: int,
) -> tuple[Path, int, int]:
    target_width, target_quality = clamp_thumb_params(width, quality)
    cache_key = f"{image_path.stem}_thumb_{THUMB_CACHE_VERSION}_{target_width}q{target_quality}.jpg"
    return cache_dir / cache_key, target_width, target_quality


def get_generated_image_thumbnail(
    *,
    image_path: Path,
    cache_dir: Path,
    width: int = 800,
    quality: int = 80,
) -> bytes | None:
    if not image_path.exists():
        return None
    cache_path, target_width, target_quality = generated_image_thumb_cache_path(
        image_path=image_path,
        cache_dir=cache_dir,
        width=width,
        quality=quality,
    )
    try:
        return _cached_or_render_jpeg(
            image_path=image_path,
            cache_path=cache_path,
            target_width=target_width,
            target_quality=target_quality,
        )
    except Exception:
        return None
