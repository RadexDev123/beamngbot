import json
import os
import time
import math
import random
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


def _get_player_pos_from_lua(bng):
    try:
        pos_data = bng.queue_lua_command(
            "local v=be:getPlayerVehicle(0); if v then local p=v:getPosition(); return {p.x,p.y,p.z} end"
        )
        if isinstance(pos_data, (list, tuple)) and len(pos_data) == 3:
            return (float(pos_data[0]) + 6.0, float(pos_data[1]), float(pos_data[2]) + 1.0)
    except Exception:
        pass
    return (0.0, 0.0, 0.0)


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


def _draw_world_marker(bng, pos, r, g, b):
    x, y, z = pos
    lua = f"""
    (function()
      local ok, err = pcall(function()
        if not debugDrawer then return end
        local p = vec3({x:.3f}, {y:.3f}, {z:.3f})
        local c = ColorF({r:.3f}, {g:.3f}, {b:.3f}, 0.9)
        debugDrawer:drawCylinder(p, p + vec3(0, 0, 8), 0.9, c)
        debugDrawer:drawSphere(p + vec3(0, 0, 0.8), 1.6, c)
      end)
      return ok and 'ok' or ('err:' .. tostring(err))
    end)()
    """
    try:
        bng.queue_lua_command(lua)
    except Exception:
        pass


def _draw_taxi_mission_markers(bng, mission):
    if not mission or not mission.get('active'):
        return
    phase = mission.get('phase')
    pickup = mission.get('pickup')
    dropoff = mission.get('dropoff')

    # Cyan = pickup, Yellow = dropoff
    if phase == 'to_pickup' and pickup:
        _draw_world_marker(bng, pickup, 0.1, 0.9, 1.0)
    elif phase == 'to_dropoff' and dropoff:
        _draw_world_marker(bng, dropoff, 1.0, 0.85, 0.1)

def _get_map_id_from_lua(bng):
    lua = """
    (function()
      local id = ''
      pcall(function()
        if getMissionFilename then
          local mf = tostring(getMissionFilename() or '')
          local level = string.match(mf, '/levels/([^/]+)/')
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
      return string.lower(id)
    end)()
    """
    try:
        value = bng.queue_lua_command(lua)
        return str(value or 'unknown').lower()
    except Exception:
        return 'unknown'


