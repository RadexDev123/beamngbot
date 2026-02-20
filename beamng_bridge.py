import json
import os
import time
import math
import random
import re
import requests
from beamngpy import BeamNGpy, Vehicle

TAXI_MAP_PROFILES = {
    'west_coast_usa': {
        'pickup_min': 90.0,
        'pickup_max': 220.0,
        'drop_min': 450.0,
        'drop_max': 1400.0,
    },
    'east_coast_usa': {
        'pickup_min': 80.0,
        'pickup_max': 200.0,
        'drop_min': 400.0,
        'drop_max': 1200.0,
    },
    'default': {
        'pickup_min': 120.0,
        'pickup_max': 260.0,
        'drop_min': 350.0,
        'drop_max': 950.0,
    },
}

PLAYER_STATE_CACHE = {
    'pos': None,
    'dir': (1.0, 0.0, 0.0),
}
PLAYER_STATE_FILE = None
WORK_VEHICLE_MISSING_LIMIT = 4
PLAYER_ABSENT_LIMIT = 8


def load_config(path='beamng_config.json'):
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def calc_distance(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def to_lua_str(value):
    s = str(value or '')
    return s.replace('\\', '\\\\').replace("'", "\\'")


LIVERY_KEYWORDS = {
    'taxi': ['taxi', 'cab'],
    'police': ['police', 'cop', 'patrol', 'sheriff'],
    'ambulance': ['ambulance', 'ems', 'rescue', 'medic'],
    'bus': ['bus', 'transit', 'coach'],
    'delivery': ['delivery', 'courier', 'cargo', 'van'],
    'executive': ['lux', 'executive', 'vip', 'limo'],
    'cargo': ['cargo', 'truck', 'hauler'],
    'street': ['street', 'gang', 'black'],
}


def _safe_int(value):
    try:
        return int(value)
    except Exception:
        return None


def _get_current_vehicle_ids(bng):
    ids = set()
    try:
        vehicles = bng.vehicles.get_current() or {}
        for key in vehicles.keys():
            iv = _safe_int(key)
            if iv is not None:
                ids.add(iv)
    except Exception:
        pass
    return ids


def _get_player_vehicle_id_safe(bng):
    try:
        vid = bng.get_player_vehicle_id(0)
        iv = _safe_int(vid)
        if iv is not None:
            return iv
    except Exception:
        pass

    lua = """
    (function()
      local v = be:getPlayerVehicle(0)
      if not v then return '' end
      if v.getID then return tostring(v:getID()) end
      return ''
    end)()
    """
    try:
        raw = bng.queue_lua_command(lua)
        iv = _safe_int(str(raw or '').strip())
        return iv
    except Exception:
        return None


def _list_model_configs_via_lua(bng, car_id):
    model = to_lua_str(car_id or '')
    lua = f"""
    (function()
      local handler = (extensions and extensions.core_vehicles) or core_vehicles
      if not handler or not handler.getModel then return '' end
      local ok, modelData = pcall(handler.getModel, '{model}')
      if not ok or not modelData or not modelData.configs then return '' end
      local lines = {{}}
      for cfgKey, cfgData in pairs(modelData.configs) do
        local name = tostring(cfgData and cfgData.name or '')
        local desc = tostring(cfgData and cfgData.description or '')
        lines[#lines + 1] = tostring(cfgKey) .. '\\t' .. name .. '\\t' .. desc
      end
      table.sort(lines)
      return table.concat(lines, '\\n')
    end)()
    """
    try:
        raw = str(bng.queue_lua_command(lua) or '').strip()
        if not raw:
            return []
        return [line.strip() for line in raw.splitlines() if line.strip()]
    except Exception:
        return []


def _log_livery_candidates(bng, car_id, livery):
    lines = _list_model_configs_via_lua(bng, car_id)
    if not lines:
        print(f"[BRIDGE] Livery debug: no configs found for model {car_id}")
        return

    token = str(livery or '').strip().lower()
    keywords = [k.lower() for k in LIVERY_KEYWORDS.get(token, [token] if token else []) if k]
    if keywords:
        matched = [line for line in lines if any(kw in line.lower() for kw in keywords)]
    else:
        matched = []

    print(f"[BRIDGE] Livery debug for model={car_id} hint={token or '-'}")
    if matched:
        for row in matched[:30]:
            print(f"[BRIDGE]   match: {row}")
        return

    print("[BRIDGE]   no matches by keywords; first configs:")
    for row in lines[:20]:
        print(f"[BRIDGE]   cfg: {row}")


def resolve_config_key_via_lua(bng, car_id, livery='', config_key=''):
    car_id = to_lua_str(car_id or '')
    config_key = to_lua_str(config_key or '')
    livery = to_lua_str(livery or '').lower()
    keywords = LIVERY_KEYWORDS.get(livery, [livery] if livery else [])
    keywords_lua = '{' + ','.join([f"'{to_lua_str(kw)}'" for kw in keywords]) + '}'

    lua = f"""
    (function()
      local model = '{car_id}'
      local requested = '{config_key}'
      if requested ~= '' then return requested end
      local kws = {keywords_lua}
      if #kws == 0 then return '' end
      local handler = (extensions and extensions.core_vehicles) or core_vehicles
      if not handler or not handler.getModel then return '' end
      local ok, modelData = pcall(handler.getModel, model)
      if not ok or not modelData or not modelData.configs then return '' end
      for cfgKey, cfgData in pairs(modelData.configs) do
        local haystack = (
          tostring(cfgKey) .. ' ' ..
          tostring(cfgData and cfgData.name or '') .. ' ' ..
          tostring(cfgData and cfgData.description or '')
        ):lower()
        for _, kw in ipairs(kws) do
          if string.find(haystack, kw, 1, true) then
            return tostring(cfgKey)
          end
        end
      end
      return ''
    end)()
    """
    try:
        return str(bng.queue_lua_command(lua) or '').strip()
    except Exception:
        return ''


def normalize_part_config(model, config_key):
    cfg = str(config_key or '').strip()
    if not cfg:
        return []
    candidates = [cfg]
    if '.pc' not in cfg.lower():
        candidates.append(f"{cfg}.pc")
    if '/' not in cfg and '\\' not in cfg:
        if '.pc' in cfg.lower():
            candidates.append(f"vehicles/{model}/{cfg}")
        else:
            candidates.append(f"vehicles/{model}/{cfg}.pc")
    seen = set()
    ordered = []
    for c in candidates:
        if c not in seen:
            ordered.append(c)
            seen.add(c)
    return ordered


def _observe_vehicle_ids(bng, before_ids, duration_sec=1.5):
    seen_new_ids = set()
    final_ids = set()
    final_count = 0
    steps = max(1, int(duration_sec / 0.1))
    for _ in range(steps):
        time.sleep(0.1)
        try:
            vehicles = bng.vehicles.get_current() or {}
            current_ids = set(vehicles.keys())
            seen_new_ids.update(current_ids - before_ids)
            final_ids = current_ids
            final_count = len(vehicles)
        except Exception:
            pass
    return final_count, sorted(list(final_ids - before_ids)), sorted(list(seen_new_ids))


def _get_player_state_from_lua(bng):
    lua = """
    (function()
      local v = be:getPlayerVehicle(0)
      if not v then return '' end
      local p = v:getPosition()
      local d = v:getDirectionVector()
      return {p.x, p.y, p.z, d.x, d.y, d.z}
    end)()
    """
    try:
        raw = bng.queue_lua_command(lua)
        # beamngpy may return either an array-like payload or a string
        if isinstance(raw, (list, tuple)) and len(raw) >= 6:
            px, py, pz, dx, dy, dz = [float(x) for x in raw[:6]]
        else:
            text = str(raw or '')
            if text.startswith('{') and text.endswith('}'):
                text = text.strip('{}').replace(' ', '')
            parts = text.split('|')
            if len(parts) != 6:
                raise ValueError(f"Unexpected player state payload: {text}")
            px, py, pz, dx, dy, dz = [float(x) for x in parts]
        # Normalize direction for stability.
        dlen = max(1e-4, math.sqrt(dx * dx + dy * dy + dz * dz))
        dx, dy, dz = dx / dlen, dy / dlen, dz / dlen
        return (px, py, pz), (dx, dy, dz)
    except Exception:
        pass
    return None, None


def _get_player_state_from_api(bng):
    try:
        vehicles = bng.vehicles.get_current() or {}
        if not vehicles:
            return None, None

        # 1) Try player vehicle id when API supports it.
        candidate_list = []
        try:
            player_vid = bng.get_player_vehicle_id(0)
            if player_vid in vehicles:
                candidate_list.append(vehicles[player_vid])
            elif str(player_vid) in vehicles:
                candidate_list.append(vehicles[str(player_vid)])
            else:
                for k, v in vehicles.items():
                    if str(k) == str(player_vid):
                        candidate_list.append(v)
                        break
        except Exception:
            pass

        # 2) Fallback: any active vehicle (common for tcom sessions with one controlled car).
        for _, v in vehicles.items():
            if v not in candidate_list:
                candidate_list.append(v)

        for vehicle in candidate_list:
            # Avoid per-tick vehicle socket reconnects here:
            # repeated connect() calls can exhaust BeamNG tech sockets.
            try:
                vehicle.update_vehicle()
            except Exception:
                pass

            state = getattr(vehicle, 'state', {}) or {}
            pos = state.get('pos')
            vel = state.get('vel')
            direction = state.get('dir')
            if pos is None:
                continue

            px, py, pz = float(pos[0]), float(pos[1]), float(pos[2])
            if direction is not None:
                dx, dy, dz = float(direction[0]), float(direction[1]), float(direction[2])
            elif vel is not None:
                dx, dy, dz = float(vel[0]), float(vel[1]), float(vel[2])
            else:
                dx, dy, dz = 1.0, 0.0, 0.0

            dlen = max(1e-4, math.sqrt(dx * dx + dy * dy + dz * dz))
            dx, dy, dz = dx / dlen, dy / dlen, dz / dlen
            return (px, py, pz), (dx, dy, dz)

        return None, None
    except Exception:
        return None, None


def _get_player_state_via_file_bridge(bng):
    if not PLAYER_STATE_FILE:
        return None, None
    lua = """
    (function()
      local out = ''
      local v = be:getPlayerVehicle(0)
      if v then
        local p = v:getPosition()
        local d = v:getDirectionVector()
        out = string.format('%.6f|%.6f|%.6f|%.6f|%.6f|%.6f', p.x, p.y, p.z, d.x, d.y, d.z)
      end
      pcall(function() writeFile('bridge_player_state.txt', out) end)
    end)()
    """
    try:
        bng.queue_lua_command(lua)
        # Give BeamNG a tiny window to flush writeFile.
        time.sleep(0.03)
        with open(PLAYER_STATE_FILE, 'r', encoding='utf-8') as f:
            text = (f.read() or '').strip()
        if not text:
            return None, None
        parts = text.split('|')
        if len(parts) != 6:
            return None, None
        px, py, pz, dx, dy, dz = [float(x) for x in parts]
        dlen = max(1e-4, math.sqrt(dx * dx + dy * dy + dz * dz))
        dx, dy, dz = dx / dlen, dy / dlen, dz / dlen
        return (px, py, pz), (dx, dy, dz)
    except Exception:
        return None, None


def _get_player_state(bng):
    pos, direction = _get_player_state_from_lua(bng)
    if _valid_world_pos(pos) and direction:
        PLAYER_STATE_CACHE['pos'] = pos
        PLAYER_STATE_CACHE['dir'] = direction
        return pos, direction

    pos, direction = _get_player_state_via_file_bridge(bng)
    if _valid_world_pos(pos) and direction:
        PLAYER_STATE_CACHE['pos'] = pos
        PLAYER_STATE_CACHE['dir'] = direction
        return pos, direction

    pos, direction = _get_player_state_from_api(bng)
    if _valid_world_pos(pos) and direction:
        PLAYER_STATE_CACHE['pos'] = pos
        PLAYER_STATE_CACHE['dir'] = direction
        return pos, direction

    cached_pos = PLAYER_STATE_CACHE.get('pos')
    cached_dir = PLAYER_STATE_CACHE.get('dir') or (1.0, 0.0, 0.0)
    if _valid_world_pos(cached_pos):
        return cached_pos, cached_dir

    return None, None


def _valid_world_pos(pos):
    if not pos:
        return False
    x, y, z = pos
    if abs(x) < 0.001 and abs(y) < 0.001 and abs(z) < 0.001:
        return False
    return True


def _get_spawn_pos_near_player(bng):
    pos, direction = _get_player_state(bng)
    if (not _valid_world_pos(pos)) or (not direction):
        return None
    px, py, pz = pos
    dx, dy, dz = direction
    # Side offset from the player's current heading: spawn close and visible.
    sx, sy = -dy, dx
    return (
        px + sx * 3.0 + dx * 1.2,
        py + sy * 3.0 + dy * 1.2,
        pz + 0.6
    )


def _get_player_pos_from_lua(bng):
    pos, _ = _get_player_state(bng)
    if _valid_world_pos(pos):
        return pos
    return None


def _get_player_damage_from_lua(bng):
    try:
        dmg = bng.queue_lua_command("local v=be:getPlayerVehicle(0); if v and v.getDamage then return v:getDamage() end; return 0")
        return float(dmg or 0.0)
    except Exception:
        return 0.0


def _show_game_message(bng, text, category='info'):
    safe = to_lua_str(text)
    cat = to_lua_str(category)
    bng.queue_lua_command(f"guihooks.trigger('Message', {{msg='{safe}', category='{cat}', icon='directions_car'}})")


def _extract_spawned_ids(result_text):
    text = str(result_text or '')
    found = set()
    for match in re.findall(r"(?:new_ids_final|seen_new_ids)=\[([^\]]*)\]", text):
        for token in match.split(','):
            token = token.strip().strip("'").strip('"')
            if not token:
                continue
            try:
                found.add(int(token))
            except Exception:
                pass
    return sorted(found)


def _delete_vehicle_ids_via_lua(bng, vehicle_ids):
    ids = []
    for value in vehicle_ids:
        try:
            ids.append(int(value))
        except Exception:
            pass
    if not ids:
        return
    ids_lua = ",".join(str(v) for v in sorted(set(ids)))
    lua = f"""
    (function()
      local ids = {{{ids_lua}}}
      for _, id in ipairs(ids) do
        local obj = be:getObjectByID(id)
        if obj then obj:delete() end
      end
    end)()
    """
    try:
        bng.queue_lua_command(lua)
    except Exception:
        pass


def _draw_world_marker(bng, pos, r, g, b, label):
    x, y, z = pos
    lua = f"""
    (function()
      local ok, err = pcall(function()
        if not debugDrawer then return end
        local p = vec3({x:.3f}, {y:.3f}, {z:.3f} + 0.2)
        local c = ColorF({r:.3f}, {g:.3f}, {b:.3f}, 0.9)
        debugDrawer:drawCylinder(p, p + vec3(0, 0, 16), 2.2, c)
        debugDrawer:drawSphere(p + vec3(0, 0, 1.8), 3.0, c)
      end)
      return ok and 'ok' or ('err:' .. tostring(err))
    end)()
    """
    try:
        res = bng.queue_lua_command(lua)
        return str(res or '')
    except Exception:
        return 'err:python_queue_failed'


def _set_nav_target_fallback(bng, pos):
    x, y, z = pos
    lua = f"""
    (function()
      local ok = false
      pcall(function()
        if freeroam_bigMapMode and freeroam_bigMapMode.navigateToPos then
          freeroam_bigMapMode.navigateToPos(vec3({x:.3f}, {y:.3f}, {z:.3f}))
          ok = true
        end
      end)
      pcall(function()
        if not ok and extensions and extensions.freeroam_bigMapMode and extensions.freeroam_bigMapMode.navigateToPos then
          extensions.freeroam_bigMapMode.navigateToPos(vec3({x:.3f}, {y:.3f}, {z:.3f}))
          ok = true
        end
      end)
      return ok and 'ok' or 'err:no_nav_api'
    end)()
    """
    try:
        res = bng.queue_lua_command(lua)
        return str(res or '')
    except Exception:
        return 'err:nav_queue_failed'


def _draw_taxi_mission_markers(bng, mission):
    if not mission or not mission.get('active'):
        return
    phase = mission.get('phase')
    pickup = mission.get('pickup')
    dropoff = mission.get('dropoff')

    # Cyan = pickup, Yellow = dropoff
    if phase == 'to_pickup' and pickup:
        marker = _draw_world_marker(bng, pickup, 0.1, 0.9, 1.0, 'PICKUP')
        if isinstance(marker, str) and marker.startswith('err:'):
            _set_nav_target_fallback(bng, pickup)
        return marker
    elif phase == 'to_dropoff' and dropoff:
        marker = _draw_world_marker(bng, dropoff, 1.0, 0.85, 0.1, 'DROPOFF')
        if isinstance(marker, str) and marker.startswith('err:'):
            _set_nav_target_fallback(bng, dropoff)
        return marker
    return 'none'

def _get_map_id_from_lua(bng):
    lua = """
    (function()
      local id = ''
      pcall(function()
        if getMissionFilename then
          local mf = tostring(getMissionFilename() or '')
          local level = string.match(mf, '[/\\\\]levels[/\\\\]([^/\\\\]+)[/\\\\]')
          if level and level ~= '' then id = level end
        end
      end)
      if id == '' then
        pcall(function()
          if core_levels and core_levels.getLevelName then
            id = tostring(core_levels.getLevelName() or '')
          end
        end)
      end
      if id == '' then id = 'unknown' end
      return string.lower(tostring(id))
    end)()
    """
    try:
        value = bng.queue_lua_command(lua)
        text = str(value or 'unknown').lower().strip()
        # common display names fallback
        if 'west coast' in text:
            return 'west_coast_usa'
        if 'east coast' in text:
            return 'east_coast_usa'
        return text
    except Exception:
        return 'unknown'


def spawn_vehicle_via_lua(bng, car_id, plate, plate_design, livery, config_key=''):
    car_id = to_lua_str(car_id or 'pigeon')
    plate = to_lua_str(plate or '')
    plate_design = to_lua_str(plate_design or 'htnv_russian_regular')
    livery = to_lua_str(livery or '')
    config_key = to_lua_str(config_key or '')

    lua = f"""
    (function()
      local model = '{car_id}'
      local pos = vec3(0, 0, 0)
      local playerVeh = be:getPlayerVehicle(0)
      if playerVeh then
        local p = playerVeh:getPosition()
        local d = playerVeh:getDirectionVector()
        local side = vec3(-d.y, d.x, 0)
        pos = p + side * 3 + d * 1.2 + vec3(0, 0, 0.6)
      end

      local handler = (extensions and extensions.core_vehicles) or core_vehicles
      if not handler then
        return 'ERR:no_core_vehicles'
      end

      local requestedConfig = '{config_key}'
      local liveryHint = string.lower('{livery}')
      local configFromHint = nil
      local liveryKeywords = {{
        taxi = {{'taxi', 'cab'}},
        police = {{'police', 'cop', 'patrol', 'sheriff'}},
        ambulance = {{'ambulance', 'ems', 'rescue', 'medic'}},
        bus = {{'bus', 'transit', 'coach'}},
        delivery = {{'delivery', 'courier', 'cargo', 'van'}},
        executive = {{'lux', 'executive', 'vip', 'limo'}},
        cargo = {{'cargo', 'truck', 'hauler'}},
        street = {{'street', 'gang', 'black'}}
      }}

      local function pickConfigByLivery(modelName, hint)
        if not hint or hint == '' then return nil end
        if not handler.getModel then return nil end
        local keywords = liveryKeywords[hint] or {{hint}}
        local ok, modelData = pcall(handler.getModel, modelName)
        if not ok or not modelData or not modelData.configs then return nil end
        for cfgKey, cfgData in pairs(modelData.configs) do
          local haystack = (
            tostring(cfgKey) .. ' ' ..
            tostring(cfgData and cfgData.name or '') .. ' ' ..
            tostring(cfgData and cfgData.description or '')
          ):lower()
          for _, kw in ipairs(keywords) do
            if string.find(haystack, kw, 1, true) then
              return cfgKey
            end
          end
        end
        return nil
      end

      if requestedConfig ~= '' then
        configFromHint = requestedConfig
      else
        configFromHint = pickConfigByLivery(model, liveryHint)
      end

      local vid = handler.spawnVehicle(model, configFromHint, pos, quat(0,0,0,1))
      if not vid and configFromHint ~= nil then
        vid = handler.spawnVehicle(model, nil, pos, quat(0,0,0,1))
      end

      if not vid and model ~= 'pigeon' then
        vid = handler.spawnVehicle('pigeon', nil, pos, quat(0,0,0,1))
        if vid then model = 'pigeon' end
      end

      -- If world/game mode does not allow adding a second vehicle,
      -- try replacing current player vehicle instead.
      if not vid then
        local replaced = false
        pcall(function()
          if handler.replaceVehicle then
            handler.replaceVehicle(model, configFromHint)
            replaced = true
          end
        end)
        if replaced then
          guihooks.trigger('Message', {{msg='Vehicle replaced: ' .. model, category='success'}})
          return 'OK:replaced:' .. tostring(model)
        end
      end

      if vid then
        if '{plate}' ~= '' then
          pcall(function() handler.setLicensePlateText(string.upper('{plate}'), vid) end)
          pcall(function() handler.setLicensePlateDesign('{plate_design}', vid) end)
        end
        guihooks.trigger('Message', {{msg='Vehicle spawned: ' .. model, category='success'}})
        return 'OK:' .. tostring(model) .. ':' .. tostring(vid)
      else
        guihooks.trigger('Message', {{msg='Spawn failed for model: ' .. model, category='error'}})
        return 'ERR:spawn_failed:' .. tostring(model)
      end
    end)()
    """

    try:
        before = bng.vehicles.get_current() or {}
        before_ids = set(before.keys())
    except Exception:
        before_ids = set()

    try:
        lua_result = str(bng.queue_lua_command(lua) or '')
    except Exception as e:
        lua_result = f'ERR:lua_queue_failed:{e}'

    final_count, new_ids_final, seen_new_ids = _observe_vehicle_ids(bng, before_ids, duration_sec=1.5)
    return f"{lua_result}; vehicles_now={final_count}; new_ids_final={new_ids_final}; seen_new_ids={seen_new_ids}"


def spawn_vehicle_via_py(bng, car_id, plate='', part_config=''):
    try:
        before = bng.vehicles.get_current() or {}
        before_ids = set(before.keys())
    except Exception:
        before_ids = set()

    pos = _get_spawn_pos_near_player(bng)
    if not _valid_world_pos(pos):
        return "py_failed:no_player_state"
    vid_name = f"bot_{int(time.time() * 1000) % 1000000}"
    model = str(car_id or 'pigeon')
    plate = str(plate or '')
    errors = []
    spawned = False
    config_candidates = normalize_part_config(model, part_config)
    if not config_candidates:
        config_candidates = [None]

    for cfg in config_candidates:
        vehicle = Vehicle(
            vid=vid_name,
            model=model,
            license=(plate or None),
            part_config=cfg
        )
        try:
            bng.vehicles.spawn(vehicle, pos=pos, rot_quat=(0, 0, 0, 1), cling=True)
            spawned = True
            break
        except TypeError:
            try:
                bng.vehicles.spawn(vehicle, pos, (0, 0, 0, 1))
                spawned = True
                break
            except Exception as e:
                errors.append(f"legacy_spawn[{cfg}]:{e}")
        except Exception as e:
            errors.append(f"spawn[{cfg}]:{e}")

    if not spawned:
        return f"py_failed:{';'.join(errors) if errors else 'unknown'}"

    final_count, new_ids_final, seen_new_ids = _observe_vehicle_ids(bng, before_ids, duration_sec=1.5)
    return f"py_ok; vehicles_now={final_count}; new_ids_final={new_ids_final}; seen_new_ids={seen_new_ids}"


def create_taxi_mission(bng, map_id='unknown'):
    pos, direction = _get_player_state(bng)
    if (not _valid_world_pos(pos)) or (not direction):
        print('[TAXI] Waiting for valid player position...')
        return None
    px, py, pz = pos
    dx, dy, dz = direction
    map_key = str(map_id or 'unknown').lower()
    profile = TAXI_MAP_PROFILES['default']
    if 'west_coast_usa' in map_key or 'west coast' in map_key:
        profile = TAXI_MAP_PROFILES['west_coast_usa']
    elif 'east_coast_usa' in map_key or 'east coast' in map_key:
        profile = TAXI_MAP_PROFILES['east_coast_usa']

    # Side vector in XY plane
    sx, sy = -dy, dx
    pickup_dist = random.uniform(profile['pickup_min'], profile['pickup_max'])
    pickup_side = random.uniform(-30.0, 30.0)
    pickup = (
        px + dx * pickup_dist + sx * pickup_side,
        py + dy * pickup_dist + sy * pickup_side,
        pz
    )

    drop_dist = random.uniform(profile['drop_min'], profile['drop_max'])
    drop_side = random.uniform(-120.0, 120.0)
    dropoff = (
        pickup[0] + dx * drop_dist + sx * drop_side,
        pickup[1] + dy * drop_dist + sy * drop_side,
        pickup[2]
    )

    route_km = drop_dist / 1000.0
    base_fare = int(1200 + route_km * 1800)
    mission = {
        'active': True,
        'phase': 'to_pickup',
        'map_id': map_id,
        'pickup': pickup,
        'dropoff': dropoff,
        'route_km': route_km,
        'base_fare': base_fare,
        'pickup_time': None,
        'damage_at_pickup': 0.0,
        'last_hint_time': 0.0,
    }

    _show_game_message(
        bng,
        f"Taxi order: pickup {int(pickup_dist)}m away. Base fare ₽{base_fare}.",
        'success'
    )
    print(f"[TAXI] New order ({map_id}): pickup={pickup}, dropoff={dropoff}, fare={base_fare}")
    return mission


def update_taxi_mission(bng, mission):
    if not mission or not mission.get('active'):
        return None

    cur = _get_player_pos_from_lua(bng)
    if not _valid_world_pos(cur):
        return None
    px, py, pz = cur
    now = time.time()

    if mission['phase'] == 'to_pickup':
        tx, ty, tz = mission['pickup']
        dist = calc_distance((px, py, pz), (tx, ty, tz))
        if dist <= 14.0:
            mission['phase'] = 'to_dropoff'
            mission['pickup_time'] = now
            mission['damage_at_pickup'] = _get_player_damage_from_lua(bng)
            _show_game_message(bng, 'Passenger onboard. Drive to destination.', 'info')
            print('[TAXI] Passenger picked up')
        elif now - mission['last_hint_time'] > 10:
            mission['last_hint_time'] = now
            _show_game_message(bng, f"Taxi: {int(dist)}m to pickup.", 'info')
        return None

    if mission['phase'] == 'to_dropoff':
        tx, ty, tz = mission['dropoff']
        dist = calc_distance((px, py, pz), (tx, ty, tz))
        if dist <= 16.0:
            trip_time = max(1.0, now - float(mission['pickup_time'] or now))
            damage_delta = max(0.0, _get_player_damage_from_lua(bng) - float(mission['damage_at_pickup']))
            expected_time = max(60.0, mission['route_km'] * 120.0)
            time_bonus = 350 if trip_time <= expected_time else 0
            damage_penalty = int(damage_delta * 5.0)
            earned = max(300, int(mission['base_fare'] + time_bonus - damage_penalty))
            _show_game_message(
                bng,
                f"Taxi complete: +₽{earned} (bonus {time_bonus}, damage -{damage_penalty})",
                'success'
            )
            print(f"[TAXI] Completed: earned={earned}, damage_delta={damage_delta:.1f}, trip_time={trip_time:.1f}s")
            mission['active'] = False
            return {'earned': earned, 'trip_time': trip_time, 'damage_penalty': damage_penalty}
        elif now - mission['last_hint_time'] > 10:
            mission['last_hint_time'] = now
            _show_game_message(bng, f"Taxi: {int(dist)}m to destination.", 'info')
        return None

    return None


def main():
    global PLAYER_STATE_FILE
    config = load_config()
    if not config:
        print('[BRIDGE] ERROR: beamng_config.json not found')
        return

    relay_host = config.get('relay_server', '127.0.0.1')
    relay_port = int(config.get('relay_port', 3000))
    username = config.get('username', 'Player')

    relay_base = f"http://{relay_host}:{relay_port}"
    poll_url = f"{relay_base}/poll?user={username}"
    report_url = f"{relay_base}/report_shift"
    PLAYER_STATE_FILE = os.path.join(config['beamng_user'], 'bridge_player_state.txt')

    print('[BRIDGE] Starting bridge')
    print(f'[BRIDGE] Relay: {relay_base}')
    print(f'[BRIDGE] User:  {username}')

    bng = BeamNGpy(
        config['remote_addr'],
        int(config['remote_port']),
        home=os.path.dirname(os.path.dirname(config['beamng_bin'])),
        user=config['beamng_user'],
        quit_on_close=False,
    )

    shift_active = False
    total_distance = 0.0
    last_pos = None
    shift_job = ''
    map_id = 'unknown'
    work_vehicle_ids = set()
    player_state_errors = 0
    work_vehicle_missing_ticks = 0
    player_absent_ticks = 0

    def finalize_shift(reason='manual', report=True, remove_work_vehicles=True):
        nonlocal shift_active
        nonlocal total_distance
        nonlocal last_pos
        nonlocal shift_job
        nonlocal work_vehicle_ids
        nonlocal player_state_errors
        nonlocal work_vehicle_missing_ticks
        nonlocal player_absent_ticks

        if report and shift_active:
            payload = {
                'user': username,
                'distance': total_distance / 1000.0,
                'type': 'shift_done',
                'job': shift_job,
                'reason': reason,
            }
            try:
                requests.post(report_url, json=payload, timeout=2)
                print(f"[BRIDGE] Shift report sent ({reason}): {payload['distance']:.3f} km")
            except Exception as e:
                print(f'[BRIDGE] WARN: failed to send shift report ({reason}): {e}')

        if remove_work_vehicles and work_vehicle_ids:
            _delete_vehicle_ids_via_lua(bng, work_vehicle_ids)
            print(f'[BRIDGE] Work vehicles removed on shift finalization: {sorted(work_vehicle_ids)}')

        shift_active = False
        total_distance = 0.0
        last_pos = None
        shift_job = ''
        work_vehicle_ids.clear()
        player_state_errors = 0
        work_vehicle_missing_ticks = 0
        player_absent_ticks = 0

    try:
        print('[BRIDGE] Connecting to BeamNG...')
        bng.open(launch=False)
        print('[BRIDGE] Connected to BeamNG')
        map_id = _get_map_id_from_lua(bng)
        if map_id == 'unknown':
            map_id = 'west_coast_usa'
            print('[BRIDGE] Map fallback applied: west_coast_usa')
        print(f'[BRIDGE] Map detected: {map_id}')

        while True:
            try:
                resp = requests.get(poll_url, timeout=2)
                if resp.status_code == 200:
                    data = resp.json()
                    cmd_type = data.get('type', 'none')
                    garage = data.get('garage') or []

                    if cmd_type != 'none':
                        print(f'[BRIDGE] Command: {cmd_type}')

                    if cmd_type in ('start_shift', 'spawn_car'):
                        car_id = data.get('carId', 'pigeon')
                        if cmd_type == 'spawn_car' and garage and car_id not in garage:
                            print(f'[BRIDGE] DENY: {car_id} not in owned list {garage}')
                            continue

                        if cmd_type == 'start_shift' and work_vehicle_ids:
                            _delete_vehicle_ids_via_lua(bng, work_vehicle_ids)
                            work_vehicle_ids.clear()

                        plate = data.get('plate', '')
                        plate_design = data.get('plateDesign', 'htnv_russian_regular')
                        livery = data.get('livery', '')
                        config_key = data.get('config', '')
                        resolved_config = resolve_config_key_via_lua(bng, car_id, livery, config_key)
                        print(f'[BRIDGE] Spawn request: car={car_id} plate={plate} config={resolved_config or "-"}')
                        if cmd_type == 'start_shift' and livery:
                            _log_livery_candidates(bng, car_id, livery)

                        # Reliability first: Python spawn is the most stable path in this setup.
                        result = spawn_vehicle_via_py(bng, car_id, plate, resolved_config)
                        if not result.startswith('py_ok'):
                            lua_result = spawn_vehicle_via_lua(
                                bng,
                                car_id,
                                plate,
                                plate_design,
                                livery,
                                resolved_config or config_key
                            )
                            result = f'{result} | lua_fallback={lua_result}'
                        print(f'[BRIDGE] Spawn result: {result}')
                        spawn_success = (
                            result.startswith('py_ok')
                            or 'OK:' in result
                            or 'OK:replaced' in result
                        )
                        spawned_ids = _extract_spawned_ids(result)
                        if spawned_ids:
                            work_vehicle_ids.update(spawned_ids)
                            print(f'[BRIDGE] Tracked work vehicle ids: {sorted(work_vehicle_ids)}')
                        elif cmd_type == 'start_shift' and spawn_success:
                            # Fallback tracking when spawn API did not report new IDs
                            player_vid = _get_player_vehicle_id_safe(bng)
                            if player_vid is not None:
                                work_vehicle_ids.add(player_vid)
                                print(f'[BRIDGE] Tracked fallback work vehicle id: {player_vid}')

                        if cmd_type == 'start_shift':
                            if spawn_success:
                                shift_active = True
                                total_distance = 0.0
                                last_pos = None
                                shift_job = str(data.get('jobId') or data.get('job') or 'shift').lower()
                                work_vehicle_missing_ticks = 0
                                player_absent_ticks = 0
                            else:
                                print('[BRIDGE] WARN: start_shift ignored because vehicle spawn failed')

                    elif cmd_type == 'end_shift':
                        finalize_shift(reason='manual_end', report=True, remove_work_vehicles=True)

                    elif cmd_type == 'despawn_all':
                        bng.queue_lua_command("extensions.core_vehicles and extensions.core_vehicles.removeAllVehicles and extensions.core_vehicles.removeAllVehicles()")
                        finalize_shift(reason='despawn_all', report=False, remove_work_vehicles=True)

                if shift_active:
                    try:
                        player_vid = _get_player_vehicle_id_safe(bng)
                        if player_vid is None:
                            player_absent_ticks += 1
                            if player_absent_ticks >= PLAYER_ABSENT_LIMIT:
                                print('[BRIDGE] Auto end shift: player vehicle is unavailable (likely left map/game).')
                                finalize_shift(reason='player_left_game', report=True, remove_work_vehicles=False)
                                continue
                        else:
                            player_absent_ticks = 0
                            if not work_vehicle_ids:
                                work_vehicle_ids.add(player_vid)

                        if work_vehicle_ids:
                            alive_ids = _get_current_vehicle_ids(bng)
                            if work_vehicle_ids.intersection(alive_ids):
                                work_vehicle_missing_ticks = 0
                            else:
                                work_vehicle_missing_ticks += 1
                                if work_vehicle_missing_ticks >= WORK_VEHICLE_MISSING_LIMIT:
                                    print('[BRIDGE] Auto end shift: work vehicle no longer exists.')
                                    _show_game_message(bng, 'Shift ended: work vehicle removed.', 'warning')
                                    finalize_shift(reason='work_vehicle_removed', report=True, remove_work_vehicles=False)
                                    continue

                        cur_pos = _get_player_pos_from_lua(bng)
                        if not _valid_world_pos(cur_pos):
                            player_state_errors += 1
                            if player_state_errors % 20 == 1:
                                print('[BRIDGE] WARN: player state unavailable (position not readable).')
                            continue
                        player_state_errors = 0
                        if last_pos is not None:
                            total_distance += calc_distance(cur_pos, last_pos)
                        last_pos = cur_pos
                    except Exception:
                        pass

            except requests.RequestException:
                pass
            except Exception as e:
                print(f'[BRIDGE] Loop error: {e}')
            time.sleep(0.05)

            time.sleep(1)

    except Exception as e:
        print(f'[BRIDGE] Fatal error: {e}')
    finally:
        try:
            bng.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
