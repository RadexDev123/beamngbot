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
                        mafia_target = data.get('mafiaTarget')
                        
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
                        
                        livery = data.get('livery')
                        if plate:
                            plate_upper = plate.upper()
                            print(f"🆔 Установка номера: {plate_upper} ({design})")
                            # Увеличиваем задержку, так как спавн может быть долгим
                            time.sleep(2.0)
                            
                            # Ливреи: маппинг на конкретные скины моделей
                            livery_map = {
                                ('etk800', 'taxi'): 'etk800_skin_taxi',
                                ('sunburst', 'police'): 'sunburst_skin_police',
                                ('van', 'ambulance'): 'van_skin_ambulance',
                                ('van', 'taxi'): 'van_skin_taxi',
                                ('roamer', 'police'): 'roamer_skin_police',
                                ('fullsize', 'police'): 'fullsize_skin_police',
                                ('roamer', 'ambulance'): 'roamer_skin_ems'
                            }
                            
                            skin_part = livery_map.get((car_id, livery), livery)
                            
                            # Пробуем несколько способов для надежности
                            lua_cmd = f"local v = be:getObjectByID('{vid}'); if v then v:setLicensePlateText('{plate_upper}'); extensions.core_vehicles.setLicensePlateDesign('{design}', '{vid}')"
                            if livery:
                                lua_cmd += f"; extensions.core_vehicle_partmgmt.setPartConfig({{['paint_design'] = '{skin_part}'}}, '{vid}')"
                            lua_cmd += " end"
                            
                            bng.queue_lua_command(lua_cmd)
                            if livery: print(f"🎨 Ливрея: {livery} -> {skin_part}")
                            print(f"✅ Команда на номер и ливрею отправлена")
                        
                        if cmd_type == 'start_shift':
                            active_vehicle = new_veh
                            total_distance = 0.0
                            last_pos = spawn_pos
                            shift_active = True
                            
                            if mafia_target:
                                target_model = mafia_target.get('model', 'pessima')
                                print(f"🕵️ ЗАДАНИЕ МАФИИ: Угнать {mafia_target.get('name')} ({mafia_target.get('color')})")
                                # Рандомные точки спавна
                                spawn_points = [(100, 100, 5), (-100, 200, 5), (300, -100, 5), (50, -300, 5)]
                                import random
                                t_pos = random.choice(spawn_points)
                                t_vid = f'target_{int(time.time())}'
                                t_veh = Vehicle(t_vid, model=target_model)
                                bng.vehicles.spawn(t_veh, pos=t_pos)
                                spawned_personal_vehicles.append(t_veh) # Для очистки
                                print(f"📍 Цель заспавнена в [{t_pos[0]}, {t_pos[1]}]")
                                
                                # Ставим "краденые" номера или просто случайные
                                time.sleep(1.0)
                                bng.queue_lua_command(f"local v = be:getObjectByID('{t_vid}'); if v then v:setLicensePlateText('STOLEN'); extensions.core_vehicles.setLicensePlateDesign('htnv_russian_regular', '{t_vid}') end")
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
