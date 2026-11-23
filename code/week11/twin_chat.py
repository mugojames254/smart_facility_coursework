import threading
import time
from typing import Literal

import matplotlib
import numpy as np
import ollama
import pandas as pd
import plotly.graph_objects as go
import viser
from pydantic import BaseModel

from complaints_rooms import locate
from twin_geometry import load_building

# ------------------------------------------------------------------ 1. load everything, join on room number
groups, room_geo, sensor_pos = load_building("data/building_twin.ifc")
rooms = pd.read_csv("data/rooms_ko.csv", dtype={"room": str}).set_index("room")
points = pd.read_csv("data/sensors.csv", dtype={"room": str})
readings = pd.read_csv("data/readings.csv", parse_dates=["timestamp"])
wide = readings.pivot(index="timestamp", columns="point_id", values="value")
times = wide.index
tickets = pd.read_csv("data/complaints.csv", parse_dates=["received", "closed_at"])
weather = pd.read_csv("data/weather.csv", parse_dates=["timestamp"])
tickets[["room", "floor"]] = tickets.text.apply(lambda t: pd.Series(locate(t)))

# room -> its point id for each quantity, e.g. point_of["203"]["temperature"] = "AHU2.R203.ZN-T"
point_of = {r: dict(zip(p.quantity, p.point_id))
            for r, p in points[points.ifc_class == "IfcSensor"].groupby("room")}

# what the colours mean: (quantity, low, high, matplotlib colour map, legend text)
LAYERS = {
    "Temperature (°C)": ("temperature", 22, 29, "RdYlBu_r", "blue = 22 °C, red = 29 °C or more"),
    "CO2 (ppm)": ("co2", 400, 1400, "YlOrRd", "yellow = 400 ppm, dark red = 1400 ppm or more"),
    "Open tickets": ("tickets", 0, 3, "Purples", "white = none, light purple = 1, dark purple = 3 or more"),
}
NO_SENSOR, NO_DATA = (200, 200, 200), (70, 70, 70)


def open_tickets(t):
    return tickets[(tickets.received <= t) & (tickets.closed_at.isna() | (tickets.closed_at > t))]


def ticket_status(ticket, t):
    if ticket.received > t:
        return "not yet"
    return "open" if pd.isna(ticket.closed_at) or ticket.closed_at > t else "closed"


def room_value(room, layer, t):
    qty = LAYERS[layer][0]
    if qty == "tickets":
        return float((open_tickets(t).room == room).sum())
    pid = point_of.get(room, {}).get(qty)
    if pid is None or rooms.use[room] in ("plant", "server"):
        return None  # no such sensor, or not a room people work in
    return wide.at[t, pid]  # NaN when the sensor sent nothing


def colour_of(value, layer):
    if value is None:
        return NO_SENSOR
    if np.isnan(value):
        return NO_DATA
    _, lo, hi, cmap, _ = LAYERS[layer]
    x = np.clip((value - lo) / (hi - lo), 0, 1)
    if cmap == "Purples":  # tickets: 0 stays white, 1 is already clearly purple
        x = 0.0 if value == 0 else 0.45 + 0.55 * x
    r, g, b, _ = matplotlib.colormaps[cmap](x)
    return int(r * 255), int(g * 255), int(b * 255)


# ------------------------------------------------------------------ 2. the 3D scene
server = viser.ViserServer()
server.scene.set_up_direction("+z")
server.scene.configure_environment_map(environment_intensity=0.5)  # softer light, truer colours
server.gui.configure_theme(control_width="large")


@server.on_client_connect
def start_view(client):
    client.camera.position = (40.0, -23.0, 25.0)
    client.camera.look_at = (27.0, 8.0, 0.0)


building = {key: server.scene.add_mesh_simple(f"/building/{key[0]}/{key[1]}", v, f, color=c,
                                              opacity=o, flat_shading=True)
            for key, (v, f, c, o) in groups.items()}
room_mesh, room_label = {}, {}
for room, g in room_geo.items():
    v = g["vertices"].copy()
    v[:, 2] = v[:, 2].clip(max=v[:, 2].min() + 2.5)
    room_mesh[room] = server.scene.add_mesh_simple(f"/rooms/{room}", v, g["faces"], flat_shading=True)
    room_label[room] = server.scene.add_label(f"/labels/{room}", room,
                                              position=(*v[:, :2].mean(axis=0), v[:, 2].max() + 0.2))
