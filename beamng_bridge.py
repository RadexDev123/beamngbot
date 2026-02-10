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
    
    print(f"--- МОСТ ЗАПУЩЕН (V2.0 - ТРЕКИНГ) ---")
    print(f"Пользователь: {config['username']}")
    print(f"Подключение к игре: {config['remote_addr']}:{config['remote_port']}")

    bng = BeamNGpy(config['remote_addr'], config['remote_port'], 
                   home=os.path.dirname(os.path.dirname(config['beamng_bin'])), 
                   user=config['beamng_user'],
                   quit_on_close=False)

    active_vehicle = None
    total_distance = 0.0
    last_pos = None
    shift_active = False

    try:
        print("Подключение к игре...")
        bng.open(launch=False)
        print("✅ Связь с игрой установлена!")

        while True:
            try:
                # Опрашиваем сервер реле
                response = requests.get(poll_url, timeout=2)
                if response.status_code == 200:
                    data = response.json()
                    
                    if data.get('type') == 'start_shift':
                        car_id = data.get('carId', 'pigeon')
                        print(f"🚀 Начало смены: {car_id}")
                        
                        # Находим позицию для спавна
                        vehicles = bng.vehicles.get_current()
                        spawn_pos = (0, 0, 0)
                        if vehicles:
                            player_v = list(vehicles.values())[0]
                            player_v.connect(bng)
                            player_v.poll_sensors()
                            pos = player_v.state['pos']
                            spawn_pos = (pos[0], pos[1] + 5, pos[2] + 2)
                        
                        # Создаем машину
                        vid = f'job_{int(time.time())}'
                        active_vehicle = Vehicle(vid, model=car_id)
                        bng.vehicles.spawn(active_vehicle, pos=spawn_pos)
                        active_vehicle.connect(bng)
                        
                        # Сбрасываем трекинг
                        total_distance = 0.0
                        last_pos = spawn_pos
                        shift_active = True
                        print(f"✅ Машина {car_id} создана. Трекинг начат.")

                    elif data.get('type') == 'end_shift':
                        if shift_active:
                            print(f"🏁 Смена завершена. Итоговая дистанция: {total_distance:.2f} м")
                            
                            # Отправляем отчет на сервер
                            report = {
                                "user": config['username'],
                                "distance": total_distance / 1000.0, # Переводим в км
                                "type": "shift_done"
                            }
                            try:
                                requests.post(report_url, json=report, timeout=2)
                                print("✅ Отчет отправлен на сервер.")
                            except:
                                print("❌ Ошибка отправки отчета!")

                            # Удаляем машину
                            if active_vehicle:
                                bng.vehicles.despawn(active_vehicle)
                                print(f"🧹 Машина {active_vehicle.vid} удалена.")
                            
                            shift_active = False
                            active_vehicle = None

                # Если смена активна, считаем расстояние
                if shift_active and active_vehicle:
                    try:
                        active_vehicle.poll_sensors()
                        curr_pos = active_vehicle.state['pos']
                        if last_pos:
                            d = calculate_distance(last_pos, curr_pos)
                            if d > 0.1: # Минимум 10 см движения
                                total_distance += d
                                last_pos = curr_pos
                                if int(total_distance) % 10 == 0: # Пишем лог каждые 10 метров
                                     print(f"📍 Пройдено: {total_distance:.1f} м")
                    except:
                        pass # Машина могла пропасть

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
