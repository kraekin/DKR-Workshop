"""Read-only Rev 1 RDRAM snapshots for runtime memory inspection.

Addresses: local ver/symbols/symbol_addrs.us.v80.txt. Structures: memory.h,
structs.h. Code mapping: ver/splat/dkr.us.v80.yaml (ROM1000 -> RAM80000400).
No process access, emulator control, memory writes or capacity approval.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import io
import struct
import zipfile
import zstandard

from src.core.rom import REV1_SHA1, AssetType, RomImage

RDRAM_SIZES = (4 * 1024 * 1024, 8 * 1024 * 1024)
MAX_CAPTURE_BYTES = 32 * 1024 * 1024
CODE_ADDRESSES = (0x8000EA54, 0x80070F7C, 0x800C6778)  # spawn, allocator, inflate
MEMORY_POOLS = 0x80123B00
NUMBER_OF_POOLS = 0x80123B40
OBJECT_POOL_POINTER = 0x8011B3E8
OBJECT_COUNT = 0x8011B3DC
OBJECT_LIST = 0x8011B3D8
OBJECT_MAP_IDS = 0x8011B428
OBJECT_MAP_POINTERS = 0x8011B430
HEADER_REFERENCES = 0x8011B3CC
LOADED_HEADERS = 0x8011B3C8
TEXTURE_CACHE = 0x801268C8
TEXTURE_COUNT = 0x801268D0
SPRITE_CACHE = 0x801268EC
SPRITE_COUNT = 0x801268F8
PARTICLES = (
    ('Triangle', 0x800E3230, 0x800E33DC),
    ('Rectangle', 0x800E323C, 0x800E33E0),
    ('Sprite', 0x800E3248, 0x800E33E4),
    ('Line', 0x800E3254, 0x800E33E8),
    ('Point', 0x800E3260, 0x800E33EC),
)


class RuntimeAuditError(ValueError):
    """Unsupported dump layout, different executable or inconsistent snapshot."""


@dataclass(frozen=True)
class PoolUsage:
    name: str
    data_bytes: int
    free_bytes: int
    largest_free: int
    descriptors: int
    maximum_descriptors: int
    free_blocks: tuple[int, ...]

    @property
    def split_allocations_remaining(self) -> int:
        return max(0, self.maximum_descriptors - 1 - self.descriptors)


@dataclass(frozen=True)
class CachedAsset:
    asset_id: int
    references: int


@dataclass(frozen=True)
class RuntimeSnapshot:
    digest: str
    byte_order: str
    object_count: int
    map_ids: tuple[int, int]
    pools: tuple[PoolUsage, ...]
    header_references: tuple[int, ...]
    sprites: tuple[CachedAsset, ...]
    textures: tuple[CachedAsset, ...]
    sprite_high_water: int
    texture_high_water: int
    particles: tuple[tuple[str, int, int], ...]
    source_format: str = 'Raw RDRAM'
    source_digest: str = ''
    core_digest: str = ''
    rdram_offset: int | None = None

    def to_text(self) -> str:
        lines = [
            'RDRAM SNAPSHOT — captured runtime memory usage',
            f'Normalized byte order: {self.byte_order}; SHA256 {self.digest}',
            f'Source format: {self.source_format}; source SHA256 {self.source_digest or self.digest}',
            'Three executable fingerprints match the original USA Rev 1 ROM.',
            'This does not identify the loaded asset/project edits or prove a worst-case peak.',
            f'Loaded map roles: {self.map_ids[0]}, {self.map_ids[1]}',
            f'Object list: {self.object_count}/512 entries including listed particles; {512-self.object_count} slots unoccupied NOW.',
            'Do not subtract particle counts again; they share that list.', '',
        ]
        if self.rdram_offset is not None:
            lines.extend((f'Decoded Core.bin SHA256: {self.core_digest}',
                          f'RDRAM offset 0x{self.rdram_offset:X}, located by three independent executable anchors.', ''))
        for pool in self.pools:
            lines.extend((f'{pool.name}: {pool.data_bytes-pool.free_bytes:,}/{pool.data_bytes:,} B occupied; '
                          f'{pool.free_bytes:,} B free; largest block {pool.largest_free:,} B.',
                          f'  Descriptors {pool.descriptors}/{pool.maximum_descriptors}; '
                          f'{pool.split_allocations_remaining} further splits before allocator refusal.',
                          '  Occupied includes pending frees; main-pool totals include the object subpool allocation.'))
        lines.extend(('', f'Sprite cache: {len(self.sprites)} active; high-water slots {self.sprite_high_water}/100.',
                      f'Texture cache: {len(self.textures)} active; high-water slots {self.texture_high_water}/700.',
                      'High-water slots include holes; cache entries are not additional object slots.', '',
                      'Particle buffers (live / configured; allocation stops at configured - 1):'))
        lines.extend(f'  {name}: {live}/{maximum}' for name, live, maximum in self.particles)
        lines.extend(('', 'Loaded object-header references (u8; 256 wraps):'))
        lines.extend(f'  Header {i}: {count}' for i, count in enumerate(self.header_references) if count)
        lines.extend(('', 'Sprite references (signed16):'))
        lines.extend(f'  Sprite {asset.asset_id}: {asset.references}' for asset in self.sprites)
        lines.extend(('', 'Texture references (unsigned8; 256 wraps):'))
        lines.extend(f'  Texture {asset.asset_id}: {asset.references}' for asset in self.textures)
        lines.extend(('', 'A snapshot cannot establish a safe extra-object count. Compare samples from',
                      'loading, races, multiplayer, weapons/drops, particles and transitions.',
                      'Observed minima/maxima are evidence for those samples, not guaranteed future reserves.'))
        return '\n'.join(lines)


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def offset(self, address: int, size: int) -> int:
        if address & 0xE0000000 not in (0x80000000, 0xA0000000):
            raise RuntimeAuditError('Snapshot contains a non-RDRAM pointer')
        offset = address & 0x1FFFFFFF
        if offset + size > len(self.data) or size < 0:
            raise RuntimeAuditError('Snapshot pointer leaves captured RDRAM')
        return offset

    def read(self, address: int, size: int) -> bytes:
        offset = self.offset(address, size)
        return self.data[offset:offset+size]

    def unpack(self, fmt: str, address: int) -> tuple[int, ...]:
        return struct.unpack(fmt, self.read(address, struct.calcsize(fmt)))

    def integer(self, address: int) -> int:
        return self.unpack('>i', address)[0]

    def pointer(self, address: int, size: int) -> int:
        pointer = self.unpack('>I', address)[0]
        if pointer & 3:
            raise RuntimeAuditError('Snapshot contains an unaligned pointer')
        self.offset(pointer, size)
        return pointer

    def pool(self, index: int, name: str, maximum: int) -> tuple[PoolUsage, int]:
        limit, count, slots, size = self.unpack('>iiIi', MEMORY_POOLS + 16 * index)
        if limit != maximum or not 1 <= count < limit or size <= limit * 20:
            raise RuntimeAuditError(f'{name}: inconsistent pool metadata')
        self.offset(slots, size)
        if slots & 15:
            raise RuntimeAuditError(f'{name}: unaligned descriptor table')
        data_start = (slots + limit * 20 + 15) & ~15
        end = data_start + size - limit * 20
        if end > slots + size:
            raise RuntimeAuditError(f'{name}: invalid data alignment')
        previous, current = -1, 0
        visited: set[int] = set()
        free: list[int] = []
        cursor = data_start
        while current != -1:
            if not 0 <= current < limit or current in visited:
                raise RuntimeAuditError(f'{name}: invalid or cyclic descriptor chain')
            visited.add(current)
            address, length, flags, prev, next_slot, _, _ = self.unpack('>IihhhhI', slots + 20 * current)
            if prev != previous or address != cursor or length <= 0 or length & 15 or flags not in range(8):
                raise RuntimeAuditError(f'{name}: inconsistent allocation descriptor')
            if address + length > end:
                raise RuntimeAuditError(f'{name}: allocation leaves the pool')
            if flags == 0:
                free.append(length)
            cursor = address + length
            previous, current = current, next_slot
        if len(visited) != count or cursor != end:
            raise RuntimeAuditError(f'{name}: descriptor count or total byte size mismatch')
        return PoolUsage(name, size - limit * 20, sum(free), max(free, default=0), count, limit, tuple(free)), slots


def _normalize_dump(data: bytes, rom: RomImage) -> tuple[bytes, str]:
    if len(data) not in RDRAM_SIZES:
        raise RuntimeAuditError('Use a raw 4 MiB or 8 MiB RDRAM dump; savestate containers are unsupported')
    if hashlib.sha1(rom.data).hexdigest() != REV1_SHA1:
        raise RuntimeAuditError('Executable comparison requires the original USA Rev 1 ROM')
    for width, name in ((1, 'Big-endian'), (2, '16-bit byte swap'), (4, '32-bit word swap')):
        if width == 1:
            normalized = data
        else:
            swapped = bytearray(len(data))
            for i in range(width):
                swapped[i::width] = data[width-i-1::width]
            normalized = bytes(swapped)
        if all(normalized[address-0x80000000:address-0x80000000+64] ==
               rom.data[address-0x80000400+0x1000:address-0x80000400+0x1040]
               for address in CODE_ADDRESSES):
            return normalized, name
    raise RuntimeAuditError('Dump does not match the Rev 1 executable (wrong ROM, byte order, container or code patches)')


def read_runtime_snapshot(data: bytes, rom: RomImage, header_count: int) -> RuntimeSnapshot:
    """Inspect a user-supplied dump without touching the editor session or game."""
    if type(header_count) is not int or header_count != rom.count(AssetType.OBJECTS):
        raise RuntimeAuditError('Invalid object-header table length')
    normalized, byte_order = _normalize_dump(data, rom)
    reader = _Reader(normalized)
    if reader.integer(NUMBER_OF_POOLS) != 1:  # source stores the last pool index.
        raise RuntimeAuditError('Capture a loaded level with main and object pools initialized')
    main_pool, _ = reader.pool(0, 'Main pool', 1600)
    object_pool, object_slots = reader.pool(1, 'Object pool', 512)
    if object_pool.data_bytes != 0x15800 or reader.pointer(OBJECT_POOL_POINTER, 512*20) != object_slots:
        raise RuntimeAuditError('Object pool does not match the verified Rev 1 allocation')
    count = reader.integer(OBJECT_COUNT)
    if not 0 <= count <= 512:
        raise RuntimeAuditError('Object count is outside its 512-entry runtime list')
    pointers = reader.pointer(OBJECT_LIST, 512*4)
    seen: set[int] = set()
    for i in range(count):
        pointer = reader.pointer(pointers + 4*i, 0x80)
        if pointer in seen:
            raise RuntimeAuditError('Object list contains duplicate pointers')
        seen.add(pointer)
    maps = list(reader.unpack('>2i', OBJECT_MAP_IDS))
    for index in range(2):
        pointer = reader.unpack('>I', OBJECT_MAP_POINTERS+4*index)[0]
        if pointer:
            reader.pointer(OBJECT_MAP_POINTERS+4*index, 0x3000)
        else:
            # A null map pointer is not a loaded role even if an ID remains.
            maps[index] = -1
    if any(not -1 <= value < rom.count(AssetType.LEVEL_OBJECT_MAPS) for value in maps):
        raise RuntimeAuditError('Snapshot map role is outside the ROM table')
    refs = reader.read(reader.pointer(HEADER_REFERENCES, header_count), header_count)
    headers = reader.pointer(LOADED_HEADERS, header_count*4)
    for i, reference in enumerate(refs):
        if reference:
            reader.pointer(headers + 4*i, 0x78)
    caches: list[tuple[CachedAsset, ...]] = []
    high_waters: list[int] = []
    for pointer_address, count_address, limit, offset, fmt in (
            (SPRITE_CACHE, SPRITE_COUNT, 100, 4, '>h'), (TEXTURE_CACHE, TEXTURE_COUNT, 700, 5, '>B')):
        high_water = reader.integer(count_address)
        if not 0 <= high_water <= limit:
            raise RuntimeAuditError('Asset-cache high-water count exceeds its allocation')
        cache = reader.pointer(pointer_address, limit*8)
        assets: list[CachedAsset] = []
        ids: set[int] = set()
        for i in range(high_water):
            asset_id = reader.integer(cache + 8*i)
            if asset_id == -1:
                continue
            if asset_id < 0 or asset_id in ids:
                raise RuntimeAuditError('Invalid or duplicate asset-cache ID')
            ids.add(asset_id)
            pointer = reader.pointer(cache + 8*i + 4, offset + struct.calcsize(fmt))
            instances = reader.unpack(fmt, pointer + offset)[0]
            if instances <= 0:
                raise RuntimeAuditError('Active asset has a zero/wrapped/negative reference count')
            assets.append(CachedAsset(asset_id, instances))
        caches.append(tuple(assets))
        high_waters.append(high_water)
    particles: list[tuple[str, int, int]] = []
    for name, current_address, maximum_address in PARTICLES:
        live, maximum = reader.integer(current_address), reader.integer(maximum_address)
        if not 0 <= maximum <= 512 or not 0 <= live <= max(0, maximum-1):
            raise RuntimeAuditError('Particle count exceeds its configured buffer')
        particles.append((name, live, maximum))
    return RuntimeSnapshot(hashlib.sha256(normalized).hexdigest(), byte_order, count, (maps[0], maps[1]),
                           (main_pool, object_pool), tuple(refs), caches[0], caches[1],
                           high_waters[0], high_waters[1], tuple(particles),
                           source_digest=hashlib.sha256(data).hexdigest())


def read_runtime_capture(data: bytes, rom: RomImage, header_count: int) -> RuntimeSnapshot:
    """Raw RDRAM or the specifically verified BizHawk2.10/Mupen state carrier.

    The RDRAM offset is derived from three ROM-code anchors, not a presumed
    serialization offset. Other state layouts/versions/ambiguous regions fail.
    Source archives are never extracted to disk or passed to an emulator.
    """
    if len(data) > MAX_CAPTURE_BYTES:
        raise RuntimeAuditError('Runtime capture exceeds the 32 MiB input limit')
    if not data.startswith(b'PK\x03\x04'):
        return read_runtime_snapshot(data, rom, header_count)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
            if len(names) > 16 or len(names) != len(set(names)) or not {'BizState 1.0', 'BizVersion.txt', 'Core.bin'} <= set(names):
                raise RuntimeAuditError('Unsupported or ambiguous BizHawk state container')
            version = archive.getinfo('BizVersion.txt')
            core_info = archive.getinfo('Core.bin')
            if any(info.flag_bits & 1 or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                   for info in (version, core_info)):
                raise RuntimeAuditError('Encrypted or unsupported ZIP members are not runtime captures')
            if version.file_size > 128 or core_info.file_size > MAX_CAPTURE_BYTES:
                raise RuntimeAuditError('Oversized BizHawk state member')
            if archive.read(version).strip() != b'Version 2.10':
                raise RuntimeAuditError('Only the inspected BizHawk 2.10 state carrier is supported')
            packed = archive.read(core_info)
        if not packed.startswith(b'\x28\xB5\x2F\xFD'):
            raise RuntimeAuditError('Unsupported BizHawk Core.bin compression')
        # The installed backend's limit is bytes (a32768 limit rejects a4MiB
        # window). Inspect the frame's byte-sized window independently too.
        if zstandard.get_frame_parameters(packed).window_size > MAX_CAPTURE_BYTES:
            raise RuntimeAuditError('Zstandard frame window exceeds the 32 MiB limit')
        with zstandard.ZstdDecompressor(max_window_size=MAX_CAPTURE_BYTES).stream_reader(io.BytesIO(packed)) as stream:
            core = stream.read(MAX_CAPTURE_BYTES + 1)
    except (zipfile.BadZipFile, KeyError, OSError, zstandard.ZstdError) as error:
        raise RuntimeAuditError(f'Invalid BizHawk state: {error}') from error
    if len(core) > MAX_CAPTURE_BYTES or core[4:12] != b'M64+SAVE' or core[12:16] != b'\x00\x01\x00\x00':
        raise RuntimeAuditError('Unsupported or oversized Mupen64Plus state payload')
    candidates: dict[tuple[int, int], bytes] = {}
    for width in (1, 2, 4):
        address = CODE_ADDRESSES[0]
        needle = rom.data[address-0x80000400+0x1000:address-0x80000400+0x1040]
        if width > 1:
            needle = b''.join(needle[i:i+width][::-1] for i in range(0, len(needle), width))
        hit = core.find(needle)
        hits = 0
        while hit >= 0:
            hits += 1
            if hits > 16:
                raise RuntimeAuditError('Too many ambiguous executable anchors in the state')
            base = hit - (address-0x80000000)
            if base >= 0:
                for size in RDRAM_SIZES:
                    if base + size > len(core):
                        continue
                    region = core[base:base+size]
                    try:
                        normalized, _ = _normalize_dump(region, rom)
                    except RuntimeAuditError:
                        continue
                    # osMemSize is source symbol80000318, not a state-container offset.
                    if struct.unpack_from('>I', normalized, 0x318)[0] == size:
                        candidates[base, size] = region
            hit = core.find(needle, hit+1)
    if len(candidates) != 1:
        raise RuntimeAuditError('State has no unique, complete Rev 1 RDRAM region')
    (base, _), region = next(iter(candidates.items()))
    return replace(read_runtime_snapshot(region, rom, header_count),
                   source_format='BizHawk 2.10 / Mupen64Plus savestate',
                   source_digest=hashlib.sha256(data).hexdigest(),
                   core_digest=hashlib.sha256(core).hexdigest(), rdram_offset=base)


def snapshot_summary(snapshots: tuple[RuntimeSnapshot, ...]) -> str:
    """Observed ranges grouped by map roles, never a reserve or approval."""
    lines = ['OBSERVED SAMPLES — no worst-case or structural-edit approval',
             'Game mode, vehicle, player count and edited asset identity are not certified.',
             'Same map roles alone do not establish matching gameplay conditions.', '']
    for maps in sorted({sample.map_ids for sample in snapshots}):
        group = [sample for sample in snapshots if sample.map_ids == maps]
        lines.extend((f'Map roles {maps}: {len(group)} samples.',
                      f'  Largest observed object list: {max(sample.object_count for sample in group)}/512.',
                      f'  Smallest observed object-pool free space: {min(sample.pools[1].free_bytes for sample in group):,} B.',
                      f'  Smallest observed largest free block: {min(sample.pools[1].largest_free for sample in group):,} B.',
                      f'  Highest observed object-pool descriptor count: {max(sample.pools[1].descriptors for sample in group)}/512.'))
    return '\n'.join(lines)
