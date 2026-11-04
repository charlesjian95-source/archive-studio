"""Local photo conversion. Outputs and incomplete files are never silently replaced."""
from __future__ import annotations

from dataclasses import dataclass
import io
import os
from pathlib import Path
import stat
import threading
import time
import warnings

from PIL import Image, ImageCms, ImageOps
from pi_heif import register_heif_opener

from archive_engine import ArchiveError, Cancelled, check_cancel, commit_output, unique_path

register_heif_opener()
Image.MAX_IMAGE_PIXELS = 60_000_000
EXTENSIONS = frozenset((".jpg", ".jpeg", ".jfif", ".png", ".webp", ".bmp", ".dib",
                        ".tif", ".tiff", ".gif", ".heic", ".heif", ".avif"))
FORMATS = {"JPG": ("JPEG", ".jpg"), "PNG": ("PNG", ".png"),
           "WebP": ("WEBP", ".webp"), "AVIF": ("AVIF", ".avif"),
           "TIFF": ("TIFF", ".tiff"), "BMP": ("BMP", ".bmp")}
MAX_FILES = 10_000
SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))


@dataclass(frozen=True)
class Options:
    format: str = "JPG"
    quality: int = 90
    max_edge: int = 0
    keep_metadata: bool = False
    background: str = "white"

    def validate(self):
        if self.format not in available_formats():
            raise ArchiveError("此版本不支援選取的照片輸出格式。")
        if not 1 <= self.quality <= 100:
            raise ArchiveError("照片品質必須介於 1 與 100。")
        if not 0 <= self.max_edge <= 20_000:
            raise ArchiveError("最長邊必須介於 1 與 20,000 像素；0 代表原尺寸。")
        if self.background not in ("white", "black"):
            raise ArchiveError("請選擇白色或黑色背景。")


@dataclass(frozen=True)
class Source:
    path: Path
    relative: Path


@dataclass(frozen=True)
class Discovery:
    sources: tuple[Source, ...]
    skipped: int


@dataclass(frozen=True)
class ItemResult:
    source: Path
    output: Path | None
    status: str
    message: str
    input_bytes: int = 0
    output_bytes: int = 0


@dataclass(frozen=True)
class BatchResult:
    path: Path
    files: int
    original_bytes: int
    output_bytes: int
    seconds: float
    items: tuple[ItemResult, ...]
    cancelled: bool

    @property
    def failures(self):
        return sum(item.status == "error" for item in self.items)


@dataclass
class Preview:
    before: Image.Image
    after: Image.Image
    original_size: tuple[int, int]
    output_size: tuple[int, int]
    input_bytes: int
    output_bytes: int


def available_formats():
    Image.init()
    return tuple(name for name, (encoder, _) in FORMATS.items() if encoder in Image.SAVE)


