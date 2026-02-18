-- BEAMNG RP MOD (REPAIR V22 - THE FINAL FIX)
local M = {}

-- Принудительно загружаем HTTP модуль (стандарт для 0.33.3)
extensions.load('core_http')

local POLL_INTERVAL = 4
local timer = 0
local config = { serverIP = "127.0.0.1", username = "Player", allowedVehicles = {} }
local lastSpawnedByBot = ""

-- Загрузка или создание конфига
local function loadConfig()
    local path = "integration_mod_config.json"
    local content = readFile(path)
    
    if content then
        local ok, data = pcall(jsonDecode, content)
        if ok and data then
            if data.serverIP then config.serverIP = data.serverIP end
            if data.username then config.username = data.username end
            print("[BOT RP] Конфиг загружен: " .. config.serverIP .. " | " .. config.username)
        end
    else
        -- Создаем дефолтный файл, если его нет
        local defaultConfig = {
            serverIP = "127.0.0.1",
            username = "Alex_Drifter"
        }
        writeFile(path, jsonEncode(defaultConfig))
        print("[BOT RP] Создан новый файл конфига: " .. path)
    end
end
loadConfig()

local RELAY_URL = "http://" .. config.serverIP .. ":3000/poll?user=" .. config.username

-- ХОРОШИЙ ХЕЛПЕР (V22): Используем core_http.get
local function httpCall(url, callback)
    if not extensions.core_http then
        print("[BOT RP] ОШИБКА: Модуль core_http не найден. Попробуйте обновить игру или переустановить мод.")
        return
    end

    -- В 0.33.3 это самый чистый способ
    extensions.core_http.get(url, function(res)
        if res and res.body then
            callback(res.body)
        end
    end)
end

local LIVERY_KEYWORDS = {
    taxi = {"taxi", "cab"},
    police = {"police", "sheriff"},
    ambulance = {"ambulance", "medic", "ems"},
    bus = {"bus"},
    delivery = {"delivery", "courier", "van"},
    cargo = {"cargo", "truck", "haul"},
    executive = {"executive", "gov", "official"},
    street = {"street", "gang", "black"}
}

local function pickConfigByLivery(model, liveryHint)
    if not liveryHint or liveryHint == "" then return nil end
    if not extensions.core_vehicles or not extensions.core_vehicles.getModel then return nil end

    local token = tostring(liveryHint):lower()
    local keywords = LIVERY_KEYWORDS[token] or {token}
    local ok, modelData = pcall(extensions.core_vehicles.getModel, model)
    if not ok or not modelData or not modelData.configs then return nil end

    for cfgKey, cfgData in pairs(modelData.configs) do
        local haystack = (
            tostring(cfgKey) .. " " ..
            tostring(cfgData and cfgData.name or "") .. " " ..
            tostring(cfgData and cfgData.description or "")
        ):lower()
        for _, kw in ipairs(keywords) do
            if string.find(haystack, kw, 1, true) then
                return cfgKey
            end
        end
    end
    return nil
end

local function spawnCar(modelName, plateText, plateRegion, spawnPos, liveryHint)
    local model = tostring(modelName or "pigeon"):lower()
    local plate = tostring(plateText or "")
    
    print("[BOT RP] === СИСТЕМА СПАВНА ===")
    print("[BOT RP] Модель: " .. model)
    print("[BOT RP] Номер: " .. plate)

    local pos = nil
    if spawnPos and spawnPos.x then
        pos = vec3(spawnPos.x, spawnPos.y, spawnPos.z)
    end

    if not pos then
        local playerVeh = be:getPlayerVehicle(0)
        if playerVeh then
            pos = playerVeh:getPosition() + playerVeh:getDirectionVector() * 6 + vec3(0,0,1)
        else
            pos = vec3(0,0,0)
        end
    end
    
    if extensions.core_vehicles then
        local configKey = pickConfigByLivery(model, liveryHint)
        local vid = extensions.core_vehicles.spawnVehicle(model, configKey, pos, quat(0,0,0,1))
        if not vid and configKey ~= nil then
            vid = extensions.core_vehicles.spawnVehicle(model, nil, pos, quat(0,0,0,1))
        end
        
        if vid then
            if plate ~= "" then
                extensions.core_vehicles.setLicensePlateText(string.upper(plate), vid)
                extensions.core_vehicles.setLicensePlateDesign('htnv_russian_regular', vid)
            end
            lastSpawnedByBot = model
            print("[BOT RP] УСПЕХ: " .. model .. " (ID: " .. tostring(vid) .. ")")
        else
            print("[BOT RP] ОШИБКА: Машина не заспавнилась.")
        end
    end
