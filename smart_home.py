import time
from time import sleep
import _thread

import network

try:
    import usocket as socket
except:
    import socket

from machine import Pin, ADC, SoftI2C
import dht

import ssd1306
from ds1302 import DS1302
from smart_home_site import smart_home_site

# TODO: szebb megoldás lenne socketek helyett mqtt protokollt használni
# de a másik chip esp01 nem támogatja


class SmartHomeConfig:
    # SmartHomeConfig konfigurációs adatok a SmartHome osztályhoz
    def __init__(self) -> None:
        # pin konfigurációk
        self.ds_clk = Pin(18)
        self.ds_data = Pin(5)
        self.ds_rst = Pin(15)

        self.dht22_sensor = Pin(13)

        self.voltage_sensor = Pin(33)
        self.voltage_sensor_atten = ADC.ATTN_11DB

        self.photo_sensor = Pin(34)
        self.photo_sensor_atten = ADC.ATTN_11DB

        self.button = Pin(26, Pin.IN, Pin.PULL_UP)
        self.button_irq_edge = Pin.IRQ_RISING

        self.movement = Pin(27, Pin.IN, Pin.PULL_UP)
        self.movement_irq_edge = Pin.IRQ_FALLING
        self.movement_treshold = 30

        self.scl=Pin(22),
        self.sda=Pin(21)

        # wifi konfigurációk
        self.ssid = "BADAM"
        self.password = "87654321"


        # kiválasztható módok
        self.smart_home_modes = [
            "Ido", "Homerseklet",
            "Paratartalom", "Feszultseg", "Fenyero"]

        self.oled_width = 128
        self.oled_height = 64

class SocketType:
    # socket osztály ami eltárol egy kapcsolatot illetve hogy mit kért a kliens
    def __init__(self, connection, address, update) -> None:
        self.conn = connection
        self.addr = address
        # update hogyha ez már nem az első kérése a kliensnek
        # ilyen esetben csak a szenzor adatokat küldjük el és nem az egész oldalt
        self.update = update

