"""DKR Rare gzip, verified in src/gzip.c and DKRCompression.cpp locally."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

MAX_UNCOMPRESSED_SIZE: int = 64 * 1024 * 1024


class CompressionError(ValueError):
    """An invalid, truncated or oversized compressed asset."""


def decompress_rare(data: bytes, *, max_size: int = MAX_UNCOMPRESSED_SIZE) -> bytes:
    """Inflate LE u32 size + 09 + raw DEFLATE, allowing table alignment bytes.

    DKR has no 1172 signature. Never use byte sniffing to decide whether an
    arbitrary asset is compressed: that decision belongs to its section loader.
    The output limit is enforced during inflation, before a large allocation.
    """
    if len(data) < 6:
        raise CompressionError("Truncated DKR Rare gzip header or payload")
    declared = struct.unpack_from("<I", data)[0]
    if max_size < 0 or declared > max_size:
        raise CompressionError(f"Declared output size {declared} exceeds limit {max_size}")
    if data[4] != 9:
        raise CompressionError(f"Unsupported DKR compression level byte: 0x{data[4]:02X}")
    decoder = zlib.decompressobj(-15)
    try:
        output = decoder.decompress(data[5:], declared + 1)
    except zlib.error as error:
        raise CompressionError(f"Invalid raw DEFLATE stream: {error}") from error
    if len(output) != declared:
        raise CompressionError(f"Uncompressed size mismatch: declared {declared}, decoded {len(output)}")
    if not decoder.eof:
        raise CompressionError("Truncated DEFLATE stream or output larger than declared")
    # Game loaders ignore bytes after the stream. They can be alignment data,
    # not necessarily zero, in original ROM tables.
    return output


def decode_asset(data: bytes, *, compressed: bool) -> bytes:
    """Explicitly decode or pass through an entry according to section metadata."""
    return decompress_rare(data) if compressed else data


@dataclass(frozen=True)
class InplaceAudit:
    """Per-stream source-model check, not a runtime object-capacity guarantee."""

    decoded: int
    stored: int
    read_bytes: int
    minimum_gap: int
    huft_bytes: int
    blocks: tuple[int, ...]


@dataclass(frozen=True)
class _Code:
    bits: int
    operation: int
    value: int = 0
    table: list[_Code] | None = None


# hasm/gzip_asm.s: gzip_cplens/cplext, cpdist/cpdext and border.
_LENGTH_BASE = (3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27,
                31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258)
_LENGTH_EXTRA = (0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2,
                 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0)
_DISTANCE_BASE = (1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129,
                  193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145,
                  8193, 12289, 16385, 24577)
_DISTANCE_EXTRA = (0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6,
                   6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13)
_CODE_ORDER = (16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15)


class _InplaceInflater:
    """Byte-access model of gzip.c and hasm/gzip_asm.s, with strict guards.

    Mirrors huft_build's table widths/allocation, root lookahead, buffered bits,
    literals, forward match copies and stored copies. Checks against independent
    zlib output. No MIPS execution or claim about unrelated engine resources.
    """

    def __init__(self, data: bytes, workspace: int, slack: int) -> None:
        self.expected = decompress_rare(data, max_size=workspace)
        self.data = data
        self.start = len(self.expected) - len(data) + slack
        if self.start < 0 or len(self.expected) + slack > workspace:
            raise CompressionError('In-place staging exceeds the map workspace')
        self.reader = 5  # gzip_inflate skips the LE-size/09 header.
        self.buffer = 0
        self.bits = 0
        self.output = bytearray()
        self.gap = workspace
        self.heap_entries = 0
        self.heap_peak = 0

    def byte(self) -> int:
        if self.reader >= len(self.data):
            raise CompressionError('Game inflater lookahead leaves the stored stream/padding')
        if self.start + self.reader < len(self.output):
            raise CompressionError('In-place output overwrites unread compressed bytes')
        value = self.data[self.reader]
        self.reader += 1
        return value

    def need(self, count: int) -> None:
        while self.bits < count:
            self.buffer |= self.byte() << self.bits
            self.bits += 8

    def take(self, count: int) -> int:
        self.need(count)
        result = self.buffer & ((1 << count) - 1)
        self.buffer >>= count
        self.bits -= count
        return result

    def put(self, value: int) -> None:
        if len(self.output) >= len(self.expected):
            raise CompressionError('Game inflater writes beyond the declared output')
        gap = self.start + self.reader - (len(self.output) + 1)
        self.gap = min(self.gap, gap)
        if self.reader < len(self.data) and gap < 0:
            raise CompressionError('In-place output overwrites unread compressed bytes')
        self.output.append(value)

    def tree(self, lengths: tuple[int, ...], root: int, simple: int,
             bases: tuple[int, ...] = (), extras: tuple[int, ...] = ()) -> tuple[list[_Code], int]:
        """Port gzip_huft_build's table topology, including link entries."""
        counts = [lengths.count(i) for i in range(17)]
        if counts[0] == len(lengths):
            return [], 0
        low = next(i for i in range(1, 17) if counts[i])
        high = max(lengths)
        root = max(low, min(root, high))
        missing = 1 << low
        for width in range(low, high):
            missing = (missing - counts[width]) << 1
        missing -= counts[high]
        if missing < 0:
            raise CompressionError('Oversubscribed game Huffman table')
        if missing and counts[0]:
            # The local C leaves `n = x[g]` commented out. Its dummy-code loop
            # can read uninitialized v[] slots when zero-length symbols exist.
            # Do not certify that case using a cleaned-up Python construction.
            raise CompressionError('Incomplete game Huffman table would read uninitialized symbols')
        counts[high] += missing
        values = [i for width in range(1, high + 1) for i, size in enumerate(lengths) if size == width]
        stack: list[list[_Code]] = []
        prefixes = [0] * 17
        code = position = 0
        level, offset = -1, -root
        table: list[_Code] = []
        first: list[_Code] = []
        table_size = 0
        for width in range(low, high + 1):
            remaining = counts[width]
            while remaining:
                remaining -= 1
                while width > offset + root:
                    level += 1
                    offset += root
                    maximum = min(high - offset, root)
                    sub_width = width - offset
                    available = 1 << sub_width
                    if available > remaining + 1:
                        available -= remaining + 1
                        next_width = width
                        sub_width += 1
                        while sub_width < maximum:
                            available <<= 1
                            next_width += 1
                            if available <= counts[next_width]:
                                break
                            available -= counts[next_width]
                            sub_width += 1
                    table_size = 1 << sub_width
                    self.heap_entries += table_size + 1
                    self.heap_peak = max(self.heap_peak, self.heap_entries * 8)
                    if self.heap_peak > 0x2800:
                        raise CompressionError('Game Huffman workspace exceeds 0x2800 bytes')
                    table = [_Code(0, 99)] * table_size
                    if level < len(stack):
                        stack[level] = table
                    else:
                        stack.append(table)
                    if level:
                        prefixes[level] = code
                        stack[level - 1][code >> (offset - root)] = _Code(root, 16 + sub_width, table=table)
                    else:
                        first = table
                if position >= len(values):
                    entry = _Code(width - offset, 99)
                else:
                    value = values[position]
                    position += 1
                    if value < simple:
                        entry = _Code(width - offset, 16 if value < 256 else 15, value)
                    elif value - simple < len(bases):
                        entry = _Code(width - offset, extras[value - simple], bases[value - simple])
                    else:
                        entry = _Code(width - offset, 99)
                for index in range(code >> offset, table_size, 1 << (width - offset)):
                    table[index] = entry
                bit = 1 << (width - 1)
                while code & bit:
                    code ^= bit
                    bit >>= 1
                code ^= bit
                while (code & ((1 << offset) - 1)) != prefixes[level]:
                    level -= 1
                    offset -= root
        return first, root

    def symbol(self, tree: tuple[list[_Code], int]) -> _Code:
        table, width = tree
        if not table:
            raise CompressionError('Game inflater requires a missing Huffman table')
        while True:
            self.need(width)
            entry = table[self.buffer & ((1 << width) - 1)]
            if entry.operation == 99:
                raise CompressionError('Invalid game Huffman code')
            self.take(entry.bits)
            if entry.operation <= 16:
                return entry
            width = entry.operation - 16
            if entry.table is None:
                raise CompressionError('Missing game Huffman subtable')
            table = entry.table

    def dynamic(self) -> tuple[tuple[list[_Code], int], tuple[list[_Code], int]]:
        literals, distances, codes = self.take(5) + 257, self.take(5) + 1, self.take(4) + 4
        if literals > 286 or distances > 30:
            raise CompressionError('Reserved game literal/distance table size')
        lengths = [0] * 19
        for index in range(codes):
            lengths[_CODE_ORDER[index]] = self.take(3)
        code_tree = self.tree(tuple(lengths), 7, 19)
        expanded: list[int] = []
        while len(expanded) < literals + distances:
            value = self.symbol(code_tree).value
            if value < 16:
                expanded.append(value)
                continue
            if value == 16:
                if not expanded:
                    raise CompressionError('Huffman repeat has no preceding length')
                count, value = self.take(2) + 3, expanded[-1]
            elif value == 17:
                count, value = self.take(3) + 3, 0
            else:
                count, value = self.take(7) + 11, 0
            expanded.extend([value] * count)
            if len(expanded) > literals + distances:
                raise CompressionError('Huffman repeat overruns the game length table')
        if expanded[256] == 0:
            raise CompressionError('Missing game end-of-block code')
        return (self.tree(tuple(expanded[:literals]), 9, 257, _LENGTH_BASE, _LENGTH_EXTRA),
                self.tree(tuple(expanded[literals:]), 6, 0, _DISTANCE_BASE, _DISTANCE_EXTRA))

    def run(self) -> InplaceAudit:
        blocks: list[int] = []
        final = 0
        while not final:
            self.heap_entries = 0  # gzip_inflate_block resets the heap each block.
            final, kind = self.take(1), self.take(2)
            blocks.append(kind)
            if kind == 0:
                self.take(self.bits & 7)
                count = self.take(16)
                if self.take(16) != count ^ 0xFFFF:
                    raise CompressionError('Invalid stored-block complement')
                # The handwritten stored-copy loop has no zero-length guard.
                if count == 0:
                    raise CompressionError('Zero-length stored block is unsafe in the game copy loop')
                if self.bits:
                    raise CompressionError('Unexpected buffered bytes before game stored copy')
                for _ in range(count):
                    self.put(self.byte())
                continue
            if kind == 1:
                literal_tree = self.tree((8,) * 144 + (9,) * 112 + (7,) * 24 + (8,) * 8,
                                         7, 257, _LENGTH_BASE, _LENGTH_EXTRA)
                distance_tree = self.tree((5,) * 30, 5, 0, _DISTANCE_BASE, _DISTANCE_EXTRA)
            elif kind == 2:
                literal_tree, distance_tree = self.dynamic()
            else:
                raise CompressionError('Reserved DEFLATE block type')
            while True:
                entry = self.symbol(literal_tree)
                if entry.operation == 16:
                    self.put(entry.value)
                elif entry.operation == 15:
                    break
                else:
                    count = entry.value + self.take(entry.operation)
                    distance = self.symbol(distance_tree)
                    back = distance.value + self.take(distance.operation)
                    if not 1 <= back <= len(self.output):
                        raise CompressionError('Game inflater back-reference precedes output')
                    for _ in range(count):
                        self.put(self.output[-back])
        if self.output != self.expected:
            raise CompressionError('Source-model inflater disagrees with independent zlib output')
        return InplaceAudit(len(self.output), len(self.data), self.reader, self.gap, self.heap_peak, tuple(blocks))


def audit_inplace_rare(data: bytes, *, workspace: int = 0x3000, slack: int = 0x20) -> InplaceAudit:
    """Verify one staged stream using the local game's inflater access order.

    Rejects overwritten unread input, out-of-span lookahead, invalid copies and
    Huffman heap overflow. This closes only a stream-loading check, never live
    object budgets or gameplay validation. Untouched ROM assets need no rewrite.
    """
    if type(workspace) is not int or type(slack) is not int or workspace <= 0 or slack < 0:
        raise CompressionError('Invalid in-place workspace or staging slack')
    return _InplaceInflater(data, workspace, slack).run()
