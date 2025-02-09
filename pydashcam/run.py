#!/usr/bin/env python
# -*- coding: utf-8 -*-

import struct
import datetime
import os
import sys
import tempfile
import tkinter as tk
from tkinter import filedialog
import cv2
from PIL import Image, ImageTk
import time
import folium
from cefpython3 import cefpython as cef
import nvtk_mp42gpx
import win32gui, win32con
from tkinter import ttk

def read_mp4_creation_time(file_path):
    use_daylight_saving_time = True
    with open(file_path, "rb") as f:
        data = f.read()

        # Suche nach dem 'mvhd' Atom, das die Erstellungszeit, Timescale und Dauer enthält
        mvhd_index = data.find(b'mvhd')
        if mvhd_index == -1:
            raise ValueError("Kein 'mvhd' Atom gefunden.")

        # Die 'mvhd' Box enthält die Zeitstempel 4 Bytes nach ihrem Start
        creation_time_offset = mvhd_index + 4 + 4  # 'mvhd' + Version/Flags (4 Bytes)
        timescale_offset = mvhd_index + 4 + 12  # Timescale befindet sich 12 Bytes nach 'mvhd'
        duration_offset = mvhd_index + 4 + 16  # Duration befindet sich 16 Bytes nach 'mvhd'

        # Extrahiere die 4-Byte Erstellungszeit
        creation_time_bytes = data[creation_time_offset:creation_time_offset + 4]
        creation_time = struct.unpack('>I', creation_time_bytes)[0]  # Unsigned 32-bit big-endian integer

        # MP4-Zeit beginnt am 1. Januar 1904
        epoch = datetime.datetime(1904, 1, 1)
        creation_datetime = epoch + datetime.timedelta(seconds=creation_time)

        # Ausgabe als Unix-Epoch
        epoch_time = int(creation_datetime.timestamp())

        # Sommer- oder Winterzeit prüfen und ggf. eine Stunde abziehen
        is_dst = time.localtime(epoch_time).tm_isdst
        if use_daylight_saving_time == True:
            if not is_dst:
                epoch_time -= 3600  # Eine Stunde (3600 Sekunden) abziehen, wenn Winterzeit

        # Extrahiere Timescale (Anzahl der Zeiteinheiten pro Sekunde)
        timescale_bytes = data[timescale_offset:timescale_offset + 4]
        timescale = struct.unpack('>I', timescale_bytes)[0]

        # Extrahiere Dauer (Gesamtdauer in Timescale-Einheiten)
        duration_bytes = data[duration_offset:duration_offset + 4]
        duration = struct.unpack('>I', duration_bytes)[0]

        # Berechnung der Dauer in Sekunden
        duration_seconds = duration / timescale if timescale > 0 else 0

        # FPS aus der 'stts' Box extrahieren
        stts_index = data.find(b'stts')
        if stts_index != -1:
            entry_count_offset = stts_index + 8  # Anzahl der Einträge in der STTS-Box
            entry_count_bytes = data[entry_count_offset:entry_count_offset + 4]
            entry_count = struct.unpack('>I', entry_count_bytes)[0]

            total_samples = 0
            total_duration = 0

            for i in range(entry_count):
                sample_count_offset = entry_count_offset + 4 + (i * 8)
                sample_count_bytes = data[sample_count_offset:sample_count_offset + 4]
                sample_count = struct.unpack('>I', sample_count_bytes)[0]

                frame_duration_offset = sample_count_offset + 4
                frame_duration_bytes = data[frame_duration_offset:frame_duration_offset + 4]
                frame_duration = struct.unpack('>I', frame_duration_bytes)[0]

                total_samples += sample_count
                total_duration += sample_count * frame_duration

            if total_duration > 0:
                fps = total_samples / (total_duration / timescale)
            else:
                fps = 0
        else:
            fps = 0  # Falls 'stts' nicht gefunden wird

        return epoch_time, is_dst, duration_seconds, fps


