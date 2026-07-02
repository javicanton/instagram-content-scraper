#!/usr/bin/env node
/* eslint-disable no-console */
const fs = require('fs');
const path = require('path');

function loadEnv() {
  const envPath = path.join(__dirname, '..', '.env');
  if (!fs.existsSync(envPath)) return '';
  const text = fs.readFileSync(envPath, 'utf8');
  for (const line of text.split('\n')) {
    const m = line.match(/^INSTAGRAM_SESSION_ID=(.*)$/);
    if (m) return m[1].trim().replace(/^["']|["']$/g, '');
  }
  return '';
}

async function main() {
  const insta = require('instatouch');
  const raw = loadEnv();
  if (!raw) {
    console.error('No INSTAGRAM_SESSION_ID in .env');
    process.exit(1);
  }
  const session = raw.startsWith('sessionid=') ? raw : `sessionid=${raw}`;
  console.log('Session length:', raw.length);
  console.log('Testing @natgeo via instatouch module...\n');

  try {
    const result = await insta.user('natgeo', {
      count: 3,
      session,
      timeout: 5000,
      filetype: 'na',
      cli: false,
    });
    console.log('count:', result.count);
    console.log('auth_error:', result.auth_error);
    console.log('collector length:', result.collector ? result.collector.length : 0);
    console.log('has_more:', result.has_more);
    if (result.collector && result.collector.length) {
      console.log('first post id:', result.collector[0].id);
    } else {
      console.log('\nSin datos. auth_error=true → sesión inválida/expirada.');
      console.log('auth_error=false → API GraphQL de instatouch probablemente rota (Instagram cambió la API).');
    }
  } catch (err) {
    console.error('Exception:', err.message || err);
    process.exit(2);
  }
}

main();
