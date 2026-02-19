-- BEAMNG RP MOD (REPAIR V22 - THE FINAL FIX)
local M = {}

-- РџСЂРёРЅСѓРґРёС‚РµР»СЊРЅРѕ Р·Р°РіСЂСѓР¶Р°РµРј HTTP РјРѕРґСѓР»СЊ (СЃС‚Р°РЅРґР°СЂС‚ РґР»СЏ 0.33.3)
extensions.load('core_http')

local POLL_INTERVAL = 4
local timer = 0
local config = { serverIP = "127.0.0.1", username = "Player", allowedVehicles = {} }
local lastSpawnedByBot = ""

local function normalizeModelName(value)
    local s = tostring(value or ""):lower()
    s = s:gsub("\\", "/")
    if string.find(s, "/", 1, true) then
        s = s:match("([^/]+)$") or s
    end
    s = s:gsub("%.jbeam$", "")
    return s
end

-- Р—Р°РіСЂСѓР·РєР° РёР»Рё СЃРѕР·РґР°РЅРёРµ РєРѕРЅС„РёРіР°
local function loadConfig()
    local path = "integration_mod_config.json"
    local content = readFile(path)

    if content then
        local ok, data = pcall(jsonDecode, content)
        if ok and data then
            if data.serverIP then config.serverIP = data.serverIP end
            if data.username then config.username = data.username end
            print("[BOT RP] Config loaded from integration_mod_config.json: " .. config.serverIP .. " | " .. config.username)
            return
        end
    end

    -- Fallback: use beamng_config.json from bridge app
    local beamngPath = "beamng_config.json"
    local beamngContent = readFile(beamngPath)
    if beamngContent then
        local ok, data = pcall(jsonDecode, beamngContent)
        if ok and data then
            if data.relay_server then config.serverIP = tostring(data.relay_server) end
            if data.username then config.username = tostring(data.username) end
            print("[BOT RP] Config loaded from beamng_config.json: " .. config.serverIP .. " | " .. config.username)
            return
        end
    end

    -- Create default integration config if nothing exists
    local defaultConfig = {
        serverIP = "127.0.0.1",
        username = "Alex_Drifter"
    }
    config.serverIP = defaultConfig.serverIP
    config.username = defaultConfig.username
    writeFile(path, jsonEncode(defaultConfig))
    print("[BOT RP] Created default config: " .. path)
end
loadConfig()

local function buildRelayUrl()
    local encodedUsername = tostring(config.username or "Player"):gsub(" ", "%%20")
    return "http://" .. tostring(config.serverIP or "127.0.0.1") .. ":3000/poll?user=" .. encodedUsername
end
print("[BOT RP] Poll target: " .. buildRelayUrl())

-- РҐРћР РћРЁРР™ РҐР•Р›РџР•Р  (V22): РСЃРїРѕР»СЊР·СѓРµРј core_http.get
local function httpCall(url, callback)
    if not extensions.core_http then
        print("[BOT RP] РћРЁРР‘РљРђ: РњРѕРґСѓР»СЊ core_http РЅРµ РЅР°Р№РґРµРЅ. РџРѕРїСЂРѕР±СѓР№С‚Рµ РѕР±РЅРѕРІРёС‚СЊ РёРіСЂСѓ РёР»Рё РїРµСЂРµСѓСЃС‚Р°РЅРѕРІРёС‚СЊ РјРѕРґ.")
        return
    end

    -- Р’ 0.33.3 СЌС‚Рѕ СЃР°РјС‹Р№ С‡РёСЃС‚С‹Р№ СЃРїРѕСЃРѕР±
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
    local model = normalizeModelName(modelName or "pigeon")
    local plate = tostring(plateText or "")
    
    print("[BOT RP] === РЎРРЎРўР•РњРђ РЎРџРђР’РќРђ ===")
    print("[BOT RP] РњРѕРґРµР»СЊ: " .. model)
    print("[BOT RP] РќРѕРјРµСЂ: " .. plate)

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

        if not vid and model ~= "pigeon" then
            print("[BOT RP] Spawn failed for model " .. model .. ", fallback to pigeon")
            model = "pigeon"
            vid = extensions.core_vehicles.spawnVehicle(model, nil, pos, quat(0,0,0,1))
        end

        if vid then
            if plate ~= "" then
                extensions.core_vehicles.setLicensePlateText(string.upper(plate), vid)
                extensions.core_vehicles.setLicensePlateDesign('htnv_russian_regular', vid)
            end
            lastSpawnedByBot = model
            print("[BOT RP] Spawn success: " .. model .. " (ID: " .. tostring(vid) .. ")")
        else
            print("[BOT RP] ERROR: vehicle spawn failed for model " .. tostring(modelName))
        end
    else
        print("[BOT RP] ERROR: core_vehicles extension is missing")
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
    print("[BOT RP] РўРµР»РµРїРѕСЂС‚Р°С†РёСЏ: " .. tostring(pos))