def extract_coordinates_from_mp4(file_path):
    vepoch_time, is_dst, duration_seconds, fps = read_mp4_creation_time(file_path)
    video_start_epoch = vepoch_time - duration_seconds
    positions = nvtk_mp42gpx.get_data_package(file_path)

    coordinates = []
    for step in positions:
        newd = {
            "epoch": step['Epoch'],
            "lat": step['Loc']['Lat']['Float'],
            "lon": step['Loc']['Lon']['Float'],
            "speed" : step['Loc']['Speed'],
            "bear" : step['Loc']['Bearing'],
            "date" : step['DT']['DT']
        }
        coordinates.append(newd)

    for i in coordinates:
        print(i)
        print()

    return video_start_epoch, coordinates


# -------------------------------------------------------------------
# Erstelle die Folium-Karte (mit dynamischem Marker)
# -------------------------------------------------------------------
def create_map(initial_coord, fullset):
    """
    Erzeugt eine Folium‑Karte, in die per JavaScript ein Marker eingebettet wird,
    der über window.updateMarker(lat, lng) aktualisiert werden kann.
    """
    m = folium.Map(location=initial_coord, zoom_start=15)

    route = []
    for step in fullset:
        posLat = step['lat']
        posLon = step['lon']
        if posLat != 0 and posLon != 0:
            newpos = [posLat, posLon]
            route.append(newpos)

    folium.PolyLine(route, tooltip="Route").add_to(m)

    map_name = m.get_name()
    custom_js = f"""
    <script>
    window.addEventListener('load', function(){{
        console.log("Map fully loaded, initializing dynamic marker.");
        window.marker = L.marker([{initial_coord[0]}, {initial_coord[1]}]).addTo({map_name});
        window.updateMarker = function(lat, lng){{
            console.log("Updating marker to:", lat, lng);
            window.marker.setLatLng([lat, lng]);
            {map_name}.panTo([lat, lng]);
        }};
    }});
    </script>
    """
    m.get_root().html.add_child(folium.Element(custom_js))
    return m


# -------------------------------------------------------------------
# CEF-Browser in Tkinter einbetten
# -------------------------------------------------------------------
class BrowserFrame(tk.Frame):
    """
    Dieser Frame bettet den CEF‑Browser in ein Tkinter‑Frame ein und sorgt
    für das regelmäßige Aufrufen von cef.MessageLoopWork().
    """
    def __init__(self, master, url, *args, **kwargs):
        tk.Frame.__init__(self, master, *args, **kwargs)
        self.url = url
        self.browser = None
        self.browser_frame = tk.Frame(self, width=800, height=600)
        self.browser_frame.grid(row=0, column=1, sticky="n")
        self.after(100, self.embed_browser)
        self.bind("<Configure>", self.on_configure)

    def embed_browser(self):
        window_info = cef.WindowInfo()
        rect = [0, 0, self.winfo_width(), self.winfo_height()]
        window_info.SetAsChild(self.browser_frame.winfo_id(), rect)
        self.browser = cef.CreateBrowserSync(window_info=window_info, url=self.url)
        self.message_loop_work()

    def on_configure(self, event):
        if self.browser:
            self.browser.SetBounds(0, 0, event.width, event.height)

    def message_loop_work(self):
        cef.MessageLoopWork()
        self.after(10, self.message_loop_work)


