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
        const lines = [`You face ${facingOf(bot.entity.yaw)}, standing at ${at(me)}.`];

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

export function wingmanSenses() {
    return [playerView, lookAround, turnTo];
}