end

-- РљРѕРјР°РЅРґС‹ РґР»СЏ РїСЂРѕРІРµСЂРєРё РІ РєРѕРЅСЃРѕР»Рё (~)
-- Р’Р°Р¶РЅРѕ: РџРёСЃР°С‚СЊ РёРјРµРЅРЅРѕ С‚Р°Рє, РєР°Рє С‚С‹ РЅР°Р·С‹РІР°РµС€СЊ С„Р°Р№Р» (РЅР°РїСЂРёРјРµСЂ extensions.botRP.testSpawn)
M.testSpawn = function()
    spawnCar("pigeon")
end

M.testConnect = function()
    local relayUrl = buildRelayUrl()
    print("[BOT RP] РџРёРЅРі СЃРµСЂРІРµСЂР° " .. relayUrl .. " ...")
    httpCall(relayUrl, function(body)
        print("[BOT RP] РЎР’РЇР—Р¬ РЈРЎРўРђРќРћР’Р›Р•РќРђ! РџРѕР»СѓС‡РµРЅ РѕС‚РІРµС‚.")
        print("РўРµР»Рѕ РѕС‚РІРµС‚Р°: " .. tostring(body))
    end)
end

local function onUpdate(dt)
    timer = timer + dt
    if timer < POLL_INTERVAL then return end
    timer = 0

    local relayUrl = buildRelayUrl()
    httpCall(relayUrl, function(body)
        -- print("[BOT RP] РћС‚РІРµС‚ СЃРµСЂРІРµСЂР°: " .. tostring(body)) -- Р Р°СЃРєРѕРјРјРµРЅС‚РёСЂСѓР№С‚Рµ РґР»СЏ РїРѕР»РЅРѕР№ РѕС‚Р»Р°РґРєРё
        local ok, data = pcall(jsonDecode, body)
        if ok and data then
            -- РЎРёРЅС…СЂРѕРЅРёР·РёСЂСѓРµРј СЃРїРёСЃРѕРє СЂР°Р·СЂРµС€РµРЅРЅС‹С… РјР°С€РёРЅ
            if data.garage then
                config.allowedVehicles = data.garage
            end

            if data.type ~= "none" then
                print("[BOT RP] >>> РџРћР›РЈР§Р•РќРђ РљРћРњРђРќР”Рђ: " .. tostring(data.type))
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

    local modelRaw = v:getJBeamResource()
    local model = normalizeModelName(modelRaw)
    print("[BOT RP] Vehicle spawned: " .. tostring(modelRaw) .. " -> " .. model)

    local isAllowed = false

    -- 1) freshly spawned by bot command
    if model == normalizeModelName(lastSpawnedByBot) then
        isAllowed = true
        lastSpawnedByBot = ""
    end

    -- 2) owned vehicle list from bot
    if not isAllowed then
        for _, allowedModel in ipairs(config.allowedVehicles) do
            if model == normalizeModelName(allowedModel) then
                isAllowed = true
                break
            end
        end
    end

    if not isAllowed then
        print("[BOT RP] BLOCKED (not purchased): " .. tostring(modelRaw))
        guihooks.trigger('Message', {msg = "This vehicle is not purchased in mini-app and will be removed.", category = "warning", icon = "warning"})
        be:queueAllObjectLua(string.format("if be:getObjectByID(%d) then be:getObjectByID(%d):delete() end", vid, vid))
    end
end

print("\n\n[BOT RP] --- РњРћР” Р—РђР“Р РЈР–Р•Рќ (V22 - FINAL) ---")
print("[BOT RP] РСЃРїРѕР»СЊР·СѓР№С‚Рµ РєРѕРјР°РЅРґС‹: testSpawn() Рё testConnect()")

M.onUpdate = onUpdate
M.onVehicleSpawned = onVehicleSpawned
return M