sensor_dots = server.scene.add_point_cloud("/sensors", np.array(list(sensor_pos.values()), np.float32),
                                           colors=(20, 20, 20), point_size=0.12, visible=False)

# ------------------------------------------------------------------ 3. the side panel
days = sorted({t.strftime("%Y-%m-%d %a") for t in times})
with server.gui.add_folder("View"):
    floor_pick = server.gui.add_dropdown("Floor", ("All", "B1", "1F", "2F", "3F"), initial_value="All")
    layer_pick = server.gui.add_dropdown("Colour by", tuple(LAYERS), initial_value="Temperature (°C)")
    zone_pick = server.gui.add_dropdown("AHU zone", ("-", "AHU-1", "AHU-2"), initial_value="-")
    show_sensors = server.gui.add_checkbox("Show sensors", False)
with server.gui.add_folder("Time"):
    day_pick = server.gui.add_dropdown("Day", tuple(days), initial_value="2026-09-17 Thu")
    hour_pick = server.gui.add_slider("Time of day", 0, 23.75, 0.25, initial_value=15.5)
    play = server.gui.add_button("▶ Play / pause")
    clock = server.gui.add_markdown("")
legend = server.gui.add_markdown("")
title = server.gui.add_markdown("**Click a room.**")
ticket_box = server.gui.add_markdown("")
chart = server.gui.add_plotly(go.Figure(), aspect=1.6, visible=False)
state = {"room": None, "focus": None, "playing": False}  # focus = room picked by the assistant


def now():
    t = pd.Timestamp(day_pick.value[:10]) + pd.Timedelta(hours=hour_pick.value)
    return times[times.get_indexer([t], method="nearest")[0]]


def refresh(_=None):
    t, layer, fl, zone = now(), layer_pick.value, floor_pick.value, zone_pick.value
    if state["room"] and fl != "All" and room_geo[state["room"]]["floor"] != fl:
        state["room"] = None  # the selected room is not on this floor
    for (floor, group), h in building.items():
        h.visible = fl != "All" and floor == fl
    for room, h in room_mesh.items():
        floor = room_geo[room]["floor"]
        h.visible = (fl == "All" and floor != "4F") or floor == fl
        room_label[room].visible = floor == fl or room == state["room"]
        h.color = colour_of(room_value(room, layer, t), layer)
        in_zone = zone == "-" or rooms.ahu[room] == zone
        in_focus = state["focus"] in (None, room)
        h.opacity = None if in_zone and in_focus else 0.08  # None = solid
    sensor_dots.visible = show_sensors.value
    clock.content = f"### {t:%Y-%m-%d %a %H:%M}"
    legend.content = (f"**{layer}**: {LAYERS[layer][4]}  \n"
                      f"light grey = not monitored · dark grey = no data")
    if state["room"]:
        show_room(state["room"])
    elif zone != "-":
        show_ahu(zone)
    else:
        title.content, ticket_box.content, chart.visible = "**Click a room.**", "", False


def show_room(room):
    t, r = now(), rooms.loc[room]
    lines = [f"### {room}호 · {r.name_ko}",
             f"{r.floor} · {r.area_m2} m² · facade {r.facade} · {r.ahu} · IFC *{r.name_ifc}*"]
    for qty, label, unit in [("temperature", "temperature", " °C"), ("co2", "CO2", " ppm"),
                             ("humidity", "humidity", " %"), ("occupancy", "people counted", "")]:
        pid = point_of.get(room, {}).get(qty)
        if pid:
            lines.append(f"- {label}: **{wide.at[t, pid]:g}{unit}** `{pid}`")
    title.content = "\n".join(lines)
    fig = go.Figure()
    pts = point_of.get(room, {})
    if layer_pick.value.startswith("CO2") and "co2" in pts:
        fig.add_scatter(x=times, y=wide[pts["co2"]], name=f"{room} CO2 (ppm)", line=dict(color="#e6550d"))
        fig.add_hline(y=1000, line=dict(color="black", dash="dash", width=1))
    elif "temperature" in pts:
        fig.add_scatter(x=weather.timestamp, y=weather.temp_c, name="outdoor (°C)",
                        line=dict(color="#aaaaaa", width=1))
        fig.add_scatter(x=times, y=wide[pts["temperature"]], name=f"{room} (°C)", line=dict(color="#d62728"))
    style_chart(fig, t)
    mine = tickets[tickets.room == room]
    ticket_box.content = "**Tickets**  \n" + ("\n".join(
        f"- {x.received:%m-%d %H:%M} · *{ticket_status(x, t)}* · {x.text}" for x in mine.itertuples()) or "none")


