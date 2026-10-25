// Senses for a Mindcraft bot that plays alongside a human: three query
// commands that Mindcraft does not have. senses_hook.mjs puts them onto
// Mindcraft's command list; the model uses them like any other command.
//
//   !playerView("name")  where the player stands relative to the bot, which
//                        way they look and what they look at, block or
//                        creature, with coordinates. For "this one", "over
//                        there", "in front of me", "where I am looking".
//   !lookAround          the bot's own facing and what lies around it within
//                        32 blocks, each with direction, distance and
//                        coordinates. For "behind you", "the water", "the
//                        house", "the lava".
//   !turnTo(x, y, z)     face a position without moving.
//   !goThroughDoor(x, y, z)  walk through a door to its other side, opening
//                        it if needed: into a house or out of it. With
//                        !goToCoordinates the bot stops at the wall, one
//                        block from the spot, and is sure it is inside.
//
// Directions: Minecraft's -z is north and +x is east. Mineflayer's yaw is 0
// when facing north and grows counter-clockwise seen from above, so a target
// at a positive angle relative to the facing is on the left.

const COMPASS = ['north', 'north-east', 'east', 'south-east', 'south', 'south-west', 'west', 'north-west'];
const EYE_HEIGHT = 1.62;
const SIGHT = 100;
const AROUND = 32;
const ALONG = 20;

const KINDS = [
    ['water', (name) => name === 'water'],
    ['lava', (name) => name === 'lava'],
    ['a door', (name) => name.endsWith('_door')],
    ['a bed', (name) => name.endsWith('_bed')],
    ['a chest', (name) => name === 'chest' || name === 'trapped_chest' || name === 'barrel'],
    ['a crafting table', (name) => name === 'crafting_table'],
    ['a furnace', (name) => name === 'furnace' || name === 'blast_furnace' || name === 'smoker'],
    ['a bell', (name) => name === 'bell'],
    ['hay', (name) => name === 'hay_block'],
    ['a tree', (name) => name.endsWith('_log')],
    ['ore', (name) => name.endsWith('_ore')],
];

function kindOf(name) {
    for (const [kind, test] of KINDS) {
        if (test(name)) return kind;
    }
    return null;
}

function compass(dx, dz) {
    const turn = Math.atan2(dx, -dz) / (2 * Math.PI); // 0 north, 0.25 east, 0.5 south
    return COMPASS[((Math.round(turn * 8) % 8) + 8) % 8];
}

function facingOf(yaw) {
    return compass(-Math.sin(yaw), -Math.cos(yaw));
}

function viewDirection(yaw, pitch) {
    const flat = Math.cos(pitch);
    return { x: -Math.sin(yaw) * flat, y: Math.sin(pitch), z: -Math.cos(yaw) * flat };
}

function vec(like, x, y, z) {
    return new like.constructor(x, y, z);
}

function at(v) {
    return `(${Math.floor(v.x)}, ${Math.floor(v.y)}, ${Math.floor(v.z)})`;
}

function pitchWord(pitch) {
    const deg = (pitch * 180) / Math.PI;
    if (deg > 50) return ' and steeply up';
    if (deg > 15) return ' and up';
    if (deg < -50) return ' and steeply down';
    if (deg < -15) return ' and down';
    return '';
}

function entityName(entity) {
    return entity.username || entity.name || entity.displayName || 'something';
}

// Dropped items, orbs and projectiles are not creatures.
function isClutter(entity) {
    return entity.type === 'object' || entity.type === 'orb' || entity.name === 'item' || entity.name === 'experience_orb';
}

// A roof or the sky above the bot: whether it is inside.
function roofAbove(bot) {
    const head = bot.entity.position.offset(0, 2, 0);
    for (let up = 0; up < 48; up++) {
        const block = bot.blockAt(head.offset(0, up, 0));
        if (!block) break;
        if (block.name === 'air' || block.name === 'cave_air' || block.name === 'void_air') continue;
        return `under a roof (${block.name}, ${up + 1} blocks above your head)`;
    }
    return 'under the open sky';
}

