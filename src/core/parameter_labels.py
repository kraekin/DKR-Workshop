"""Verified display labels; serialized parameter names remain unchanged."""
from __future__ import annotations

from dataclasses import dataclass
import re

@dataclass(frozen=True)
class ParameterInfo:
    label: str
    description: str
    choices: tuple[tuple[int, str], ...] = ()


CHECKPOINT_BEHAVIORS: tuple[tuple[int, str], ...] = (
    (0, "No extra behavior"), (1, "Boss animation cue"),
    (2, "AI alternate route"), (3, "Unidentified"),
    (4, "AI slowdown"), (5, "Water / alternate route"),
    (6, "Set lap beyond race length"),
)
CHECKPOINT_CUES: tuple[tuple[int, str], ...] = (
    (0, "No new cue"), (1, "Left turn"), (2, "Sharp left"),
    (3, "Left U-turn"), (4, "Right turn"), (5, "Sharp right"),
    (6, "Right U-turn"), (7, "Up"), (8, "Down"), (9, "Exclamation"),
)
CHECKPOINT_PARAMETERS: dict[str, ParameterInfo] = {
    "scale": ParameterInfo("Path scale", "Raw scale byte. The game uses max(value, 5) / 32 for lane offsets. Also scales alternate-entry proximity; the marker sphere is an editor aid."),
    "index": ParameterInfo("Checkpoint index", "Order within this checkpoint set. Alternate checkpoints pair with the main checkpoint of the same index."),
    "angleY": ParameterInfo("Yaw", "Raw yaw byte: 5.625 degrees per unit, wrapping every 64. Sets the crossing plane and sideways offset direction."),
    "isAltCheckpoint": ParameterInfo("Alternate checkpoint", "Nonzero marks an alternate paired with the same main index and checkpoint set.", ((0, "Main"), (1, "Alternate"))),
    "unk18": ParameterInfo("Unused byte (0x18)", "No checkpoint reader identified in Revision 1; all original checkpoints store -1. The original purpose is unknown."),
    "unk19": ParameterInfo("HUD course cue", "On crossing, requests a course cue for 120 timer units. Course directions must be enabled; displayed in single-player before race finish. Zero does not cancel an active prior cue.", CHECKPOINT_CUES),
    "vehicleType": ParameterInfo("Checkpoint set", "Set ID selected through the level header's Car/Hovercraft/Plane mapping. Four AI lane numbers are independent of the vehicle and set IDs."),
    "unk1B": ParameterInfo("Unused byte (0x1B)", "No checkpoint reader identified in Revision 1; all original checkpoints store 0. The original purpose is unknown."),
}
for _lane, (_lateral, _height, _behavior) in enumerate(zip(
    ("unkB", "unkC", "unkD", "unkE"), ("unkF", "unk10", "unk11", "unk12"),
    ("unk13", "unk14", "unk15", "unk16"),
)):
    CHECKPOINT_PARAMETERS[_lateral] = ParameterInfo(
        f"AI lane {_lane} lateral",
        f"Signed sideways offset for AI lane {_lane}. World offset = value × max(scale, 5) / 32, rotated by checkpoint yaw. AI racers can switch lanes during a race.",
    )
    CHECKPOINT_PARAMETERS[_height] = ParameterInfo(
        f"AI lane {_lane} height",
        f"Signed vertical offset for AI lane {_lane}. Adds value × max(scale, 5) / 32 to the path height. Vehicle physics still apply.",
    )
    CHECKPOINT_PARAMETERS[_behavior] = ParameterInfo(
        f"AI lane {_lane} behavior",
        f"Behavior selector for lane {_lane}, not bit flags. 1: Bluey turn / Wizpig jump or flying animation. 2: AI alternate route on passing. 3: unidentified. 4: physical AI slowdown. 5: keeps detailed AI simulation active and selects alternate route in water. 6: sets lap to race laps + 1. Effects depend on racer/context; existing alternate nodes define alternate routes.",
        CHECKPOINT_BEHAVIORS,
    )


