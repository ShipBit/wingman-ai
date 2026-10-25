// Starts Mindcraft's MindServer from the Mindcraft checkout in the current
// working directory, without agents and without opening the browser UI.
// The Wingman AI Minecraft Bot skill runs this file with Node.js and then
// creates the bot over the MindServer's Socket.IO API.
//
//   node launcher.mjs --port 8080      (cwd = the Mindcraft folder)

import path from 'path';
import { pathToFileURL } from 'url';

const args = process.argv.slice(2);
let port = 8080;
for (let i = 0; i < args.length; i++) {
    if (args[i] === '--port' && args[i + 1]) {
        port = Number(args[i + 1]);
    }
}

const entry = path.resolve(process.cwd(), 'src', 'mindcraft', 'mindcraft.js');

let Mindcraft;
try {
    Mindcraft = await import(pathToFileURL(entry).href);
} catch (err) {
    const reason = err && err.message ? err.message : String(err);
    console.error(`WINGMAN_MINDCRAFT_IMPORT_FAILED ${entry}: ${reason}`);
    process.exit(2);
}

try {
    await Mindcraft.init(false, port, false);
} catch (err) {
    const reason = err && err.message ? err.message : String(err);
    console.error(`WINGMAN_MINDSERVER_FAILED ${reason}`);
    process.exit(3);
}

console.log(`WINGMAN_MINDSERVER_READY ${port}`);
