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

local function spawnCar(modelName, plateText, plateRegion, spawnPos)
    local model = tostring(modelName or "pigeon"):lower()
    local plate = tostring(plateText or "")
    local region = tostring(plateRegion or "")
    
    local fullPlate = plate
    if region ~= "" then fullPlate = plate .. " " .. region end

    print("[BOT RP] Попытка спавна: " .. model .. " | Номер: " .. fullPlate)
    
    local posStr = "nil"
    if spawnPos and spawnPos.x then
        posStr = string.format("vec3(%f, %f, %f)", spawnPos.x, spawnPos.y, spawnPos.z)
    end

    local luaCmd = string.format([[
        (function()
            local pos = %s
            local playerVeh = be:getPlayerVehicle(0)
            if not pos and playerVeh then
                pos = playerVeh:getPosition() + vec3(0, 5, 1)
            elseif not pos then
                pos = vec3(0,0,0)
            end
            
            if extensions.core_vehicles then
                local vid = extensions.core_vehicles.spawnVehicle('%s', nil, pos, quat(0,0,0,1))
                if vid and '%s' ~= '' then
                    local pText = string.upper('%s')
                    extensions.core_vehicles.setLicensePlateText(pText, vid)
                    extensions.core_vehicles.setLicensePlateDesign('htnv_russian_regular', vid)
                end
            end
        end)()
    ]], posStr, model, plate, plate)
    
    be:queueAllObjectLua(luaCmd)
    lastSpawnedByBot = model
end

local function teleportPlayer(targetPos)
    if not targetPos or not targetPos.x then return end
    local posStr = string.format("vec3(%f, %f, %f)", targetPos.x, targetPos.y, targetPos.z)
    
    local luaCmd = string.format([[
        (function()
            local playerVeh = be:getPlayerVehicle(0)
            if playerVeh then
                playerVeh:setPosition(%s)
            else
                be:setFreeCameraPos(%s)
            end
        end)()
    ]], posStr, posStr)
    
    be:queueAllObjectLua(luaCmd)
    print("[BOT RP] Телепортация: " .. posStr)
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
        local ok, data = pcall(jsonDecode, body)
        if ok and data then
            -- Синхронизируем список разрешенных машин
            if data.garage then
                config.allowedVehicles = data.garage
            end

            if data.type ~= "none" then
                print("[BOT RP] Найдена команда: " .. tostring(data.type))
                if data.type == "start_shift" or data.type == "spawn_car" then
                    print("[BOT RP] Запрос на спавн: " .. tostring(data.carId))
                    spawnCar(data.carId, data.plate, data.plateRegion, data.pos)
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
