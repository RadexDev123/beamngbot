const http = require('http');
const url = require('url');
const fs = require('fs');
const path = require('path');

const DB_PATH = path.join(__dirname, 'database.json');
let db = { users: {} };

// Загрузка БД при старте
if (fs.existsSync(DB_PATH)) {
    try {
        db = JSON.parse(fs.readFileSync(DB_PATH, 'utf8'));
        console.log('[DB] База данных загружена. Пользователей:', Object.keys(db.users).length);
    } catch (e) {
        console.error('[DB] Ошибка парсинга БД!', e);
    }
}

function saveToDisk() {
    try {
        fs.writeFileSync(DB_PATH, JSON.stringify(db, null, 2));
    } catch (e) {
        console.error('[DB] Ошибка записи на диск!', e);
    }
}

let userQueues = {}; // { username: [commands] }
let userReports = {}; // { username: reportData }
let userVehicles = {}; // { username: [modelNames] }

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
                const username = data.user || 'Unknown';
                console.log(`[BOT] -> Команда для ${username}:`, data.type);

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
                const username = data.user || 'Unknown';
                console.log(`[GAME] -> Отчет от ${username}:`, data.distance, 'км');

                userReports[username] = data;

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
                const username = data.user || 'Unknown';
                userVehicles[username] = data.vehicles || [];
                console.log(`[BOT] -> Гараж синхронизирован для ${username}:`, userVehicles[username]);
                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ status: 'ok' }));
            } catch (e) {
                res.writeHead(400); res.end('Invalid JSON');
            }
        });
    } else if (pathname === '/get_shift_report' && req.method === 'GET') {
        const username = query.user;
        res.writeHead(200, { 'Content-Type': 'application/json' });
        if (username && userReports[username]) {
            res.end(JSON.stringify(userReports[username]));
            delete userReports[username];
        } else {
            res.end(JSON.stringify({ type: 'none' }));
        }
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

                    // Автоматически обновляем список машин для синхронизации с игрой
                    if (data.garage && Array.isArray(data.garage)) {
                        // Нам нужны названия моделей для Lua мода
                        // В идеале бот должен присылать их, или мы можем хранить карту тут
                        // Но проще пусть бот шлет уже готовый список в отдельном поле или мы его вытащим
                        // Для надежности, пусть бот шлет поле 'garageModels'
                        if (data.garageModels) {
                            userVehicles[data.name || 'Unknown'] = data.garageModels;
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
        const username = query.user || 'Unknown';
        res.writeHead(200, { 'Content-Type': 'application/json' });

        if (userQueues[username] && userQueues[username].length > 0) {
            const command = userQueues[username].shift();
            console.log(`[GAME] <<< Подана команда игроку ${username}:`, command.type);
            res.end(JSON.stringify({ ...command, garage: userVehicles[username] || [] }));
        } else {
            res.end(JSON.stringify({ type: 'none', garage: userVehicles[username] || [] }));
        }
    } else {
        res.writeHead(404);
        res.end('Not Found');
    }
});

const PORT = 3000;
server.listen(PORT, '0.0.0.0', () => {
    console.log(`\n=== МУЛЬТИПЛЕЕРНЫЙ СЕРВЕР ЗАПУЩЕН НА ПОРТУ ${PORT} ===`);
    console.log(`Игроки должны указать ваш IP в настройках приложения и в моде.`);
});
