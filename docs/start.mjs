process.on('uncaughtException', e => console.error('UNCAUGHT:', e));
process.on('unhandledRejection', e => console.error('UNHANDLED:', e));
import('./server.js');
