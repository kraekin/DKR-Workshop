"""BPS1 and xdelta-compatible VCDIFF export, independent of Qt/native tools.

BPS numbers/actions/checksums follow the BPS format (reference: Floating IPS).
VCDIFF uses RFC3284's default ADD/COPY table and xdelta3's Adler32 extension.
The decoders below validate our generated dialect; they are not an import UI.
"""
from __future__ import annotations

from collections.abc import Iterator
import struct
import zlib

MAX_SIZE = 64 * 1024 * 1024


def _bounded(source: bytes, target: bytes) -> None:
    if len(source) > MAX_SIZE or len(target) > MAX_SIZE:
        raise ValueError("Patch input exceeds the 64 MiB export bound")


def _common(source: bytes, offset: int, target: bytes, position: int) -> int:
    limit = min(len(source) - offset, len(target) - position)
    size = 0
    while size + 4096 <= limit and source[offset + size:offset + size + 4096] == target[position + size:position + size + 4096]:
        size += 4096
    low, high = size, min(limit, size + 4096)
    while low < high:
        middle = (low + high + 1) // 2
        if source[offset + size:offset + middle] == target[position + size:position + middle]:
            low = middle
        else:
            high = middle - 1
    return low


def _runs(source: bytes, target: bytes) -> Iterator[tuple[bool, int, int, int]]:
    """Bounded sampled source dictionary also matches relocated unchanged assets."""
    _bounded(source, target)
    index: dict[bytes, int] | None = None
    position = literal = 0
    while position < len(target):
        offset, size = position, 0
        if source[position:position + 16] == target[position:position + 16] and position < len(source):
            size = _common(source, position, target, position)
        if size < 16 and position + 16 <= len(target):
            if index is None:
                index = {}
                for start in range(0, max(0, len(source) - 15), 32):
                    index.setdefault(source[start:start + 16], start)
            candidate = index.get(target[position:position + 16])
            if candidate is not None:
                length = _common(source, candidate, target, position)
                if length > size:
                    offset, size = candidate, length
        if size >= 16 or (size and position + size == len(target)):
            if literal < position:
                yield False, 0, literal, position - literal
            yield True, offset, position, size
            position += size
            literal = position
        else:
            position += 1
    if literal < position:
        yield False, 0, literal, position - literal


def _bps_number(number: int) -> bytes:
    result = bytearray()
    while True:
        low = number & 127
        number >>= 7
        if not number:
            result.append(low | 128)
            return bytes(result)
        result.append(low)
        number -= 1


def _vcd_number(number: int) -> bytes:
    result = bytearray((number & 127,))
    while number >> 7:
        number >>= 7
        result.insert(0, (number & 127) | 128)
    return bytes(result)


def encode_bps(source: bytes, target: bytes, metadata: bytes = b"") -> bytes:
    if len(metadata) > 65536:
        raise ValueError("Patch metadata is too large")
    out = bytearray(b"BPS1" + _bps_number(len(source)) + _bps_number(len(target)) + _bps_number(len(metadata)) + metadata)
    relative = 0
    for copy, offset, position, length in _runs(source, target):
        action = 0 if copy and offset == position else 2 if copy else 1
        out.extend(_bps_number(((length - 1) << 2) | action))
        if action == 2:
            delta = offset - relative
            out.extend(_bps_number((abs(delta) << 1) | int(delta < 0)))
            relative = offset + length
        elif action == 1:
            out.extend(target[position:position + length])
    out.extend(struct.pack("<II", zlib.crc32(source), zlib.crc32(target)))
    out.extend(struct.pack("<I", zlib.crc32(out)))
    return bytes(out)


def encode_xdelta(source: bytes, target: bytes) -> bytes:
    """One VCD_SOURCE window; default SELF addresses and xdelta Adler32 checksum."""
    data, instructions, addresses = bytearray(), bytearray(), bytearray()
    for copy, offset, position, length in _runs(source, target):
        instructions.append(19 if copy else 1)
        instructions.extend(_vcd_number(length))
        if copy:
            addresses.extend(_vcd_number(offset))
        else:
            data.extend(target[position:position + length])
    delta = (_vcd_number(len(target)) + b"\0" + _vcd_number(len(data))
             + _vcd_number(len(instructions)) + _vcd_number(len(addresses))
             + struct.pack(">I", zlib.adler32(target)) + data + instructions + addresses)
    window = b"\x05" + _vcd_number(len(source)) + b"\0" if source else b"\x04"
    return bytes(b"\xd6\xc3\xc4\0\0" + window + _vcd_number(len(delta)) + delta)


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data, self.position = data, 0

    def take(self, count: int) -> bytes:
        if count < 0 or self.position + count > len(self.data):
            raise ValueError("Truncated patch data")
        result = self.data[self.position:self.position + count]
        self.position += count
        return result

    def number(self, *, bps: bool = False) -> int:
        value, shift = 0, 1
        for _ in range(10):
            byte = self.take(1)[0]
            if bps:
                value += (byte & 127) * shift
                if byte & 128:
                    return value
                shift <<= 7
                value += shift
            else:
                value = value * 128 + (byte & 127)
                if not byte & 128:
                    return value
        raise ValueError("Patch integer is too large")