def show_ahu(ahu):
    a = ahu.replace("-", "")
    served = rooms[rooms.ahu == ahu]
    title.content = (f"### {ahu} · 공조기\nServes {len(served)} rooms on "
                     f"{', '.join(sorted(served.floor.unique()))}  \n"
                     f"- supply air: **{wide.at[now(), a + '.SAT']:g} °C** (setpoint 14 °C)\n"
                     f"- chilled-water valve: **{wide.at[now(), a + '.CHW-VLV']:g} %**")
    fig = go.Figure()
    fig.add_scatter(x=times, y=wide[a + ".SAT"], name="supply air °C", line=dict(color="#1f77b4"))
    fig.add_scatter(x=times, y=wide[a + ".RAT"], name="return air °C", line=dict(color="#d62728"))
    fig.add_scatter(x=times, y=wide[a + ".CHW-VLV"], name="valve (%)", yaxis="y2",
                    line=dict(color="rgba(120,120,120,0.5)", width=1))
    style_chart(fig, now())
    ticket_box.content = ""


def style_chart(fig, t):
    fig.add_vline(x=t, line=dict(color="black", dash="dot"))
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.12),
                      yaxis2=dict(overlaying="y", side="right", showgrid=False),
                      xaxis=dict(tickformat="%d %b"))
    chart.figure = fig
    chart.visible = True


def make_click(room):
    def on_click(event):
        state["room"], state["focus"] = room, None
        refresh()
    return on_click


for room, h in room_mesh.items():
    h.on_click(make_click(room))


def zone_changed(_):
    state["room"] = state["focus"] = None
    refresh()


def toggle_play(_):
    state["playing"] = not state["playing"]


# ------------------------------------------------------------------ 4. the AI assistant (gemma3:4b on Ollama)
# The LLM never sees the numbers. It only turns the question into one Command (like the Week 9 agent);
# pandas then finds the room, so every value in the answer comes from the data, not from the model.
MODEL = "gemma3:4b"
FLOORS = ("B1", "1F", "2F", "3F")
METRICS = {  # metric -> (words for the answer, unit, matching "Colour by" layer)
    "temperature": ("temperature", " °C", "Temperature (°C)"),
    "co2": ("CO2", " ppm", "CO2 (ppm)"),
    "humidity": ("humidity", " %", None),
    "occupancy": ("number of people", "", None),
    "open_tickets": ("number of open tickets", "", "Open tickets"),
    "alarm_hours": ("alarm time today (over 26 °C or 1000 ppm)", " h", None),
}


class Command(BaseModel):
    action: Literal["find_room", "go_to_room", "show_ahu", "reset_view", "answer"]
    metric: Literal["temperature", "co2", "humidity", "occupancy", "open_tickets", "alarm_hours", "none"]
    rank: Literal["highest", "lowest"]
    floor: Literal["any", "B1", "1F", "2F", "3F"]
    room: str  # a room number such as "303", or ""
    ahu: Literal["AHU-1", "AHU-2", "none"]
    reply: str  # only used by "answer"