class SmartHome:
    # Fő osztály ami tartalmazza
    # kommunikációt a klienssel
    # wifi kapcsolatot
    # szenzor és egyéb hw kezelést

    # alapértelmezett konfiguráció
    defaultCfg = SmartHomeConfig()

    # alapértelmezett html oldal smart_home_site.py-ban
    html = smart_home_site

    def __init__(self, config: SmartHomeConfig = defaultCfg):
        # konstruktor

        # konfiguráció
        self.config = config
        self.current_mode = 0  # TIME

        # oldal adatok
        self.date = ""
        self.temperature = ""
        self.humidity = ""
        self.voltage = ""
        self.luminosity = ""
        self.movement = "nincs mozgas"
        self.mode = self.config.smart_home_modes[self.current_mode]
        self.html_content = ""

        # wifi kapcsolat
        self.station = None

        # relé kommunikáció
        self.relay_ip = None
        self.movement_activate = False
        self.movement_sent = False
        self.last_movement_time = None
        self.config.movement.irq(
            trigger=config.movement_irq_edge,
            handler=self._movement_interrupt)

        # gombnyomás
        self.last_button_press_time = time.time()
        self.config.button.irq(
            trigger=config.button_irq_edge,
            handler=self._button_interrupt)

        # egyéb szenzorok
        self.rtc = DS1302(config.ds_clk, config.ds_data, config.ds_rst)

        self.dht22_sensor = dht.DHT22(config.dht22_sensor)

        self.voltage_sensor = ADC(config.voltage_sensor)
        self.voltage_sensor.atten(config.voltage_sensor_atten)

        self.photo_sensor = ADC(config.photo_sensor)
        self.photo_sensor.atten(config.photo_sensor_atten)

        # kliens szerver kapcsolat
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.s.bind(('', 80))
        self.s.listen(5)
        self.connection_list = []
        # lock hogy ne akadjon össze a több szál ami kommunikál
        self.connection_lock = _thread.allocate_lock()

        self.generate_site_content()

        self.i2c = SoftI2C(scl=Pin(22), sda=Pin(21))
        self.oled = ssd1306.SSD1306_I2C(self.config.oled_width, self.config.oled_height, self.i2c)

    def _socket_thread(self):
        # socket száll ami a kliensektől várja a kéréseket
        # amennyiben a kérés /getSensorData akkor csak a szenzor adatokat küldi el
        # hozzáfűzi az új kapcsolatot a connection_list-hez
        while True:
            conn, addr = self.s.accept()
            # kizárólag egy száll használhatja a connection_lock-ot egyszerre
            with self.connection_lock:
                request = conn.recv(1024)
                conn.settimeout(None)
                request = str(request)
                update = request.find('/getSensorData') == 6
                self.connection_list.append(SocketType(conn, addr, update))

    def _site_thread(self):
        # oldal kezelésére szolgáló thread
        # ez küldi el a tartalmat a kliensnek
        while True:
            # kizárólag egy száll használhatja a connection_lock-ot egyszerre
            with self.connection_lock:
                if len(self.connection_list) == 0:
                    # ha nincs bejövő kapcsolat várunk 100ms-et
                    sleep(0.1)
                else:
                    for elem in self.connection_list:
                        # minden connection-nek kiküldjük amit kértek
                        try:
                            elem.conn.send('HTTP/1.1 200 OK\n')
                            elem.conn.send('Content-Type: text/html\n')
                            elem.conn.send('Connection: close\n\n')

                            if elem.update:
                                # a kérés csak szenzoradat
                                elem.conn.sendall(self.html_content)
                            else:
                                # a kérés a teljes oldal
                                elem.conn.sendall(self.html)

                            # lezárjuk a kapcsolatot és töröljük a listából
                            elem.conn.close()
                            self.connection_list.remove(elem)
                        except OSError as error:
                            elem.conn.close()
                            self.connection_list.remove(elem)
                            print(error)
                            print('Connection closed')

    def check_button_debounce(self):
        # néha a gomb nyomásakor többször is meghívódik a gomb interrupt
        # ezért csak 0.5 másodpercenként engedjük a gombnyomást
        if time.time()-self.last_button_press_time < 0.5:
            return False
        return True

    def _button_interrupt(self, pin):
        # gombnyomás interrupt
        # ha a gombnyomás 0.5 másodpercen belül van akkor nem csinálunk semmit
        # ha a gombnyomás 0.5 másodpercen túl van akkor a következő módra váltunk
        if not self.check_button_debounce():
            return

        self.last_button_press_time = time.time()
        self.current_mode += 1

        if self.current_mode >= len(self.config.smart_home_modes):
            # ha a listán túllógunk akkor legyen a 0-dik al egyenlő az új mód
            # enum használata nem lehetséges a micropythonban
            self.current_mode = 0

    def _movement_interrupt(self, pin):
        # mozgásérzékelő interrupt
        self.movement_activate = True
        self.last_movement_time = time.time()

    def set_date_time(self, date_time):
        # beállíthatjuk az órát
        # de ez nem szükséges csak egyszer egészen addig amíg az elem le nem merül
        # date_time = (year, month, day, weekday, hour, minute, second, microsecond)
        self.rtc.date_time(date_time)

    def get_date_time_raw(self):
        return self.rtc.date_time()

    def get_date_time(self):
        # formázza a jelenlegi időt
        date_time = self.get_date_time_raw()
        self.date = f"{date_time[0]}.{date_time[1]:02d}.{date_time[2]:02d} {date_time[4]:02d}:{date_time[5]:02d}:{date_time[6]:02d}"

        return self.date

    def _measure_dht22(self):
        # mérés a DHT22 szenzorral
        self.dht22_sensor.measure()

    def get_temperature(self) -> str:
        # hőmérséklet érték lekérése és formázása
        self.temperature = f"{self.dht22_sensor.temperature():.2f} Celsius"

        return self.temperature

    def get_humidity(self) -> str:
        # páratartalom érték lekérése és formázása
        self.humidity = f"{self.dht22_sensor.humidity():.2f}%"

        return self.humidity

    def get_raw_voltage(self):
        # nyers feszültség lekérése 0-4095 között
        return self.voltage_sensor.read()

    def get_voltage(self) -> str:
        # feszültés érték lekérése és formázása
        # 3.3 V-ot veszszünk alapul
        volt = 3.3*(self.get_raw_voltage()/4095)
        self.voltage = f"{volt:.2f}V"

        return self.voltage

    def get_button_value(self):
        # gomb érték lekérése
        return self.config.button.value()

    def get_raw_luminosity(self):
        # nyers fényerő lekérése 0-4095 között
        return self.photo_sensor.read()

    def get_luminosity(self) -> str:
        # fényerő érték lekérése és formázása
        # mivel ez relatív érték a fotoresistorhoz képest ezért csak szzázalékban adjuk meg
        percentate = self.get_raw_luminosity()*100.0/4095.0
        self.luminosity = f"{percentate:.2f}%"
        return self.luminosity

    def connect(self) -> bool:
        # wifi csatlakozás a configurációban megadott adatokkal
        try:
            self.station = network.WLAN(network.STA_IF)
            self.station.active(True)
            self.station.connect(self.config.ssid, self.config.password)
            self.station.isconnected()
            self.station.ifconfig()
        except OSError as error:
            print(error)
            print("Could not connect. See error message above.")
            return False

        return self.station.isconnected()
    
    def generate_site_content(self):
        # generálja a weboldal tartalmát
        # kizárólag a szenzor adatokat fogja visszaadni
        self.html_content = self.get_date_time() + "|"+self.get_temperature() + "|" + \
            self.get_humidity() + "|"+self.get_voltage() + "|"+self.get_luminosity()+"|" + \
            self.movement + "|"+self.config.smart_home_modes[self.current_mode]

    def connect_relay(self):
        # TODO: rele csatlakoztatása
        pass

    def send_movement(self, movement: bool):
        # TODO: movement parancs küldése a relének
        
        pass

    def display_state_on_screen(self, state: str):
        # a kijelző jelenleg nem működik úgyhogy csak kiiratom mégegyszer az adatokat konzolra
        self.oled.fill(0)
        self.oled.text(f"{self.config.smart_home_modes[self.current_mode]}:", 0, 10)
        self.oled.text(f"{state}", 0, 30)
        self.oled.show()

    def display_state(self, state: str):
        # adatok megjelenítése
        print(f"{self.config.smart_home_modes[self.current_mode]}:\n{state}")
        self.display_state_on_screen(state)

    def handle_mode(self):
        try:
            # szenzor adatok lekérése
            self._measure_dht22()

            self.get_date_time()
            self.get_temperature()
            self.get_humidity()
            self.get_voltage()
            self.get_luminosity()

            # a jelenlegi mód kiválasztása és megjelenítése
            if self.current_mode == 0:
                self.display_state(self.date)
            elif self.current_mode == 1:
                self.display_state(self.temperature)
            elif self.current_mode == 2:
                self.display_state(self.humidity)
            elif self.current_mode == 3:
                self.display_state(self.voltage)
            elif self.current_mode == 4:
                self.display_state(self.luminosity)
            else:
                # ha nem létező mód van beállítva akkor visszaállítjuk a default-ra
                # ez történik ha a gombnyomásokkal körbeérünk a listán
                self.current_mode = 0
            self.mode = self.config.smart_home_modes[self.current_mode]
        except OSError as error:
            print(error)
            print("Could not get sensor data. See error message above.")

    def handle_relay(self):
        # mozgás érzékelés
        self.movement = "mozgas eszlelve" if self.config.movement.value() > 0 else "nincs mozgás"

        # ha kapcsolódtunk a reléhez
        if self.connect_relay():
            # ha volt mozgás és még nem küldtük ki a relének
            # kapcsoljuk fel a fényeket
            if (self.movement_activate and not self.movement_sent):
                self.send_movement(True)
                self.movement_sent = True
                self.config.e.send(self.config.peer, 1, True) 

            # mozgás és jelenlegi idő közötti különbség másodpercben
            timdifference = time.time() - self.last_movement_time

            # ha eltelt a threshold idő és nem volt mozgás és most csin mozgás
            # akkor küldjük ki a relének a parancsot hogy kapcsolja le a fényeket
            if timdifference > self.config.movement_treshold and not self.movement_activate and self.config.movement.value() < 1:
                self.send_movement(False)
                self.movement_activate = False
                self.movement_sent = False
                self.config.e.send(self.config.peer, 0, True) 

    def start(self):
        # fő száll ami a program futását irányítja

        # socket kapcsolat várakozó száll
        _thread.start_new_thread(self._socket_thread, ())

        # beérkező kapcsolatoknak küldi ki a weboldalt
        _thread.start_new_thread(self._site_thread, ())

        while True:
            # wifi kapcsolódás, ha nincs akkor próbálkozik
            while self.station is None or (not self.station.isconnected()):
                self.connect()
                sleep(1)

            self.handle_mode()
            self.handle_relay()

            self.generate_site_content()

            sleep(1)
