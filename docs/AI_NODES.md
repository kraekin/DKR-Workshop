# AI nodes: uses, fields and editing

Reviewed against the local Rev 1 source and the original USA Rev 1 ROM on
2026-10-22. This is a source review; no application or game data was changed.

## What uses them

AI nodes are positions in a directed navigation graph. Their numeric IDs do
not define the order of a route. Each node stores up to four outgoing links.

- Taj and T.T. use the graph when roaming. Their movement helper samples a
  Catmull–Rom path through successive nodes, so the actual path can curve
  between the editor's straight connection lines.
- Moving golden balloons use the same NPC path helper in their roaming state.
- Battle and banana challenge opponents navigate this graph, either wandering
  or searching for a destination. This covers Darkwater Beach, Icicle Pyramid
  and Smokey Castle in the original game.
- Loop-de-loop handling uses the graph for computer-controlled steering in
  that special vehicle mode.
- Ordinary race opponents use checkpoint paths and their four AI lanes.
  Fire Mountain's egg challenge instead targets eggs/nests/other objectives
  directly. Adding AI nodes does not replace either of these systems.

The original Ancient Lake has four AI nodes, IDs 0–3, each with all four links
set to 255. They do not form an opponent raceline. Their original intended
purpose has not been established here.

Fish proximity was checked separately: `obj_init_fish` and `obj_loop_fish`
(`object_functions.c:1418–1600`) do not read AI nodes. They generate a rotated
figure-eight horizontal path around each fish's stored spawn X/Z, with its
own radius (`unk8`, u16), phase rate (`unkE << 4`) and heading (`unkF << 8`).
Random vertical movement uses the stored spawn Y and `unkA` range. Thus the
nearby Ancient Lake nodes do not bound or guide these fish. Whether those
nodes are leftovers from an earlier design remains unknown.

## Stored fields

`LevelObjectEntry_AiNode` is 0x10 bytes including the common ID/size/XYZ header.

| Field | Meaning |
|---|---|
| Position X/Y/Z | The node's world position. It controls path shape and contributes to link distance and elevation thresholds. |
| `0x08 unk8` | Destination tag used by challenge routing; see below. This byte is used. |
| `0x09 nodeID` | Unique ID 0–127 in one global table for all loaded object maps. It is independent of the editor row number. 255 requests runtime assignment. |
| `0x0A…0x0D adjacent[4]` | Four outgoing node IDs; 255 means no connection. Slots are alternatives, not four successive steps and not compass directions. |
| `0x0E elevation` | Logical height layer for challenge navigation. Use 0–3 for that system. It is separate from the actual Y coordinate. |
| `0x0F padF` | No reader identified in the reviewed node consumers. Preserve it. |

The loader derives elevation thresholds from nodes sorted by actual Y and
their low two elevation bits. Nearest-node filtering and challenge checks also
compare the stored elevation value directly. It is therefore inaccurate to
assume the upper bits are ignored everywhere. Several stock non-challenge
nodes store -1; preserve those unless deliberately changing their purpose.

### Destination tags (`unk8`)

| Value | Verified role |
|---|---|
| 0 | Ordinary/default node; no special destination request for tag 0 was found in the reviewed challenge calls. |
| 1 | Destination category requested by weapon-seeking challenge AI and its related response state. Stock placements generally lead to weapon balloon locations; the tag does not create a pickup. |
| 2 | Exists in stock Icicle Pyramid. No special routing request for tag 2 was identified; its intended meaning remains unknown. |
| 3 | Recovery candidate: after an elevation mismatch, challenge AI searches for the nearest tag-3 node on its current elevation layer. |
| 4–7 | Banana deposit destination for racer slots 0–3 respectively (`racerIndex + 4`). Stock Smokey Castle nodes are beside the corresponding treasure boxes. These are racer slots, not character IDs. |

Challenge routing searches the linked graph using cached 3D link distances.
It can seek a tag or a particular node near an opponent. Generic wandering
cycles through outgoing slots while avoiding an immediate return to the
previous node; slot order can therefore affect branch choices. Link weights
do not include a collision or walkability test. Connections must follow
traversable space rather than crossing walls or gaps.

## Using the editor

1. Select an AI node through **Objects**, then open **Tools → Routes**.
2. Give each node a unique `nodeID` in **Objects**. IDs are global across both
   object maps loaded for the level. Prefer explicit IDs for editable routes.
3. Move nodes to form the desired path. For a simple roaming loop, connect
   `0 → 1 → 2 → 3 → 0`, using one outgoing slot per node. Other slots can be 255.
4. Under **AI directed connections**, choose a target for a slot or use
   **Pick…** and click its marker. Escape cancels picking.
5. A link from A to B does not add B to A. Add reciprocal links separately
   only where travel in both directions is intended. Avoid dead ends for
   roaming actors: their usual next-node chooser excludes the previous node.
6. Enable **Racelines** to see graph connections. The straight lines represent
   stored links, not a full simulation of NPC curves or vehicle steering.
7. Check the panel's diagnostics for duplicate IDs, missing targets and other
   reference problems. Changing an ID does not automatically retarget links.

For a normal custom race, build checkpoints and adjust their AI lanes first.
AI nodes are needed when the relevant roaming, challenge or special-mode
consumer is present; they do not define lap progression or the starting grid.

## Local source evidence

- `research/Diddy-Kong-Racing/include/level_object_entries.h:184`: entry layout.
- `research/Diddy-Kong-Racing/src/objects.c:7327`: global table, link distances
  and elevation thresholds; `:7464` nearest-node filters; `:7510` NPC path;
  `:7636` outgoing-slot selection; `:7674` graph search by tag or target ID.
- `research/Diddy-Kong-Racing/src/object_functions.c:1361`, `:3024`, `:3485`:
  T.T., Taj and golden balloon consumers; `:3283` loop-de-loop entry;
  `:4183` AI node initialization and runtime-assigned IDs.
- `research/Diddy-Kong-Racing/src/racer.c:610`: race-type dispatch; `:922–975`
  challenge destinations and recovery; `:1036` separate egg challenge;
  `:3762` loop steering; `:9060` ordinary checkpoint AI lane sampling.
- `src/core/objects.py:626`, `src/core/routes.py:45` and
  `src/ui/route_panel.py`: editor graph preview, connection edits and diagnostics.

This review establishes source behavior. Gameplay changes remain subject to
the user's in-game testing; no emulator or gameplay ROM was produced.