# -------------------------------------------------------------------
# OpenCVVideoPlayer: Videoanzeige mit OpenCV in Tkinter
# -------------------------------------------------------------------
class OpenCVVideoPlayer(tk.Frame):
    """
    Dieser Frame integriert einen OpenCV-basierten Videoplayer in Tkinter.
    Er beinhaltet einen Videobereich, Play-/Pause‑Buttons und einen Schieberegler,
    mit dem man im Video navigieren kann.
    """
    def __init__(self, master, video_path, *args, **kwargs):
        tk.Frame.__init__(self, master, *args, **kwargs)
        self.video_path = video_path
        self.cap = cv2.VideoCapture(self.video_path)
        if not self.cap.isOpened():
            raise Exception("Fehler beim Öffnen des Videos.")
        # Videoeigenschaften ermitteln
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.frame_count = self.cap.get(cv2.CAP_PROP_FRAME_COUNT)
        self.duration = (self.frame_count / self.fps) * 1000  # Gesamtdauer in ms

        self.playing = False  # Wiedergabezustand
        self.current_frame = None

        # --- Grid-Konfiguration für den gesamten Frame ---
        # self.rowconfigure(0, weight=1)   # Videoanzeige soll sich ausdehnen
        # self.rowconfigure(1, weight=0)   # Steuerung nimmt nur den benötigten Platz ein
        # self.columnconfigure(0, weight=1)

        # --- Videoanzeige (Label) in Grid-Zeile 0 ---
        self.video_panel = tk.Label(self, bg="black")
        self.video_panel.grid(row=0, column=0, sticky="ew")

        # --- Steuerungsbereich in Grid-Zeile 1 ---
        self.controls = tk.Frame(self)
        self.controls.grid(row=5, column=0, sticky="ew")
        # Innerhalb des Steuerungsbereichs: Spalte 2 (der Slider) soll sich horizontal ausdehnen
        self.controls.columnconfigure(2, weight=1)

        # Play-Button in Spalte 0
        self.play_button = tk.Button(self.controls, text="Play", command=self.play)
        self.play_button.grid(row=0, column=0, padx=5, pady=5)

        # Pause-Button in Spalte 1
        self.pause_button = tk.Button(self.controls, text="Pause", command=self.pause)
        self.pause_button.grid(row=0, column=1, padx=5, pady=5)

        # Schieberegler (Slider) in Spalte 2
        self.scale_var = tk.DoubleVar()
        self.slider = tk.Scale(
            self.controls,
            variable=self.scale_var,
            orient=tk.HORIZONTAL,
            from_=0,
            to=1000,
            length=300,
            command=self.on_slider
        )
        self.slider.grid(row=0, column=2, padx=5, pady=5, sticky="ew")

        # Lade neue Datei
        self.loadfile_button = tk.Button(self.controls, text="load file", command=self.loadfilefromdisk)
        self.loadfile_button.grid(row=1, column=0, columnspan=2, padx=5, pady=5)

        # Starte das regelmäßige Aktualisieren des Sliders
        self.update_slider()
        #self.play()

    def play(self):
        if not self.playing:
            self.playing = True
            self.update_frame()

    def pause(self):
        self.playing = False

    def loadfilefromdisk(self):
        print('xxx')
        print('dashcam_restart')
        sys.exit(0)

    def image_resize(self, image, width = None, height = None, inter = cv2.INTER_AREA):
        dim = None
        (h, w) = image.shape[:2]
        if width is None and height is None:
            return image
        if width is None:
            r = height / float(h)
            dim = (int(w * r), height)
        else:
            r = width / float(w)
            dim = (width, int(h * r))

        resized = cv2.resize(image, dim, interpolation = inter)
        return resized

    def update_frame(self):
        """
        Liest den nächsten Frame, konvertiert ihn und zeigt ihn im Label an.
        Falls das Video noch läuft, wird die Funktion erneut über after() aufgerufen.
        """
        if self.playing:
            ret, frame = self.cap.read()
            if ret:
                self.current_frame = frame
                # Konvertiere BGR (OpenCV) zu RGB (Pillow)
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                frame_rgb = self.image_resize(frame_rgb, 600)
                image = Image.fromarray(frame_rgb)

                imgtk = ImageTk.PhotoImage(image=image)
                self.video_panel.imgtk = imgtk  # Referenz speichern
                self.video_panel.config(image=imgtk)
                # Aktualisiere den Slider basierend auf der aktuellen Wiedergabezeit
                current_time = self.cap.get(cv2.CAP_PROP_POS_MSEC)
                if self.duration > 0:
                    normalized = (current_time / self.duration) * 1000
                    self.scale_var.set(normalized)
                delay = int(1000 / self.fps)
                self.after(delay, self.update_frame)
            else:
                # Video zu Ende – Wiedergabe stoppen
                self.playing = False

    def on_slider(self, value):
        """
        Wird aufgerufen, wenn der Schieberegler bewegt wird.
        Setzt den Videostand basierend auf dem normierten Slider-Wert.
        """
        try:
            val = float(value)
        except ValueError:
            val = 0.0
        new_time = (val / 1000) * self.duration
        self.cap.set(cv2.CAP_PROP_POS_MSEC, new_time)
        if not self.playing:
            ret, frame = self.cap.read()
            if ret:
                self.current_frame = frame
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = Image.fromarray(frame_rgb)
                panel_width = self.video_panel.winfo_width()
                panel_height = self.video_panel.winfo_height()
                if panel_width > 0 and panel_height > 0:
                    image = image.resize((panel_width, panel_height))
                imgtk = ImageTk.PhotoImage(image=image)
                self.video_panel.imgtk = imgtk
                self.video_panel.config(image=imgtk)

    def update_slider(self):
        if self.playing:
            current_time = self.cap.get(cv2.CAP_PROP_POS_MSEC)
            if self.duration > 0:
                normalized = (current_time / self.duration) * 1000
                self.scale_var.set(normalized)
        self.after(500, self.update_slider)