end

local function teleportPlayer(targetPos)
    if not targetPos or not targetPos.x then return end
    local pos = vec3(targetPos.x, targetPos.y, targetPos.z)
    
    local playerVeh = be:getPlayerVehicle(0)
    if playerVeh then
        playerVeh:setPosition(pos)
    else
        be:setFreeCameraPos(pos)
    end
    print("[BOT RP] Телепортация: " .. tostring(pos))
end

-- Команды для проверки в консоли (~)
-- Важно: Писать именно так, как ты называешь файл (например extensions.botRP.testSpawn)
M.testSpawn = function()
    spawnCar("pigeon")
end

M.testConnect = function()
    print("[BOT RP] Пинг сервера " .. RELAY_URL .. " ...")
    httpCall(RELAY_URL, function(body)
        print("[BOT RP] СВЯЗЬ УСТАНОВЛЕНА! Получен ответ.")
        print("Тело ответа: " .. tostring(body))
    end)
end

local function onUpdate(dt)
    timer = timer + dt
    if timer < POLL_INTERVAL then return end
    timer = 0

    httpCall(RELAY_URL, function(body)
        -- print("[BOT RP] Ответ сервера: " .. tostring(body)) -- Раскомментируйте для полной отладки
        local ok, data = pcall(jsonDecode, body)
        if ok and data then
            -- Синхронизируем список разрешенных машин
            if data.garage then
                config.allowedVehicles = data.garage
            end

            if data.type ~= "none" then
                print("[BOT RP] >>> ПОЛУЧЕНА КОМАНДА: " .. tostring(data.type))
                if data.type == "start_shift" or data.type == "spawn_car" then
                    spawnCar(data.carId, data.plate, data.plateRegion, data.pos, data.livery)
                elseif data.type == "teleport" then
                    teleportPlayer(data.pos)
                end
            end
        end
    end)
end

local function onVehicleSpawned(vid)
    local v = be:getObjectByID(vid)
    if not v then return end
    
    local model = v:getJBeamResource()
    print("[BOT RP] Заспавнена машина: " .. tostring(model))

    -- Проверяем, разрешена ли эта машина
    local isAllowed = false
    
    -- 1. Была ли заспавнена через бот только что?
    if model == lastSpawnedByBot then
        isAllowed = true
        lastSpawnedByBot = "" -- Сбрасываем флаг
    end

    -- 2. Есть ли она в купленных?
    if not isAllowed then
        for _, allowedModel in ipairs(config.allowedVehicles) do
            if model == allowedModel then
                isAllowed = true
                break
            end
        end
    end

    -- 3. Если не разрешена - удаляем
    if not isAllowed then
        print("[BOT RP] !!! МАШИНА НЕ КУПЛЕНА: " .. model .. " !!!")
        guihooks.trigger('Message', {msg = "Эта машина не куплена в ТГ боте! Она будет удалена.", category = "warning", icon = "warning"})
        
        -- Удаляем через 1 секунду, чтобы игрок успел увидеть сообщение
        be:queueAllObjectLua(string.format("if be:getObjectByID(%d) then be:getObjectByID(%d):delete() end", vid, vid))
    end
end

print("\n\n[BOT RP] --- МОД ЗАГРУЖЕН (V22 - FINAL) ---")
print("[BOT RP] Используйте команды: testSpawn() и testConnect()")

M.onUpdate = onUpdate
M.onVehicleSpawned = onVehicleSpawned
return M