# objects.c:obj_init_animobject/func_8002125C and the animated-object update loop.
ANIMATION_PARAMETERS: dict[str, ParameterInfo] = {
    'z_rotation': ParameterInfo('Roll', 'Unsigned angle: 256 units per revolution.'),
    'x_rotation': ParameterInfo('Pitch', 'Unsigned angle: 256 units per revolution.'),
    'y_rotation': ParameterInfo('Yaw', 'Unsigned angle: 256 units per revolution.'),
    'scale': ParameterInfo('Scale', 'max(raw value, 1) / 64, multiplied by the spawned object definition scale.'),
    'objectIdToSpawn': ParameterInfo('Spawn object ID', 'Object translation-table ID for this actor; negative values do not spawn an object.'),
    'animationStartDelay': ParameterInfo('Start delay', 'NTSC timer ticks. Negative values wait for input or another actor to release this actor.'),
    'actorIndex': ParameterInfo('Actor ID', 'Nodes with the same actor ID form a path. -2 reuses the preceding ID; -1 resolves to 0. Ambient actors use a separate signed ID range.'),
    'order': ParameterInfo('Node order', 'Stored path order. The game sorts these nodes before playback.'),
    'objAnimIndex': ParameterInfo('Model animation clip', 'Clip index within the spawned model. On subsequent nodes, negative values keep the current clip; use a valid clip on the first node.'),
    'unk13': ParameterInfo('Particle emitter mask', 'Nonnegative values select enabled particle emitters by bit mask. Negative values retain the previous mask.'),
    'nodeSpeed': ParameterInfo('Travel speed', 'Raw value × 0.1 game units per NTSC tick. Negative values retain the previous speed.'),
    'unk15': ParameterInfo('Release actor ID', 'Nonnegative values release another actor that is waiting on a negative start delay.'),
    'unk16': ParameterInfo('Initial clip frame', 'Initial model-animation frame in sixteenths. Also used when changing clips.'),
    'objAnimSpeed': ParameterInfo('Clip speed', 'Model-animation progress per NTSC tick, measured in sixteenths of a frame.'),
    'objAnimLoopType': ParameterInfo('Clip playback', 'Loop behavior of the model animation.',
        ((0, 'Loop'), (1, 'Ping-pong'), (2, 'Play once'), (3, 'Forward and back once'))),
    'rotateType': ParameterInfo('Rotation mode', 'Controls stored rotations, continuous spin, tangent following or look-at behavior.',
        ((0, 'Stored rotation'), (1, 'Spin'), (2, 'Follow path'), (3, 'Look at actor'))),
    'yawSpinSpeed': ParameterInfo('Yaw spin speed', 'Signed angular increment used by spin rotation mode.'),
    'rollSpinSpeed': ParameterInfo('Roll spin speed', 'Signed angular increment used by spin rotation mode.'),
    'pitchSpinSpeed': ParameterInfo('Pitch spin speed', 'Signed angular increment used by spin rotation mode.'),
    'goToNode': ParameterInfo('Loop target node', 'Last-node loop target ordinal. -1 ends the path; eligible paths can loop to an earlier node.'),
    'unk1E': ParameterInfo('Sound ID', 'Sound request: 0 makes no request; 255 stops the previous actor sound.'),
    'unk1F': ParameterInfo('Music ID', 'Positive values request a music sequence. Nonpositive values make no music request.'),
    'unk20': ParameterInfo('Input release buttons', 'Buttons that release a negative start delay: bit 0=A, bit 1=B, bit 2=Start.'),
    'channel': ParameterInfo('Scene channel', 'Scene ID; 20 is ambient playback and -1 resolves to the active scene.'),
    'unk22': ParameterInfo('Live actor / camera mode', 'Selects live transform behavior. 0 uses stored nodes; 1 uses camera control points; 10–17 copy racer transforms; 18 copies the active camera transform. Other values also affect actor initialization.'),
    'pauseFrameCount': ParameterInfo('Pause ticks', 'Nonnegative values pause at the node; -1 disables the pause.'),
    'specialHide': ParameterInfo('Hide on delay / finish', 'Nonzero hides the actor while delayed or after the path finishes.'),
    'messageId': ParameterInfo('Message ID', 'Requests a game-text message. 255 disables the request.'),
    'unk28': ParameterInfo('Advance scene counter', 'A nonnegative value increments the active scene counter when this node is reached. Negative values leave it unchanged.'),
    'unk29': ParameterInfo('Screen transition / fog', 'Low seven bits select a transition or fog preset; 127 disables the request. The high bit changes transition direction/behavior.'),
    'unk2A': ParameterInfo('Switch scene ID', 'Nonnegative values switch the active game scene when this node is reached.'),
    'fadeAlpha': ParameterInfo('Transition duration', 'Duration multiplier for screen transitions and fog changes; the game scales it by its six-tick interval.'),
    'nextAnim': ParameterInfo('Look-at actor ID', 'Actor target for look-at rotation mode. This is not a model-animation clip index.'),
    'unk2D': ParameterInfo('Path interpolation', 'Position and rotation interpolation; scale retains smooth interpolation.',
        ((0, 'Smooth curve'), (1, 'Linear'))),
    'soundEffect': ParameterInfo('Transition color index', 'Color-table index used by screen transitions; this field does not select a sound effect.'),
    'fadeOptions': ParameterInfo('Actor opacity flags', 'Bit 0 fades out instead of in; bit 1 resets opacity before fading.'),
    'unk30': ParameterInfo('Music fade', 'Signed music-fade request, scaled by 256. Zero leaves the current fade unchanged.'),
}