SYSTEM = """You control the 3D digital twin of a research building. Turn the user's request
(English or Korean) into ONE command. Pick the action:
- find_room: the room with the highest or lowest value. Set metric, rank and floor.
    temperature  = hot, warm, cold, 덥다, 춥다, 온도
    co2          = stuffy, air quality, ventilation, 답답하다, 환기, CO2
    humidity     = humid, dry, 습도
    occupancy    = people, crowded, busy, empty, 사람, 인원
    open_tickets = complaints, tickets, 민원
    alarm_hours  = faults, alarms, problems, most issues, 고장, 문제, 알람
- go_to_room: ONLY when the user names one specific room, e.g. "303", "303호", "세미나실".
    Put the number (or the name) in room. "the most crowded room" is find_room, not go_to_room.
- show_ahu: the user asks about an air handling unit: AHU-1, AHU-2, 공조기.
- reset_view: show the whole building, start over, 전체 보기, 처음으로.
- answer: greetings, or questions about what you can do. Write a short reply. Never invent sensor values.
Floors: B1 = basement, 지하; 1F = 1층; 2F = 2층; 3F = 3층. No floor named -> "any".
Fields an action does not use: metric "none", rank "highest", floor "any", room "", ahu "none", reply "".

Examples:
"take me to the hottest room on 3F" -> find_room, temperature, highest, 3F
"2층에서 제일 답답한 방은?" -> find_room, co2, highest, 2F
"which room has the most faults" -> find_room, alarm_hours, highest, any
"가장 사람이 많은 방으로 가줘" -> find_room, occupancy, highest, any
"show me 세미나실" -> go_to_room, room "세미나실"
"what is wrong with AHU-2?" -> show_ahu, ahu "AHU-2"
"""


def ask_llm(question):
    response = ollama.chat(model=MODEL, keep_alive="30m", options={"temperature": 0},
                           messages=[{"role": "system", "content": SYSTEM},
                                     {"role": "user", "content": question}],
                           format=Command.model_json_schema())
    return Command.model_validate_json(response.message.content)


def value_now(room, metric, t):
    """One number for one room at time t, straight from the data (NaN = no sensor or no data)."""
    pts = point_of.get(room, {})
    if metric == "open_tickets":
        return float((open_tickets(t).room == room).sum())
    if metric == "alarm_hours":  # 15-minute readings since midnight that were too hot or too stuffy
        if "temperature" not in pts and "co2" not in pts:
            return np.nan
        today = wide.loc[t.normalize(): t]
        alarm = pd.Series(False, index=today.index)
        if "temperature" in pts:
            alarm |= today[pts["temperature"]] > 26
        if "co2" in pts:
            alarm |= today[pts["co2"]] > 1000
        return alarm.sum() / 4
    return wide.at[t, pts[metric]] if metric in pts else np.nan


def rank_rooms(metric, rank, floor, t):
    floors = FLOORS if floor == "any" else (floor,)
    candidates = [r for r in room_mesh
                  if rooms.floor[r] in floors and rooms.use[r] not in ("plant", "server")]
    values = pd.Series({r: value_now(r, metric, t) for r in candidates}, dtype=float).dropna()
    return values.sort_values(ascending=rank == "lowest")


def fly_to(look_at, position, steps=25):
    """Glide every open browser's camera to a new view in about one second."""
    for client in server.get_clients().values():
        p0, l0 = np.array(client.camera.position), np.array(client.camera.look_at)
        for s in np.linspace(0, 1, steps)[1:]:
            s = 3 * s**2 - 2 * s**3  # ease in, ease out
            with client.atomic():
                client.camera.position = p0 + (np.array(position) - p0) * s
                client.camera.look_at = l0 + (np.array(look_at) - l0) * s
            time.sleep(0.04)


def go_to_room(room):
    """Show the room's floor, select and highlight the room, and fly the camera to it."""
    v = room_geo[room]["vertices"]
    centre = np.array([*v[:, :2].mean(axis=0), v[:, 2].min()])
    size = np.ptp(v[:, :2], axis=0).max()
    zone_pick.value = "-"  # (this clears the selection, so select the room after it)
    state["room"] = state["focus"] = room
    floor_pick.value = rooms.floor[room]
    refresh()
    fly_to(centre, centre + np.array([0.35, -0.75, 1.0]) * (size + 7))


def overview():
    state["room"] = state["focus"] = None
    floor_pick.value = "All"
    refresh()
    fly_to((27.0, 8.0, 0.0), (40.0, -23.0, 25.0))


