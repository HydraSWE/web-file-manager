"""
QR Code generation utilities for console display and web frontend.
"""
import sys
import io

def print_terminal_qr(url: str):
    """
    Prints an ASCII QR code to stdout for scanning with mobile cameras.
    """
    try:
        # Ensure stdout handles UTF-8 block characters on Windows
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        print("\n  [Scan with your Mobile Phone Camera to Open]")
        print("  " + "-" * 42)
        qr.print_ascii(invert=True)
        print("  " + "-" * 42 + "\n")
    except Exception as e:
        # Fallback if qrcode module fails
        print(f"\n  (Mobile URL: {url})\n")

def get_qr_svg(url: str) -> str:
    """
    Returns an SVG string of the QR code if requested by frontend or fallback.
    """
    try:
        import qrcode
        import qrcode.image.svg
        factory = qrcode.image.svg.SvgPathImage
        img = qrcode.make(url, image_factory=factory, border=2)
        stream = io.BytesIO()
        img.save(stream)
        return stream.getvalue().decode('utf-8')
    except Exception:
        return ""