def spawn_vehicle_via_lua(bng, car_id, plate, plate_design, livery):
    car_id = to_lua_str(car_id or 'pigeon')
    plate = to_lua_str(plate or '')
    plate_design = to_lua_str(plate_design or 'htnv_russian_regular')
    livery = to_lua_str(livery or '')

    lua = f"""
    (function()
      local model = '{car_id}'
      local pos = vec3(0, 0, 0)
      local playerVeh = be:getPlayerVehicle(0)
      if playerVeh then
        pos = playerVeh:getPosition() + playerVeh:getDirectionVector() * 6 + vec3(0, 0, 1)
      end

      local handler = (extensions and extensions.core_vehicles) or core_vehicles
      if not handler then
        return 'ERR:no_core_vehicles'
      end

      -- Stable mode: ignore livery config to avoid invalid-config spawn failures.
      local vid = handler.spawnVehicle(model, nil, pos, quat(0,0,0,1))

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
            handler.replaceVehicle(model, nil)
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

    bng.queue_lua_command(lua)

    final_count, new_ids_final, seen_new_ids = _observe_vehicle_ids(bng, before_ids, duration_sec=1.5)
    return f"queued; vehicles_now={final_count}; new_ids_final={new_ids_final}; seen_new_ids={seen_new_ids}"


def spawn_vehicle_via_py(bng, car_id):
    try:
        before = bng.vehicles.get_current() or {}
        before_ids = set(before.keys())
    except Exception:
        before_ids = set()

    pos = _get_player_pos_from_lua(bng)
    vid_name = f"bot_{int(time.time() * 1000) % 1000000}"
    vehicle = Vehicle(vid=vid_name, model=str(car_id or 'pigeon'))
    errors = []
    spawned = False

    try:
        bng.vehicles.spawn(vehicle, pos=pos, rot_quat=(0, 0, 0, 1), cling=True)
        spawned = True
    except TypeError:
        try:
            bng.vehicles.spawn(vehicle, pos, (0, 0, 0, 1))
            spawned = True
        except Exception as e:
            errors.append(f"legacy_spawn:{e}")
    except Exception as e:
        errors.append(f"spawn:{e}")

    if not spawned:
        return f"py_failed:{';'.join(errors) if errors else 'unknown'}"

    final_count, new_ids_final, seen_new_ids = _observe_vehicle_ids(bng, before_ids, duration_sec=1.5)
    return f"py_ok; vehicles_now={final_count}; new_ids_final={new_ids_final}; seen_new_ids={seen_new_ids}"


def create_taxi_mission(bng, map_id='unknown'):
    px, py, pz = _get_player_pos_from_lua(bng)
    profile = TAXI_MAP_PROFILES['default']
    if 'west_coast_usa' in map_id:
        profile = TAXI_MAP_PROFILES['west_coast_usa']
    elif 'east_coast_usa' in map_id:
        profile = TAXI_MAP_PROFILES['east_coast_usa']

    pickup_dist = random.uniform(profile['pickup_min'], profile['pickup_max'])
    pickup_ang = random.uniform(0.0, math.tau)
    pickup = (
        px + math.cos(pickup_ang) * pickup_dist,
        py + math.sin(pickup_ang) * pickup_dist,
        pz
    )

    drop_dist = random.uniform(profile['drop_min'], profile['drop_max'])
    drop_ang = random.uniform(0.0, math.tau)
    dropoff = (
        pickup[0] + math.cos(drop_ang) * drop_dist,
        pickup[1] + math.sin(drop_ang) * drop_dist,
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

    px, py, pz = _get_player_pos_from_lua(bng)
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
    taxi_mission = None
    taxi_trips = 0
    taxi_earned = 0
    map_id = 'unknown'

    try:
        print('[BRIDGE] Connecting to BeamNG...')
        bng.open(launch=False)
        print('[BRIDGE] Connected to BeamNG')
        map_id = _get_map_id_from_lua(bng)
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

                        plate = data.get('plate', '')
                        plate_design = data.get('plateDesign', 'htnv_russian_regular')
                        livery = data.get('livery', '')
                        print(f'[BRIDGE] Spawn request: car={car_id} plate={plate}')
                        result = spawn_vehicle_via_py(bng, car_id)
                        if ('new_ids_final=[]' in result and 'seen_new_ids=[]' in result) or result.startswith('py_failed:'):
                            lua_result = spawn_vehicle_via_lua(bng, car_id, plate, plate_design, livery)
                            result = f'{result} | lua_fallback={lua_result}'
                        print(f'[BRIDGE] Spawn result: {result}')

                        if cmd_type == 'start_shift':
                            shift_active = True
                            total_distance = 0.0
                            last_pos = None
                            shift_job = str(data.get('jobId') or data.get('job') or 'shift').lower()
                            taxi_trips = 0
                            taxi_earned = 0
                            taxi_mission = create_taxi_mission(bng, map_id=map_id)

                    elif cmd_type == 'end_shift':
                        if shift_active:
                            report = {
                                'user': username,
                                'distance': total_distance / 1000.0,
                                'type': 'shift_done',
                                'job': shift_job,
                                'taxiTrips': taxi_trips,
                                'taxiEarned': taxi_earned
                            }
                            requests.post(report_url, json=report, timeout=2)
                        shift_active = False
                        total_distance = 0.0
                        last_pos = None
                        shift_job = ''
                        taxi_mission = None
                        taxi_trips = 0
                        taxi_earned = 0

                    elif cmd_type == 'despawn_all':
                        bng.queue_lua_command("extensions.core_vehicles and extensions.core_vehicles.removeAllVehicles and extensions.core_vehicles.removeAllVehicles()")
                        shift_active = False
                        total_distance = 0.0
                        last_pos = None
                        shift_job = ''
                        taxi_mission = None

                if shift_active:
                    try:
                        cur_pos = _get_player_pos_from_lua(bng)
                        if last_pos is not None:
                            total_distance += calc_distance(cur_pos, last_pos)
                        last_pos = cur_pos

                        if taxi_mission is None or not taxi_mission.get('active'):
                            taxi_mission = create_taxi_mission(bng, map_id=map_id)
                        else:
                            taxi_done = update_taxi_mission(bng, taxi_mission)
                            if taxi_done:
                                taxi_trips += 1
                                taxi_earned += int(taxi_done.get('earned', 0))
                                taxi_mission = create_taxi_mission(bng, map_id=map_id)

                        # Draw visual mission marker in-world every loop.
                        _draw_taxi_mission_markers(bng, taxi_mission)
                    except Exception:
                        pass

            except requests.RequestException:
                pass
            except Exception as e:
                print(f'[BRIDGE] Loop error: {e}')

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
