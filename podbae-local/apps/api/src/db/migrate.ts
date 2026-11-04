import { client, initDb } from './client.js';

await initDb();
await client.close();
console.log('migrations applied');