# -------------------------------------------------------------------
# VideoMapApp: Hauptanwendung – links der Videoplayer, rechts die Karte
# -------------------------------------------------------------------
class VideoMapApp(tk.Frame):
    def __init__(self, master, video_path, map_url, video_start_epoch, coordinates, *args, **kwargs):
        tk.Frame.__init__(self, master, *args, **kwargs)
        self.video_start_epoch = video_start_epoch  # Video-Startzeit (Epoch Time in s)
        self.coordinates = coordinates              # Liste der GPS-Daten (Dicts mit "lat", "lon", "epoch")

        # Layout: Zwei Spalten (links: Video, rechts: Karte)
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        # Linker Bereich: OpenCV-Videoplayer
        self.video_frame = OpenCVVideoPlayer(self, video_path)
        self.video_frame.grid(row=0, column=0, sticky="nsew")

        # Rechter Bereich: Karte und Steuerung
        right_frame = tk.Frame(self)
        right_frame.grid(row=0, column=1, sticky="nsew")
        right_frame.rowconfigure(0, weight=1)
        right_frame.rowconfigure(1, weight=0)
        right_frame.columnconfigure(0, weight=1)

        self.browser_frame = BrowserFrame(right_frame, map_url)
        self.browser_frame.grid(row=0, column=0, sticky="nsew")

        # Optionale manuelle Map-Daten
        self.gui_speed_kmh_var = tk.StringVar()
        self.gui_speed_mps_var = tk.StringVar()
        self.gui_var_lat = tk.StringVar()
        self.gui_var_lon = tk.StringVar()
        self.gui_var_gpstime = tk.StringVar()

        self.map_controls = tk.Frame(right_frame)
        self.map_controls.grid(row=1, column=0, sticky="ew")

        self.Labelframe_speed = tk.LabelFrame(self.map_controls, text="Speed:")
        self.Labelframe_speed.grid(row=0, column=0, sticky="ew", padx=25, pady=5)
        self.Label_Speed_kmh = tk.Label(self.Labelframe_speed, textvariable = self.gui_speed_kmh_var)
        self.Label_Speed_mps = tk.Label(self.Labelframe_speed, textvariable = self.gui_speed_mps_var)
        self.gui_speed_kmh_var.set('0')
        self.gui_speed_mps_var.set('0')
        self.Label_Speed_kmh.grid(row=0, column=0, sticky="ew", padx=15, pady=2)
        self.Label_Speed_mps.grid(row=1, column=0, sticky="ew", padx=15, pady=2)

        self.Labelframe_gpspos = tk.LabelFrame(self.map_controls, text="GPS Position:")
        self.Labelframe_gpspos.grid(row=0, column=1, sticky="ew", padx=25, pady=5)
        self.Label_gps_lat = tk.Label(self.Labelframe_gpspos, textvariable = self.gui_var_lat)
        self.Label_gps_lon = tk.Label(self.Labelframe_gpspos, textvariable = self.gui_var_lon)
        self.gui_var_lat.set('0')
        self.gui_var_lon.set('0')
        self.Label_gps_lat.grid(row=0, column=0, sticky="ew", padx=15, pady=2)
        self.Label_gps_lon.grid(row=1, column=0, sticky="ew", padx=15, pady=2)

        self.Labelframe_timestamp = tk.LabelFrame(self.map_controls, text="GPS Timestamp:")
        self.Labelframe_timestamp.grid(row=0, column=2, sticky="ew", padx=25, pady=5)
        self.Label_gps_time = tk.Label(self.Labelframe_timestamp, textvariable = self.gui_var_gpstime)
        self.gui_var_gpstime.set('0')
        self.Label_gps_time.grid(row=0, column=0, sticky="ew", padx=15, pady=2)


        # Starte den periodischen Timer zur Aktualisierung des Markers
        self.update_map_marker()
        self.video_frame.play()
        self.video_frame.pause()


        self.after(3000, self.video_frame.play)

    def get_nearest_coordinate(self, current_epoch):
        """
        Sucht in der Liste der GPS-Daten den Eintrag,
        dessen "epoch" am nächsten an current_epoch liegt.
        """
        nearest = None
        smallest_diff = float('inf')
        for coord in self.coordinates:
            diff = abs(coord["epoch"] - current_epoch)
            if diff < smallest_diff:
                smallest_diff = diff
                nearest = coord
        return nearest

    def update_map_marker(self):
        """
        Ermittelt anhand der aktuellen Video-Position (plus Video-Startzeit)
        den nächstgelegenen GPS-Punkt und aktualisiert den Marker in der Karte.
        Diese Funktion wird alle 500 ms erneut aufgerufen.
        """
        # Hole die aktuelle Wiedergabezeit (in ms)
        current_time_ms = self.video_frame.cap.get(cv2.CAP_PROP_POS_MSEC)
        # Umrechnung in Sekunden
        current_time = current_time_ms / 1000.0
        # Aktuelle Epoch Time = Video-Startzeit + aktuelle Videodauer (in s)
        current_epoch = self.video_start_epoch + current_time
        nearest_coord = self.get_nearest_coordinate(current_epoch)
        if nearest_coord and self.browser_frame.browser:
            lat = nearest_coord["lat"]
            lon = nearest_coord["lon"]
            js_code = f"window.updateMarker({lat}, {lon});"
            self.browser_frame.browser.ExecuteJavascript(js_code)

            speed_kmh = round(nearest_coord["speed"] * 3.6, 2)
            speed_mps = round(nearest_coord["speed"], 4)
            speedstring_kmh = str(str(speed_kmh) + " km/h")
            speedstring_mps = str(str(speed_mps) + " m/s")
            self.gui_speed_kmh_var.set(speedstring_kmh)
            self.gui_speed_mps_var.set(speedstring_mps)
            plat_str = str( "Lat.: " + str(nearest_coord["lat"]))
            plon_str = str( "Lon.: " + str(nearest_coord["lon"]))
            self.gui_var_lat.set(plat_str)
            self.gui_var_lon.set(plon_str)
            ptime = str(nearest_coord["date"])
            self.gui_var_gpstime.set(ptime)

        self.after(500, self.update_map_marker)

    def go_forward(self):
        """
        Manuelle Steuerung: Setzt den Marker auf den nächsten GPS-Punkt.
        (Kann alternativ zur automatischen Aktualisierung verwendet werden.)
        """
        # Finde den aktuell angezeigten Punkt
        current_epoch = self.video_start_epoch + (self.video_frame.cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0)
        # Suche den ersten Punkt, dessen epoch größer als current_epoch ist
        for coord in self.coordinates:
            if coord["epoch"] > current_epoch:
                if self.browser_frame.browser:
                    js_code = f"window.updateMarker({coord['lat']}, {coord['lon']});"
                    self.browser_frame.browser.ExecuteJavascript(js_code)
                break

    def go_back(self):
        """
        Manuelle Steuerung: Setzt den Marker auf den vorherigen GPS-Punkt.
        """
        current_epoch = self.video_start_epoch + (self.video_frame.cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0)
        for coord in reversed(self.coordinates):
            if coord["epoch"] < current_epoch:
                if self.browser_frame.browser:
                    js_code = f"window.updateMarker({coord['lat']}, {coord['lon']});"
                    self.browser_frame.browser.ExecuteJavascript(js_code)
                break


