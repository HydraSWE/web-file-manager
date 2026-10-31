"""
QR Code generation utilities for console display and web frontend.
  - Terminal CLI: Pure clean high-contrast scannable QR code.
  - Web UI: Signature Branded QR via Hydra Cloud API (with silent local fallback).
"""
import os
import sys
import io
import urllib.request
import urllib.parse
import logging

logger = logging.getLogger("web_file_manager.qr")

def _load_env_file():
    """Lightweight zero-dependency .env loader that populates os.environ."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(base_dir, ".env"), os.path.join(os.getcwd(), ".env")):
        if os.path.isfile(cand):
            try:
                with open(cand, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip("'\"")
                        if k and k not in os.environ:
                            os.environ[k] = v
            except Exception:
                pass

_load_env_file()

HYDRA_CLOUD_QR_API = os.environ.get("HYDRA_CLOUD_QR_API", "").strip()
_QR_CACHE = {}


def _get_base_qr_matrix(url: str):
    import qrcode
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    return [row[:] for row in qr.get_matrix()]


def _render_qr_lines(matrix):
    n = len(matrix)
    lines = []
    for y in range(0, n, 2):
        line = ''
        for x in range(n):
            top_dark = matrix[y][x]
            bot_dark = matrix[y + 1][x] if y + 1 < n else False
            if not top_dark and not bot_dark:
                line += '█'
            elif not top_dark and bot_dark:
                line += '▀'
            elif top_dark and not bot_dark:
                line += '▄'
            else:
                line += ' '
        lines.append(line)
    return lines


def print_terminal_qr(url: str, **kwargs):
    """
    Prints a clean, high-contrast, perfectly scannable terminal QR code.
    Zero clutter, maximum instant camera scanning reliability.
    """
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')

        matrix = _get_base_qr_matrix(url)
        n = len(matrix)

        print("\n  [Scan with your Mobile Phone Camera to Connect]")
        print("  " + "-" * (n + 4))
        for line in _render_qr_lines(matrix):
            print("  " + line)
        print("  " + "-" * (n + 4) + "\n")

    except Exception:
        print(f"\n  (Mobile URL: {url})\n")


def _generate_local_fallback_qr(url: str) -> bytes:
    """
    Local offline fallback using open-source qrcode library.
    Generates a clean styled QR with rounded modules.
    """
    import qrcode
    from qrcode.image.styledpil import StyledPilImage
    from qrcode.image.styles.moduledrawers.pil import RoundedModuleDrawer
    from qrcode.image.styles.colormasks import RadialGradiantColorMask

    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=12,
        border=3
    )
    qr.add_data(url)
    qr.make(fit=True)

    qr_img = qr.make_image(
        image_factory=StyledPilImage,
        module_drawer=RoundedModuleDrawer(),
        color_mask=RadialGradiantColorMask(
            back_color=(255, 255, 255),
            center_color=(2, 132, 199),   # Electric Cyan (#0284c7)
            edge_color=(15, 26, 48)       # Deep Oceanic (#0f1a30)
        )
    ).convert('RGBA')

    stream = io.BytesIO()
    qr_img.save(stream, format='PNG')
    return stream.getvalue()


def generate_branded_qr_png(url: str, output_path: str = None, shape: str = "star") -> bytes:
    cache_key = f"{url}:{shape}"
    if cache_key in _QR_CACHE:
        png_bytes = _QR_CACHE[cache_key]
        if output_path:
            with open(output_path, "wb") as f:
                f.write(png_bytes)
        return png_bytes

    # Attempt Cloud API call
    try:
        api_url = f"{HYDRA_CLOUD_QR_API}?url={urllib.parse.quote(url)}&app=file&shape={shape}&dot=0.50&dark=%23061a3d"
        req = urllib.request.Request(api_url, headers={"User-Agent": "WebFileManager/1.0"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            if resp.status == 200:
                png_bytes = resp.read()
                _QR_CACHE[cache_key] = png_bytes
                if output_path:
                    with open(output_path, "wb") as f:
                        f.write(png_bytes)
                return png_bytes
    except Exception as e:
        logger.debug(f"Cloud QR API unavailable, using local generator: {e}")

    # Fallback to local styled generator
    png_bytes = _generate_local_fallback_qr(url)
    _QR_CACHE[cache_key] = png_bytes
    if output_path:
        with open(output_path, "wb") as f:
            f.write(png_bytes)
    return png_bytes


def get_qr_svg(url: str) -> str:
    """
    Returns an SVG string of the QR code with High Error Correction.
    """
    try:
        import qrcode
        import qrcode.image.svg
        factory = qrcode.image.svg.SvgPathImage
        qr = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            border=2,
            image_factory=factory
        )
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image()
        stream = io.BytesIO()
        img.save(stream)
        return stream.getvalue().decode('utf-8')
    except Exception:
        return ""
