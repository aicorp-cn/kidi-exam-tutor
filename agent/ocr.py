"""OCR via tesseract CLI with quality gating and cancellation support."""

import asyncio
import os


class OCRError(Exception):
    """Raised when OCR fails quality checks."""
    pass


async def ocr_images(image_paths: list[str], cancel_evt: asyncio.Event = None) -> str:
    """Run tesseract on each image, concatenate with PAGE markers.

    Accepts optional cancel_evt — when set, cancels the in-flight tesseract
    subprocess and raises asyncio.CancelledError.

    Raises OCRError if any page produces empty or too-short text.

    Returns:
        Concatenated OCR text with === PAGE N/M === markers.
    """
    pages = []
    total = len(image_paths)

    for i, path in enumerate(image_paths, 1):
        text = await _tesseract_page(path, cancel_evt=cancel_evt)

        # Quality gate: empty
        if not text or not text.strip():
            raise OCRError(
                f"第 {i}/{total} 页识别为空（前 {len(pages)} 页已成功）。"
                f"请重新拍摄第 {i} 页。"
            )

        # Quality gate: too short (likely blank page or severe noise)
        stripped = text.strip()
        if len(stripped) < 50:
            raise OCRError(
                f"第 {i}/{total} 页文字过少（{len(stripped)} 字符，前 {len(pages)} 页已成功）。"
                f"请重新拍摄第 {i} 页。"
            )

        # Quality gate: English character ratio — blocking for extreme cases
        alpha_chars = sum(1 for c in stripped if c.isascii() and c.isalpha())
        ratio = alpha_chars / max(len(stripped), 1)
        if ratio < 0.3:
            raise OCRError(
                f"第 {i}/{total} 页英文字符占比过低（{ratio:.0%}，前 {len(pages)} 页已成功）。"
                f"请确认第 {i} 页为英文试卷。"
            )

        pages.append(f"=== PAGE {i}/{total} ===\n{stripped}")

    return "\n\n".join(pages)


async def _tesseract_page(image_path: str, timeout: float = 60.0,
                          cancel_evt: asyncio.Event = None) -> str:
    """Run tesseract on a single image. Cancellable via cancel_evt.

    Args:
        image_path: Path to JPEG/PNG image
        timeout: Max seconds for tesseract to complete
        cancel_evt: When set, kills the tesseract subprocess

    Returns:
        Extracted text, or empty string on failure.
    """
    if not os.path.exists(image_path):
        raise OCRError(f"图片文件未找到: {image_path}")

    try:
        proc = await asyncio.create_subprocess_exec(
            "tesseract", image_path, "stdout",
            "--psm", "6",
            "-l", "eng",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Race: tesseract completion vs cancellation
        comm_task = asyncio.create_task(proc.communicate())
        if cancel_evt:
            cancel_watch = asyncio.create_task(cancel_evt.wait())
            done, _ = await asyncio.wait(
                [comm_task, cancel_watch],
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            cancel_watch.cancel()
            if cancel_evt.is_set():
                comm_task.cancel()
                proc.kill()
                await proc.wait()
                raise asyncio.CancelledError("OCR cancelled by user")
            if comm_task not in done:
                comm_task.cancel()
                proc.kill()
                await proc.wait()
                raise asyncio.TimeoutError(
                    f"文字识别超时（{timeout}秒），图片可能过大或系统繁忙，请重试。"
                )
            stdout, stderr = await comm_task
        else:
            try:
                stdout, stderr = await asyncio.wait_for(
                    comm_task, timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise asyncio.TimeoutError(
                    f"文字识别超时（{timeout}秒），图片可能过大或系统繁忙，请重试。"
                )

        # Check return code for crash signals
        if proc.returncode == -9:
            raise OCRError(
                "系统内存不足，无法完成文字识别。请稍后重试。"
            )
        if proc.returncode != 0 and proc.returncode is not None:
            stderr_text = stderr.decode("utf-8", errors="replace").strip() if stderr else ""
            raise OCRError(
                f"文字识别失败（错误码 {proc.returncode}），请确认图片清晰且包含英文文字。"
                + (f" 详情: {stderr_text[:200]}" if stderr_text else "")
            )

        return stdout.decode("utf-8", errors="replace")

    except OCRError:
        raise
    except asyncio.CancelledError:
        raise
    except FileNotFoundError:
        raise OCRError(
            "文字识别组件未安装。请运行: sudo apt-get install tesseract-ocr tesseract-ocr-eng"
        )
    except Exception as e:
        raise OCRError(f"文字识别异常: {str(e)}")