def run_command(cmd, question):
    t = now()
    if cmd.action == "find_room" and cmd.metric != "none":
        words, unit, layer = METRICS[cmd.metric]
        ranked = rank_rooms(cmd.metric, cmd.rank, cmd.floor, t)
        where = "in the building" if cmd.floor == "any" else f"on {cmd.floor}"
        if ranked.empty:
            return f"No {words} data {where} at {t:%d %b %H:%M}."
        best, value = ranked.index[0], ranked.iloc[0]
        if cmd.rank == "highest" and value == 0:
            return f"Every room {where} is at 0 for {words} at {t:%d %b %H:%M}."
        if layer:
            layer_pick.value = layer  # colour the rooms by what was asked
        go_to_room(best)
        top3 = " · ".join(f"{r}호 {v:g}{unit}" for r, v in ranked.head(3).items())
        return (f"**{best}호 {rooms.name_ko[best]}** has the {cmd.rank} {words} {where} "
                f"at {t:%d %b %H:%M}: **{value:g}{unit}**  \nTop 3: {top3}")
    if cmd.action == "go_to_room":
        room = cmd.room.strip().removesuffix("호")
        if room not in room_geo:  # a name like "세미나실": find the number the same way as in step 4
            room = locate(cmd.room)[0] or locate(question)[0]
        if room not in room_geo or rooms.floor[room] not in FLOORS:
            return f"I could not find room \"{cmd.room}\" in the twin."
        go_to_room(room)
        return f"Here is **{room}호 {rooms.name_ko[room]}** ({rooms.floor[room]})."
    if cmd.action == "show_ahu" and cmd.ahu != "none":
        layer_pick.value = "Temperature (°C)"
        overview()
        zone_pick.value = cmd.ahu  # same as picking it in "AHU zone": fades the other rooms
        return f"Showing **{cmd.ahu}** and the rooms it serves. See the chart in the side panel."
    if cmd.action == "reset_view":
        zone_pick.value = "-"
        overview()
        return "Back to the whole building."
    return cmd.reply or "Ask me about a room, a floor or an AHU."


panel = server.gui.add_panel()  # a floating window, separate from the side panel
with panel.add_tab("Assistant", viser.Icon.MESSAGE_CHATBOT):
    question_box = server.gui.add_text("Ask", "Take me to the hottest room on 3F")
    ask_button = server.gui.add_button("Ask", icon=viser.Icon.SEND)
    answer_box = server.gui.add_markdown(
        "Try: *which room has the most faults?* · *2층에서 제일 답답한 방은?* · "
        "*show me 세미나실* · *what is wrong with AHU-2?* · *show the whole building*")
panel.float(x=15, y=-15, width=400)


@ask_button.on_click
def ask(_):
    question = question_box.value.strip()
    if not question:
        return
    ask_button.disabled = True
    answer_box.content = f"**You:** {question}  \n*thinking…*"
    try:
        cmd = ask_llm(question)
        reply = run_command(cmd, question)
        fields = {"find_room": ("metric", "rank", "floor"), "go_to_room": ("room",), "show_ahu": ("ahu",)}
        used = " ".join(f"`{x}`" for x in [cmd.action] + [getattr(cmd, f) for f in fields.get(cmd.action, ())])
        answer_box.content = f"**You:** {question}  \n{reply}  \n<sub>LLM command: {used}</sub>"
    except Exception as e:  # Ollama not running, model not pulled, ...
        answer_box.content = f"**You:** {question}  \n⚠ {e.__class__.__name__}: {e}"
    ask_button.disabled = False


def warm_up():  # load the model into memory now, so the first question is not slow
    try:
        ollama.generate(model=MODEL, prompt="", keep_alive="30m")
    except Exception as e:
        print(f"Ollama: {e}  (start Ollama, then run: ollama pull {MODEL})")


threading.Thread(target=warm_up, daemon=True).start()


for control in (floor_pick, layer_pick, show_sensors, day_pick, hour_pick):
    control.on_update(refresh)
zone_pick.on_update(zone_changed)
play.on_click(toggle_play)
refresh()

print("Digital twin + assistant running: open http://localhost:8080  (Ctrl+C to stop)")
while True:
    time.sleep(0.4)
    if state["playing"]:  # one hour per tick; roll over to the next day
        h = hour_pick.value + 1
        if h > 23.75:
            i = days.index(day_pick.value)
            day_pick.value = days[(i + 1) % len(days)]
            h = 0.0
        hour_pick.value = h
