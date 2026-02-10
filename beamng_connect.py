import json
import os
from beamngpy import BeamNGpy, Vehicle, Scenario

def load_config():
    config_path = 'beamng_config.json'
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def main():
    config = load_config()
    if not config:
        print("Ошибка: Файл beamng_config.json не найден!")
        return

    print(f"Попытка подключения к {config['remote_addr']}:{config['remote_port']}...")
    
    # Инициализация BeamNGpy
    bng = BeamNGpy(config['remote_addr'], config['remote_port'], 
                   home=os.path.dirname(os.path.dirname(config['beamng_bin'])), 
                   user=config['beamng_user'],
                   quit_on_close=False)

    try:
        # Подключаемся БЕЗ запуска (launch=False)
        # Предполагаем, что игра уже запущена с флагами -tcom -tport 25252
        bng.open(launch=False)
        print("✅ Успешно подключено к BeamNG.drive!")

        # Получаем данные о машинах
        print("Поиск машин в сцене...")
        vehicles = bng.vehicles.get_current()
        
        if vehicles:
            print(f"Найдено машин: {len(vehicles)}")
            for vid, vehicle in vehicles.items():
                try:
                    vehicle.connect(bng)
                    # Можно вытянуть базовые данные
                    print(f"  - ID: {vid}, Модель: {vehicle.vid}")
                except Exception as ve:
                    print(f"  - Ошибка при получении данных машины {vid}: {ve}")
        else:
            print("⚠️ Машины не найдены. Убедись, что ты сидишь в машине.")

    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
        print("\nЧТО ДЕЛАТЬ:")
        print("1. Полностью закрой игру.")
        print("2. В Steam нажми правой кнопкой на BeamNG -> Свойства.")
        print("3. В поле 'Параметры запуска' впиши: -tcom -tport 25252")
        print("4. Запусти игру из Steam, загрузи карту и сядь в машину.")
        print("5. Запусти этот скрипт снова.")
    finally:
        try:
            bng.close()
        except:
            pass

if __name__ == "__main__":
    main()
