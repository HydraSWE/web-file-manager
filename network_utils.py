"""
Network utilities for local Wi-Fi / LAN IP detection.
Uses UDP socket routing table query, hostname adapter inspection, and ipconfig fallback.
"""
import socket
import subprocess
import re
import logging

logger = logging.getLogger("file_manager.network")


def get_lan_ip() -> str:
    """
    Detects the active LAN / Wi-Fi IPv4 address of the host machine.
    """
    # Method 1: UDP socket routing table query (fastest, most accurate)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith('127.') and not ip.startswith('169.254.'):
            return ip
    except Exception as e:
        logger.debug(f"UDP route check failed: {e}")

    # Method 2: Hostname inspection
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if ip.startswith('192.168.') or ip.startswith('10.') or (ip.startswith('172.') and not ip.startswith('172.23.')):
                return ip
    except Exception as e:
        logger.debug(f"Hostname inspection failed: {e}")

    # Method 3: ipconfig fallback (Windows)
    try:
        output = subprocess.check_output("ipconfig", text=True, errors="ignore")
        matches = re.findall(r'IPv4 Address[.\s]+:\s*([0-9.]+)', output)
        for ip in matches:
            if ip.startswith('192.168.') or ip.startswith('10.'):
                return ip
        if matches:
            return matches[0]
    except Exception as e:
        logger.debug(f"ipconfig fallback failed: {e}")

    return '127.0.0.1'
