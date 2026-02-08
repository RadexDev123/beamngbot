-- BeamNG.drive Integration Mod (Beamng RP)
-- Place this file in your Userpath/scripts/modules/ (e.g. Documents/BeamNG.drive/scripts/modules/integration_mod.lua)
-- Or load it via main.lua

local M = {}

local POLL_INTERVAL = 2 -- seconds
local timer = 0
local RELAY_URL = "http://localhost:3000/poll"

local function onUpdate(dt)
    timer = timer + dt
    if timer < POLL_INTERVAL then return end
    timer = 0

    -- Simple HTTP Get using core_online (or socket if available)
    -- Note: BeamNG's Lua environment has specific ways to handle HTTP
    -- This is a template using common internal functions
    
    core_online.apiCall('GET', RELAY_URL, nil, function(response)
        if not response or not response.body then return end
        
        local data = jsonDecode(response.body)
        if data and data.type == "spawn_car" then
            print("Received spawn command for: " .. tostring(data.carId))
            
            -- Find car internal name (could be passed in data)
            local carName = data.carId or "pigeon"
            
            -- Spawn vehicle
            local options = {
                model = carName,
                config = data.config or nil,
                licenseText = "RP BOT"
            }
                
            core_vehicles.spawnVehicle(options.model, options.config, options.pos, options.rot)
            guihooks.trigger('Message', {msg = "Бот заспавнил машину: " .. carName, category = "info", icon = "directions_car"})
        end
    end)
end

M.onUpdate = onUpdate

return M
