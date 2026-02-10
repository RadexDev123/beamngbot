import json
import os
import time
import requests
import math
from beamngpy import BeamNGpy, Vehicle

def load_config():
    config_path = 'beamng_config.json'
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def calculate_distance(p1, p2):
    return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2 + (p1[2]-p2[2])**2)

def main():
    config = load_config()
    if not config:
        print("Ошибка: Файл beamng_config.json не найден!")
        return

    relay_url = f"http://{config['relay_server']}:{config['relay_port']}"
    poll_url = f"{relay_url}/poll?user={config['username']}"
    report_url = f"{relay_url}/report_shift"
    
    print(f"--- МОСТ ЗАПУЩЕН (V2.1 - SPAWN & PLATES) ---")
    print(f"Пользователь: {config['username']}")
    print(f"Подключение к игре: {config['remote_addr']}:{config['remote_port']}")

    bng = BeamNGpy(config['remote_addr'], config['remote_port'], 
                   home=os.path.dirname(os.path.dirname(config['beamng_bin'])), 
                   user=config['beamng_user'],
                   quit_on_close=False)

    active_vehicle = None
    spawned_personal_vehicles = []
    total_distance = 0.0
    last_pos = None
    shift_active = False

    try:
        print("Подключение к игре... (Убедитесь, что игра запущена с -tcom -tport 25252)")
        bng.open(launch=False)
        print("✅ Связь с игрой установлена!")

        while True:
            try:
                # Опрашиваем сервер реле
                response = requests.get(poll_url, timeout=2)
                if response.status_code == 200:
                    data = response.json()
                    cmd_type = data.get('type')
                    garage = data.get('garage', [])
                    
                    if cmd_type in ['start_shift', 'spawn_car']:
                        car_id = data.get('carId', 'pigeon')
                        
                        # Security: ownership check
                        if cmd_type == 'spawn_car' and car_id not in garage:
                            print(f"❌ ОТКАЗАНО: {car_id} нет в гараже!")
                            continue

                        plate = data.get('plate', '')
                        design = data.get('plateDesign', 'htnv_russian_regular')
                        
                        print(f"🚀 Запрос на спавн: {car_id} | Номер: {plate}")
                        
                        try:
                            vehicles = bng.vehicles.get_current()
                            if vehicles:
                                player_v = list(vehicles.values())[0]
                                player_v.connect(bng)
                                player_v.poll_sensors()
                                pos = player_v.state['pos']
                                dir_vec = player_v.state['dir']
                                spawn_pos = (pos[0] + dir_vec[0]*6, pos[1] + dir_vec[1]*6, pos[2] + 1)
                            else:
                                spawn_pos = (0, 0, 1) 
                        except:
                            spawn_pos = (0, 0, 1)
                        
                        vid = f'bot_{int(time.time())}'
                        new_veh = Vehicle(vid, model=car_id)
                        bng.vehicles.spawn(new_veh, pos=spawn_pos)
                        new_veh.connect(bng)
                        
                        if plate:
                            print(f"🆔 Номер: {plate} ({design})")
                            time.sleep(0.5)
                            bng.queue_lua_command(f"extensions.core_vehicles.setLicensePlateText('{plate}', '{vid}')")
                            bng.queue_lua_command(f"extensions.core_vehicles.setLicensePlateDesign('{design}', '{vid}')")
                        
                        if cmd_type == 'start_shift':
                            active_vehicle = new_veh
                            total_distance = 0.0
                            last_pos = spawn_pos
                            shift_active = True
                        else:
                            spawned_personal_vehicles.append(new_veh)

                    elif cmd_type == 'despawn_all':
                        print("🧹 Очистка...")
                        if shift_active:
                            report = {"user": config['username'], "distance": total_distance / 1000.0, "type": "shift_done"}
                            requests.post(report_url, json=report, timeout=2)
                            if active_vehicle:
                                try: bng.vehicles.despawn(active_vehicle)
                                except: pass
                            shift_active = False
                            active_vehicle = None
                        
                        for v in spawned_personal_vehicles:
                            try: bng.vehicles.despawn(v)
                            except: pass
                        spawned_personal_vehicles = []

                    elif cmd_type == 'end_shift':
                        if shift_active:
                            report = {"user": config['username'], "distance": total_distance / 1000.0, "type": "shift_done"}
                            requests.post(report_url, json=report, timeout=2)
                            if active_vehicle:
                                bng.vehicles.despawn(active_vehicle)
                            shift_active = False
                            active_vehicle = None

                if shift_active and active_vehicle:
                    try:
                        active_vehicle.poll_sensors()
                        curr_pos = active_vehicle.state['pos']
                        if last_pos:
                            d = calculate_distance(last_pos, curr_pos)
                            if d > 0.1:
                                total_distance += d
                                last_pos = curr_pos
                                if int(total_distance) % 10 == 0:
                                     print(f"📍 Дистанция: {total_distance:.1f} м")
                    except: pass

            except requests.exceptions.RequestException:
                pass # Пропуск ошибок сети
            except Exception as e:
                print(f"⚠ Ошибка: {e}")

            time.sleep(1) # Короткий цикл для плавного трекинга

    except Exception as e:
        print(f"❌ Ошибка моста: {e}")
    finally:
        try: bng.close()
        except: pass

if __name__ == "__main__":
    main()
