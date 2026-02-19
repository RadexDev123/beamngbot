const http = require('http');
const url = require('url');
const fs = require('fs');
const path = require('path');
const os = require('os');

const DB_PATH = path.join(__dirname, 'database.json');
let db = { users: {} };
let userQueues = {}; // { username: [commands] }
let userReports = {}; // { username: reportData }
let userVehicles = {}; // { username: [modelNames] }
let userOrderStatus = {}; // { username: orderStatus }

function normalizeUsername(value) {
    const raw = String(value || '').trim();
    return raw ? raw.toLowerCase() : 'unknown';
}

function getLocalIPv4List() {
    const interfaces = os.networkInterfaces();
    const ips = [];
    for (const list of Object.values(interfaces)) {
        for (const addr of list || []) {
            if (addr && addr.family === 'IPv4' && !addr.internal) {
                ips.push(addr.address);
            }
        }
    }
    return Array.from(new Set(ips));
}

// Load DB on startup
if (fs.existsSync(DB_PATH)) {
    try {
        db = JSON.parse(fs.readFileSync(DB_PATH, 'utf8'));
        console.log('[DB] Database loaded. Users:', Object.keys(db.users).length);

        // Restore garage cache for bridge
        Object.values(db.users).forEach(u => {
            if (u.name && u.garageModels) {
                userVehicles[normalizeUsername(u.name)] = u.garageModels;
            }
        });
    } catch (e) {
        console.error('[DB] Failed to parse DB!', e);
    }
}

function saveToDisk() {
    try {
        fs.writeFileSync(DB_PATH, JSON.stringify(db, null, 2));
    } catch (e) {
        console.error('[DB] Failed to write DB to disk!', e);
    }
}

const server = http.createServer((req, res) => {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    if (req.method === 'OPTIONS') {
        res.writeHead(204);
        res.end();
        return;
    }

    const parsedUrl = url.parse(req.url, true);
    const pathname = parsedUrl.pathname;
    const query = parsedUrl.query;

    if (pathname === '/') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ status: 'ok', server: 'BeamNG Relay' }));
        return;
    }

    if (pathname === '/command' && req.method === 'POST') {
        let body = '';
        req.on('data', chunk => { body += chunk.toString(); });
        req.on('end', () => {
            try {
                const data = JSON.parse(body);
                const username = normalizeUsername(data.user || 'Unknown');
                console.log(`[BOT] -> Command for ${username}:`, data.type);

                if (!userQueues[username]) userQueues[username] = [];
                userQueues[username].push(data);

                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ status: 'ok' }));
            } catch (e) {
                res.writeHead(400); res.end('Invalid JSON');
            }
        });
    } else if (pathname === '/report_shift' && req.method === 'POST') {
        let body = '';
        req.on('data', chunk => { body += chunk.toString(); });
        req.on('end', () => {
            try {
                const data = JSON.parse(body);
                const username = normalizeUsername(data.user || 'Unknown');
                console.log(`[GAME] -> Report from ${username}:`, data.distance, 'km');

                userReports[username] = data;

                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ status: 'ok' }));
            } catch (e) {
                res.writeHead(400); res.end('Invalid JSON');
            }
        });
    } else if (pathname === '/report_order' && req.method === 'POST') {
        let body = '';
        req.on('data', chunk => { body += chunk.toString(); });
        req.on('end', () => {
            try {
                const data = JSON.parse(body);
                const username = normalizeUsername(data.user || 'Unknown');
                userOrderStatus[username] = data;
                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ status: 'ok' }));
            } catch (e) {
                res.writeHead(400); res.end('Invalid JSON');
            }
        });
    } else if (pathname === '/sync_garage' && req.method === 'POST') {
        let body = '';
        req.on('data', chunk => { body += chunk.toString(); });
        req.on('end', () => {
            try {
                const data = JSON.parse(body);
                const username = normalizeUsername(data.user || 'Unknown');
                userVehicles[username] = data.vehicles || [];
                console.log(`[BOT] -> Garage synced for ${username}:`, userVehicles[username]);
                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ status: 'ok' }));
            } catch (e) {
                res.writeHead(400); res.end('Invalid JSON');
            }
        });
    } else if (pathname === '/get_shift_report' && req.method === 'GET') {
        const username = normalizeUsername(query.user);
        res.writeHead(200, { 'Content-Type': 'application/json' });
        if (userReports[username]) {
            res.end(JSON.stringify(userReports[username]));
            delete userReports[username];
        } else {
            res.end(JSON.stringify({ type: 'none' }));
        }
    } else if (pathname === '/get_order_status' && req.method === 'GET') {
        const username = normalizeUsername(query.user);
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(userOrderStatus[username] || { type: 'none' }));
    } else if (pathname === '/get_user' && req.method === 'GET') {
        const userId = query.id;
        res.writeHead(200, { 'Content-Type': 'application/json' });
        if (userId && db.users[userId]) {
            res.end(JSON.stringify(db.users[userId]));
        } else {
            res.end(JSON.stringify({ status: 'not_found' }));
        }
    } else if (pathname === '/save_user' && req.method === 'POST') {
        let body = '';
        req.on('data', chunk => { body += chunk.toString(); });
        req.on('end', () => {
            try {
                const data = JSON.parse(body);
                const userId = data.id;
                if (userId) {
                    db.users[userId] = data;

                    // Update car list for game sync
                    if (data.garage && Array.isArray(data.garage)) {
                        // Bot should send resolved model list in `garageModels`
                        if (data.garageModels) {
                            userVehicles[normalizeUsername(data.name)] = data.garageModels;
                        }
                    }

                    saveToDisk();
                    res.writeHead(200, { 'Content-Type': 'application/json' });
                    res.end(JSON.stringify({ status: 'ok' }));
                } else {
                    res.writeHead(400); res.end('Missing ID');
                }
            } catch (e) {
                res.writeHead(400); res.end('Invalid JSON');
            }
        });
    } else if (pathname === '/poll') {
        const username = normalizeUsername(query.user || 'Unknown');
        res.writeHead(200, { 'Content-Type': 'application/json' });

        let queue = userQueues[username];
        if ((!queue || queue.length === 0) && username !== 'unknown' && userQueues.unknown && userQueues.unknown.length > 0) {
            queue = userQueues.unknown;
        }

        if (queue && queue.length > 0) {
            const command = queue.shift();
            console.log(`[GAME] <<< Command delivered to ${username}:`, command.type);
            res.end(JSON.stringify({ ...command, garage: userVehicles[username] || [] }));
        } else {
            res.end(JSON.stringify({ type: 'none', garage: userVehicles[username] || [] }));
        }
    } else if (pathname === '/get_leaderboard' && req.method === 'GET') {
        const users = Object.values(db.users)
            .sort((a, b) => b.balance - a.balance)
            .slice(0, 50); // limit 50 users
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(users));
    } else {
        res.writeHead(404);
        res.end('Not Found');
    }
});

const PORT = 3000;
server.listen(PORT, '0.0.0.0', () => {
    console.log(`\n=== MULTIPLAYER RELAY STARTED ON PORT ${PORT} ===`);
    const ips = getLocalIPv4List();
    if (ips.length === 0) {
        console.log(`[NET] No external IPv4 found. Localhost: http://127.0.0.1:${PORT}`);
    } else {
        console.log('[NET] Use one of these IPs in mini-app and mod config:');
        ips.forEach((ip) => console.log(` - http://${ip}:${PORT}`));
    }
    console.log('Players must set your PC IP in mini-app settings and in the game mod config.');
});