def apply_bps(source: bytes, patch: bytes) -> bytes:
    if len(patch) < 19 or patch[:4] != b"BPS1" or zlib.crc32(patch[:-4]) != struct.unpack_from("<I", patch, len(patch) - 4)[0]:
        raise ValueError("Invalid BPS header or patch checksum")
    source_crc, target_crc = struct.unpack_from("<II", patch, len(patch) - 12)
    reader = _Reader(patch[4:-12])
    if reader.number(bps=True) != len(source) or source_crc != zlib.crc32(source):
        raise ValueError("BPS requires the exact original source ROM")
    length = reader.number(bps=True)
    if length > MAX_SIZE:
        raise ValueError("Patch target exceeds export bound")
    reader.take(reader.number(bps=True))
    out = bytearray()
    relative = [0, 0]
    while len(out) < length:
        instruction = reader.number(bps=True)
        action, size = instruction & 3, (instruction >> 2) + 1
        if size > length - len(out):
            raise ValueError("BPS instruction exceeds target size")
        if action == 0:
            start = len(out)
            if start + size > len(source):
                raise ValueError("BPS SourceRead exceeds source")
            out.extend(source[start:start + size])
        elif action == 1:
            out.extend(reader.take(size))
        else:
            delta = reader.number(bps=True)
            slot = action - 2
            relative[slot] += -(delta >> 1) if delta & 1 else delta >> 1
            start = relative[slot]
            if start < 0 or (action == 2 and start + size > len(source)) or (action == 3 and start >= len(out)):
                raise ValueError("BPS copy address exceeds its source")
            if action == 2:
                out.extend(source[start:start + size])
            else:
                for i in range(size):
                    out.append(out[start + i])
            relative[slot] += size
    if reader.position != len(reader.data) or zlib.crc32(out) != target_crc:
        raise ValueError("BPS target checksum or instruction length mismatch")
    return bytes(out)


def apply_generated_xdelta(source: bytes, patch: bytes) -> bytes:
    """Validate our uncompressed default-table VCDIFF dialect before publishing."""
    reader = _Reader(patch)
    if reader.take(5) != b"\xd6\xc3\xc4\0\0":
        raise ValueError("Invalid generated VCDIFF header")
    window = reader.take(1)[0]
    if window not in (4, 5):
        raise ValueError("Unsupported generated VCDIFF window")
    if window == 5 and (reader.number() != len(source) or reader.number() != 0):
        raise ValueError("VCDIFF source window mismatch")
    delta = _Reader(reader.take(reader.number()))
    if reader.position != len(reader.data):
        raise ValueError("Unexpected VCDIFF trailing data")
    length = delta.number()
    if length > MAX_SIZE or delta.take(1) != b"\0":
        raise ValueError("Invalid VCDIFF target size or compression flags")
    data_length, instructions_length, addresses_length = delta.number(), delta.number(), delta.number()
    checksum = struct.unpack(">I", delta.take(4))[0]
    data, instructions, addresses = (_Reader(delta.take(n)) for n in (data_length, instructions_length, addresses_length))
    if delta.position != len(delta.data):
        raise ValueError("VCDIFF section length mismatch")
    out = bytearray()
    while instructions.position < len(instructions.data):
        opcode, size = instructions.take(1)[0], instructions.number()
        if not size or size > length - len(out):
            raise ValueError("VCDIFF instruction exceeds target size")
        if opcode == 1:
            out.extend(data.take(size))
        elif opcode == 19:
            offset = addresses.number()
            if window != 5 or offset + size > len(source):
                raise ValueError("VCDIFF copy exceeds source window")
            out.extend(source[offset:offset + size])
        else:
            raise ValueError("Unsupported generated VCDIFF instruction")
    if len(out) != length or zlib.adler32(out) != checksum or data.position != len(data.data) or addresses.position != len(addresses.data):
        raise ValueError("VCDIFF target checksum or section consumption mismatch")
    return bytes(out)
