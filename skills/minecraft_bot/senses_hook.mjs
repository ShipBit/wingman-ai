// Gives the Mindcraft bot the senses it lacks when it plays alongside a human:
// where the player stands and looks, what lies around the bot. The commands are
// in senses.mjs; this file gets them into Mindcraft.
//
// Mindcraft has no plugin API, and its command list is built once when
// src/agent/commands/index.js is evaluated. So the skill starts every Node
// process of Mindcraft with NODE_OPTIONS=--import=<this file>. Loaded before
// anything else, it registers a module hook that appends a few lines to
// src/agent/commands/queries.js as it is read: the senses are pushed onto
// Mindcraft's query list before index.js builds the command list from it.
// Nothing in the user's checkout is changed, and when Mindcraft moves or
// rewrites that file, the hook adds nothing and the bot plays without the
// extra senses.
//
// Needs Node.js 20.6 or newer (module.register); the skill checks the version.

import { register } from 'node:module';
import { isMainThread } from 'node:worker_threads';

const QUERIES_FILE = '/src/agent/commands/queries.js';
const QUERY_LIST = 'export const queryList';
const SENSES_URL = new URL('./senses.mjs', import.meta.url).href;

// The main thread of each process registers the hook; the hook itself runs on
// Node's loader thread, where this module is loaded a second time.
if (isMainThread) {
    try {
        register(import.meta.url, { data: { sensesUrl: SENSES_URL } });
    } catch (err) {
        console.warn(`[Wingman] The bot's senses are not available: ${err && err.message ? err.message : err}`);
    }
}

let sensesUrl = SENSES_URL;

export function initialize(data) {
    if (data && data.sensesUrl) {
        sensesUrl = data.sensesUrl;
    }
}

export async function load(url, context, nextLoad) {
    const result = await nextLoad(url, context);
    if (!url.endsWith(QUERIES_FILE) || result.format !== 'module' || result.source == null) {
        return result;
    }
    const source = typeof result.source === 'string' ? result.source : Buffer.from(result.source).toString('utf8');
    if (!source.includes(QUERY_LIST)) {
        console.warn('[Wingman] Mindcraft\'s queries.js looks different; the bot plays without the extra senses.');
        return result;
    }
    const addition =
        `\n// Added by Wingman AI's Minecraft Bot skill (senses_hook.mjs).\n` +
        `import { wingmanSenses } from ${JSON.stringify(sensesUrl)};\n` +
        `import * as wingmanSkills from '../library/skills.js';\n` +
        `queryList.push(...wingmanSenses(wingmanSkills));\n`;
    console.log('[Wingman] Senses added to the bot: !playerView, !lookAround, !whereIs, !turnTo, !goThroughDoor');
    return { ...result, source: source + addition };
}
