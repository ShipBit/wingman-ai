"""Dashboard sharing, using Accountant's chat image format and QR library."""
import base64
import io
import logging
import socket


def get_lan_ip() -> str:
    """Find the outbound interface without sending application data."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(('8.8.8.8', 80))
            address = sock.getsockname()[0]
            return address if not address.startswith('127.') else ''
    except OSError:
        return ''


def qr_png_base64(url: str) -> str | None:
    """Generate the PNG attachment understood by Wingman's chat renderer."""
    try:
        from PIL import Image, ImageDraw
        if __package__:
            from .accountant_ui.qrcodegen import QrCode
        else:
            from accountant_ui.qrcodegen import QrCode
        qr = QrCode.encode_text(url, QrCode.Ecc.LOW)
        size, scale, border = qr.get_size(), 3, 4
        image = Image.new('RGB', ((size + 2 * border) * scale,) * 2, 'white')
        draw = ImageDraw.Draw(image)
        for y in range(size):
            for x in range(size):
                if qr.get_module(x, y):
                    left, top = (x + border) * scale, (y + border) * scale
                    draw.rectangle((left, top, left + scale - 1, top + scale - 1), fill='black')
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        return base64.b64encode(buffer.getvalue()).decode('ascii')
    except Exception:
        logging.getLogger(__name__).warning('Accountant QR generation failed', exc_info=True)
        return None