# -------------------------------------------------------------------
# Hauptfunktion
# -------------------------------------------------------------------
def main():
    # 1. Dateiauswahl: Wähle die MP4-Datei aus.
    file_root = tk.Tk()
    file_root.withdraw()  # Hauptfenster verstecken
    video_file = filedialog.askopenfilename(
        title="Bitte wählen Sie eine MP4-Datei",
        filetypes=[("MP4 Dateien", "*.mp4")]
    )
    file_root.destroy()

    if not video_file:
        print("Keine Datei ausgewählt. Programm wird beendet.")
        return
    print("Ausgewählte Datei:", video_file)

    # 2. Extrahiere die Video-Startzeit und GPS-Daten aus dem Video.
    video_start_epoch, coordinates = extract_coordinates_from_mp4(video_file)
    if not coordinates:
        print("Keine GPS-Daten gefunden. Programm wird beendet.")
        return
    # Verwende als initiale Kartenposition den ersten GPS-Punkt
    initial_coord = (coordinates[0]["lat"], coordinates[0]["lon"])

    # 3. Erstelle die Folium‑Karte und speichere sie als temporäre HTML‑Datei.
    m = create_map(initial_coord, coordinates)
    temp_dir = tempfile.gettempdir()
    map_file = os.path.join(temp_dir, "folium_map.html")
    m.save(map_file)
    map_url = "file:///" + map_file.replace("\\", "/")

    # 4. Initialisiere CEF.
    sys.excepthook = cef.ExceptHook
    cef.Initialize()

    # 5. Erstelle das Tkinter‑Hauptfenster mit Video- und Kartenanzeige.
    root = tk.Tk()
    #root.geometry("1200x700")
    root.title("Python dashcam player")

    app = VideoMapApp(root, video_file, map_url, video_start_epoch, coordinates)
    app.grid(row=0, column=0, sticky="n")

    def on_closing():
        if app.browser_frame.browser:
            app.browser_frame.browser.CloseBrowser(True)
        # Stoppe das Video (falls es läuft)
        app.video_frame.playing = False
        root.destroy()
        cef.Shutdown()
        print("xxxx")
        print("dashcam_close")
        #sys.exit(0)

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == '__main__':
    startup_arguments = sys.argv[1]
    dsp_name = str(win32gui.GetWindowText(win32gui.GetForegroundWindow()))

    if 'rundashcamscript' in dsp_name and startup_arguments in dsp_name:
        the_program_to_hide = win32gui.GetForegroundWindow()
        win32gui.ShowWindow(the_program_to_hide , win32con.SW_HIDE)
    main()
