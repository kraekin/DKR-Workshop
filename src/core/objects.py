"""Headless object maps and metadata; layouts from the local decomp.

Schema constants below mirror include/level_object_entries.h and the extractor's
behavior-to-entry order. They contain format metadata, never extracted assets.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import struct
from typing import Any

import numpy as np
from numpy.typing import NDArray

from src.core.rom import AssetError, AssetType, DecompAssets, RomImage, read_json

BEHAVIOR_NAMES: tuple[str, ...] = (
    'BHV_NONE',
    'BHV_RACER',
    'BHV_SCENERY',
    'BHV_FISH',
    'BHV_ANIMATOR',
    'BHV_WEAPON',
    'BHV_SMOKE',
    'BHV_EXIT',
    'BHV_AUDIO',
    'BHV_AUDIO_LINE',
    'BHV_CAMERA_CONTROL',
    'BHV_SETUP_POINT',
    'BHV_DINO_WHALE',
    'BHV_CHECKPOINT',
    'BHV_DOOR',
    'BHV_FOG_CHANGER',
    'BHV_AINODE',
    'BHV_WEAPON_BALLOON',
    'BHV_WEAPON_2',
    'BHV_AUDIO_LINE_2',
    'BHV_UNK_14',
    'BHV_UNK_15',
    'BHV_BOMB_EXPLOSION',
    'BHV_BALLOON_POP',
    'BHV_UNK_18',
    'BHV_UNK_19',
    'BHV_SKY_CONTROL',
    'BHV_AUDIO_REVERB',
    'BHV_TORCH_MIST',
    'BHV_TEXTURE_SCROLL',
    'BHV_MODECHANGE',
    'BHV_STOPWATCH_MAN',
    'BHV_BANANA',
    'BHV_LIGHT_RGBA',
    'BHV_UNK_22',
    'BHV_UNK_23',
    'BHV_BUOY_PIRATE_SHIP',
    'BHV_WEATHER',
    'BHV_BRIDGE_WHALE_RAMP',
    'BHV_RAMP_SWITCH',
    'BHV_SEA_MONSTER',
    'BHV_BONUS',
    'BHV_UNK_2A',
    'BHV_LENS_FLARE',
    'BHV_LENS_FLARE_SWITCH',
    'BHV_COLLECT_EGG',
    'BHV_EGG_CREATOR',
    'BHV_CHARACTER_FLAG',
    'BHV_UNK_30',
    'BHV_ANIMATION',
    'BHV_ANIMATED_OBJECT',
    'BHV_CAMERA_ANIMATION',
    'BHV_INFO_POINT',
    'BHV_CAR_ANIMATION',
    'BHV_CHARACTER_SELECT',
    'BHV_TRIGGER',
    'BHV_VEHICLE_ANIMATION',
    'BHV_ZIPPER_WATER',
    'BHV_TIMETRIAL_GHOST',
    'BHV_WAVE_GENERATOR',
    'BHV_WAVE_POWER',
    'BHV_BUTTERFLY',
    'BHV_PARK_WARDEN',
    'BHV_UNK_3F',
    'BHV_WORLD_KEY',
    'BHV_BANANA_SPAWNER',
    'BHV_TREASURE_SUCKER',
    'BHV_LOG',
    'BHV_LAVA_SPURT',
    'BHV_POS_ARROW',
    'BHV_HIT_TESTER',
    'BHV_MIDI_FADE',
    'BHV_HIT_TESTER_2',
    'BHV_EFFECT_BOX',
    'BHV_TROPHY_CABINET',
    'BHV_BUBBLER',
    'BHV_FLY_COIN',
    'BHV_GOLDEN_BALLOON',
    'BHV_LASER_BOLT',
    'BHV_LASER_GUN',
    'BHV_PARK_WARDEN_2',
    'BHV_ANIMATED_OBJECT_2',
    'BHV_ZIPPER_GROUND',
    'BHV_OVERRIDE_POS',
    'BHV_WIZPIG_SHIP',
    'BHV_ANIMATED_OBJECT_3',
    'BHV_ANIMATED_OBJECT_4',
    'BHV_TAJ_TELEPOINT',
    'BHV_SILVER_COIN',
    'BHV_BOOST',
    'BHV_WARDEN_SMOKE',
    'BHV_UNK_5B',
    'BHV_UNK_5C',
    'BHV_ZIPPER_AIR',
    'BHV_UNK_5E',
    'BHV_DYNAMIC_LIGHT_OBJECT_2',
    'BHV_SNOWBALL',
    'BHV_SNOWBALL_2',
    'BHV_TELEPORT',
    'BHV_ROCKET_SIGNPOST',
    'BHV_ROCKET_SIGNPOST_2',
    'BHV_SNOWBALL_3',
    'BHV_SNOWBALL_4',
    'BHV_HIT_TESTER_3',
    'BHV_HIT_TESTER_4',
    'BHV_RANGE_TRIGGER',
    'BHV_UNK_6A',
    'BHV_BOSS_HAZARD_TRIGGER',
    'BHV_FIREBALL_OCTOWEAPON',
    'BHV_FROG',
    'BHV_SILVER_COIN_2',
    'BHV_TT_DOOR',
    'BHV_MIDI_FADE_POINT',
    'BHV_DOOR_OPENER',
    'BHV_UNK_72',
    'BHV_PIG_ROCKETEER',
    'BHV_FIREBALL_OCTOWEAPON_2',
    'BHV_LEVEL_NAME',
    'BHV_MIDI_CHANNEL_SET',
    'BHV_WIZPIG_GHOSTS',
    'BHV_UNK_78',
    'BHV_UNK_79',
    'BHV_UNK_7A',
    'BHV_UNK_7B',
    'BHV_UNK_7C',
    'BHV_UNK_7D',
    'BHV_UNK_7E',
    'BHV_UNK_7F',
)

ENTRY_LAYOUTS: tuple[tuple[int, tuple[tuple[str, int, str, int, str], ...]], ...] = (
    (8, ()),  # LevelObjectEntryCommon
    (16, (('angleZ', 8, 'h', 1, ''), ('angleX', 10, 'h', 1, ''), ('angleY', 12, 'h', 1, ''), ('playerIndex', 14, 'h', 1, ''))),  # LevelObjectEntry_Racer
    (12, (('modelIndex', 8, 'B', 1, ''), ('radius', 9, 'B', 1, ''), ('angleY', 10, 'B', 1, 'Angle, DivideBy:64'), ('solid', 11, 'B', 1, ''))),  # LevelObjectEntry_Scenery
    (16, (('unk8', 8, 'H', 1, ''), ('unkA', 10, 'B', 1, ''), ('unkB', 11, 'B', 1, ''), ('unkC', 12, 'B', 1, ''), ('unkD', 13, 'B', 1, ''), ('unkE', 14, 'B', 1, ''), ('unkF', 15, 'B', 1, ''))),  # LevelObjectEntry_Fish
    (12, (('batchID', 8, 'b', 1, ''), ('speedFactorX', 9, 'b', 1, ''), ('speedfactorY', 10, 'b', 1, ''), ('padB', 11, 'b', 1, ''))),  # LevelObjectEntry_Animator
    (8, ()),  # LevelObjectEntry_Weapon
    (8, ()),  # LevelObjectEntry_Smoke
    (26, (('destinationMapId', 8, 'B', 1, 'AssetId:ASSET_LEVEL_HEADERS'), ('pad9', 9, 'B', 1, ''), ('overworldSpawnIndex', 10, 'b', 1, ''), ('padB', 11, 'B', 5, ''), ('radius', 16, 'B', 1, 'Scale, DivideBy:128'), ('angleY', 17, 'B', 1, 'Angle, DivideBy:64'), ('pad12', 18, 'B', 5, ''), ('returnSpawnIndex', 23, 'B', 1, ''), ('bossFlag', 24, 'b', 1, 'Enum:WarpFlag'), ('pad19', 25, 'B', 1, ''))),  # LevelObjectEntry_Exit
    (18, (('soundId', 8, 'H', 1, ''), ('range', 10, 'H', 1, ''), ('volume', 12, 'B', 1, ''), ('minVolume', 13, 'B', 1, ''), ('pitch', 14, 'B', 1, ''), ('fastFalloff', 15, 'B', 1, ''), ('priority', 16, 'B', 1, ''), ('unk11', 17, 'B', 1, ''))),  # LevelObjectEntry_Audio
    (20, (('unk8', 8, 'B', 1, ''), ('unk9', 9, 'B', 1, ''), ('soundID', 10, 'H', 1, ''), ('lineID', 12, 'B', 1, ''), ('unkD', 13, 'B', 1, ''), ('unkE', 14, 'H', 1, ''), ('unk10', 16, 'B', 1, ''), ('unk11', 17, 'B', 1, ''), ('unk12', 18, 'B', 1, ''), ('unk13', 19, 'B', 1, ''))),  # LevelObjectEntry_AudioLine
    (10, (('cameraID', 8, 'b', 1, ''), ('pad9', 9, 'b', 1, ''))),  # LevelObjectEntry_CameraControl
    (12, (('racerIndex', 8, 'B', 1, ''), ('entranceID', 9, 'B', 1, ''), ('angleY', 10, 'B', 1, 'Angle, DivideBy:64'), ('vehicle', 11, 'b', 1, 'Enum:Vehicle'))),  # LevelObjectEntry_SetupPoint
    (8, ()),  # LevelObjectEntry_Dino_Whale
    (28, (('scale', 8, 'B', 1, ''), ('index', 9, 'B', 1, ''), ('angleY', 10, 'B', 1, 'Angle, DivideBy:64'), ('unkB', 11, 'b', 1, ''), ('unkC', 12, 'b', 1, ''), ('unkD', 13, 'b', 1, ''), ('unkE', 14, 'b', 1, ''), ('unkF', 15, 'b', 1, ''), ('unk10', 16, 'b', 1, ''), ('unk11', 17, 'b', 1, ''), ('unk12', 18, 'b', 1, ''), ('unk13', 19, 'b', 1, ''), ('unk14', 20, 'b', 1, ''), ('unk15', 21, 'b', 1, ''), ('unk16', 22, 'b', 1, ''), ('isAltCheckpoint', 23, 'B', 1, ''), ('unk18', 24, 'b', 1, ''), ('unk19', 25, 'B', 1, ''), ('vehicleType', 26, 'b', 1, ''), ('unk1B', 27, 'B', 1, ''))),  # LevelObjectEntry_Checkpoint
    (22, (('closedRotation', 8, 'B', 1, 'Angle, DivideBy:64'), ('openRotation', 9, 'B', 1, 'Angle, DivideBy:64'), ('modelIndex', 10, 'B', 1, ''), ('distanceToOpen', 11, 'B', 1, ''), ('doorID', 12, 'b', 1, ''), ('balloonCount', 13, 'B', 1, ''), ('doorType', 14, 'B', 1, ''), ('textID', 15, 'B', 1, ''), ('unk10', 16, 'B', 1, ''), ('keyID', 17, 'b', 1, ''), ('scale', 18, 'B', 1, ''), ('localBalloons', 19, 'b', 1, ''), ('levelID', 20, 'b', 1, ''), ('balloonCountOverride', 21, 'B', 1, ''))),  # LevelObjectEntry_Door
    (18, (('distance', 8, 'B', 1, ''), ('r', 9, 'B', 1, ''), ('g', 10, 'B', 1, ''), ('b', 11, 'B', 1, ''), ('near', 12, 'h', 1, ''), ('far', 14, 'h', 1, ''), ('switchTimer', 16, 'h', 1, ''))),  # LevelObjectEntry_FogChanger
    (16, (('unk8', 8, 'B', 1, ''), ('nodeID', 9, 'B', 1, ''), ('adjacent', 10, 'B', 4, ''), ('elevation', 14, 'b', 1, ''), ('padF', 15, 'b', 1, ''))),  # LevelObjectEntry_AiNode
    (12, (('unk8', 8, 'B', 1, ''), ('balloonType', 9, 'B', 1, 'Enum:BalloonType'), ('scale', 10, 'B', 1, 'Scale, DivideBy:64'), ('padB', 11, 'B', 1, ''))),  # LevelObjectEntry_WeaponBalloon
    (8, ()),  # LevelObjectEntry_Weapon
    (20, (('unk8', 8, 'B', 12, ''),)),  # LevelObjectEntry_AudioSeqLine
    (8, ()),  # LevelObjectEntry_Unknown20
    (8, ()),  # LevelObjectEntry_Unknown21
    (10, (('opacity_hi', 8, 'b', 1, ''),)),  # LevelObjectEntry_BombExplosion
    (8, ()),  # LevelObjectEntryCommon
    (8, ()),  # LevelObjectEntry_Unknown24
    (8, ()),  # LevelObjectEntry_Unknown25
    (10, (('setting', 8, 'B', 1, ''), ('radius', 9, 'B', 1, ''))),  # LevelObjectEntry_SkyControl
    (12, (('magnitude', 8, 'B', 1, ''), ('lineID', 9, 'B', 1, ''), ('vertexIndex', 10, 'B', 1, ''), ('unkB', 11, 'B', 1, ''))),  # LevelObjectEntry_AudioReverb
    (12, (('animSpeed', 8, 'B', 1, ''), ('radius', 9, 'B', 1, ''), ('unkA', 10, 'B', 1, ''), ('unkB', 11, 'B', 1, ''))),  # LevelObjectEntry_Torch_Mist
    (12, (('textureIndex', 8, 'h', 1, ''), ('unkA', 10, 'b', 1, ''), ('unkB', 11, 'b', 1, ''))),  # LevelObjectEntry_TexScroll
    (12, (('radius', 8, 'B', 1, ''), ('angleY', 9, 'B', 1, 'Angle, DivideBy:64'), ('vehicleID', 10, 'B', 1, 'Enum:Vehicle'), ('padB', 11, 'B', 1, ''))),  # LevelObjectEntry_ModeChange
    (12, (('unk8', 8, 'B', 4, ''),)),  # LevelObjectEntry_StopWatchMan
    (8, ()),  # LevelObjectEntry_Banana
    (30, (('unk8', 8, 'B', 1, ''), ('unk9', 9, 'B', 1, ''), ('colourR', 10, 'B', 1, ''), ('colourG', 11, 'B', 1, ''), ('colourB', 12, 'B', 1, ''), ('intensity', 13, 'B', 1, ''), ('radius', 14, 'h', 1, ''), ('unk10', 16, 'h', 1, ''), ('unk12', 18, 'h', 1, ''), ('unk14', 20, 'h', 1, ''), ('unk16', 22, 'h', 1, ''), ('unk18', 24, 'h', 1, ''), ('unk1A', 26, 'h', 1, ''), ('unk1C', 28, 'B', 1, ''))),  # LevelObjectEntry_RgbaLight
    (8, ()),  # LevelObjectEntry_Unknown34
    (8, ()),  # LevelObjectEntry_Unknown35
    (12, (('unk8', 8, 'B', 4, ''),)),  # LevelObjectEntry_Buoy_PirateShip
    (20, (('radius', 8, 'h', 1, ''), ('unkA', 10, 'h', 1, ''), ('unkC', 12, 'h', 1, ''), ('unkE', 14, 'h', 1, ''), ('unk10', 16, 'B', 1, ''), ('unk11', 17, 'B', 1, ''), ('unk12', 18, 'h', 1, ''))),  # LevelObjectEntry_Weather
    (16, (('modelIndex', 8, 'B', 1, ''), ('angleY', 9, 'B', 1, 'Angle, DivideBy:64'), ('unkA', 10, 'B', 1, ''), ('unkB', 11, 'B', 1, ''), ('radius', 12, 'B', 1, ''), ('unkD', 13, 'B', 1, ''), ('bobAmount', 14, 'b', 1, ''), ('allowedVehicles', 15, 'B', 1, ''))),  # LevelObjectEntry_Bridge_WhaleRamp
    (10, (('unk8', 8, 'B', 1, ''), ('unk9', 9, 'B', 1, ''))),  # LevelObjectEntry_RampSwitch
    (8, ()),  # LevelObjectEntry_SeaMonster
    (12, (('radius', 8, 'B', 1, ''), ('angleY', 9, 'B', 1, 'Angle, DivideBy:64'), ('unkA', 10, 'B', 1, ''))),  # LevelObjectEntry_Bonus
    (8, ()),  # LevelObjectEntry_Unknown42
    (20, (('angleX', 8, 'h', 1, ''), ('angleY', 10, 'h', 1, ''), ('set1', 12, 'B', 1, ''), ('set2', 13, 'B', 1, ''), ('largeShine', 14, 'B', 1, ''), ('padA', 15, 'B', 1, ''), ('red', 16, 'B', 1, ''), ('green', 17, 'B', 1, ''), ('blue', 18, 'B', 1, ''), ('alpha', 19, 'B', 1, ''))),  # LevelObjectEntry_LensFlare
    (20, (('radius', 8, 'h', 1, ''), ('pad', 10, 'B', 10, ''))),  # LevelObjectEntry_LensFlareSwitch
    (8, ()),  # LevelObjectEntry_CollectEgg
    (8, ()),  # LevelObjectEntry_EggCreator
    (16, (('angleZ', 8, 'h', 1, ''), ('radius', 10, 'h', 1, ''), ('angleY', 12, 'h', 1, ''), ('playerIndex', 14, 'h', 1, ''))),  # LevelObjectEntry_CharacterFlag
    (8, ()),  # LevelObjectEntry_Unknown48
    (50, (('z_rotation', 8, 'B', 1, 'Angle, DivideBy:256'), ('x_rotation', 9, 'B', 1, 'Angle, DivideBy:256'), ('y_rotation', 10, 'B', 1, 'Angle, DivideBy:256'), ('scale', 11, 'B', 1, 'Scale, DivideBy:64'), ('objectIdToSpawn', 12, 'h', 1, 'Object'), ('animationStartDelay', 14, 'h', 1, 'Time, RoundToPlaces:3'), ('actorIndex', 16, 'b', 1, ''), ('order', 17, 'b', 1, ''), ('objAnimIndex', 18, 'b', 1, ''), ('unk13', 19, 'b', 1, ''), ('nodeSpeed', 20, 'b', 1, ''), ('unk15', 21, 'b', 1, ''), ('unk16', 22, 'B', 1, ''), ('objAnimSpeed', 23, 'b', 1, ''), ('objAnimLoopType', 24, 'B', 1, ''), ('rotateType', 25, 'B', 1, ''), ('yawSpinSpeed', 26, 'b', 1, ''), ('rollSpinSpeed', 27, 'b', 1, ''), ('pitchSpinSpeed', 28, 'b', 1, ''), ('goToNode', 29, 'b', 1, ''), ('unk1E', 30, 'B', 1, ''), ('unk1F', 31, 'b', 1, ''), ('unk20', 32, 'b', 1, ''), ('channel', 33, 'b', 1, ''), ('unk22', 34, 'b', 1, ''), ('unk23', 35, 'b', 1, ''), ('pauseFrameCount', 36, 'h', 1, 'Time, RoundToPlaces:4'), ('specialHide', 38, 'b', 1, ''), ('messageId', 39, 'B', 1, 'AssetId:ASSET_GAME_TEXT'), ('unk28', 40, 'b', 1, ''), ('unk29', 41, 'b', 1, ''), ('unk2A', 42, 'b', 1, ''), ('fadeAlpha', 43, 'b', 1, ''), ('nextAnim', 44, 'b', 1, ''), ('unk2D', 45, 'b', 1, ''), ('soundEffect', 46, 'b', 1, ''), ('fadeOptions', 47, 'b', 1, ''), ('unk30', 48, 'b', 1, ''), ('unk31', 49, 'B', 1, ''))),  # LevelObjectEntry_Animation
    (8, ()),  # LevelObjectEntry_AnimatedObject
    (8, ()),  # LevelObjectEntry_CameraAnimation
    (12, (('hitbox', 8, 'B', 3, ''), ('unkB', 11, 'B', 1, ''))),  # LevelObjectEntry_InfoPoint
    (8, ()),  # LevelObjectEntryCommon
    (50, (('pad8', 8, 'B', 10, ''), ('unk12', 18, 'b', 1, ''), ('unk13', 19, 'b', 1, ''), ('unk14', 20, 'b', 1, ''), ('unk15', 21, 'b', 1, ''), ('unk16', 22, 'B', 1, ''), ('unk17', 23, 'b', 1, ''), ('unk18', 24, 'B', 1, ''), ('pad19', 25, 'b', 5, ''), ('unk1E', 30, 'B', 1, ''), ('unk1F', 31, 'b', 1, ''), ('pad20', 32, 'b', 4, ''), ('unk24', 36, 'h', 1, ''), ('unk26', 38, 'b', 1, ''), ('unk27', 39, 'B', 1, ''), ('unk28', 40, 'b', 1, ''), ('unk29', 41, 'b', 1, ''), ('unk2A', 42, 'b', 1, ''), ('unk2B', 43, 'b', 1, ''), ('unk2C', 44, 'b', 1, ''), ('unk2D', 45, 'b', 1, ''), ('unk2E', 46, 'b', 1, ''), ('unk2F', 47, 'b', 1, ''), ('unk30', 48, 'b', 1, ''))),  # LevelObjectEntry_CharacterSelect
    (14, (('scale', 8, 'B', 1, ''), ('index', 9, 'b', 1, ''), ('angleY', 10, 'B', 1, 'Angle, DivideBy:64'), ('unkB', 11, 'B', 1, ''), ('unkC', 12, 'B', 1, ''), ('unkD', 13, 'B', 1, ''))),  # LevelObjectEntry_Trigger
    (8, ()),  # LevelObjectEntryCommon
    (12, (('unk8', 8, 'B', 1, ''), ('radius', 9, 'B', 1, ''), ('angleY', 10, 'B', 1, 'Angle, DivideBy:64'), ('padB', 11, 'B', 1, ''))),  # LevelObjectEntry_AirZippers_WaterZippers
    (8, ()),  # LevelObjectEntry_TimeTrial_Ghost
    (18, (('unk8', 8, 'B', 1, ''), ('unk9', 9, 'B', 1, ''), ('waveSize', 10, 'H', 1, ''), ('unkC', 12, 'H', 1, ''), ('unkE', 14, 'H', 1, ''), ('unk10', 16, 'B', 1, ''), ('unk11', 17, 'B', 1, ''))),  # LevelObjectEntry_WaveGenerator
    (14, (('radius', 8, 'H', 1, ''), ('power', 10, 'H', 1, ''), ('divisor', 12, 'H', 1, ''))),  # LevelObjectEntry_WavePower
    (12, (('unk8', 8, 'H', 1, ''), ('unkA', 10, 'B', 1, ''), ('unkB', 11, 'B', 1, ''))),  # LevelObjectEntry_Butterfly
    (8, ()),  # LevelObjectEntry_Parkwarden
    (8, ()),  # LevelObjectEntry_Unknown63
    (10, (('keyID', 8, 'B', 1, ''), ('pad9', 9, 'B', 1, ''))),  # LevelObjectEntry_WorldKey
    (8, ()),  # LevelObjectEntry_BananaCreator
    (10, (('playerID', 8, 'b', 1, ''), ('pad9', 9, 'B', 1, ''))),  # LevelObjectEntry_TreasureSucker
    (12, (('modelIndex', 8, 'B', 1, ''), ('radius', 9, 'B', 1, ''), ('angleY', 10, 'B', 1, 'Angle, DivideBy:64'), ('padB', 11, 'B', 1, ''))),  # LevelObjectEntry_Log
    (10, (('delayTimer', 8, 'B', 1, 'Time'), ('initialTimer', 9, 'B', 1, 'Time'))),  # LevelObjectEntry_LavaSpurt
    (8, ()),  # LevelObjectEntry_PosArrow
    (8, ()),  # LevelObjectEntry_HitTester
    (28, (('scale', 8, 'B', 1, ''), ('angleY', 9, 'B', 1, 'Angle, DivideBy:64'), ('unkA', 10, 'B', 16, ''), ('unk1A', 26, 'B', 1, ''), ('unk1B', 27, 'B', 1, ''))),  # LevelObjectEntry_MidiFade
    (8, ()),  # LevelObjectEntry_HitTester
    (16, (('unk8', 8, 'B', 1, ''), ('unk9', 9, 'B', 1, ''), ('unkA', 10, 'B', 1, ''), ('unkB', 11, 'B', 1, ''), ('unkC', 12, 'B', 1, ''), ('unkD', 13, 'B', 1, ''), ('unkE', 14, 'B', 1, ''), ('unkF', 15, 'B', 1, ''))),  # LevelObjectEntry_EffectBox
    (10, (('angleY', 8, 'B', 1, 'Angle, DivideBy:64'), ('pad9', 9, 'B', 1, ''))),  # LevelObjectEntry_TrophyCab
    (16, (('particlePropertyID', 8, 'B', 1, ''), ('particleBehaviourID', 9, 'B', 1, ''), ('particleDensity', 10, 'H', 1, ''), ('unkC', 12, 'B', 4, ''))),  # LevelObjectEntry_Bubbler
    (8, ()),  # LevelObjectEntry_FlyCoin
    (12, (('balloonID', 8, 'b', 1, ''), ('scale', 9, 'B', 1, ''), ('challengeID', 10, 'b', 1, ''), ('padB', 11, 'B', 1, ''))),  # LevelObjectEntry_GoldenBalloon
    (8, ()),  # LevelObjectEntry_Laserbolt
    (14, (('angleY', 8, 'B', 1, 'Angle, DivideBy:256'), ('angleX', 9, 'B', 1, ''), ('targeting', 10, 'b', 1, ''), ('fireRate', 11, 'b', 1, ''), ('laserDuration', 12, 'B', 1, ''), ('radius', 13, 'B', 1, ''))),  # LevelObjectEntry_Lasergun
    (8, ()),  # LevelObjectEntry_ParkWarden
    (8, ()),  # LevelObjectEntry_AnimatedObject
    (12, (('unk8', 8, 'B', 1, ''), ('scale', 9, 'B', 1, ''), ('angleY', 10, 'B', 1, 'Angle, DivideBy:64'), ('unkB', 11, 'B', 1, ''))),  # LevelObjectEntry_GroundZipper
    (10, (('behaviorId', 8, 'b', 1, ''), ('cutsceneId', 9, 'b', 1, ''))),  # LevelObjectEntry_OverridePos
    (8, ()),  # LevelObjectEntry_WizpigShip
    (8, ()),  # LevelObjectEntry_AnimatedObject
    (8, ()),  # LevelObjectEntry_AnimatedObject
    (8, ()),  # LevelObjectEntry_TajTelepoint
    (8, ()),  # LevelObjectEntry_SilverCoin
    (8, ()),  # LevelObjectEntry_Boost
    (8, ()),  # LevelObjectEntry_WardenSmoke
    (8, ()),  # LevelObjectEntry_Unknown91
    (10, (('unk8', 8, 'B', 1, ''), ('unk9', 9, 'B', 1, ''))),  # LevelObjectEntry_Unknown92
    (12, (('unk8', 8, 'B', 1, ''), ('radius', 9, 'B', 1, ''), ('angleY', 10, 'B', 1, 'Angle, DivideBy:64'), ('padB', 11, 'B', 1, ''))),  # LevelObjectEntry_AirZippers_WaterZippers
    (8, ()),  # LevelObjectEntry_Unknown94
    (8, ()),  # LevelObjectEntry_DynamicLightObject2
    (8, ()),  # LevelObjectEntry_Snowball
    (8, ()),  # LevelObjectEntry_Snowball
    (10, (('levelID', 8, 'b', 1, ''), ('pad9', 9, 'B', 1, ''))),  # LevelObjectEntry_Teleport
    (12, (('unk8', 8, 'B', 1, ''), ('radius', 9, 'B', 1, ''), ('angleY', 10, 'B', 1, 'Angle, DivideBy:64'), ('padB', 11, 'B', 1, ''))),  # LevelObjectEntry_Lighthouse_RocketSignpost
    (12, (('unk8', 8, 'B', 1, ''), ('radius', 9, 'B', 1, ''), ('angleY', 10, 'B', 1, 'Angle, DivideBy:64'), ('padB', 11, 'B', 1, ''))),  # LevelObjectEntry_Lighthouse_RocketSignpost
    (8, ()),  # LevelObjectEntry_Snowball
    (8, ()),  # LevelObjectEntry_Snowball
    (8, ()),  # LevelObjectEntry_HitTester
    (8, ()),  # LevelObjectEntry_HitTester
    (12, (('radius', 8, 'H', 1, ''), ('particleFlags', 10, 'H', 1, ''))),  # LevelObjectEntry_RangeTrigger
    (8, ()),  # LevelObjectEntry_Unknown106
    (12, (('unk8', 8, 'B', 4, ''),)),  # LevelObjectEntry_BossHazardTrigger
    (8, ()),  # LevelObjectEntry_Fireball_Octoweapon
    (12, (('homeRadius', 8, 'h', 1, ''), ('drumstick', 10, 'B', 1, ''), ('padB', 11, 'B', 1, ''))),  # LevelObjectEntry_Frog
    (8, ()),  # LevelObjectEntry_SilverCoinAdv2
    (16, (('angleY', 8, 'B', 1, 'Angle, DivideBy:64'), ('unk9', 9, 'B', 1, 'Angle, DivideBy:64'), ('radius', 10, 'B', 1, ''), ('textID', 11, 'B', 1, ''), ('scale', 12, 'B', 1, ''), ('padD', 13, 'B', 1, ''), ('doorType', 14, 'b', 1, ''), ('padF', 15, 'b', 1, ''))),  # LevelObjectEntry_TTDoor
    (30, (('unk8', 8, 'H', 1, ''), ('unkA', 10, 'H', 1, ''), ('unkC', 12, 'B', 16, ''), ('unk1C', 28, 'B', 1, ''), ('unk1D', 29, 'B', 1, ''))),  # LevelObjectEntry_MidiFadePoint
    (8, ()),  # LevelObjectEntry_DoorOpener
    (8, ()),  # LevelObjectEntry_Unknown114
    (8, ()),  # LevelObjectEntry_PigRocketeer
    (8, ()),  # LevelObjectEntry_Fireball_Octoweapon
    (10, (('levelID', 8, 'b', 1, ''), ('radius', 9, 'b', 1, ''))),  # LevelObjectEntry_LevelName
    (12, (('unk8', 8, 'H', 1, ''), ('unkA', 10, 'B', 1, ''), ('unkB', 11, 'B', 1, ''))),  # LevelObjectEntry_Midichset
    (8, ()),  # LevelObjectEntry_WizpigGhosts
    (8, ()),  # LevelObjectEntry_Unknown120
    (8, ()),  # LevelObjectEntry_Unknown121
    (8, ()),  # LevelObjectEntry_Unknown122
    (8, ()),  # LevelObjectEntry_Unknown123
    (8, ()),  # LevelObjectEntry_Unknown124
    (8, ()),  # LevelObjectEntry_Unknown125
    (8, ()),  # LevelObjectEntry_Unknown126
    (8, ()),  # LevelObjectEntry_Unknown127
)

class ObjectError(AssetError):
    """Invalid object header, translation or map record."""


@dataclass(frozen=True)
class ObjectDefinition:
    header_id: int
    name: str
    behavior_id: int
    scale: float
    raw_data: bytes | None = None
    model_type: int = 0
    model_ids: tuple[int, ...] = ()

    @property
    def behavior(self) -> str:
        return BEHAVIOR_NAMES[self.behavior_id] if self.behavior_id >= 0 else 'BHV_NONE (-1)'

    @classmethod
    def from_bytes(cls, data: bytes, header_id: int) -> ObjectDefinition:
        if len(data) < 0x78:
            raise ObjectError('ObjectHeader requires at least 0x78 bytes')
        behavior = struct.unpack_from('>b', data, 0x54)[0]
        if behavior < -1:
            raise ObjectError('Invalid signed object behavior ID')
        try:
            name = data[0x60:0x70].split(b'\0', 1)[0].decode('ascii')
        except UnicodeError as error:
            raise ObjectError('Object internal name is not ASCII') from error
        scale = struct.unpack_from('>f', data, 0x0C)[0]
        if not math.isfinite(scale):
            raise ObjectError('Object header scale is not finite')
        model_type = struct.unpack_from('>b',data,0x53)[0]
        model_count = struct.unpack_from('>b',data,0x55)[0]
        model_offset = struct.unpack_from('>I',data,0x10)[0]
        if model_count < 0 or model_count and (model_offset < 0x78 or model_offset + model_count*4 > len(data)):
            raise ObjectError('Object model-ID array is outside its header asset')
        model_ids = struct.unpack_from('>' + str(model_count) + 'I',data,model_offset) if model_count else ()
        return cls(header_id, name or f'Object {header_id}', behavior, scale, data,model_type,model_ids)


@dataclass(frozen=True)
class ObjectDatabase:
    translation: tuple[int, ...]
    definitions: tuple[ObjectDefinition, ...]

    def resolve(self, object_id: int) -> ObjectDefinition:
        if not 0 <= object_id < 512:
            raise ObjectError(f'Object ID {object_id} is outside the 9-bit translation table')
        header_id = self.translation[object_id]
        if not 0 <= header_id < len(self.definitions):
            raise ObjectError(f'Object ID {object_id} refers to unmapped header {header_id}')
        return self.definitions[header_id]

    @classmethod
    def from_bytes(cls, translation: bytes, headers: tuple[bytes, ...]) -> ObjectDatabase:
        if len(translation) != 1024:
            raise ObjectError('Object translation table must contain 512 BE s16 values')
        return cls(struct.unpack('>512h', translation), tuple(
            ObjectDefinition.from_bytes(data, index) for index, data in enumerate(headers)))


def load_object_database(source: RomImage | DecompAssets) -> ObjectDatabase:
    if isinstance(source, RomImage):
        return ObjectDatabase.from_bytes(source.section(AssetType.LEVEL_OBJECT_TRANSLATION_TABLE), tuple(
            source.read_asset(AssetType.OBJECTS, index) for index in range(source.count(AssetType.OBJECTS))))
    definitions: list[ObjectDefinition] = []
    for index in range(source.count(AssetType.OBJECTS)):
        path = source.entry_path(AssetType.OBJECTS, index)
        document = read_json(path) if path.suffix.casefold() == '.json' else {}
        if document and 'raw' not in document:
            if document.get('type') != 'ObjectHeader':
                raise ObjectError('Expected ObjectHeader JSON')
            name = document.get('internal-name')
            behavior = document.get('behavior')
            if not isinstance(name, str) or behavior is not None and behavior not in BEHAVIOR_NAMES:
                raise ObjectError(f'Invalid object metadata in {path.name}')
            scale = document.get('scale', 1.0)
            if type(scale) not in (int, float) or not math.isfinite(scale):
                raise ObjectError('Object scale must be finite')
            model_type = ('OBJECT_MODEL_TYPE_3D_MODEL','OBJECT_MODEL_TYPE_SPRITE_BILLBOARD',
                          'OBJECT_MODEL_TYPE_VEHICLE_PART','OBJECT_MODEL_TYPE_UNKNOWN3','OBJECT_MODEL_TYPE_MISC').index(
                              document.get('model-type','OBJECT_MODEL_TYPE_3D_MODEL'))
            models = document.get('models',[])
            if not isinstance(models,list):
                raise ObjectError('Object models must be an array')
            section = {1: AssetType.SPRITES, 4: AssetType.TEXTURES_2D}.get(model_type)
            model_ids = tuple(source.resolve_id(section, value) for value in models) if section is not None else ()
            definitions.append(ObjectDefinition(index, name, BEHAVIOR_NAMES.index(behavior) if behavior else -1,
                                                float(scale),model_type=model_type,model_ids=model_ids))
        else:
            definitions.append(ObjectDefinition.from_bytes(source.read_asset(AssetType.OBJECTS, index), index))
    path = source.entry_path(AssetType.LEVEL_OBJECT_TRANSLATION_TABLE, 0)
    document = read_json(path) if path.suffix.casefold() == '.json' else {}
    if document and 'raw' not in document:
        if document.get('type') != 'LevelObjectTranslationTable':
            raise ObjectError('Expected LevelObjectTranslationTable JSON')
        table = document.get('table')
        if not isinstance(table, list) or len(table) > 512:
            raise ObjectError('Translation JSON table must contain at most 512 entries')
        translation = tuple(512 if value is None else source.resolve_id(AssetType.OBJECTS, value) for value in table)
        translation += (512,) * (512 - len(translation))
    else:
        data = source.read_asset(AssetType.LEVEL_OBJECT_TRANSLATION_TABLE, 0)
        if len(data) != 1024:
            raise ObjectError('Object translation table must contain 1024 bytes')
        translation = struct.unpack('>512h', data)
    return ObjectDatabase(translation, tuple(definitions))


@dataclass(frozen=True)
class ObjectParameter:
    name: str
    offset: int
    format: str
    value: Any


@dataclass(frozen=True)
class LevelObject:
    map_id: int
    index: int
    offset: int | None
    object_id: int
    definition: ObjectDefinition
    position: tuple[int, int, int]
    byte_size: int
    size_bit6: bool
    parameters: tuple[ObjectParameter, ...]
    raw_data: bytes | None

    @property
    def key(self) -> tuple[int, int]:
        return self.map_id, self.index

    def value(self, name: str, default: Any = None) -> Any:
        return next((p.value for p in self.parameters if p.name == name), default)

    @property
    def category(self) -> str:
        behavior = self.definition.behavior_id
        if behavior in (1, 11): return 'Player spawns'
        if behavior == 13: return 'Checkpoints'
        if behavior == 16: return 'AI nodes'
        if behavior == 17: return 'Weapon balloons'
        if behavior in (32, 65): return 'Bananas'
        if behavior in (57, 82, 93, 89): return 'Speed zippers'
        if behavior in (8, 9, 19, 27, 71, 112, 118): return 'Sound triggers'
        if behavior in (2, 3, 12, 28, 36, 50, 54, 60, 61, 67, 81, 84, 85, 86, 109): return 'Scenery'
        if behavior in (49, 51, 53, 56): return 'Animation / cameras'
        return 'Other gameplay'

    @property
    def yaw(self) -> float | None:
        value = self.value('angleY')
        if type(value) in (int, float):
            return float(value) * (2 * math.pi / (65536 if self.definition.behavior_id == 1 else 64))
        return None


@dataclass(frozen=True)
class ObjectMap:
    map_id: int
    objects: tuple[LevelObject, ...]
    payload_size: int
    header: bytes
    padding: bytes

    @classmethod
    def from_bytes(cls, data: bytes, database: ObjectDatabase, *, map_id: int = 0) -> ObjectMap:
        if not data:
            return cls(map_id, (), 0, b'', b'')
        if len(data) < 16:
            raise ObjectError('Truncated 16-byte object-map header')
        size = struct.unpack_from('>I', data)[0]
        end = size + 16
        if end > len(data) or len(data) - end > 7 or any(data[end:]):
            raise ObjectError('Object-map payload length or alignment padding is invalid')
        objects: list[LevelObject] = []
        offset = 16
        while offset < end:
            if end - offset < 8:
                raise ObjectError('Truncated common object entry')
            low, bits, x, y, z = struct.unpack_from('>BBhhh', data, offset)
            length = bits & 0x3F
            if length < 8 or length % 2 or offset + length > end:
                raise ObjectError(f'Invalid object entry length {length} at 0x{offset:X}')
            object_id = low | ((bits & 0x80) << 1)
            definition = database.resolve(object_id)
            fields = ENTRY_LAYOUTS[definition.behavior_id][1] if definition.behavior_id >= 0 else ()
            expected = ENTRY_LAYOUTS[definition.behavior_id][0] if definition.behavior_id >= 0 else length
            if length != expected:
                raise ObjectError(f'{definition.behavior}: entry is {length} bytes; expected {expected}')
            raw = data[offset:offset + length]
            parameters: list[ObjectParameter] = []
            for name, location, format, count, hint in fields:
                values = struct.unpack_from('>' + str(count) + format, raw, location)
                parameters.append(ObjectParameter(name, location, format, values[0] if count == 1 else values))
            objects.append(LevelObject(map_id, len(objects), offset, object_id, definition, (x, y, z),
                                       length, bool(bits & 64), tuple(parameters), raw))
            offset += length
        return cls(map_id, tuple(objects), size, data[:16], data[end:])


def _gltf_map(source: DecompAssets, map_id: int, database: ObjectDatabase, document: dict[str, Any], path: Path) -> ObjectMap:
    if document.get('type') != 'LevelObjectMap':
        raise ObjectError('Expected LevelObjectMap JSON')
    filename = document.get('objects')
    if filename is None:
        return ObjectMap(map_id, (), 0, b'', b'')
    gltf = read_json(source._path(path.parent, filename))
    nodes = gltf.get('nodes')
    if not isinstance(nodes, list):
        raise ObjectError('Object-map glTF is missing nodes')
    roots = [node for node in nodes if isinstance(node, dict) and node.get('name') == 'objects']
    if len(roots) != 1:
        raise ObjectError('Object-map glTF must contain one objects root')
    children = roots[0].get('children', [])
    if not isinstance(children, list) or not all(type(child) is int for child in children) or len(set(children)) != len(children):
        raise ObjectError('Invalid object-map children')
    objects: list[LevelObject] = []
    order = source.order(AssetType.OBJECTS)
    for child in children:
        if type(child) is not int or not 0 <= child < len(nodes) or not isinstance(nodes[child], dict):
            raise ObjectError('Object-map node index outside glTF')
        node = nodes[child]
        extras = node.get('extras', {})
        if not isinstance(extras, dict) or extras.get('id') not in order:
            raise ObjectError('Object-map node has no valid object build ID')
        header_id = order.index(extras['id'])
        try:
            object_id = database.translation.index(header_id)
        except ValueError as error:
            raise ObjectError('Object header is absent from translation table') from error
        definition = database.resolve(object_id)
        position = node.get('translation', [0, 0, 0])
        if not isinstance(position, list) or len(position) != 3 or any(
            type(v) not in (int, float) or not math.isfinite(v) or v != int(v) or not -32768 <= v <= 32767 for v in position):
            raise ObjectError('Object glTF position must be three s16 world coordinates')
        if 'matrix' in node or 'rotation' in node or 'scale' in node:
            raise ObjectError('Transformed object nodes are not emitted by the supported DKR extractor')
        length, fields = ENTRY_LAYOUTS[max(0, definition.behavior_id)]
        parameters: list[ObjectParameter] = []
        for name, location, format, count, hint in fields:
            value = extras.get(name, (0,) * count if count > 1 else 0)
            if hint.startswith(('Angle','Scale','Time')):
                try:
                    if type(value) not in (int,float) or not math.isfinite(value):
                        raise ValueError('Expected finite number')
                except (ValueError,OverflowError) as error:
                    raise ObjectError(f'Invalid extracted parameter {name}') from error
            if hint.startswith('Angle') and type(value) in (int, float):
                divisor = 256 if '256' in hint else 64
                value = round(value / 360 * divisor) & (255 if format == 'B' else 65535)
            elif hint.startswith('Scale') and type(value) in (int, float):
                value = round(value * (128 if '128' in hint else 64))
            elif hint.startswith('Time') and type(value) in (int, float):
                value = round(value * 60)
            if count > 1 and isinstance(value, list): value = tuple(value)
            if not hint:
                values = value if count > 1 else (value,)
                if not isinstance(values, tuple) or len(values) != count:
                    raise ObjectError(f'Invalid extracted parameter {name}')
                try:
                    if any(type(v) not in (int,float) or not math.isfinite(v) for v in values):
                        raise ValueError('Expected finite numbers')
                    struct.pack('>' + str(count) + format,*values)
                except (ValueError,TypeError,OverflowError,struct.error) as error:
                    raise ObjectError(f'Invalid extracted parameter {name}') from error
            parameters.append(ObjectParameter(name, location, format, value))
        # glTF does not retain original alias IDs, raw bits, offsets or padding.
        objects.append(LevelObject(map_id, len(objects), None, object_id, definition,
                                   tuple(int(v) for v in position), length, False, tuple(parameters), None))
    return ObjectMap(map_id, tuple(objects), sum(obj.byte_size for obj in objects), b'', b'')


def load_object_map(source: RomImage | DecompAssets, map_id: int, database: ObjectDatabase) -> ObjectMap:
    if isinstance(source, DecompAssets):
        path = source.entry_path(AssetType.LEVEL_OBJECT_MAPS, map_id)
        if path.suffix.casefold() == '.json':
            document = read_json(path)
            if 'raw' not in document:
                return _gltf_map(source, map_id, database, document, path)
    return ObjectMap.from_bytes(source.read_asset(AssetType.LEVEL_OBJECT_MAPS, map_id, decompress=True), database, map_id=map_id)


@dataclass(frozen=True)
class RacePath:
    name: str
    kind: str
    checkpoint_set: int
    alternate: bool
    points: NDArray[np.float32]
    object_keys: tuple[tuple[int, int], ...]
    closed: bool


def catmull_rom(points: NDArray, *, closed: bool, subdivisions: int = 12) -> NDArray[np.float32]:
    """Same cubic coefficients as objects.c:9642; no loop for an open chain."""
    if len(points) < 2 or subdivisions < 1:
        return np.asarray(points, dtype=np.float32).copy()
    result: list[NDArray] = []
    for index in range(len(points) if closed else len(points) - 1):
        p0, p1, p2, p3 = (points[j % len(points)] if closed else points[min(max(j, 0), len(points) - 1)]
                          for j in (index - 1, index, index + 1, index + 2))
        t = np.arange(subdivisions, dtype=np.float32)[:, None] / subdivisions
        a = -.5 * p0 + 1.5 * p1 - 1.5 * p2 + .5 * p3
        b = p0 - 2.5 * p1 + 2 * p2 - .5 * p3
        c = .5 * (p2 - p0)
        result.extend(((a * t + b) * t + c) * t + p1)
    result.append(points[0] if closed else points[-1])
    return np.ascontiguousarray(result, dtype=np.float32)


def build_race_paths(objects: tuple[LevelObject, ...], checkpoint_sets: tuple[int, int, int],
                     *, vehicle: int = -1, lane: int = -1) -> tuple[RacePath, ...]:
    """Checkpoint-set centerline, four AI lanes and explicit AI-node graph edges.

    Lane indices are AI racing lines, not vehicle IDs (racer.c:9060). Alternate
    checkpoint replacements follow the main sequence, joining at their indexes.
    """
    paths: list[RacePath] = []
    sets = sorted({int(obj.value('vehicleType')) for obj in objects if obj.definition.behavior_id == 13})
    for group in sets:
        vehicles = [name for index, name in enumerate(('Car', 'Hovercraft', 'Plane')) if checkpoint_sets[index] == group]
        if vehicle >= 0 and checkpoint_sets[vehicle] != group: continue
        checkpoints = [obj for obj in objects if obj.definition.behavior_id == 13 and obj.value('vehicleType') == group]
        main = sorted((obj for obj in checkpoints if not obj.value('isAltCheckpoint')), key=lambda obj: obj.value('index'))
        alternates = {obj.value('index'): obj for obj in checkpoints if obj.value('isAltCheckpoint')}
        if len(main) < 2: continue
        for alternate in (False, True) if alternates else (False,):
            sequence = [alternates.get(obj.value('index'), obj) if alternate else obj for obj in main]
            for selected_lane in (range(4) if lane == 4 else (lane,)):
                positions = np.array([obj.position for obj in sequence], dtype=np.float32)
                if selected_lane >= 0:
                    for index, obj in enumerate(sequence):
                        scale = max(float(obj.value('scale')), 5) / 32
                        yaw = obj.yaw or 0
                        lateral = float(obj.value(('unkB', 'unkC', 'unkD', 'unkE')[selected_lane]))
                        vertical = float(obj.value(('unkF', 'unk10', 'unk11', 'unk12')[selected_lane]))
                        positions[index] += [scale * math.cos(yaw) * lateral, scale * vertical, -scale * math.sin(yaw) * lateral]
                name = f"{' / '.join(vehicles) or 'Unmapped'} · set {group} · " + ('alternate' if alternate else 'main')
                name += ' · centerline' if selected_lane < 0 else f' · AI lane {selected_lane}'
                paths.append(RacePath(name, 'checkpoint', group, alternate, catmull_rom(positions, closed=True),
                                      tuple(obj.key for obj in sequence), True))
    # AI nodes form an adjacency graph, not an ordered closed raceline.
    # objects.c:7347 uses one global table for all loaded maps. Ambiguous IDs
    # are diagnosed by the route tools; do not silently pick one for preview.
    candidates: dict[int, list[LevelObject]] = {}
    for obj in objects:
        if obj.definition.behavior_id == 16 and 0 <= obj.value('nodeID', 255) < 128:
            candidates.setdefault(obj.value('nodeID'), []).append(obj)
    nodes = {node_id: matches[0] for node_id, matches in candidates.items() if len(matches) == 1}
    for node_id, obj in sorted(nodes.items()):
        for target in obj.value('adjacent', ()):
            if target in nodes and target != node_id:
                other = nodes[target]
                points = np.array([obj.position, other.position], dtype=np.float32)
                paths.append(RacePath(f'AI graph {node_id} → {target}', 'ai', -1, False, points, (obj.key, other.key), False))
    return tuple(paths)