# object_functions.c:obj_init/loop_fish, obj_init_butterfly,
# obj_init/loop_texscroll; objects.c:render_misc_object (fish height scale).
PARAMETER_LABELS: dict[int, dict[str, ParameterInfo]] = {
    3: {
        'unk8': ParameterInfo('Swim radius', 'Horizontal figure-eight path radius in game units.'),
        'unkA': ParameterInfo('Depth variation', 'Maximum random vertical excursion around the stored home height.'),
        'unkB': ParameterInfo('Texture variant', 'Selects one of this fish definition\'s textures, with fallback to variant 0.'),
        'unkC': ParameterInfo('Scale', 'Raw value × 0.01.'),
        'unkD': ParameterInfo('Height scale', 'Additional vertical artwork scale: raw value × 0.01.'),
        'unkE': ParameterInfo('Swim speed', 'Path phase advance per tick: raw value × 16 binary-angle units.'),
        'unkF': ParameterInfo('Swim path yaw', 'Orientation of the horizontal path: 256 units per revolution.'),
    },
    13: CHECKPOINT_PARAMETERS,
    14: {'unk10': ParameterInfo('Blocked vehicle mask', 'Vehicles prevented from opening the door: bit 0=Car, bit 1=Hovercraft, bit 2=Plane.')},
    17: {'unk8': ParameterInfo('Unused byte (0x08)', 'The Revision 1 weapon-balloon initializer does not read this field; its original purpose is unknown.')},
    29: {
        'unkA': ParameterInfo('U scroll speed', 'Signed horizontal scroll rate; 128 units correspond to one texel per NTSC tick.'),
        'unkB': ParameterInfo('V scroll speed', 'Signed vertical scroll rate; 128 units correspond to one texel per NTSC tick.'),
    },
    37: {
        'unkA': ParameterInfo('Weather velocity X', 'Horizontal weather velocity, passed to weather_set as raw value × 256.'),
        'unkC': ParameterInfo('Weather velocity Y', 'Vertical weather velocity, passed to weather_set as raw value × 256.'),
        'unkE': ParameterInfo('Weather velocity Z', 'Horizontal weather velocity, passed to weather_set as raw value × 256.'),
        'unk10': ParameterInfo('Weather intensity', 'Intensity passed to weather_set as raw value × 257.'),
        'unk11': ParameterInfo('Weather opacity', 'Opacity passed to weather_set as raw value × 257.'),
        'unk12': ParameterInfo('Weather transition ticks', 'Duration passed to weather_set. Positive values enable the transition.'),
    },
    38: {
        'unkA': ParameterInfo('Bridge timer ID', 'Connects the bridge to its ramp switch; also selects the bell position for a drawbridge.'),
        'unkB': ParameterInfo('Bridge activation mode', 'Selects proximity, timer, vehicle or drawbridge behavior.',
            ((0, 'Proximity'), (1, 'Timer'), (2, 'Vehicle'), (3, 'Drawbridge'))),
        'unkD': ParameterInfo('Bridge hold ticks', 'Timer activation holds the bridge for raw value × 2 ticks, refreshed while the switch timer is active.'),
    },
    39: {'unk8': ParameterInfo('Bridge timer ID', 'Timer started by this switch when a racer is within 45 game units.')},
    49: ANIMATION_PARAMETERS,
    55: {
        'unkB': ParameterInfo('Message ID', 'Text requested on crossing. 255 disables the message.'),
        'unkC': ParameterInfo('Release ambient actor ID', 'Values 0–127 release a waiting ambient actor. The game adds 128 and wraps to eight bits; 255 disables the request.'),
        'unkD': ParameterInfo('Excluded racer mask', 'Bit 0 excludes computer racers; bit 1 excludes human racers from activating this trigger.'),
    },
    61: {
        'unk8': ParameterInfo('Roaming / trigger radius', 'Radius used to search for nearby racers or butterfly targets; some flight states use twice this radius.'),
        'unkA': ParameterInfo('Texture variant', 'Selects the butterfly texture; variant 2 also changes flight behavior.'),
        'unkB': ParameterInfo('Scale', 'Raw value × 0.01.'),
    },
    71: {
        'unkA': ParameterInfo('Channel fade actions', '16 stored channel bytes. Bits 0–1 apply in one crossing direction; bits 2–3 in the other. Actions: 0 off, 1 on, 2 fade out, 3 fade in.'),
        'unk1A': ParameterInfo('Fade duration seconds', 'Transition duration multiplied by the video refresh rate.'),
        'unk1B': ParameterInfo('Music ID', 'Fade zone only applies while this music sequence is playing.'),
    },
    111: {'unk9': ParameterInfo('Open yaw', 'Open-door yaw: 64 units per revolution, using the low six bits.')},
    112: {
        'unk8': ParameterInfo('Inner fade radius', 'Distance at which the inner channel mix is reached.'),
        'unkA': ParameterInfo('Outer fade radius', 'Distance at which the outer channel mix is reached; the game corrects values below the inner radius.'),
        'unkC': ParameterInfo('Channel fade actions', 'Stored channel array: action 1 fades out with distance, action 2 fades in with distance. The initializer copies only the first 15 bytes.'),
        'unk1C': ParameterInfo('Music ID', 'Distance fade only applies while this music sequence is playing.'),
    },
    118: {
        'unk8': ParameterInfo('Music channel mask', 'Channel mask passed to music_dynamic_set while this music sequence is playing.'),
        'unkA': ParameterInfo('Activation radius', 'Raw value × 4 game units.'),
        'unkB': ParameterInfo('Music ID', 'Channel change only applies while this music sequence is playing.'),
    },
}


def parameter_info(behavior: int, name: str) -> ParameterInfo | None:
    return PARAMETER_LABELS.get(behavior, {}).get(name)


def parameter_label(behavior: int, name: str, offset: int) -> str:
    info = parameter_info(behavior, name)
    if info is not None:
        return info.label
    if re.fullmatch(r'unk[0-9a-f]+', name, re.IGNORECASE):
        return f'Unknown (0x{offset:02X})'
    if name.startswith('pad'):
        return f'Padding (0x{offset:02X})'
    label = re.sub(r'(?<=[a-z0-9])(?=[A-Z])|_', ' ', name)
    return label[:1].upper()+label[1:].replace(' Id', ' ID')
