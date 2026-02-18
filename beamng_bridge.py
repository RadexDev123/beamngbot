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
        bng.queue_lua_command("guihooks.trigger('Message', {msg='BOT RP: Мост подключен!', category='info', icon='directions_car'})")

        while True:
            try:
                # Опрашиваем сервер реле
                response = requests.get(poll_url, timeout=2)
                if response.status_code == 200:
                    data = response.json()
                    if cmd_type != 'none':
                        print(f"📩 Получена команда: {cmd_type}")
                        if cmd_type in ['spawn_car', 'start_shift']:
                            print(f"📦 Ваш гараж на сервере: {garage}")

                    if cmd_type in ['start_shift', 'spawn_car']:
                        car_id = data.get('carId', 'pigeon')
                        mafia_target = data.get('mafiaTarget')
                        
                        # Security: ownership check (только для личных машин)
                        if cmd_type == 'spawn_car':
                            if not garage:
                                print(f"⚠️ ПРЕДУПРЕЖДЕНИЕ: Гараж на сервере пуст! Попробуйте сохранить профиль или купить машину.")
                            
                            if car_id not in garage:
                                print(f"❌ ОТКАЗАНО: {car_id} нет в вашем списке владельца ({garage})")
                                bng.queue_lua_command(f"guihooks.trigger('Message', {{msg='Транспорт {car_id} не найден в вашем гараже!', category='error'}})")
                                continue

                        plate = data.get('plate', '')
                        design = data.get('plateDesign', 'htnv_russian_regular')
                        livery = str(data.get('livery', '')).replace("'", "")
                        
                        print(f"🚀 Запрос на спавн: {car_id} | Номер: {plate} | Ливрея: {livery or 'default'}")
                        
                        spawn_lua = f"""
                        (function()
                            local model = '{car_id}'
                            local pos = vec3(0,0,0)
                            local playerVeh = be:getPlayerVehicle(0)
                            if playerVeh then
                                pos = playerVeh:getPosition() + playerVeh:getDirectionVector() * 6 + vec3(0,0,1)
                            end
                            
                            -- Пробуем через core_vehicles или extensions.core_vehicles
                            local handler = core_vehicles or (extensions and extensions.core_vehicles)
                            if not handler then
                                print('[BRIDGE] Error: core_vehicles extension not found')
                                return
                            end

                            local preferredConfig = '{livery}'
                            if preferredConfig == '' then preferredConfig = nil end
                            local vid = handler.spawnVehicle(model, preferredConfig, pos, quat(0,0,0,1))
                            if not vid and preferredConfig ~= nil then
                                vid = handler.spawnVehicle(model, nil, pos, quat(0,0,0,1))
                            end
                            if vid then
                                if '{plate}' ~= '' then
                                    handler.setLicensePlateText('{plate.upper()}', vid)
                                    handler.setLicensePlateDesign('{design}', vid)
                                end
                                guihooks.trigger('Message', {{msg='Транспорт ' .. model .. ' заспавнен!', category='success'}})
                            else
                                guihooks.trigger('Message', {{msg='Ошибка: модель ' .. model .. ' не найдена.', category='error'}})
                            end
                        end)()
                        """
                        bng.queue_lua_command(spawn_lua)
                        print(f"✅ Команда на спавн {car_id} отправлена")
                        
                        if cmd_type == 'start_shift':
                            time.sleep(1) 
                            vehicles = bng.vehicles.get_current()
                            if vehicles:
                                active_vehicle = list(vehicles.values())[-1]
                                active_vehicle.connect(bng)
                                total_distance = 0.0
                                last_pos = active_vehicle.state['pos']
                                shift_active = True
                                print(f"🛠️ Смена начата на {car_id}")
                            
                            if mafia_target:
                                target_model = mafia_target.get('model', 'pessima')
                                bng.queue_lua_command(f"core_vehicles.spawnVehicle('{target_model}', nil, vec3(100,100,5), quat(0,0,0,1))")
                        else:
                            pass


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
                    except Exception as e: 
                        print(f"⚠ Ошибка сенсоров: {e}")
                        pass

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
