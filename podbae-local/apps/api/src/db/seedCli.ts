import { client, initDb } from './client.js';
import { seedDatabase } from './seed.js';

await initDb();
const result = await seedDatabase();
await client.close();
if (result.skipped) console.log('Database already seeded. Use `npm run reset` to wipe and reseed.');
else {
  console.log('\nSeeded demo data (all fake, demo=true). Logins:');
  console.log('  admin@podbae.local      / admin123  (admin)');
  console.log('  podcaster@podbae.local  / demo123   (podcaster, flirt tier)');
  console.log('  brand@podbae.local      / demo123   (advertiser)');
  console.log('  other demo accounts: *@demo.podbae.local / demo123');
}
