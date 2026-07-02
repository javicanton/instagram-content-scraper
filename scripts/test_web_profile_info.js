#!/usr/bin/env node
/* eslint-disable no-console */
const fs = require('fs');
const path = require('path');
const https = require('https');

function loadEnv() {
  const envPath = path.join(__dirname, '..', '.env');
  const text = fs.readFileSync(envPath, 'utf8');
  for (const line of text.split('\n')) {
    const m = line.match(/^INSTAGRAM_SESSION_ID=(.*)$/);
    if (m) return m[1].trim().replace(/^["']|["']$/g, '');
  }
  return '';
}

function get(url, headers) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, { headers }, (res) => {
      let data = '';
      res.on('data', (c) => { data += c; });
      res.on('end', () => {
        resolve({ status: res.statusCode, ct: res.headers['content-type'], body: data });
      });
    });
    req.on('error', reject);
    req.setTimeout(15000, () => req.destroy(new Error('timeout')));
  });
}

async function main() {
  const raw = loadEnv();
  const session = raw.startsWith('sessionid=') ? raw : `sessionid=${raw}`;
  const headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'X-IG-App-ID': '936619743392459',
    Accept: '*/*',
    cookie: session,
  };

  const endpoints = [
    'https://i.instagram.com/api/v1/users/web_profile_info/?username=natgeo',
    'https://www.instagram.com/api/v1/users/web_profile_info/?username=natgeo',
  ];

  for (const url of endpoints) {
    console.log('\n---', url);
    try {
      const r = await get(url, headers);
      console.log('status:', r.status, 'type:', r.ct);
      if (r.body.startsWith('{')) {
        const j = JSON.parse(r.body);
        const user = j.data?.user || j.user;
        const edges = user?.edge_owner_to_timeline_media?.edges || [];
        console.log('user:', user?.username, 'posts in page:', edges.length);
        if (edges.length) console.log('first shortcode:', edges[0].node?.shortcode);
      } else {
        console.log('body preview:', r.body.slice(0, 200));
      }
    } catch (e) {
      console.log('error:', e.message);
    }
  }
}

main();
