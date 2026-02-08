const http = require('http');

let commandQueue = [];

const server = http.createServer((req, res) => {
    // Enable CORS for the Telegram Mini App
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    if (req.method === 'OPTIONS') {
        res.writeHead(204);
        res.end();
        return;
    }

    if (req.url === '/command' && req.method === 'POST') {
        let body = '';
        req.on('data', chunk => { body += chunk.toString(); });
        req.on('end', () => {
            try {
                const data = JSON.parse(body);
                console.log('Received command:', data);
                commandQueue.push(data);
                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ status: 'ok', msg: 'Command queued' }));
            } catch (e) {
                res.writeHead(400);
                res.end('Invalid JSON');
            }
        });
    } else if (req.url === '/poll' && req.method === 'GET') {
        // Return first command and remove it from queue
        const command = commandQueue.shift() || { type: 'none' };
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(command));
    } else {
        res.writeHead(404);
        res.end('Not Found');
    }
});

const PORT = 3000;
server.listen(PORT, () => {
    console.log(`Relay Server running on http://localhost:${PORT}`);
    console.log('Endpoint for Bot: http://localhost:3000/command (POST)');
    console.log('Endpoint for Game: http://localhost:3000/poll (GET)');
});