function doorProps(block) {
    if (!block) return {};
    try {
        return (block.getProperties ? block.getProperties() : block._properties) || {};
    } catch (err) {
        return block._properties || {};
    }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Into a house or out of it: stand before the door, open it, step to the far side.
async function walkThroughDoor(bot, skills, x, y, z) {
    const log = (message) => {
        bot.output += message + '\n';
    };
    let door = bot.blockAt(vec(bot.entity.position, Math.floor(x), Math.floor(y), Math.floor(z)));
    if (!door || !door.name.endsWith('_door')) {
        log(`There is no door at (${x}, ${y}, ${z}), there is ${door ? door.name : 'nothing loaded'}. !lookAround names the nearest door with its coordinates.`);
        return;
    }
    if (doorProps(door).half === 'upper') door = bot.blockAt(door.position.offset(0, -1, 0)) || door;
    const base = door.position;
    if (door.name.startsWith('iron_')) {
        log(`The ${door.name} at ${at(base)} is iron: it opens only with a button, lever or pressure plate.`);
        return;
    }
    const step = { north: [0, -1], south: [0, 1], east: [1, 0], west: [-1, 0] }[doorProps(door).facing];
    if (!step) {
        log(`Cannot tell which way the ${door.name} at ${at(base)} faces.`);
        return;
    }
    const front = base.offset(step[0], 0, step[1]);
    const back = base.offset(-step[0], 0, -step[1]);
    const me = bot.entity.position;
    const [near, far] = me.distanceTo(front) <= me.distanceTo(back) ? [front, back] : [back, front];
    const beyond = far.offset(far.x - base.x, 0, far.z - base.z); // one block further in: the doorway itself is not "through"

    await skills.goToPosition(bot, near.x, near.y, near.z, 1);
    if (bot.interrupt_code) return;
    const open = doorProps(bot.blockAt(base)).open;
    if (open === false || open === 'false') {
        try {
            await bot.activateBlock(bot.blockAt(base));
            await sleep(400);
        } catch (err) {
            log(`Could not open the ${door.name}: ${err.message}.`);
        }
    }
    // The block the bot stands in decides the side: the doorway itself is neither.
    const onFarSide = () => {
        const node = bot.entity.position.floored();
        return (far.x - base.x) * (node.x - base.x) + (far.z - base.z) * (node.z - base.z) > 0;
    };
    await skills.goToPosition(bot, beyond.x, beyond.y, beyond.z, 1);
    if (bot.interrupt_code) return;
    if (!onFarSide()) {
        await skills.goToPosition(bot, far.x, far.y, far.z, 0);
        if (bot.interrupt_code) return;
    }
    const here = bot.entity.position;
    if (onFarSide()) {
        log(`You went through the ${door.name} at ${at(base)} and stand on its other side now, at ${at(here)}, ${roofAbove(bot)}.`);
    } else {
        log(`You did not get through the ${door.name} at ${at(base)}; you stand at ${at(here)}. Something blocks the way behind it.`);
    }
}

// "4 blocks south-east, 1 higher (to your left)": a place seen from the bot.
function whereFrom(bot, target) {
    const me = bot.entity.position;
    const dx = target.x - me.x;
    const dy = target.y - me.y;
    const dz = target.z - me.z;
    const flat = Math.sqrt(dx * dx + dz * dz);
    let text = flat < 1.5 ? 'right next to you' : `${Math.round(flat)} blocks ${compass(dx, dz)}`;
    if (dy >= 1.5) text += `, ${Math.round(dy)} higher`;
    else if (dy <= -1.5) text += `, ${Math.round(-dy)} lower`;
    if (flat < 1.5) return text;
    const toTarget = Math.atan2(-dx, -dz);
    const rel = (Math.atan2(Math.sin(toTarget - bot.entity.yaw), Math.cos(toTarget - bot.entity.yaw)) * 180) / Math.PI;
    if (Math.abs(rel) <= 45) text += ' (in front of you)';
    else if (Math.abs(rel) >= 135) text += ' (behind you)';
    else text += rel > 0 ? ' (to your left)' : ' (to your right)';
    return text;
}

// The first creature on a line of sight, nearer than maxDistance.
function creatureOnRay(bot, eye, dir, maxDistance, skip) {
    let best = null;
    let bestT = maxDistance;
    for (const entity of Object.values(bot.entities)) {
        if (!entity || !entity.position || entity === skip || isClutter(entity)) continue;
        const height = entity.height || 1;
        const width = entity.width || 0.6;
        const center = entity.position.offset(0, height / 2, 0);
        const vx = center.x - eye.x;
        const vy = center.y - eye.y;
        const vz = center.z - eye.z;
        const t = vx * dir.x + vy * dir.y + vz * dir.z; // how far along the line
        if (t <= 0 || t > bestT) continue;
        const px = vx - dir.x * t;
        const py = vy - dir.y * t;
        const pz = vz - dir.z * t;
        const off = Math.sqrt(px * px + py * py + pz * pz); // how far from the line
        if (off <= Math.max(width, height) / 2 + 0.3) {
            best = entity;
            bestT = t;
        }
    }
    return best;
}

const playerView = {
    name: '!playerView',
    description:
        'Where a player stands relative to you, which way they look and what they look at, with coordinates. ' +
        'Use it when the player says "this", "there", "in front of me" or "where I am looking".',
    params: {
        player_name: { type: 'string', description: "The player's name." },
    },
    perform: function (agent, playerName) {
        const bot = agent.bot;
        const record = bot.players[playerName];
        const player = record && record.entity;
        if (!player) return `${playerName} is out of sight: too far away or not in the world.`;
        const yaw = player.headYaw ?? player.yaw ?? 0;
        const pitch = player.pitch ?? 0;
        const dir = viewDirection(yaw, pitch);
        const eye = player.position.offset(0, EYE_HEIGHT, 0);
        let block = null;
        try {
            block = bot.world.raycast(eye, vec(eye, dir.x, dir.y, dir.z), SIGHT);
        } catch (err) {
            block = null;
        }
        const blockDistance = block && block.intersect ? block.intersect.distanceTo(eye) : SIGHT;
        const creature = creatureOnRay(bot, eye, dir, blockDistance, player);
        let look = `${playerName} looks ${compass(dir.x, dir.z)}${pitchWord(pitch)}`;
        if (creature) {
            look += ` at ${entityName(creature)} at ${at(creature.position)}, ${Math.round(creature.position.distanceTo(eye))} blocks from them`;
        } else if (block) {
            look += ` at ${block.name} at ${at(block.position)}, ${Math.round(blockDistance)} blocks from them`;
        } else {
            look += ` at nothing within ${SIGHT} blocks, sky or open distance`;
        }
        const ahead = eye.offset(dir.x * ALONG, dir.y * ALONG, dir.z * ALONG);
        return (
            `${playerName} stands ${whereFrom(bot, player.position)}, at ${at(player.position)}. ` +
            `${look}. ${ALONG} blocks along their line of sight is ${at(ahead)}.`
        );
    },
};

const lookAround = {
    name: '!lookAround',
    description:
        'Your own facing and what lies around you within 32 blocks: water, lava, doors, beds, chests, tables, furnaces, ' +
        'bells, hay, trees, ore and the creatures and players nearby, each with direction, distance and coordinates. ' +
        'Use it when the player says "behind you", "the water", "the house" or "over there".',
    perform: function (agent) {
        const bot = agent.bot;
        const me = bot.entity.position;
        const lines = [`You face ${facingOf(bot.entity.yaw)}, standing at ${at(me)}, ${roofAbove(bot)}.`];

        const nearest = new Map();
        let positions = [];
        try {
            positions = bot.findBlocks({ matching: (block) => kindOf(block.name) !== null, maxDistance: AROUND, count: 600 });
        } catch (err) {
            positions = [];
        }
        for (const point of positions) {
            const block = bot.blockAt(point);
            if (!block) continue;
            const kind = kindOf(block.name);
            const distance = point.distanceTo(me);
            const known = nearest.get(kind);
            if (!known || distance < known.distance) nearest.set(kind, { block, distance });
        }
        const things = [];
        for (const [kind] of KINDS) {
            const hit = nearest.get(kind);
            if (hit) things.push(`${kind} (${hit.block.name}) ${whereFrom(bot, hit.block.position)} at ${at(hit.block.position)}`);
        }
        lines.push(
            things.length
                ? `Around you within ${AROUND} blocks: ${things.join('; ')}.`
                : `Nothing notable within ${AROUND} blocks: no water, lava, doors, beds, chests, tables, furnaces, bells, hay, trees or ore.`
        );

        const creatures = new Map();
        for (const entity of Object.values(bot.entities)) {
            if (!entity || entity === bot.entity || !entity.position || isClutter(entity)) continue;
            const distance = entity.position.distanceTo(me);
            if (distance > AROUND) continue;
            const name = entityName(entity);
            const known = creatures.get(name);
            if (!known || distance < known.distance) creatures.set(name, { entity, distance });
        }
        const list = [...creatures.values()]
            .sort((a, b) => a.distance - b.distance)
            .slice(0, 8)
            .map(({ entity }) => `${entityName(entity)} ${whereFrom(bot, entity.position)}`);
        if (list.length) lines.push(`Creatures and players: ${list.join('; ')}.`);
        return lines.join('\n');
    },
};

const turnTo = {
    name: '!turnTo',
    description: 'Turn to face a position without moving, for example what the player looks at or a creature.',
    params: {
        x: { type: 'float', description: 'The x coordinate.', domain: [-Infinity, Infinity] },
        y: { type: 'float', description: 'The y coordinate.', domain: [-64, 320] },
        z: { type: 'float', description: 'The z coordinate.', domain: [-Infinity, Infinity] },
    },
    perform: async function (agent, x, y, z) {
        const bot = agent.bot;
        await bot.lookAt(vec(bot.entity.position, x, y, z));
        return `You now face ${compass(x - bot.entity.position.x, z - bot.entity.position.z)}.`;
    },
};

function goThroughDoor(skills) {
    return {
        name: '!goThroughDoor',
        description:
            'Walk through the door at x, y, z to its other side, opening it if needed: this is how you get into a house ' +
            'or out of it. Take the coordinates from !lookAround or !playerView. !goToCoordinates cannot do this, it stops at the wall.',
        params: {
            x: { type: 'float', description: "The door's x coordinate.", domain: [-Infinity, Infinity] },
            y: { type: 'float', description: "The door's y coordinate.", domain: [-64, 320] },
            z: { type: 'float', description: "The door's z coordinate.", domain: [-Infinity, Infinity] },
        },
        perform: async function (agent, x, y, z) {
            if (!skills || typeof skills.goToPosition !== 'function') {
                return 'Walking through doors is not available in this Mindcraft.';
            }
            const result = await agent.actions.runAction('action:goThroughDoor', async () => {
                await walkThroughDoor(agent.bot, skills, x, y, z);
            });
            if (result.interrupted && !result.timedout) return;
            return result.message;
        },
    };
}

// `skills` is Mindcraft's src/agent/library/skills.js, handed in by senses_hook.mjs.
export function wingmanSenses(skills) {
    return [playerView, lookAround, turnTo, goThroughDoor(skills)];
}
