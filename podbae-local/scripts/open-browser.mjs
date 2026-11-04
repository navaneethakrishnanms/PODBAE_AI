import open from 'open';

await open(process.argv[2] ?? 'http://localhost:5173');
console.log('opened browser');
