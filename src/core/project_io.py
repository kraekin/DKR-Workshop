"""Versioned project serialization and dependency-ordered loading, without Qt/GL.

The session owns editable state/history; this module owns the on-disk schema.
Load into a private session and validate structural maps before header references.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from src.core.editing import EditError, EditSession, AssetKey, ObjectKey, WRITABLE_ASSETS, _integer, _raw_map
from src.core.geometry import geometry_changed
from src.core.image_assets import IMAGE_SECTIONS, TEXTURE_SECTIONS
from src.core.level_header import LevelNames
from src.core.materials import validate_material_edit
from src.core.minimap import validate_model_edit
from src.core.model_editing import MODEL_ASSETS
from src.core.object_structure import MAX_IDENTITY, state_document, state_from_document, validate_capacity
from src.core.rom import REV1_SHA1, AssetType, RomImage, read_json
from src.core.track_artwork import MAX_CUSTOM_TEXTURES
from src.core.track_import import validate_compiled_track


def project_document(session: EditSession, selected_level: int = 0) -> dict[str, Any]:
    session._require_idle()
    _integer(selected_level, 0, 64)
    edits: list[dict[str, Any]] = []
    for map_id in session.modified_maps:
        if map_id in session._structures:
            continue
        for original, current in zip(session.original_map(map_id).objects, session.current_map(map_id).objects):
            if original.raw_data == current.raw_data:
                continue
            assert original.raw_data is not None and current.raw_data is not None
            edits.append({"map_id": map_id, "entry_index": current.index, "object_id": original.object_id,
                          "base_entry_sha1": hashlib.sha1(original.raw_data).hexdigest(),
                          "bytes": [{"offset": i, "value": b} for i, (a, b) in enumerate(zip(original.raw_data, current.raw_data)) if a != b]})
    asset_edits = []
    for (section, index), raw in sorted(session._assets.items()):
        if section==AssetType.LEVEL_NAMES:continue  # Variable-length names use the v12 records below.
        if section == AssetType.OBJECT_MODELS and len(raw) != len(session.original_asset(section, index)):
            continue  # Canonical variable layouts use v15 records below.
        if section==AssetType.LEVEL_MODELS and index in session._track_imports:
            continue
        base = session.original_asset(section, index)
        asset_edits.append({"section": int(section), "index": index,
                            "encoding": "texture-decoded" if section in TEXTURE_SECTIONS else "rare-decoded" if section == AssetType.LEVEL_MODELS or section in MODEL_ASSETS else "raw",
                            "base_asset_sha1": hashlib.sha1(base).hexdigest(),
                            "bytes": [{"offset": i, "value": b} for i, (a, b) in enumerate(zip(base, raw)) if a != b]})
    notes = [{"map_id": key[0], "entry_index": key[1], "field": key[2],
              "base_entry_sha1": hashlib.sha1(session._note_base(key[:2])).hexdigest(),
              "text": value.text, "result": value.result} for key, value in sorted(session._notes.items())]
    geometry = any(section == AssetType.LEVEL_MODELS and geometry_changed(session.track_base(index), raw)
                   for (section, index), raw in session._assets.items())
    name_edits=[{'index':i,'encoding':'raw-names','base_asset_sha1':hashlib.sha1(session.original_asset(s,i)).hexdigest(),'data':raw.hex()}
        for (s,i),raw in sorted(session._assets.items()) if s==AssetType.LEVEL_NAMES]
    global_edits = any(section == AssetType.OBJECTS for section, _ in session._assets)
    model_edits = any(section in MODEL_ASSETS for section, _ in session._assets)
    rebuilds = [{'index': i, 'base_asset_sha1': hashlib.sha1(session.original_asset(s, i)).hexdigest(),
        'encoding': 'static-model', 'data': raw.hex()} for (s, i), raw in sorted(session._assets.items())
        if s == AssetType.OBJECT_MODELS and len(raw) != len(session.original_asset(s, i))]
    document = {"format": "dkr-object-project", "version": 15 if rebuilds else 14 if model_edits else 13 if global_edits else 12 if name_edits else 11 if session._custom_textures else max((session.track_import_version(i) for i in session._track_imports),default=0) if session._track_imports else 8 if geometry else 7 if session._structures else 6,
            "base_rom": {"sha1": REV1_SHA1, "path": str(session.rom.source_path or "")},
            "selected_level": selected_level, "edits": edits, "asset_edits": asset_edits,
            "research": {"experiment": session.experiment_name, "notes": notes}}
    if name_edits:document['course_names']=name_edits
    if rebuilds:document['object_rebuilds'] = rebuilds
    if session._structures:
        document['structural_maps'] = [state_document(session, session._map_state(m),
            session._next_identity.get(m, len(session.original_map(m).objects))) for m in sorted(session._structures)]
    if session._custom_textures:
        document['custom_textures'] = [raw.hex() for raw in session._custom_textures]
    if session._track_imports:
        document['track_imports'] = [{'index':index,
            'base_asset_sha1':hashlib.sha1(session.original_asset(AssetType.LEVEL_MODELS,index)).hexdigest(),
            'baseline':baseline.hex(),'current':session.current_asset(AssetType.LEVEL_MODELS,index).hex()}
            for index,baseline in sorted(session._track_imports.items())]
    return document



def load_project(session_type: type[EditSession], path: Path, *, base_path: Path | None = None) -> EditSession:
    document = read_json(path)
    if (any(key in document for key in ('structural_edits', 'stable_entries'))
            or ('structural_maps' in document and document.get('version') not in (7, 8, 9, 10, 11, 12, 13, 14, 15))
            or ('track_imports' in document and document.get('version') not in (9,10,11,12,13,14,15))
            or ('custom_textures' in document and document.get('version') not in (11,12,13,14,15))
            or ('course_names' in document and document.get('version') not in (12,13,14,15))
            or ('object_rebuilds' in document and document.get('version') != 15)):
        raise EditError('Legacy structural drafts cannot be installed in editor projects')
    if document.get("format") != "dkr-object-project" or type(document.get("version")) is not int or document["version"] not in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15):
        raise EditError("Unsupported DKR object project format/version")
    base = document.get("base_rom")
    if not isinstance(base, dict) or base.get("sha1") != REV1_SHA1 or not isinstance(base.get("path"), str) or not base["path"]:
        raise EditError("Project does not identify an original USA Rev 1 base ROM")
    source_path = base_path or Path(base["path"])
    if not source_path.is_absolute():
        source_path = path.resolve().parent / source_path
    session = session_type(RomImage.from_file(source_path))
    pool = document.get('custom_textures',[])
    if not isinstance(pool,list) or len(pool)>MAX_CUSTOM_TEXTURES:
        raise EditError('Invalid custom texture pool')
    decoded = []
    for value in pool:
        if not isinstance(value,str) or not 0<len(value)<=2*(4096+32) or len(value)%2:
            raise EditError('Invalid custom texture binary size')
        try:decoded.append(bytes.fromhex(value))
        except ValueError as error:raise EditError('Invalid custom texture hex') from error
    session._set_texture_pool(tuple(decoded))
    edits = document.get("edits")
    if not isinstance(edits, list) or len(edits) > 9426:
        raise EditError("Invalid project edit list")
    keys: set[ObjectKey] = set()
    for edit in edits:
        if not isinstance(edit, dict):
            raise EditError("Invalid project object edit")
        key = (_integer(edit.get("map_id"), 0, 137), _integer(edit.get("entry_index"), 0, 9425))
        if key in keys:
            raise EditError("Duplicate project object edit")
        keys.add(key)
        obj = session.object(key)
        assert obj.raw_data is not None and obj.offset is not None
        if type(edit.get("object_id")) is not int or edit["object_id"] != obj.object_id or edit.get("base_entry_sha1") != hashlib.sha1(obj.raw_data).hexdigest():
            raise EditError("Project object does not match its base entry")
        changes = edit.get("bytes")
        if not isinstance(changes, list) or len(changes) > obj.byte_size - 2:
            raise EditError("Invalid project byte changes")
        offsets: set[int] = set()
        raw = bytearray(obj.raw_data)
        for change in changes:
            if not isinstance(change, dict):
                raise EditError("Invalid project byte edit")
            offset = _integer(change.get("offset"), 2, obj.byte_size - 1)
            if offset in offsets:
                raise EditError("Duplicate project byte offset")
            offsets.add(offset)
            raw[offset] = _integer(change.get("value"), 0, 255)
        model = _raw_map(session.current_map(key[0]))
        session._install(key[0], model[:obj.offset] + raw + model[obj.offset + obj.byte_size:])
    asset_edits = document.get("asset_edits", [])
    if not isinstance(asset_edits, list) or len(asset_edits) > sum(session.asset_source.count(section) for section in WRITABLE_ASSETS) or (document["version"] == 1 and asset_edits):
        raise EditError("Invalid project asset edit list")
    asset_keys: set[AssetKey] = set()
    headers: list[tuple[AssetKey, bytes]] = []
    for edit in asset_edits:
        if not isinstance(edit, dict):
            raise EditError("Invalid project asset edit")
        section = _integer(edit.get("section"), 0, 49)
        if section not in WRITABLE_ASSETS or section==AssetType.LEVEL_NAMES or (section in MODEL_ASSETS and document['version'] < 14) or (section == AssetType.OBJECTS and document['version'] < 13) or (section == AssetType.LEVEL_MODELS and document["version"] < 4) or (section in IMAGE_SECTIONS and document["version"] < 6):
            raise EditError("Editing this asset type is not enabled")
        if edit.get("encoding", "raw") != ("texture-decoded" if section in TEXTURE_SECTIONS else "rare-decoded" if section == AssetType.LEVEL_MODELS or section in MODEL_ASSETS else "raw"):
            raise EditError("Invalid asset edit encoding")
        key = (AssetType(section), _integer(edit.get("index"), 0, session.asset_source.count(AssetType(section)) - 1))
        if key in asset_keys:
            raise EditError("Duplicate project asset edit")
        asset_keys.add(key)
        original = session.original_asset(*key)
        if edit.get("base_asset_sha1") != hashlib.sha1(original).hexdigest():
            raise EditError("Project asset does not match its base")
        changes = edit.get("bytes")
        if not isinstance(changes, list) or len(changes) > len(original):
            raise EditError("Invalid project asset byte changes")
        raw = bytearray(original)
        offsets: set[int] = set()
        for change in changes:
            if not isinstance(change, dict):
                raise EditError("Invalid project asset byte edit")
            offset = _integer(change.get("offset"), 0, len(raw) - 1)
            if offset in offsets:
                raise EditError("Duplicate project asset byte offset")
            offsets.add(offset)
            raw[offset] = _integer(change.get("value"), 0, 255)
        if section == AssetType.LEVEL_MODELS and document["version"] == 4:
            try:
                validate_material_edit(original, bytes(raw), session.material_references)
            except ValueError as error:
                raise EditError(str(error)) from error
        if section == AssetType.LEVEL_MODELS and 5 <= document['version'] <= 7:
            try:
                validate_model_edit(original, bytes(raw), session.material_references, session.minimap_references)
            except ValueError as error:
                raise EditError(str(error)) from error
        if section == AssetType.LEVEL_HEADERS:
            # These references can point to checkpoint sets created in structural_maps.
            headers.append((key, bytes(raw)))
        else:
            session._install_asset(key, bytes(raw))
    object_rebuilds = document.get('object_rebuilds', [])
    if not isinstance(object_rebuilds, list) or len(object_rebuilds) > session.rom.count(AssetType.OBJECT_MODELS):
        raise EditError('Invalid static object rebuild list')
    from src.core.object_rebuild import MAX_MODEL_BYTES, validate_rebuild
    for row in object_rebuilds:
        if not isinstance(row, dict):
            raise EditError('Invalid static object rebuild record')
        index = _integer(row.get('index'), 0, session.rom.count(AssetType.OBJECT_MODELS)-1)
        key = AssetType.OBJECT_MODELS, index
        original = session.original_asset(*key)
        if key in asset_keys or row.get('encoding') != 'static-model' or row.get('base_asset_sha1') != hashlib.sha1(original).hexdigest():
            raise EditError('Duplicate/mixed static model edit or incorrect base/encoding')
        value = row.get('data')
        if not isinstance(value, str) or not 0 < len(value) <= 2*MAX_MODEL_BYTES or len(value) % 2:
            raise EditError('Invalid static model binary size')
        try:
            raw = bytes.fromhex(value)
        except ValueError as error:
            raise EditError('Invalid static model hex') from error
        validate_rebuild(session.rom, index, original, raw)
        session._install_asset(key, raw)
        asset_keys.add(key)
    imports = document.get('track_imports',[])
    if not isinstance(imports,list) or len(imports)>session.rom.count(AssetType.LEVEL_MODELS):
        raise EditError('Invalid imported track list')
    imported_ids: set[int] = set()
    for row in imports:
        if not isinstance(row,dict):
            raise EditError('Invalid imported track record')
        index = _integer(row.get('index'),0,session.rom.count(AssetType.LEVEL_MODELS)-1)
        key = AssetType.LEVEL_MODELS,index
        if index in imported_ids or key in asset_keys:
            raise EditError('Duplicate or mixed imported track edits')
        imported_ids.add(index)
        if row.get('base_asset_sha1') != hashlib.sha1(session.original_asset(*key)).hexdigest():
            raise EditError('Imported track does not match its base ROM model')
        buffers = []
        for name in ('baseline','current'):
            value = row.get(name)
            if not isinstance(value,str) or not 0 < len(value) <= 2*0x82A00 or len(value)%2:
                raise EditError('Invalid imported track binary size')
            try:buffers.append(bytes.fromhex(value))
            except ValueError as error:raise EditError('Invalid imported track hex data') from error
        baseline,current = buffers
        if document['version']==9:
            validate_compiled_track(session.original_asset(*key),baseline,
                session.material_references,session.minimap_references)
        session._install_track_import(index,current,baseline)
    structures = document.get('structural_maps', [])
    if not isinstance(structures, list) or len(structures) > 138:
        raise EditError('Invalid structural map list')
    states = []
    counters = {}
    for row in structures:
        state, counter = state_from_document(session, row)
        if state.map_id in counters or any(key[0] == state.map_id for key in keys):
            raise EditError('Duplicate structural map or mixed legacy/structural edits')
        states.append(state)
        counters[state.map_id] = counter
    validate_capacity(session, tuple(states))
    session._install_states(tuple(states))
    session._next_identity.update(counters)
    # Every referenced map is now available; validate against the complete project.
    for key, raw in headers:
        session._install_asset(key, raw)
    names=document.get('course_names',[])
    if not isinstance(names,list) or len(names)>session.rom.count(AssetType.LEVEL_NAMES):
        raise EditError('Invalid course-name edit list')
    name_ids:set[int]=set()
    for row in names:
        if not isinstance(row,dict):raise EditError('Invalid course-name record')
        index=_integer(row.get('index'),0,session.rom.count(AssetType.LEVEL_NAMES)-1)
        original=session.original_asset(AssetType.LEVEL_NAMES,index)
        if index in name_ids or row.get('encoding')!='raw-names' or row.get('base_asset_sha1')!=hashlib.sha1(original).hexdigest():
            raise EditError('Duplicate course name or incorrect base/encoding')
        value=row.get('data')
        if not isinstance(value,str) or not 0<len(value)<=2*(len(original)+3*64) or len(value)%2:
            raise EditError('Invalid course-name binary size')
        try:raw=bytes.fromhex(value)
        except ValueError as error:raise EditError('Invalid course-name hex') from error
        session._install_asset((AssetType.LEVEL_NAMES,index),raw)
        name_ids.add(index)
    research = document.get("research", {})
    if not isinstance(research, dict) or (document["version"] < 3 and research):
        raise EditError("Invalid project note metadata")
    notes = research.get("notes", [])
    if not isinstance(notes, list) or len(notes) > 100000:
        raise EditError("Invalid project note list")
    session.set_experiment_name(research.get("experiment", ""))
    note_keys: set[tuple[int, int, str]] = set()
    for note in notes:
        if not isinstance(note, dict):
            raise EditError("Invalid project note")
        key = (_integer(note.get("map_id"), 0, 137), _integer(note.get("entry_index"), 0, MAX_IDENTITY-1 if document['version'] >= 7 else 9425))
        field = note.get("field")
        if not isinstance(field, str) or (*key, field) in note_keys:
            raise EditError("Invalid or duplicate note parameter")
        note_keys.add((*key, field))
        session.object(key)
        if note.get("base_entry_sha1") != hashlib.sha1(session._note_base(key)).hexdigest():
            raise EditError("Project note does not match its original entry")
        session.set_note(key, field, note.get("text"), note.get("result"))
    session._history.clear()
    session._cursor = 0
    session.last_key, session.last_asset_key, session.last_keys = None, None, ()
    session.selected_level = _integer(document.get("selected_level", 0), 0, 64)
    session.project_path = path.resolve()
    session._saved_signature = session._signature()
    return session
