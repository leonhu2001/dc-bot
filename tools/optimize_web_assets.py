from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
from typing import Iterable

from PIL import Image, ImageSequence


ROOT = Path(__file__).resolve().parents[1]
IMG_DIR = ROOT / "web" / "app" / "static" / "img"


@dataclass(frozen=True)
class StaticAsset:
    source: str
    target: str
    animated: bool = False
    lossless: bool = False
    quality: int = 90


ASSETS = (
    StaticAsset(
        source="home_hero_mascot_final.png",
        target="home_hero_mascot_final.webp",
        quality=92,
    ),
    StaticAsset(
        source="staff_profile_bg_gothic_hall.png",
        target="staff_profile_bg_gothic_hall.webp",
        quality=90,
    ),
    StaticAsset(
        source="server_logo.gif",
        target="server_logo.webp",
        animated=True,
        lossless=True,
        quality=100,
    ),
)


def _frame_durations(image: Image.Image) -> list[int]:
    durations: list[int] = []
    for frame in ImageSequence.Iterator(image):
        durations.append(int(frame.info.get("duration", image.info.get("duration", 0)) or 0))
    return durations


def _convert_static(source: Path, target: Path, asset: StaticAsset) -> None:
    with Image.open(source) as image:
        image.load()
        source_size = image.size
        source_mode = image.mode
        has_alpha = "A" in source_mode or "transparency" in image.info

        working = image.convert("RGBA" if has_alpha else "RGB")
        working.save(
            target,
            format="WEBP",
            quality=asset.quality,
            method=6,
            lossless=asset.lossless,
        )

    with Image.open(target) as converted:
        converted.load()
        if converted.size != source_size:
            raise RuntimeError(f"size changed for {asset.source}: {source_size} -> {converted.size}")


def _convert_animated(source: Path, target: Path, asset: StaticAsset) -> bool:
    encoder = shutil.which("gif2webp")
    if not encoder:
        raise RuntimeError("gif2webp is required for verified animated WebP conversion")

    with Image.open(source) as image:
        source_frames = int(getattr(image, "n_frames", 1) or 1)
        if source_frames <= 1:
            raise RuntimeError(f"expected animated source: {asset.source}")
        source_loop = int(image.info.get("loop", 0) or 0)
        source_size = image.size

    command = [
        encoder,
        "-q",
        str(asset.quality),
        "-m",
        "4",
        "-mt",
        str(source),
        "-o",
        str(target),
    ]
    if not asset.lossless:
        command.insert(1, "-lossy")

    subprocess.run(command, check=True)

    # Do not trade a smaller legacy GIF for a larger lossless WebP.  Check this
    # before deeper metadata validation because some Pillow/WebP builds do not
    # expose per-frame duration metadata even when the encoded animation is valid.
    if target.stat().st_size >= source.stat().st_size:
        after = target.stat().st_size
        target.unlink(missing_ok=True)
        print(
            f"ASSET_KEEP {asset.source}: lossless animated WebP would grow "
            f"{source.stat().st_size} -> {after} bytes"
        )
        return False

    with Image.open(target) as converted:
        converted_frames = int(getattr(converted, "n_frames", 1) or 1)
        converted_loop = int(converted.info.get("loop", 0) or 0)
        converted_size = converted.size

    if converted_frames != source_frames:
        raise RuntimeError(
            f"animation frame count changed for {asset.source}: "
            f"{source_frames} -> {converted_frames}"
        )
    if converted_loop != source_loop:
        raise RuntimeError(
            f"animation loop changed for {asset.source}: {source_loop} -> {converted_loop}"
        )
    if converted_size != source_size:
        raise RuntimeError(
            f"animation dimensions changed for {asset.source}: {source_size} -> {converted_size}"
        )
    return True


def optimize_assets(assets: Iterable[StaticAsset] = ASSETS) -> None:
    for asset in assets:
        source = IMG_DIR / asset.source
        target = IMG_DIR / asset.target
        if not source.is_file():
            raise FileNotFoundError(source)

        before = source.stat().st_size
        if asset.animated:
            if not _convert_animated(source, target, asset):
                continue
        else:
            _convert_static(source, target, asset)

        after = target.stat().st_size
        if after >= before:
            target.unlink(missing_ok=True)
            raise RuntimeError(
                f"optimized asset is not smaller: {asset.source} {before} -> {after}"
            )

        reduction = (1 - (after / before)) * 100
        print(
            f"ASSET_OK {asset.source} -> {asset.target} "
            f"{before} -> {after} bytes ({reduction:.1f}% smaller)"
        )


if __name__ == "__main__":
    optimize_assets()