def _linked(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def discover(inputs, cancel=None):
    found = []
    seen = set()
    skipped = 0

    def add(path, relative):
        nonlocal skipped
        check_cancel(cancel)
        if _linked(path) or path.suffix.lower() not in EXTENSIONS:
            skipped += 1
            return
        key = os.path.normcase(str(path.resolve()))
        if key in seen:
            return
        seen.add(key)
        found.append(Source(path.resolve(), relative))
        if len(found) > MAX_FILES:
            raise ArchiveError("單批最多加入 10,000 張照片，請分批處理。")

    def visit(folder, relative):
        nonlocal skipped
        check_cancel(cancel)
        with os.scandir(folder) as scan:
            children = sorted(scan, key=lambda child: child.name.casefold())
        for child in children:
            check_cancel(cancel)
            path = Path(child.path)
            if _linked(path):
                skipped += 1
            elif child.is_dir(follow_symlinks=False):
                visit(path, relative / child.name)
            elif child.is_file(follow_symlinks=False):
                add(path, relative / child.name)

    selected = []
    for value in inputs:
        path = Path(value).absolute()
        if not path.exists():
            raise ArchiveError("找不到檔案：" + str(path))
        if _linked(path):
            skipped += 1
            continue
        path = path.resolve()
        if path not in selected:
            selected.append(path)
    selected = [path for path in selected if not any(
        parent != path and parent.is_dir() and parent in path.parents for parent in selected)]
    for path in selected:
        if path.is_dir():
            visit(path, Path(path.name))
        else:
            add(path, Path(path.name))
    return Discovery(tuple(found), skipped)


def _load(path, options):
    options.validate()
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            with Image.open(path) as original:
                if getattr(original, "n_frames", 1) > 1:
                    raise ArchiveError("這是動畫或多頁影像；本功能只轉換單張照片，請先取出要轉換的畫面。")
                if original.width * original.height > Image.MAX_IMAGE_PIXELS:
                    raise ArchiveError("照片超過 6,000 萬像素，請先縮小後再轉換。")
                original.load()
                oriented = ImageOps.exif_transpose(original)
                size = oriented.size
                exif = oriented.getexif()
                has_alpha = "A" in oriented.getbands() or "transparency" in oriented.info
                mode = "RGBA" if has_alpha else "RGB"
                profile = oriented.info.get("icc_profile")
                if profile:
                    try:
                        image = ImageCms.profileToProfile(
                            oriented, ImageCms.ImageCmsProfile(io.BytesIO(profile)), SRGB,
                            outputMode=mode)
                    except (ImageCms.PyCMSError, OSError, ValueError):
                        # A malformed ICC profile must not block otherwise readable photos.
                        image = oriented.convert(mode)
                else:
                    image = oriented.convert(mode)
                image = image.copy()
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise ArchiveError("照片超過 6,000 萬像素，請先縮小後再轉換。") from exc
        except (Image.UnidentifiedImageError, OSError) as exc:
            raise ArchiveError("無法讀取照片，檔案可能損壞或格式不受支援。") from exc
    if options.max_edge:
        image.thumbnail((options.max_edge, options.max_edge), Image.Resampling.LANCZOS)
    if options.format in ("JPG", "BMP"):
        if image.mode == "RGBA":
            backdrop = Image.new("RGB", image.size, options.background)
            backdrop.paste(image, mask=image.getchannel("A"))
            image = backdrop
        else:
            image = image.convert("RGB")
    image.info.clear()
    kwargs = {}
    if options.format != "BMP":
        kwargs["icc_profile"] = SRGB.tobytes()
    if options.keep_metadata and options.format != "BMP":
        exif.pop(274, None)
        if exif:
            exif[40962], exif[40963] = image.size
            kwargs["exif"] = exif.tobytes()
    if options.format == "JPG":
        kwargs.update(quality=options.quality, optimize=True, progressive=True)
    elif options.format == "WebP":
        kwargs.update(quality=options.quality, method=4)
    elif options.format == "AVIF":
        kwargs.update(quality=options.quality, speed=6, max_threads=2)
    elif options.format == "PNG":
        kwargs.update(compress_level=6)
    elif options.format == "TIFF":
        kwargs.update(compression="tiff_deflate")
    return image, kwargs, size


def preview(source, options, cancel=None):
    check_cancel(cancel)
    image, kwargs, original_size = _load(source, options)
    check_cancel(cancel)
    output_size = image.size
    encoded = io.BytesIO()
    image.save(encoded, FORMATS[options.format][0], **kwargs)
    check_cancel(cancel)
    output_bytes = encoded.tell()
    encoded.seek(0)
    with Image.open(encoded) as saved:
        after = saved.convert("RGBA")
        after.thumbnail((560, 360), Image.Resampling.LANCZOS)
    # Read the source in display orientation, independently of the output resize.
    with Image.open(source) as original:
        before = ImageOps.exif_transpose(original).convert("RGBA")
        before.thumbnail((560, 360), Image.Resampling.LANCZOS)
    image.close()
    encoded.close()
    return Preview(before, after, original_size, output_size, Path(source).stat().st_size, output_bytes)


def convert_batch(sources, output_dir, options=Options(), progress=None, item_callback=None, cancel=None):
    options.validate()
    if not sources:
        raise ArchiveError("請先加入照片。")
    if len(sources) > MAX_FILES:
        raise ArchiveError("單批最多處理 10,000 張照片。")
    check_cancel(cancel)
    started = time.monotonic()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    folder = unique_path(output_dir, "照片轉檔")
    folder.mkdir()
    progress = progress or (lambda *args: None)
    item_callback = item_callback or (lambda *args: None)
    sizes = [source.path.stat().st_size if source.path.is_file() else 0 for source in sources]
    total_bytes = sum(sizes)
    completed_bytes = 0
    results = []
    cancelled = False
    for index, source in enumerate(sources):
        if cancel is not None and cancel.is_set():
            cancelled = True
            break
        progress(index / len(sources), source.path.name, completed_bytes, total_bytes)
        partial = None
        image = None
        try:
            relative = source.relative
            if relative.is_absolute() or any(part in ("..", "") for part in relative.parts):
                raise ArchiveError("照片輸出相對路徑無效。")
            target_dir = folder / relative.parent
            if not target_dir.resolve().is_relative_to(folder.resolve()):
                raise ArchiveError("照片輸出路徑超出目的資料夾。")
            target_dir.mkdir(parents=True, exist_ok=True)
            image, kwargs, _ = _load(source.path, options)
            check_cancel(cancel)
            final = unique_path(target_dir, source.path.stem + FORMATS[options.format][1])
            partial = unique_path(target_dir, final.name + ".partial")
            with partial.open("xb") as output:
                image.save(output, FORMATS[options.format][0], **kwargs)
            check_cancel(cancel)
            if final.exists():
                final = unique_path(target_dir, final.name)
            commit_output(partial, final, cancel)
            result = ItemResult(source.path, final, "done", "完成", sizes[index], final.stat().st_size)
        except Cancelled:
            cancelled = True
            result = ItemResult(source.path, partial, "cancelled", "已取消；未完成檔案保留。", sizes[index])
        except Exception as exc:
            message = str(exc) or type(exc).__name__
            if partial is not None and partial.exists():
                message += "\n未完成檔案：" + str(partial)
            result = ItemResult(source.path, None, "error", message, sizes[index])
        finally:
            if image is not None:
                image.close()
        results.append(result)
        item_callback(index, result)
        completed_bytes += sizes[index]
        progress((index + 1) / len(sources), source.path.name, completed_bytes, total_bytes)
        if cancelled:
            break
    for source in sources[len(results):]:
        results.append(ItemResult(source.path, None, "pending", "尚未處理"))
    successes = [result for result in results if result.status == "done"]
    return BatchResult(folder, len(successes), sum(item.input_bytes for item in successes),
                       sum(item.output_bytes for item in successes), time.monotonic() - started,
                       tuple(results), cancelled)
